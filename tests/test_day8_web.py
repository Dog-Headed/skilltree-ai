"""真实 FastAPI + Graph + 临时 SQLite；模型替身沿用 conftest。"""

from concurrent.futures import ThreadPoolExecutor
import json
from threading import Event
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.db.repository import LearningRepository
from app.main import create_app
from app.models.schemas import DiagnosisResult
from app.services.learning_session import open_learning_session
from tests.conftest import make_fake_plan


@pytest.fixture
def web(tmp_path):
    paths = {"learning_db_path": tmp_path / "learning.sqlite", "checkpoint_db_path": tmp_path / "checkpoints.sqlite"}
    return TestClient(create_app(**paths)), paths


def create(client, goal="学习 Python"):
    response = client.post("/projects", json={"goal": goal, "request_id": str(uuid4())})
    assert response.status_code == 201
    return response.json()


def resume(client, project, action, **extra):
    return client.post(f"/projects/{project['project_id']}/resume", json={
        "pending_input_id": project["pending_input_id"], "action": action, **extra,
    })


def answer_quiz(client, project):
    return resume(client, project, "submit_answer", answers={q["id"]: "独立填写的测试答案" for q in project["quiz"]["questions"]}).json()


def test_page_and_read_only_restore_do_not_call_models(web, monkeypatch):
    client, paths = web
    project = create(client)
    for name in ("app.agents.planner.generate_plan", "app.agents.tutor.generate_tutor_content"):
        monkeypatch.setattr(name, lambda *a, **k: pytest.fail("GET 不允许调用模型"))
    assert client.get("/").status_code == 200
    restored = TestClient(create_app(**paths)).get("/projects/" + project["project_id"]).json()
    assert restored == project
    assert project["page_state"] == "learning"
    assert project["pending_input_id"].startswith("learning_")
    assert client.get("/projects").json()[0]["project_id"] == project["project_id"]


def test_question_changes_input_identity_and_stale_event_conflicts(web):
    client, _ = web
    project = create(client)
    result = resume(client, project, "ask", message="变量是什么？")
    assert result.status_code == 200
    asked = result.json()
    assert asked["pending_input_id"] != project["pending_input_id"]
    assert any(t["content"] == "变量是什么？" for t in asked["conversation"])
    assert resume(client, project, "start_quiz").status_code == 409


def test_quiz_restart_partial_answers_and_submission_identity(web):
    client, paths = web
    project = create(client)
    quiz = resume(client, project, "start_quiz").json()
    restarted = TestClient(create_app(**paths))
    assert restarted.get("/projects/" + quiz["project_id"]).json() == quiz
    partial = resume(client, quiz, "submit_answer", answers={"q1": "部分答案"}).json()
    assert partial["page_state"] == "quiz"
    assert partial["quiz"] == quiz["quiz"]
    assert partial["answers"] == {"q1": "部分答案"}
    assert partial["answer_error"]
    assert partial["pending_input_id"] != quiz["pending_input_id"]
    assert resume(client, quiz, "submit_answer", answers={"q1": "重放"}).status_code == 409
    result = resume(client, partial, "submit_answer", answers={"q2": "答案", "q3": "答案", "q4": "答案"}).json()
    assert result["completed_count"] == 1
    assert result["results"][0]["total_score"] == 100


def test_two_nodes_complete_with_results_and_and_dependencies(web):
    client, _ = web
    project = create(client)
    for count in (1, 2):
        quiz = resume(client, project, "start_quiz").json()
        project = answer_quiz(client, quiz)
        assert project["completed_count"] == count
        assert project["total_count"] == 8
        assert len(project["results"]) == count
    statuses = {n["id"]: n["status"] for n in project["nodes"]}
    assert statuses["variables"] == statuses["lists"] == "completed"
    assert statuses[project["current_node_id"]] == "learning"
    assert statuses["for_loops"] == "available"
    assert statuses["practice"] == "locked"
    assert client.get("/projects/" + project["project_id"]).json()["results"] == project["results"]


def test_whole_project_completes_and_has_no_actions(web):
    client, _ = web
    project = create(client)
    for _ in range(8):
        project = answer_quiz(client, resume(client, project, "start_quiz").json())
    assert project["page_state"] == "completed"
    assert project["completed_count"] == project["total_count"] == 8
    assert project["allowed_actions"] == []


