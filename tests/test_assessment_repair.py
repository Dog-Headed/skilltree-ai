import runpy
from copy import deepcopy
from pathlib import Path

import pytest
from langchain_core.exceptions import OutputParserException
from pydantic import ValidationError

import app.agents.assessment as assessment
from app.db.repository import LearningRepository
from app.services.llm import ModelCallBudget, ModelOutputValidationError
from tests.test_acceptance_regressions import make_quiz, node as valid_node


REAL_GENERATE_QUIZ = assessment.generate_quiz


@pytest.fixture
def valid_quiz(valid_node):
    return make_quiz(valid_node, "assessment_repair", "新情境")


class FakeStructuredModel:
    def __init__(self, outcomes, before_call=None):
        self.outcomes = list(outcomes)
        self.messages = []
        self.before_call = before_call

    @property
    def call_count(self):
        return len(self.messages)

    def with_structured_output(self, schema, **kwargs):
        assert schema is assessment.AssessmentQuiz
        assert kwargs == {"method": "json_mode"}
        return self

    def invoke(self, messages):
        self.messages.append(messages)
        if self.before_call:
            self.before_call()
        outcome = self.outcomes[self.call_count - 1]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def generate(node, quiz, model, *, old_prompts=None, budget=None):
    return assessment.generate_quiz_with_governance(
        node=node, assessment_id=quiz.assessment_id,
        previous_question_prompts=old_prompts or [],
        structured_llm=model, budget=budget,
    )


def test_invalid_objective_repairs_once(valid_node, valid_quiz):
    invalid = valid_quiz.model_copy(deep=True)
    invalid.questions[0].objective_id = "ghost_objective"
    model = FakeStructuredModel([invalid, valid_quiz])
    budget = ModelCallBudget()
    assert generate(valid_node, valid_quiz, model, budget=budget) == valid_quiz
    assert model.call_count == budget.request_count == 2
    assert budget.output_repair_count == 1
    assert budget.network_retry_count == 0
    assert model.messages[0] == model.messages[1][:2]
    prompt = model.messages[1][-1].content
    assert "ghost_objective" in prompt
    assert valid_quiz.assessment_id in prompt
    assert valid_node.id in prompt
    assert "默认生成 4 道题" in model.messages[0][1].content
    assert "JSON Schema" in model.messages[0][1].content


def test_old_question_repairs_once(valid_node, valid_quiz):
    old_prompt = valid_quiz.questions[0].prompt
    repaired = valid_quiz.model_copy(deep=True)
    repaired.questions[0].prompt = "分析 total = total + item 的一个全新案例"
    model = FakeStructuredModel([valid_quiz, repaired])
    budget = ModelCallBudget()
    result = generate(valid_node, valid_quiz, model, old_prompts=[old_prompt], budget=budget)
    assert result == repaired
    assert model.call_count == budget.request_count == 2
    assert budget.output_repair_count == 1
    assert old_prompt in model.messages[0][1].content
    assert "复测试卷重复了旧题" in model.messages[1][-1].content


def test_timeout_old_question_then_repair_shares_three_requests(valid_node, valid_quiz):
    repaired = valid_quiz.model_copy(deep=True)
    repaired.questions[0].prompt = "分析一个新的列表遍历案例"
    model = FakeStructuredModel([TimeoutError("超时"), valid_quiz, repaired, valid_quiz])
    budget = ModelCallBudget()
    assert generate(
        valid_node, valid_quiz, model, old_prompts=[valid_quiz.questions[0].prompt], budget=budget,
    ) == repaired
    assert model.call_count == budget.request_count == 3
    assert budget.network_retry_count == budget.output_repair_count == 1
    assert model.messages[0] == model.messages[1]


def test_timeout_and_failed_repair_never_make_fourth_request(valid_node, valid_quiz):
    model = FakeStructuredModel([TimeoutError("超时"), valid_quiz, valid_quiz, valid_quiz])
    budget = ModelCallBudget()
    with pytest.raises(ModelOutputValidationError, match="重复了旧题"):
        generate(
            valid_node, valid_quiz, model, old_prompts=[valid_quiz.questions[0].prompt], budget=budget,
        )
    assert model.call_count == budget.request_count == 3
    assert budget.network_retry_count == budget.output_repair_count == 1


