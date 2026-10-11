import json

import pytest
from langchain_core.messages import AIMessage

from app.agents.diagnosis import (
    build_diagnosis_evidence_registry, build_tool_execution_context, collect_tool_evidence,
)
from app.db.repository import LearningRepository, dump_json
from app.tools.executor import execute_tool_call
from app.tools.history import get_learning_history
from app.tools.knowledge import get_node_material, get_prerequisite_status
from tests.support.tool_database import create_tool_project, save_tool_assessment
from tests.test_tool_execution_summary import (
    REAL_RUN_REAL_DIAGNOSIS, RecordingFinalModel, ToolModel, evidence_from,
    make_state, request_tools, summary_from,
)


def test_current_assessment_is_excluded_before_history_query(tool_database):
    with LearningRepository(tool_database) as repo:
        for number, assessment_id in enumerate(("A", "B", "C"), 1):
            save_tool_assessment(repo, assessment_id, round_no=number)
    state = {**make_state(), "assessment_id": "B", "learning_db_path": str(tool_database)}
    state["evaluation"] = {**state["evaluation"], "assessment_id": "B"}
    result = execute_tool_call(
        tool_name="get_learning_history", tool_args={"node_id": "python_variables"},
        context=build_tool_execution_context(state),
    )
    assert result["status"] == "found"
    assert [record["assessment_id"] for record in result["records"]] == ["C", "A"]
    registry = build_diagnosis_evidence_registry(state, [{"tool_name": "get_learning_history", "result": result}])
    assert registry["assessment:B:q1"]["source"] == "current_assessment"
    assert registry["assessment:A:q1"]["score"] == 0.0
    assert registry["assessment:A:q2"]["score"] == 15.0
    assert registry["assessment:A:q1"]["evidence"] != registry["assessment:A:q2"]["evidence"]


def test_history_is_isolated_between_projects_with_same_node_id(tool_database):
    with LearningRepository(tool_database) as repo:
        create_tool_project(repo, "project_A")
        create_tool_project(repo, "project_B")
        save_tool_assessment(repo, "assessment_A", project_id="project_A")
        save_tool_assessment(repo, "assessment_B", project_id="project_B")
    for project_id, expected in (("project_A", "assessment_A"), ("project_B", "assessment_B")):
        result = get_learning_history(project_id=project_id, node_id="python_variables", db_path=tool_database)
        assert [row["assessment_id"] for row in result["records"]] == [expected]


def test_prerequisite_completion_is_isolated_between_projects(tool_database):
    with LearningRepository(tool_database) as repo:
        create_tool_project(repo, "project_A")
        create_tool_project(repo, "project_B")
        save_tool_assessment(repo, "completed_B", project_id="project_B", node_id="python_basics")
        progress = repo.mark_node_completed(project_id="project_B", node_id="python_basics", assessment_id="completed_B")
    unfinished = get_prerequisite_status(project_id="project_A", node_id="python_variables", db_path=tool_database)
    completed = get_prerequisite_status(project_id="project_B", node_id="python_variables", db_path=tool_database)
    assert unfinished["all_completed"] is False
    assert unfinished["prerequisites"][0]["completion_assessment_id"] is None
    assert completed["all_completed"] is True
    assert completed["prerequisites"][0]["completed_at"] == progress["completed_at"]
    assert completed["prerequisites"][0]["completion_assessment_id"] == "completed_B"


def test_history_ids_survive_reopening_and_private_quiz_is_not_returned(tool_database):
    with LearningRepository(tool_database) as repo:
        save_tool_assessment(repo, "stable_id")
    first = get_learning_history(project_id="demo_project", node_id="python_variables", db_path=tool_database)
    second = get_learning_history(project_id="demo_project", node_id="python_variables", db_path=tool_database)
    assert first == second
    record = first["records"][0]
    assert record["percentage"] == 37.5
    assert record["evidence_ids"] == ["assessment:stable_id:q1", "assessment:stable_id:q2"]
    assert record["error_tags"] == ["assignment_confusion", "incorrect_output"]
    assert len(record["answer_snippets"]["q1"]) <= 160
    serialized = json.dumps(first, ensure_ascii=False)
    for forbidden in ("answer_key", "rubric", "私有参考答案", "私有评分规则", "questions"):
        assert forbidden not in serialized


