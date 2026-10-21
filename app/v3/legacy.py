"""V2 history projection. Never initialize a schema or deserialize a Checkpoint.

The V2 business database remains the authority for completed learning facts.
Checkpoint metadata is used only to explain which historical files are present;
it is never passed to a Graph, model, or V3 repository.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from app.models.schemas import (
    AssessmentEvaluation,
    AssessmentQuiz,
    SkillNode,
    validate_and_score_evaluation,
)


class LegacyHistory:
    """Read the existing V2 stores, including older schemas, without migration."""

    def __init__(self, business_path: str | Path, checkpoint_path: str | Path | None = None):
        self.business_path = Path(business_path).resolve()
        self.checkpoint_path = Path(checkpoint_path).resolve() if checkpoint_path else None

    @staticmethod
    @contextmanager
    def _open(path: Path | None):
        if path is None or not path.is_file():
            yield None
            return
        connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA query_only = ON")
            yield connection
        finally:
            connection.close()

    @staticmethod
    def _tables(connection) -> set[str]:
        if connection is None:
            return set()
        return {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )}

    def _checkpoint_ids(self) -> set[str]:
        with self._open(self.checkpoint_path) as connection:
            if "checkpoints" not in self._tables(connection):
                return set()
            columns = {row[1] for row in connection.execute("PRAGMA table_info(checkpoints)")}
            if "thread_id" not in columns:
                return set()
            return {row[0] for row in connection.execute("SELECT DISTINCT thread_id FROM checkpoints")
                    if isinstance(row[0], str) and row[0]}

    @staticmethod
    def _nodes(connection, tables: set[str], project_id: str) -> list[dict]:
        if "knowledge_nodes" not in tables:
            return []
        result = []
        for row in connection.execute(
            "SELECT * FROM knowledge_nodes WHERE project_id = ? ORDER BY sort_order, id", (project_id,)
        ):
            try:
                node = SkillNode.model_validate({
                    **{key: row[key] for key in (
                        "id", "title", "description", "difficulty", "estimated_minutes"
                    )},
                    "objectives": json.loads(row["objectives_json"]),
                    "prerequisite_ids": json.loads(row["prerequisite_ids_json"]),
                })
            except (ValueError, TypeError):
                # Invalid historical model output is not presented as a valid plan.
                continue
            result.append(node.model_dump())
        return result

    @staticmethod
    def _progress(connection, tables: set[str], project_id: str) -> dict[str, dict]:
        if "learning_progress" not in tables:
            return {}
        return {row["node_id"]: dict(row) for row in connection.execute(
            "SELECT node_id, started_at, completed_at, completion_assessment_id "
            "FROM learning_progress WHERE project_id = ?", (project_id,)
        )}

    @staticmethod
    def _assessments(connection, tables: set[str], project_id: str) -> list[dict]:
        if "assessments" not in tables:
            return []
        result = []
        for row in connection.execute(
            "SELECT id, node_id, round_no, status, created_at, quiz_json, evaluation_json "
            "FROM assessments WHERE project_id = ? ORDER BY created_at DESC, id DESC", (project_id,)
        ):
            # Only explicit public fields are copied, never a dict(row) of private data.
            item = {"assessment_id": row["id"], "node_id": row["node_id"],
                    "round_no": row["round_no"], "status": row["status"],
                    "created_at": row["created_at"], "quiz": None, "feedback": None}
            try:
                quiz = AssessmentQuiz.model_validate(json.loads(row["quiz_json"]))
                if quiz.assessment_id != row["id"] or quiz.node_id != row["node_id"]:
                    raise ValueError("Historical assessment identity mismatch")
            except (ValueError, TypeError):
                result.append(item)
                continue
            item["quiz"] = {
                "assessment_id": quiz.assessment_id, "node_id": quiz.node_id,
                "questions": [{key: question.model_dump()[key] for key in (
                    "id", "objective_id", "type", "prompt", "options", "max_score"
                )} for question in quiz.questions],
            }
            if row["status"] == "graded" and row["evaluation_json"]:
                try:
                    evaluation = AssessmentEvaluation.model_validate(json.loads(row["evaluation_json"]))
                    summary = validate_and_score_evaluation(quiz, evaluation)
                except (ValueError, TypeError):
                    pass
                else:
                    maxima = {question.id: question.max_score for question in quiz.questions}
                    item["feedback"] = {
                        "total_score": summary["total_score"],
                        "max_score": summary["total_max_score"],
                        "question_scores": [{"question_id": score.question_id,
                                             "score": score.score,
                                             "max_score": maxima[score.question_id]}
                                            for score in evaluation.question_results],
                    }
            result.append(item)
        return result

    def _projects(self, *, detail: bool) -> list[dict]:
        checkpoint_ids = self._checkpoint_ids()
        projects = []
        deleted_ids = set()
        with self._open(self.business_path) as connection:
            tables = self._tables(connection)
            if "deleted_projects" in tables:
                deleted_ids = {row[0] for row in connection.execute("SELECT project_id FROM deleted_projects")}
            labels = ({row[0]: row[1] for row in connection.execute(
                "SELECT project_id, display_name FROM project_labels"
            )} if "project_labels" in tables else {})
            rows = (connection.execute("SELECT id, goal, created_at FROM learning_projects "
                                       "ORDER BY created_at DESC, id DESC").fetchall()
                    if "learning_projects" in tables else [])
            business_ids = {row["id"] for row in rows}
            for row in rows:
                project_id = row["id"]
                if project_id in deleted_ids:
                    continue
                nodes = self._nodes(connection, tables, project_id)
                progress = self._progress(connection, tables, project_id)
                completed = {node["id"] for node in nodes
                             if progress.get(node["id"], {}).get("completed_at")}
                availability = ("business_and_checkpoint" if project_id in checkpoint_ids
                                else "business_only")
                item = {
                    "project_id": project_id, "version": "v2", "read_only": True,
                    "allowed_actions": [], "page_state": "legacy_readonly",
                    "goal": row["goal"], "display_name": labels.get(project_id),
                    "created_at": row["created_at"], "total_count": len(nodes),
                    "completed_count": len(completed), "availability": availability,
                    "notice": "V2 历史只读。可查看已保存的学习记录；继续学习请创建 V3 项目。",
                }
                if availability == "business_only":
                    item["notice"] += " 未找到旧 Checkpoint，当前等待点不可查看。"
                if detail:
                    item["nodes"] = [dict(
                        node,
                        status=("completed" if node["id"] in completed else
                                "learning" if progress.get(node["id"], {}).get("started_at") else
                                "available" if set(node["prerequisite_ids"]).issubset(completed)
                                else "locked"),
                    ) for node in nodes]
                    item["results"] = self._assessments(connection, tables, project_id)
                    item["completed_node_ids"] = sorted(completed)
                projects.append(item)
            for project_id in sorted(checkpoint_ids - business_ids - deleted_ids):
                item = {
                    "project_id": project_id, "version": "v2", "read_only": True,
                    "allowed_actions": [], "page_state": "legacy_readonly",
                    "goal": "旧版学习存档", "display_name": None, "created_at": None,
                    "total_count": 0, "completed_count": 0, "availability": "checkpoint_only",
                    "notice": "仅找到 V2 Checkpoint，缺少业务记录；无法展示课程或成绩，不能在 V3 继续执行。",
                }
                if detail:
                    item.update(nodes=[], results=[], completed_node_ids=[])
                projects.append(item)
        return projects

    def list_projects(self) -> list[dict]:
        return self._projects(detail=False)

    def get_project(self, project_id: str) -> dict:
        for project in self._projects(detail=True):
            if project["project_id"] == project_id:
                return project
        raise KeyError(project_id)

    def contains(self, project_id: str) -> bool:
        return any(project["project_id"] == project_id for project in self.list_projects())
