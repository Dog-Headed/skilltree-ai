from pathlib import Path
from typing import Any

from app.db import repository
from app.db.repository import LearningRepository
from app.models.schemas import AssessmentEvaluation, AssessmentQuiz, validate_and_score_evaluation


def _answer_snippet(value: Any, max_length: int = 160) -> str:
    text = str(value)
    return text if len(text) <= max_length else text[:max_length - 3] + "..."


def get_learning_history(
    *,
    project_id: str,
    node_id: str,
    limit: int = 3,
    exclude_assessment_id: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """按需读取当前项目最近 1–3 次有效评分，不把当前轮重复当成历史。"""
    base = {"tool": "get_learning_history", "node_id": node_id}
    try:
        with LearningRepository(db_path or repository.DEFAULT_DB_PATH) as repo:
            if repo.get_node(project_id=project_id, node_id=node_id) is None:
                return {**base, "ok": False, "status": "node_not_found", "records": [],
                        "error_type": "node_not_found", "error": "当前项目中不存在该节点"}
            rows = repo.list_recent_graded_assessments(
                project_id=project_id, node_id=node_id, limit=limit,
                exclude_assessment_id=exclude_assessment_id,
            )

        records = []
        for row in rows:
            quiz = AssessmentQuiz.model_validate(row["quiz"])
            evaluation = AssessmentEvaluation.model_validate(row["evaluation"])
            percentage = validate_and_score_evaluation(quiz, evaluation)["percentage"]
            error_tags = list(dict.fromkeys(
                tag for result in evaluation.question_results for tag in result.error_tags
            ))
            evidence_items = [
                {"evidence_id": f"assessment:{row['id']}:{result.question_id}",
                 **result.model_dump()}
                for result in evaluation.question_results
            ]
            # 仅投影诊断契约字段，不返回私有试卷或任意额外字段。
            diagnosis = row["diagnosis"]
            if isinstance(diagnosis, dict):
                diagnosis = {key: diagnosis[key] for key in (
                    "weak_points", "evidence_ids", "recommended_action", "reason", "review_node_id"
                ) if key in diagnosis}
            else:
                diagnosis = None
            records.append({
                "assessment_id": row["id"], "round_no": row["round_no"],
                "percentage": round(percentage, 2), "error_tags": error_tags,
                "diagnosis": diagnosis,
                "answer_snippets": {
                    question.id: _answer_snippet(row["answers"][question.id])
                    for question in quiz.questions
                },
                "evidence_ids": [item["evidence_id"] for item in evidence_items],
                "evidence_items": evidence_items, "created_at": row["created_at"],
            })
    except Exception as exc:
        return {**base, "ok": False, "status": "query_error", "records": [],
                "error_type": "query_error", "error": f"学习历史查询失败：{exc}"}

    return {**base, "ok": True, "status": "found" if records else "no_history",
            "records": records, "message": (
                f"读取到 {len(records)} 条历史有效测评" if records else "该节点暂无历史有效测评"
            )}