@pytest.mark.parametrize("problem", [
    "objective", "assessment_id", "node_id", "duplicate_prompt", "duplicate_id",
    "coverage", "answer_key", "options", "infinite_max_score", "empty_prompt",
])
def test_continuous_invalid_output_stops_after_two_requests(valid_node, valid_quiz, problem):
    invalid = valid_quiz.model_copy(deep=True)
    if problem == "objective":
        invalid.questions[0].objective_id = "ghost_objective"
    elif problem == "assessment_id":
        invalid.assessment_id = "wrong_assessment"
    elif problem == "node_id":
        invalid.node_id = "wrong_node"
    elif problem == "duplicate_prompt":
        invalid.questions[0].prompt = "  ＬＯＯＰ \n Test "
        invalid.questions[1].prompt = "looptest"
    elif problem == "duplicate_id":
        invalid.questions[1].id = invalid.questions[0].id
    elif problem == "coverage":
        for question in invalid.questions:
            question.objective_id = valid_node.objectives[0].id
    elif problem == "answer_key":
        invalid.questions[0].type = "single_choice"
        invalid.questions[0].options = ["赋值", "比较"]
        invalid.questions[0].answer_key = "不存在的选项"
    elif problem == "options":
        invalid.questions[0].type = "single_choice"
        invalid.questions[0].options = ["赋值", "赋值"]
        invalid.questions[0].answer_key = "赋值"
    elif problem == "infinite_max_score":
        invalid.questions[0].max_score = float("inf")
    elif problem == "empty_prompt":
        invalid.questions[0].prompt = " \n "
    model = FakeStructuredModel([invalid, invalid, valid_quiz])
    budget = ModelCallBudget()
    with pytest.raises(ModelOutputValidationError):
        generate(valid_node, valid_quiz, model, budget=budget)
    assert model.call_count == budget.request_count == 2
    assert budget.output_repair_count == 1
    assert budget.network_retry_count == 0


@pytest.mark.parametrize("failure_type", ["json", "pydantic"])
def test_structured_parsing_failures_can_be_repaired(valid_node, valid_quiz, failure_type):
    if failure_type == "json":
        failure = OutputParserException("非法 JSON")
    else:
        with pytest.raises(ValidationError) as captured:
            assessment.AssessmentQuiz.model_validate({"questions": []})
        failure = captured.value
    model = FakeStructuredModel([failure, valid_quiz])
    budget = ModelCallBudget()
    assert generate(valid_node, valid_quiz, model, budget=budget) == valid_quiz
    assert model.call_count == budget.request_count == 2
    assert budget.output_repair_count == 1
    assert "结构化输出失败" in model.messages[1][-1].content


def test_parse_and_business_errors_share_one_repair(valid_node, valid_quiz):
    invalid = valid_quiz.model_copy(deep=True)
    invalid.questions[0].objective_id = "ghost_objective"
    model = FakeStructuredModel([OutputParserException("非法 JSON"), invalid, valid_quiz])
    budget = ModelCallBudget()
    with pytest.raises(ModelOutputValidationError, match="ghost_objective"):
        generate(valid_node, valid_quiz, model, budget=budget)
    assert model.call_count == budget.request_count == 2
    assert budget.output_repair_count == 1


def prepared_state(tmp_path, node, assessment_id, *, other_node=None):
    path = tmp_path / "learning.sqlite"
    state = {
        "project_id": "assessment_project", "learning_db_path": str(path),
        "tree": [node.model_dump()] + ([other_node.model_dump()] if other_node else []),
        "current_node_id": node.id,
        "assessment_id": assessment_id, "assessment_round_no": 1,
    }
    with LearningRepository(path) as repo:
        repo.create_project_with_tree(project_id=state["project_id"], goal="学习循环", tree=state["tree"])
        repo.create_prepared_assessment(
            assessment_id=assessment_id, project_id=state["project_id"], node_id=node.id, round_no=1,
        )
    return state


def install_node_model(monkeypatch, model):
    monkeypatch.setattr(assessment, "generate_quiz", REAL_GENERATE_QUIZ)
    monkeypatch.setattr(assessment, "get_llm", lambda: model)