def test_remediation_displays_new_lesson_instead_of_previous_tutorial(web, monkeypatch, mock_assessment_grade_llm):
    monkeypatch.setattr("app.agents.tutor.generate_tutor_content", lambda state, node: state.get("lesson_mode", "normal") + "课程")
    mock_assessment_grade_llm["score_ratio"] = .4
    client, _ = web
    project = create(client)
    assert project["conversation"][0]["content"] == "normal课程"
    project = answer_quiz(client, resume(client, project, "start_quiz").json())
    assert project["lesson_mode"] == "remediate"
    assert project["conversation"] == [{"role": "assistant", "content": "remediate课程"}]


def test_legacy_diagnosis_displays_learning_content_without_internal_identifiers(web, monkeypatch):
    original = {}

    def legacy_diagnosis(state, **kwargs):
        objective_id = state["tree"][0]["objectives"][0]["id"]
        original.update(DiagnosisResult(
            weak_points=["遗漏了安装或启用 Python 扩展（missing_python_extension）"],
            evidence_ids=[f"assessment:{state['assessment_id']}:q3"],
            recommended_action="remediate",
            reason=f"目标 {objective_id} 仍需巩固，q3 遗漏了安装 Python 扩展（error_tags: missing_python_extension）。"
                   "能运行 print(\"Hello World\")，保存 .py 文件并识别 SyntaxError。"
                   "本轮仅查询了本节点历史（1 次调用，未达调用与轮数上限）。"
                   "建议补齐这一操作后复测，最终仍由 Graph 的确定性规则决定。",
        ).model_dump())
        return DiagnosisResult.model_validate(original)

    monkeypatch.setattr("app.agents.diagnosis.run_real_diagnosis", legacy_diagnosis)
    client, paths = web
    project = answer_quiz(client, resume(client, create(client), "start_quiz").json())
    assert project["lesson_mode"] == "remediate"
    result = project["results"][0]
    text = result["reason"] + " ".join(result["weak_points"])
    for internal in ("variables_obj_1", "q3", "missing_python_extension", "error_tags", "次调用", "Graph"):
        assert internal not in text
    assert "第3题" in text and "理解变量的基本作用" in text
    assert 'print("Hello World")' in text and ".py" in text and "SyntaxError" in text
    assert result["weak_points"] == ["遗漏了安装或启用 Python 扩展"]
    with LearningRepository(paths["learning_db_path"]) as repo:
        assert repo.get_assessment(result["assessment_id"])["diagnosis"] == original
    # 刷新展示只做只读转换，不重新调用诊断模型、不修改原记录。
    monkeypatch.setattr("app.agents.diagnosis.run_real_diagnosis", lambda *a, **k: pytest.fail("刷新不应调用诊断模型"))
    assert client.get("/projects/" + project["project_id"]).json()["results"] == project["results"]


def test_feedback_question_numbers_follow_the_quiz_order(web):
    client, paths = web
    project = answer_quiz(client, resume(client, create(client), "start_quiz").json())
    assessment_id = project["results"][0]["assessment_id"]
    with LearningRepository(paths["learning_db_path"]) as repo:
        evaluation = repo.get_assessment(assessment_id)["evaluation"]
        evaluation["question_results"].reverse()
        repo.conn.execute("UPDATE assessments SET evaluation_json = ? WHERE id = ?", (json.dumps(evaluation), assessment_id))
        repo.conn.commit()
    result = client.get("/projects/" + project["project_id"]).json()["results"][0]
    assert [item["question_id"] for item in result["question_results"]] == ["q1", "q2", "q3", "q4"]


def test_return_to_teaching_abandons_original_quiz_without_round_credit(web):
    client, paths = web
    project = create(client)
    original = resume(client, project, "start_quiz").json()
    teaching = resume(client, original, "return_to_teaching").json()
    assert teaching["page_state"] == "learning"
    assert teaching["rounds"] == 0
    assert teaching["quiz"] is None and teaching["answers"] == {}
    assert resume(client, original, "submit_answer", answers={"q1": "旧答案"}).status_code == 409
    new = resume(client, teaching, "start_quiz").json()
    assert new["quiz"]["assessment_id"] != original["quiz"]["assessment_id"]
    with LearningRepository(paths["learning_db_path"]) as repo:
        assert repo.get_assessment(original["quiz"]["assessment_id"])["status"] == "abandoned"
        assert repo.count_graded_assessments(project_id=project["project_id"], node_id="variables") == 0


