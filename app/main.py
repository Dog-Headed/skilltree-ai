"""本地单用户 Web 入口。使用一个 worker，项目锁覆盖校验和实际执行。"""

import logging
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from threading import Lock, RLock

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse

from app.db.repository import DEFAULT_DB_PATH, LearningRepository
from app.graph import CHECKPOINT_DB_PATH
from app.models.web import CreateProject, DeleteProject, RenameProject, ProjectSummary, ProjectView, ResumeProject, RetryProject
from app.services.learning_session import open_learning_session
from app.services.project_deletion import delete_project_record
from app.services.project_view import build_project_view
from app.services.quiz_answers import normalize_choice_answer

logger = logging.getLogger(__name__)
STATIC_ROOT = Path(__file__).resolve().parent / "static"


class WebError(Exception):
    def __init__(self, status, code, message, project_id=None):
        self.status, self.code, self.message, self.project_id = status, code, message, project_id


def create_app(*, learning_db_path=DEFAULT_DB_PATH, checkpoint_db_path=CHECKPOINT_DB_PATH):
    app = FastAPI(title="SkillTree AI", docs_url=None, redoc_url=None, openapi_url=None)
    paths = {"learning_db_path": Path(learning_db_path).resolve(), "checkpoint_db_path": Path(checkpoint_db_path).resolve()}
    locks = {}
    locks_guard = Lock()

    def project_lock(project_id):
        with locks_guard:
            return locks.setdefault(project_id, RLock())

    def check_id(project_id):
        if not re.fullmatch(r"[\w.-]{1,128}", project_id):
            raise WebError(404, "project_not_found", "找不到这个学习项目。")

    @contextmanager
    def execution(project_id):
        check_id(project_id)
        lock = project_lock(project_id)
        if not lock.acquire(blocking=False):
            raise WebError(409, "project_busy", "项目正在处理，请稍候再查看最新状态。", project_id)
        try:
            yield
        finally:
            lock.release()

    def require_view(session, repo):
        result = build_project_view(session, repo)
        if result is None:
            raise WebError(404, "project_not_found", "找不到这个学习项目。")
        return result

    def require_existing_id(repo, project_id):
        if repo.is_project_deleted(project_id):
            raise WebError(404, "project_not_found", "这个学习项目已删除。", project_id)

    def run_step(operation, project_id):
        try:
            operation()
        except Exception as exc:
            # 私有异常只记录类型，响应由存档投影产生。
            logger.error("Project %s failed: %s", project_id, type(exc).__name__)

    @app.middleware("http")
    async def local_origin(request: Request, call_next):
        # 防止其他网站向本地无登录服务提交动作。CLI 无 Origin 仍可使用。
        origin = request.headers.get("origin")
        if request.method in {"POST", "DELETE", "PATCH"} and origin and origin != str(request.base_url).rstrip("/"):
            return JSONResponse(status_code=403, content={"error": {"code": "invalid_origin", "message": "请从当前学习工作台提交操作。"}})
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        return response

    @app.exception_handler(WebError)
    async def handle_error(request, exc):
        return JSONResponse(status_code=exc.status, content={"error": {"code": exc.code, "message": exc.message}, "project_id": exc.project_id})

    @app.exception_handler(RequestValidationError)
    async def handle_validation(request, exc):
        # 不回传 Pydantic 的原始 input/ctx，避免包含提交的私有内容。
        return JSONResponse(status_code=422, content={"error": {"code": "invalid_input", "message": "输入格式不正确，请检查学习目标、操作或答案。"}})

    @app.exception_handler(Exception)
    async def handle_unexpected(request, exc):
        logger.error("Web request failed: %s", type(exc).__name__)
        return JSONResponse(status_code=500, content={"error": {"code": "service_error", "message": "暂时无法读取学习记录，请稍后刷新状态。"}})

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC_ROOT / "index.html")

    @app.get("/projects", response_model=list[ProjectSummary])
    def list_projects():
        with LearningRepository(paths["learning_db_path"]) as repo:
            ids = [project["id"] for project in repo.list_projects()]
            deleted = repo.deleted_project_ids()
        if paths["checkpoint_db_path"].exists():
            with sqlite3.connect(paths["checkpoint_db_path"]) as conn:
                if conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'checkpoints'").fetchone():
                    ids.extend(row[0] for row in conn.execute("SELECT DISTINCT thread_id FROM checkpoints") if row[0] not in ids and row[0] not in deleted)
        summaries = []
        for project_id in ids:
            try:
                result = read_project(project_id)
            except WebError as exc:
                if exc.status == 404:
                    continue  # 列表读取期间该项目可能刚好被另一标签页删除。
                raise
            if result:
                summaries.append(ProjectSummary(**result.model_dump(include={"project_id", "goal", "display_name", "completed_count", "total_count", "page_state"})))
        return summaries

    @app.get("/projects/{project_id}", response_model=ProjectView)
    def read_project(project_id: str):
        check_id(project_id)
        lock = project_lock(project_id)
        acquired = lock.acquire(blocking=False)
        try:
            with LearningRepository(paths["learning_db_path"]) as repo:
                require_existing_id(repo, project_id)
            with open_learning_session(project_id, **paths) as session, LearningRepository(paths["learning_db_path"]) as repo:
                result = build_project_view(session, repo, running=not acquired)
            if result is None:
                raise WebError(404, "project_not_found", "找不到这个学习项目。")
            return result
        finally:
            if acquired:
                lock.release()

    @app.post("/projects", response_model=ProjectView, status_code=201)
    def create_project(payload: CreateProject):
        project_id = "project_" + payload.request_id.hex
        with execution(project_id):
            with LearningRepository(paths["learning_db_path"]) as repo:
                if repo.is_project_deleted(project_id):
                    raise WebError(409, "project_deleted", "原项目已删除，请重新新建一个学习项目。", project_id)
            with open_learning_session(project_id, **paths) as session, LearningRepository(paths["learning_db_path"]) as repo:
                if session.snapshot().values or repo.get_project(project_id):
                    raise WebError(409, "duplicate_creation", "项目已经创建，请查看已保存的项目。", project_id)
                run_step(lambda: session.start(payload.goal), project_id)
                result = require_view(session, repo)
        return result

    @app.post("/projects/{project_id}/resume", response_model=ProjectView)
    def resume_project(project_id: str, payload: ResumeProject):
        with execution(project_id):
            with LearningRepository(paths["learning_db_path"]) as repo:
                require_existing_id(repo, project_id)
            with open_learning_session(project_id, **paths) as session, LearningRepository(paths["learning_db_path"]) as repo:
                current = require_view(session, repo)
                if payload.pending_input_id != current.pending_input_id:
                    raise WebError(409, "stale_input", "学习状态已变化，已提交的操作不能重复使用。请查看最新进度。", project_id)
                if payload.action not in current.allowed_actions:
                    raise WebError(422, "action_not_allowed", "当前学习阶段不支持这个操作。", project_id)
                event = payload.model_dump(exclude_none=True)
                if payload.action == "ask":
                    if not payload.message or not payload.message.strip() or payload.answers is not None:
                        raise WebError(422, "invalid_question", "请填写要追问的问题。", project_id)
                    event["message"] = payload.message.strip()
                elif payload.message is not None:
                    raise WebError(422, "invalid_input", "当前操作不能携带提问内容。", project_id)
                if payload.action == "submit_answer":
                    if payload.answers is None or len(payload.answers) > 30:
                        raise WebError(422, "invalid_answers", "请按当前题目填写答案。", project_id)
                    question_map = {q.id: q for q in current.quiz.questions}
                    if set(payload.answers) - set(question_map):
                        raise WebError(422, "unknown_question", "答案包含其他试卷的题号，请刷新当前试卷。", project_id)
                    for key, answer in payload.answers.items():
                        question = question_map[key]
                        options = question.options or []
                        if question.type == "multiple_choice":
                            valid = isinstance(answer, list) and len(answer) <= len(options) and all(normalize_choice_answer(item, options) in options for item in answer)
                        else:
                            valid = isinstance(answer, str) and len(answer) <= 12000
                            if question.type == "single_choice" and answer:
                                valid = valid and normalize_choice_answer(answer, options) in options
                        if not valid:
                            raise WebError(422, "invalid_answer", "答案类型或选项不符合当前题目，请检查后再提交。", project_id)
                elif payload.answers is not None:
                    raise WebError(422, "invalid_input", "当前操作不能携带答卷。", project_id)
                if payload.action != "rest":
                    run_step(lambda: session.resume(event), project_id)
                return require_view(session, repo)

    @app.post("/projects/{project_id}/retry", response_model=ProjectView)
    def retry_project(project_id: str, payload: RetryProject):
        with execution(project_id):
            with LearningRepository(paths["learning_db_path"]) as repo:
                require_existing_id(repo, project_id)
            with open_learning_session(project_id, **paths) as session, LearningRepository(paths["learning_db_path"]) as repo:
                current = require_view(session, repo)
                if "retry" not in current.allowed_actions or payload.retry_token != current.retry_token:
                    raise WebError(409, "stale_retry", "当前步骤已变化，请查看最新状态。", project_id)
                run_step(session.retry, project_id)
                return require_view(session, repo)

    @app.delete("/projects/{project_id}")
    def delete_project(project_id: str, payload: DeleteProject):
        with execution(project_id):
            if payload.confirm_project_id != project_id:
                raise WebError(422, "delete_confirmation_mismatch", "请选择并确认要删除的同一个学习项目。", project_id)
            with LearningRepository(paths["learning_db_path"]) as repo:
                if not delete_project_record(repo, paths["checkpoint_db_path"], project_id):
                    raise WebError(404, "project_not_found", "找不到这个学习项目。", project_id)
        return {"project_id": project_id, "deleted": True}

    @app.patch("/projects/{project_id}")
    def rename_project(project_id: str, payload: RenameProject):
        with execution(project_id), LearningRepository(paths["learning_db_path"]) as repo:
            if repo.get_project(project_id) is None:
                raise WebError(404, 'project_not_found', '找不到这个学习项目。', project_id)
            repo.rename_project(project_id, payload.display_name)
        return {'project_id': project_id, 'display_name': payload.display_name}

    app.state.paths = paths
    return app


app = create_app()