def test_invalid_quiz_never_becomes_a_business_fact(tmp_path, monkeypatch, valid_node, valid_quiz):
    state = prepared_state(tmp_path, valid_node, valid_quiz.assessment_id)
    unchanged = deepcopy(state)
    invalid = valid_quiz.model_copy(deep=True)
    invalid.questions[0].objective_id = "ghost_objective"
    model = FakeStructuredModel([invalid, invalid, valid_quiz])
    install_node_model(monkeypatch, model)
    with pytest.raises(ModelOutputValidationError, match="ghost_objective"):
        assessment.assessment_generate_node(state)
    assert state == unchanged
    assert model.call_count == 2
    with LearningRepository(state["learning_db_path"]) as repo:
        record = repo.get_assessment(valid_quiz.assessment_id)
        assert record["quiz"] is record["answers"] is record["evaluation"] is record["diagnosis"] is None
        assert record["status"] == "prepared"
        assert repo.conn.execute("SELECT COUNT(*) FROM assessments").fetchone()[0] == 1


def test_repaired_quiz_is_saved_once_and_reused_without_model(
    tmp_path, monkeypatch, valid_node, valid_quiz,
):
    state = prepared_state(tmp_path, valid_node, valid_quiz.assessment_id)
    invalid = valid_quiz.model_copy(deep=True)
    invalid.questions[0].objective_id = "ghost_objective"

    def assert_not_saved():
        with LearningRepository(state["learning_db_path"]) as repo:
            assert repo.get_assessment(valid_quiz.assessment_id)["quiz"] is None

    model = FakeStructuredModel([invalid, valid_quiz], before_call=assert_not_saved)
    install_node_model(monkeypatch, model)
    result = assessment.assessment_generate_node(state)
    assert model.call_count == 2
    assert result["assessment_id"] == valid_quiz.assessment_id
    assert result["assessment_round_no"] == 1
    assert result["quiz"] == valid_quiz.model_dump()
    state.update(result)
    # 模型替身已没有后续结果，再次执行会在任何额外调用时失败。
    restored = assessment.assessment_generate_node(state)
    assert restored["quiz"] == result["quiz"]
    assert restored["assessment_history"] == result["assessment_history"]
    assert model.call_count == 2
    with LearningRepository(state["learning_db_path"]) as repo:
        assert repo.get_assessment(valid_quiz.assessment_id)["quiz"] == valid_quiz.model_dump()
        assert repo.conn.execute("SELECT COUNT(*) FROM assessments").fetchone()[0] == 1


def test_database_history_prevents_repeats_when_state_history_is_empty(
    tmp_path, monkeypatch, valid_node, valid_quiz,
):
    state = prepared_state(tmp_path, valid_node, valid_quiz.assessment_id)
    old = valid_quiz.model_copy(deep=True)
    old.assessment_id = "old_abandoned"
    old.questions[0].prompt = "此前展示过的题目"
    old.questions[0].answer_key = "SECRET_PERSISTED_ANSWER"
    old.questions[0].rubric = "SECRET_PERSISTED_RUBRIC"
    with LearningRepository(state["learning_db_path"]) as repo:
        repo.create_prepared_assessment(
            assessment_id=old.assessment_id, project_id=state["project_id"], node_id=valid_node.id, round_no=2,
        )
        repo.save_quiz_if_absent(assessment_id=old.assessment_id, quiz=old.model_dump())
        with repo.conn:
            repo.conn.execute("UPDATE assessments SET status='abandoned' WHERE id=?", (old.assessment_id,))
    repeated = valid_quiz.model_copy(deep=True)
    for index, question in enumerate(repeated.questions):
        question.prompt = old.questions[index].prompt
    repaired = make_quiz(valid_node, valid_quiz.assessment_id, "全新的应用情境")
    model = FakeStructuredModel([repeated, repaired])
    install_node_model(monkeypatch, model)
    result = assessment.assessment_generate_node(state)
    assert model.call_count == 2
    assert result["quiz"] == repaired.model_dump()
    assert "此前展示过的题目" in model.messages[0][1].content
    assert "SECRET_PERSISTED" not in str(model.messages)
    assert "answer_key" not in str(result["assessment_history"])
    assert "rubric" not in str(result["assessment_history"])