@pytest.mark.parametrize("payload", [
    {"action": "ask", "message": "   "},
    {"action": "submit_answer", "answers": {"q1": "答案"}},
    {"action": "start_quiz", "answers": {}},
    {"action": "start_quiz", "message": "不允许的内容"},
])
def test_invalid_actions_are_rejected_without_mutation(web, payload):
    client, _ = web
    project = create(client)
    assert resume(client, project, **payload).status_code == 422
    assert client.get("/projects/" + project["project_id"]).json() == project


def test_unknown_questions_and_invalid_types_do_not_consume_input(web):
    client, _ = web
    quiz = resume(client, create(client), "start_quiz").json()
    for answers in ({"other": "答案"}, {"q1": ["无效类型"]}, {"q1": 123}):
        assert resume(client, quiz, "submit_answer", answers=answers).status_code == 422
    assert client.get("/projects/" + quiz["project_id"]).json() == quiz


def test_choices_are_normalized_and_unknown_options_rejected(web, monkeypatch):
    import app.agents.assessment as assessment
    original = assessment.generate_quiz

    def mixed(node, assessment_id, **kwargs):
        quiz = original(node, assessment_id, **kwargs)
        quiz.questions[0].type = "single_choice"
        quiz.questions[0].options = ["赋值", "比较"]
        quiz.questions[0].answer_key = "赋值"
        quiz.questions[1].type = "multiple_choice"
        quiz.questions[1].options = ["变量", "数值", "其他"]
        quiz.questions[1].answer_key = ["变量", "数值"]
        return quiz

    monkeypatch.setattr(assessment, "generate_quiz", mixed)
    client, _ = web
    quiz = resume(client, create(client), "start_quiz").json()
    assert resume(client, quiz, "submit_answer", answers={"q1": "C"}).status_code == 422
    assert resume(client, quiz, "submit_answer", answers={"q2": ["未知"]}).status_code == 422
    result = resume(client, quiz, "submit_answer", answers={"q1": "A", "q2": ["A", "B"], "q3": "答案", "q4": "答案"}).json()
    assert result["completed_count"] == 1


def test_pause_rest_and_round_extension_are_idempotent(web, mock_assessment_grade_llm):
    mock_assessment_grade_llm["score_ratio"] = .4
    client, _ = web
    project = create(client)
    for _ in range(3):
        project = answer_quiz(client, resume(client, project, "start_quiz").json())
    assert project["page_state"] == "paused"
    assert project["rounds"] == project["round_limit"] == 3
    rested = resume(client, project, "rest").json()
    assert rested == project
    extended = resume(client, rested, "retry_3").json()
    assert extended["round_limit"] == 6 and extended["rounds"] == 3
    assert resume(client, rested, "retry_3").status_code == 409
    assert client.get("/projects/" + project["project_id"]).json()["round_limit"] == 6


@pytest.mark.parametrize("branch", ["collect_more_evidence", "revisit_prerequisite"])
def test_diagnosis_routes_and_return_from_prerequisite(web, monkeypatch, branch):
    client, _ = web
    project = answer_quiz(client, resume(client, create(client), "start_quiz").json())

    def diagnosis(state, **kwargs):
        return DiagnosisResult(weak_points=["需要巩固"], evidence_ids=["test"], recommended_action=branch,
                               reason="测试指定分支", review_node_id="variables" if branch == "revisit_prerequisite" else None)

    monkeypatch.setattr("app.agents.diagnosis.run_real_diagnosis", diagnosis)
    project = answer_quiz(client, resume(client, project, "start_quiz").json())
    assert project["current_node_id"] == "lists" and project["completed_count"] == 1
    assert project["results"][0]["recommended_action"] == branch
    if branch == "collect_more_evidence":
        assert project["page_state"] == "quiz"
    else:
        assert project["lesson_mode"] == "revisit" and project["teaching_node_id"] == "variables"
        returned = resume(client, project, "return_to_current").json()
        assert returned["current_node_id"] == returned["teaching_node_id"] == "lists"