def test_recent_history_limit_and_order_use_timestamp_then_round(tool_database):
    with LearningRepository(tool_database) as repo:
        for number in range(1, 5):
            save_tool_assessment(repo, f"round_{number}", round_no=number)
        # 第一轮较新，其他记录时间相同；同时验证两个排序条件。
        with repo.conn:
            repo.conn.execute("UPDATE assessments SET created_at = '2026-01-01'")
            repo.conn.execute("UPDATE assessments SET created_at = '2026-01-02' WHERE id = 'round_1'")
    result = get_learning_history(project_id="demo_project", node_id="python_variables", db_path=tool_database)
    assert [record["assessment_id"] for record in result["records"]] == ["round_1", "round_4", "round_3"]
    limited = get_learning_history(project_id="demo_project", node_id="python_variables", limit=1, db_path=tool_database)
    assert [record["assessment_id"] for record in limited["records"]] == ["round_1"]


@pytest.mark.parametrize("damage", ["empty_quiz", "wrong_id", "incomplete_evaluation", "invalid_json", "over_score"])
def test_invalid_legacy_records_do_not_hide_older_valid_history(tool_database, damage):
    with LearningRepository(tool_database) as repo:
        save_tool_assessment(repo, "valid_old")
        for number in range(4):
            record = save_tool_assessment(repo, f"invalid_{number}", round_no=number + 2)
            quiz, evaluation = record["quiz"], record["evaluation"]
            if damage == "empty_quiz":
                quiz["questions"] = []
            elif damage == "wrong_id":
                quiz["assessment_id"] = "foreign_assessment"
            elif damage == "incomplete_evaluation":
                evaluation["question_results"] = evaluation["question_results"][:1]
            elif damage == "over_score":
                evaluation["question_results"][0]["score"] = 1000.0
            with repo.conn:
                repo.conn.execute(
                    "UPDATE assessments SET quiz_json=?, evaluation_json=? WHERE id=?",
                    ("{" if damage == "invalid_json" else dump_json(quiz), dump_json(evaluation), record["id"]),
                )
    result = get_learning_history(project_id="demo_project", node_id="python_variables", db_path=tool_database)
    assert result["status"] == "found"
    assert [record["assessment_id"] for record in result["records"]] == ["valid_old"]


def test_ungraded_and_abandoned_records_are_not_history(tool_database):
    with LearningRepository(tool_database) as repo:
        save_tool_assessment(repo, "valid")
        save_tool_assessment(repo, "abandoned")
        with repo.conn:
            repo.conn.execute("UPDATE assessments SET status='abandoned' WHERE id='abandoned'")
        repo.create_prepared_assessment(assessment_id="pending", project_id="demo_project", node_id="python_variables", round_no=3)
    result = get_learning_history(project_id="demo_project", node_id="python_variables", db_path=tool_database)
    assert [record["assessment_id"] for record in result["records"]] == ["valid"]


@pytest.mark.parametrize("tool", [get_learning_history, get_prerequisite_status, get_node_material])
def test_missing_node_and_database_failure_are_distinct(tool_database, tmp_path, tool):
    missing = tool(project_id="other_project", node_id="python_variables", db_path=tool_database)
    broken = tmp_path / "broken.sqlite"
    broken.write_text("not a database", encoding="utf-8")
    failed = tool(project_id="demo_project", node_id="python_variables", db_path=broken)
    assert missing["ok"] is failed["ok"] is False
    assert missing["status"] == "node_not_found"
    assert failed["status"] == "query_error"
    assert failed["error"]
    assert collect_tool_evidence([{"tool_name": tool.__name__, "result": failed}]) == {}