def test_previous_quiz_query_is_scoped_and_includes_ungraded_and_abandoned(
    tmp_path, valid_node, valid_quiz,
):
    other_node = valid_node.model_copy(deep=True)
    other_node.id = "other_node"
    state = prepared_state(tmp_path, valid_node, valid_quiz.assessment_id, other_node=other_node)
    with LearningRepository(state["learning_db_path"]) as repo:
        repo.create_project_with_tree(
            project_id="other_project", goal="另一个项目", tree=[valid_node.model_dump(), other_node.model_dump()],
        )
        cases = [
            ("ungraded", state["project_id"], valid_node, "awaiting_answer"),
            ("abandoned", state["project_id"], valid_node, "abandoned"),
            ("another_project", "other_project", valid_node, "awaiting_answer"),
            ("another_node", state["project_id"], other_node, "awaiting_answer"),
        ]
        for index, (record_id, project_id, node, status) in enumerate(cases, 2):
            quiz = make_quiz(node, record_id, record_id)
            repo.create_prepared_assessment(
                assessment_id=record_id, project_id=project_id, node_id=node.id, round_no=index,
            )
            repo.save_quiz_if_absent(assessment_id=record_id, quiz=quiz.model_dump())
            with repo.conn:
                repo.conn.execute("UPDATE assessments SET status=?, created_at=? WHERE id=?", (status, "2026-10-11", record_id))
        repo.save_quiz_if_absent(assessment_id=valid_quiz.assessment_id, quiz=valid_quiz.model_dump())
        records = repo.list_previous_quizzes(
            project_id=state["project_id"], node_id=valid_node.id,
            exclude_assessment_id=valid_quiz.assessment_id,
        )
        assert [record["assessment_id"] for record in records] == ["abandoned", "ungraded"]
        assert len(repo.list_previous_quizzes(
            project_id=state["project_id"], node_id=valid_node.id,
            exclude_assessment_id=valid_quiz.assessment_id, limit=1,
        )) == 1
        with pytest.raises(ValueError, match="limit"):
            repo.list_previous_quizzes(
                project_id=state["project_id"], node_id=valid_node.id,
                exclude_assessment_id=valid_quiz.assessment_id, limit=4,
            )


def test_broken_legacy_quiz_does_not_hide_older_questions(tmp_path, valid_node, valid_quiz):
    state = prepared_state(tmp_path, valid_node, valid_quiz.assessment_id)
    with LearningRepository(state["learning_db_path"]) as repo:
        for index in range(2, 7):
            quiz = make_quiz(valid_node, f"quiz_{index}", f"第 {index} 轮")
            repo.create_prepared_assessment(
                assessment_id=quiz.assessment_id, project_id=state["project_id"], node_id=valid_node.id, round_no=index,
            )
            repo.save_quiz_if_absent(assessment_id=quiz.assessment_id, quiz=quiz.model_dump())
        with repo.conn:
            repo.conn.execute("UPDATE assessments SET quiz_json='{' WHERE id='quiz_6'")
        records = repo.list_previous_quizzes(
            project_id=state["project_id"], node_id=valid_node.id,
            exclude_assessment_id=valid_quiz.assessment_id,
        )
        assert [record["assessment_id"] for record in records] == ["quiz_5", "quiz_4", "quiz_3"]


@pytest.mark.parametrize("demo_name", ["assessment_demo.py", "grading_demo.py"])
def test_standalone_demos_prepare_stable_ids_before_generating(monkeypatch, demo_name):
    monkeypatch.setattr(
        assessment, "generate_quiz",
        lambda node, assessment_id, **kwargs: make_quiz(node, assessment_id, "演示题"),
    )
    namespace = runpy.run_path(str(Path(__file__).resolve().parents[1] / demo_name))
    state = namespace["state"]
    with assessment.repository_for_state(state) as repo:
        record = repo.get_assessment(namespace["result"]["assessment_id"] if demo_name == "assessment_demo.py" else state["assessment_id"])
        assert record["project_id"] == state["project_id"]
        assert record["quiz"] is not None
        assert record["status"] == ("awaiting_answer" if demo_name == "assessment_demo.py" else "graded")