def test_creation_failure_keeps_identity_and_retry_uses_same_project(web, monkeypatch):
    client, _ = web
    with monkeypatch.context() as m:
        m.setattr("app.agents.planner.generate_plan", lambda *a: (_ for _ in ()).throw(RuntimeError("private secret C:/local.env")))
        failed = create(client)
    assert failed["page_state"] == "error" and failed["allowed_actions"] == ["retry"]
    assert "private secret" not in str(failed) and "local.env" not in str(failed)
    assert client.get("/projects").json()[0]["project_id"] == failed["project_id"]
    restored = client.post(f"/projects/{failed['project_id']}/retry", json={"retry_token": failed["retry_token"]}).json()
    assert restored["page_state"] == "learning" and restored["project_id"] == failed["project_id"]
    assert client.post(f"/projects/{failed['project_id']}/retry", json={"retry_token": failed["retry_token"]}).status_code == 409


def test_failed_execution_retry_does_not_replay_accepted_answer(web, monkeypatch):
    client, _ = web
    quiz = resume(client, create(client), "start_quiz").json()
    with monkeypatch.context() as m:
        m.setattr("app.agents.assessment.grade_short_answer", lambda *a: (_ for _ in ()).throw(TimeoutError("private")))
        failed = answer_quiz(client, quiz)
    assert failed["page_state"] == "error"
    restored = client.post(f"/projects/{failed['project_id']}/retry", json={"retry_token": failed["retry_token"]}).json()
    assert restored["completed_count"] == 1
    assert len(restored["results"]) == 1


def test_two_tab_race_is_locked_and_read_shows_running(web, monkeypatch):
    client, _ = web
    project = create(client)
    entered, finish = Event(), Event()

    def tutor(*args):
        entered.set()
        assert finish.wait(10)
        return "并发测试教学"

    monkeypatch.setattr("app.agents.tutor.generate_tutor_content", tutor)
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(resume, client, project, "ask", message="追问")
        assert entered.wait(5)
        try:
            assert resume(client, project, "ask", message="第二个标签").status_code == 409
            running = client.get("/projects/" + project["project_id"]).json()
            assert running["page_state"] == "running" and not running["allowed_actions"]
        finally:
            finish.set()
        assert first.result().status_code == 200
    assert resume(client, project, "ask", message="重放").status_code == 409


def test_duplicate_create_has_known_identity_and_does_not_replan(web):
    client, _ = web
    payload = {"goal": "学习 Python", "request_id": str(uuid4())}
    first = client.post("/projects", json=payload).json()
    duplicate = client.post("/projects", json=payload)
    assert duplicate.status_code == 409 and duplicate.json()["project_id"] == first["project_id"]
    assert len(client.get("/projects").json()) == 1


def test_orphan_business_record_has_safe_error_without_planning(web):
    client, paths = web
    with LearningRepository(paths["learning_db_path"]) as repo:
        repo.create_project_with_tree(project_id="orphan", goal="旧项目", tree=make_fake_plan().model_dump()["nodes"])
    result = client.get("/projects/orphan").json()
    assert result["page_state"] == "error" and result["error"]["code"] == "checkpoint_missing"
    assert not result["allowed_actions"]
    assert client.post("/projects/orphan/retry", json={"retry_token": "missing"}).status_code == 409


def test_public_data_has_no_private_nested_fields_and_is_project_scoped(web):
    client, _ = web
    first, second = create(client), create(client)
    graded = answer_quiz(client, resume(client, first, "start_quiz").json())
    quiz = resume(client, graded, "start_quiz").json()
    forbidden = {"answer_key", "rubric", "tutor_messages", "tool_messages", "learning_db_path", "checkpoint_db_path", "LLM_API_KEY"}

    def inspect(value):
        if isinstance(value, dict):
            assert not forbidden.intersection(value)
            for item in value.values():
                inspect(item)
        elif isinstance(value, list):
            for item in value:
                inspect(item)

    inspect(quiz)
    assert all(r["assessment_id"] != quiz["quiz"]["assessment_id"] for r in quiz["results"])
    assert client.get("/projects/" + second["project_id"]).json()["results"] == []
    assert client.get("/projects/nonexistent").status_code == 404


def test_error_validation_omits_input_and_foreign_origins_are_blocked(web):
    client, _ = web
    secret = "sensitive-invalid-field"
    result = client.post("/projects", json={"goal": "a", "request_id": secret})
    assert result.status_code == 422 and secret not in result.text
    assert client.post("/projects", json={"goal": "学习 Python"}, headers={"Origin": "https://other.example"}).status_code == 403
    assert client.get("/").headers["x-content-type-options"] == "nosniff"