def test_no_history_no_material_and_no_prerequisites_are_valid_empty_results(tool_database):
    history = get_learning_history(project_id="demo_project", node_id="python_variables", db_path=tool_database)
    material = get_node_material(project_id="demo_project", node_id="python_lists", db_path=tool_database)
    prerequisites = get_prerequisite_status(project_id="demo_project", node_id="python_basics", db_path=tool_database)
    assert history["ok"] is material["ok"] is prerequisites["ok"] is True
    assert history["status"] == "no_history"
    assert material["status"] == "no_material"
    assert prerequisites["prerequisites"] == []
    assert prerequisites["all_completed"] is True
    assert collect_tool_evidence([{"tool_name": "get_node_material", "result": material}]) == {}


@pytest.mark.parametrize("argument,value", [("project_id", "other"), ("exclude_assessment_id", "A"), ("db_path", "other.sqlite")])
def test_model_cannot_override_trusted_context(argument, value):
    result = execute_tool_call(
        tool_name="get_learning_history", tool_args={"node_id": "python_variables", argument: value},
        context=build_tool_execution_context(make_state()),
    )
    assert result["error_type"] == "invalid_arguments"


def test_final_diagnosis_distinguishes_real_empty_database_from_query_failure(tool_database, tmp_path):
    broken = tmp_path / "broken.sqlite"
    broken.write_text("broken", encoding="utf-8")
    summaries = []
    for db_path in (tool_database, broken):
        final = RecordingFinalModel()
        REAL_RUN_REAL_DIAGNOSIS(
            {**make_state(), "learning_db_path": str(db_path)},
            tool_llm=ToolModel([request_tools("history"), AIMessage(content="查询结束")]),
            final_llm=final,
        )
        summaries.append(summary_from(final))
        assert set(evidence_from(final)) == {"assessment:summary_test:q1"}
    assert summaries[0]["calls"][0]["query_status"] == "no_history"
    assert summaries[0]["calls"][0]["status"] == "empty"
    assert summaries[1]["calls"][0]["query_status"] == "query_error"
    assert summaries[1]["calls"][0]["status"] == "failed"
    assert summaries[1]["calls"][0]["error"]


def test_final_model_can_cite_real_history_without_repeating_current_round(tool_database):
    with LearningRepository(tool_database) as repo:
        save_tool_assessment(repo, "old_round")
        current = save_tool_assessment(repo, "summary_test", round_no=2)
    final = RecordingFinalModel(evidence_id="assessment:old_round:q2")
    REAL_RUN_REAL_DIAGNOSIS(
        {**make_state(), "learning_db_path": str(tool_database), "evaluation": current["evaluation"]},
        tool_llm=ToolModel([request_tools("history"), AIMessage(content="查询结束")]),
        final_llm=final,
    )
    evidence = evidence_from(final)
    assert evidence["assessment:old_round:q2"]["source"] == "learning_history"
    assert evidence["assessment:summary_test:q2"]["source"] == "current_assessment"
    assert summary_from(final)["calls"][0]["result_count"] == 1


def test_real_diagnosis_demo_reads_current_assessment_from_database(tool_database):
    from real_diagnosis_demo import load_diagnosis_state

    with LearningRepository(tool_database) as repo:
        save_tool_assessment(repo, "demo_latest", round_no=2)
    state = load_diagnosis_state(project_id="demo_project", node_id="python_variables", db_path=tool_database)
    assert state["assessment_id"] == "demo_latest"
    assert state["score_summary"]["percentage"] == 37.5
    assert state["learning_db_path"] == str(tool_database.resolve())
    assert "assessment_history" not in state
    context = build_tool_execution_context(state)
    result = execute_tool_call(tool_name="get_learning_history", tool_args={"node_id": "python_variables"}, context=context)
    assert result["status"] == "no_history"


def test_real_diagnosis_demo_refuses_fake_or_foreign_assessment(tool_database):
    from real_diagnosis_demo import load_diagnosis_state

    with pytest.raises(ValueError, match="没有有效"):
        load_diagnosis_state(project_id="demo_project", node_id="python_variables", db_path=tool_database)
    with LearningRepository(tool_database) as repo:
        create_tool_project(repo, "other")
        save_tool_assessment(repo, "foreign", project_id="other")
    with pytest.raises(ValueError, match="当前项目"):
        load_diagnosis_state(project_id="demo_project", node_id="python_variables", db_path=tool_database, assessment_id="foreign")
