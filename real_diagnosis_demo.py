"""使用真实数据库的当前评分和按需历史，运行模型自主选择工具的诊断。"""
import argparse
import sqlite3
from pathlib import Path
from pprint import pprint

from app.agents.diagnosis import (
    run_diagnosis_tool_loop, build_diagnosis_evidence_registry,
    build_tool_execution_summary, generate_final_diagnosis,
)
from app.db.repository import DEFAULT_DB_PATH, LearningRepository
from app.models.schemas import (
    AssessmentEvaluation, AssessmentQuiz, SkillNode,
    validate_and_score_evaluation, validate_quiz_against_node,
)


def load_diagnosis_state(*, project_id, node_id, db_path=DEFAULT_DB_PATH, assessment_id=None):
    with LearningRepository(db_path) as repo:
        node = repo.get_node(project_id=project_id, node_id=node_id)
        if node is None:
            raise ValueError(f"项目 {project_id} 中不存在节点 {node_id}")
        if assessment_id:
            record = repo.get_assessment(assessment_id)
        else:
            records = repo.list_recent_graded_assessments(
                project_id=project_id, node_id=node_id, limit=1,
            )
            record = records[0] if records else None
        if record is None:
            raise ValueError(
                "该节点没有有效的已评分测验。请先在 day6_restore_demo.py 中完成答题，"
                "再使用相同项目和节点 ID 运行本演示；空试卷演示记录不能用于真实诊断。"
            )
        if (record["project_id"] != project_id or record["node_id"] != node_id
                or record["status"] != "graded"):
            raise ValueError("测验必须是当前项目、当前节点的已评分测验")
        quiz = AssessmentQuiz.model_validate(record["quiz"])
        evaluation = AssessmentEvaluation.model_validate(record["evaluation"])
        if quiz.assessment_id != record["id"]:
            raise ValueError("试卷 ID 与数据库测验 ID 不一致")
        validate_quiz_against_node(quiz, SkillNode.model_validate({
            key: value for key, value in node.items() if key not in {"project_id", "sort_order"}
        }))
        score_summary = validate_and_score_evaluation(quiz, evaluation)
        tree = repo.get_tree(project_id)
    return {
        "project_id": project_id, "learning_db_path": str(Path(db_path).resolve()),
        "current_node_id": node_id, "tree": tree,
        "assessment_id": record["id"], "quiz": quiz.model_dump(),
        "evaluation": evaluation.model_dump(), "score_summary": score_summary,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-id", default="day6_demo_project")
    parser.add_argument("--node-id", default="python_variables")
    parser.add_argument("--assessment-id", help="默认使用该节点最新的有效已评分测验")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    args = parser.parse_args(argv)
    try:
        state = load_diagnosis_state(
            project_id=args.project_id, node_id=args.node_id, db_path=args.db_path,
            assessment_id=args.assessment_id,
        )
    except (ValueError, sqlite3.Error) as exc:
        print(f"无法开始诊断：{exc}")
        return 1
    print(f"项目：{state['project_id']}；节点：{state['current_node_id']}")
    print(f"当前测验：{state['assessment_id']}；成绩：{state['score_summary']['percentage']:.2f}%")
    print("\n" + "=" * 70 + "\n阶段 1：真实 Tool Loop\n" + "=" * 70)
    tool_result = run_diagnosis_tool_loop(state)
    for log in tool_result["tool_logs"]:
        print("\n模型选择：", log["tool_name"])
        print("参数：", log["tool_args"])
        pprint(log["result"], sort_dicts=False)

    print("\n" + "=" * 70 + "\n阶段 2：构造真实证据池\n" + "=" * 70)
    evidence_registry = build_diagnosis_evidence_registry(state, tool_result["tool_logs"])
    for evidence_id in evidence_registry:
        print("有效证据：", evidence_id)
    execution_summary = build_tool_execution_summary(tool_result)
    print("\n工具执行摘要：")
    pprint(execution_summary, sort_dicts=False)

    print("\n" + "=" * 70 + "\n阶段 3：生成最终 DiagnosisResult\n" + "=" * 70)
    diagnosis = generate_final_diagnosis(
        state, evidence_registry=evidence_registry, tool_execution_summary=execution_summary,
    )
    pprint(diagnosis.model_dump(), sort_dicts=False)
    assert all(evidence_id in evidence_registry for evidence_id in diagnosis.evidence_ids)
    print("\n真实诊断完成，全部引用已通过证据检查。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
