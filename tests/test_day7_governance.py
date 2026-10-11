import json
from types import SimpleNamespace

import pytest
from langchain_core.exceptions import OutputParserException
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command

import app.agents.assessment as assessment
import app.agents.diagnosis as diagnosis
import app.agents.tutor as tutor
from app.db.repository import repository_for_state
from app.graph import build_graph, can_advance, extend_round_limit_node, route_after_diagnosis
from app.models.schemas import AssessmentEvaluation, QuestionEvaluation, validate_and_score_evaluation
from app.services.llm import ModelCallBudget, ModelOutputValidationError
from app.services.learning_session import open_learning_session
from app.services.learning_session import LearningSession
from tests.conftest import make_fake_plan


REAL_GRADE = assessment.grade_short_answer
REAL_TUTOR = tutor.generate_tutor_content


class FakeModel:
    def __init__(self, outcomes):
        self.outcomes = iter(outcomes)
        self.messages = []

    def with_structured_output(self, schema, *, method):
        return self

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        self.messages.append(list(messages))
        outcome = next(self.outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def grade(score=25.0):
    return {"score": score, "error_tags": [], "evidence": "学生正确解释赋值", "feedback": "正确"}


def question():
    return {"id": "q1", "prompt": "解释赋值", "answer_key": "用 = 赋值", "rubric": "正确说明作用", "max_score": 25.0}


@pytest.mark.parametrize("bad", [-1.0, 26.0, float("nan"), float("inf"), -float("inf")])
def test_short_answer_score_repaired_in_shared_budget(bad):
    model = FakeModel([grade(bad), grade()])
    budget = ModelCallBudget()
    result = REAL_GRADE(question(), "用 = 赋值", structured_llm=model, budget=budget)
    assert result.score == 25
    assert budget.request_count == 2 and budget.output_repair_count == 1
    assert "评分" in model.messages[1][-1].content or "得分" in model.messages[1][-1].content


@pytest.mark.parametrize("outcomes, count", [
    ([TimeoutError("timeout"), grade()], 2),
    ([TimeoutError("timeout"), grade(26), grade()], 3),
    ([grade(26), ConnectionError("network"), grade()], 3),
    ([OutputParserException("bad JSON"), grade()], 2),
])
def test_short_answer_network_and_output_share_budget(outcomes, count):
    model = FakeModel(outcomes)
    budget = ModelCallBudget()
    assert REAL_GRADE(question(), "答案", structured_llm=model, budget=budget).score == 25
    assert len(model.messages) == budget.request_count == count


@pytest.mark.parametrize("bad", [-1.0, 26.0, float("nan"), float("inf")])
def test_invalid_score_never_saved_or_unlocks(monkeypatch, bad, answers_for_quiz):
    model = FakeModel([grade(bad), grade(bad)])
    monkeypatch.setattr(assessment, "grade_short_answer", lambda q, a: REAL_GRADE(q, a, structured_llm=model))
    graph = build_graph()
    config = {"configurable": {"thread_id": "bad-grade"}, "recursion_limit": 30}
    graph.invoke({"project_id": "bad-grade", "goal": "学习变量"}, config=config)
    result = graph.invoke(Command(resume={"action": "start_quiz"}), config=config)
    with pytest.raises(ModelOutputValidationError):
        graph.invoke(Command(resume={"action": "submit_answer", "answers": answers_for_quiz(result["quiz"])}), config=config)
    saved = graph.get_state(config)
    assert saved.next == ("assessment_grade",)
    with repository_for_state(saved.values) as repo:
        record = repo.get_assessment(result["assessment_id"])
        assert record["evaluation"] is record["diagnosis"] is None
        assert not repo.get_progress(project_id="bad-grade", node_id="variables")["completed_at"]
    assert len(model.messages) == 2
    assert not saved.values.get("rounds_by_node")


def diagnosis_state():
    return {"project_id": "diagnosis-governance", "assessment_id": "test", "current_node_id": "lists",
            "tree": make_fake_plan().model_dump()["nodes"]}


def final_result(**changes):
    return {"weak_points": ["索引理解"], "evidence_ids": ["assessment:test:q1"],
            "recommended_action": "remediate", "reason": "答案混淆索引", "review_node_id": None, **changes}


@pytest.mark.parametrize("bad", [
    {"evidence_ids": ["forged"]},
    {"recommended_action": "revisit_prerequisite", "review_node_id": "practice"},
    {"recommended_action": "invented_action"},
    {"extra": "forbidden"},
])
def test_diagnosis_repairs_structure_and_business(bad):
    model = FakeModel([final_result(**bad), final_result()])
    budget = ModelCallBudget()
    trace = []
    result = diagnosis.generate_final_diagnosis(diagnosis_state(), evidence_registry={"assessment:test:q1": {}},
                                                llm=model, budget=budget, attempt_records=trace)
    assert result.recommended_action == "remediate"
    assert budget.request_count == 2 and budget.output_repair_count == 1
    assert trace[-1]["structure_valid"] and trace[-1]["business_valid"]
    assert "校验" in model.messages[1][-1].content


@pytest.mark.parametrize("outcomes, count", [
    ([TimeoutError(), final_result()], 2),
    ([TimeoutError(), final_result(evidence_ids=["forged"]), final_result()], 3),
    ([final_result(evidence_ids=["forged"]), ConnectionError(), final_result()], 3),
])
def test_final_diagnosis_network_output_combination(outcomes, count):
    model, budget = FakeModel(outcomes), ModelCallBudget()
    result = diagnosis.generate_final_diagnosis(diagnosis_state(), evidence_registry={"assessment:test:q1": {}}, llm=model, budget=budget)
    assert result.recommended_action == "remediate"
    assert budget.request_count == len(model.messages) == count


def test_tool_http_retry_does_not_reset_execution_limit(tool_database):
    def call(number):
        return {"name": "get_node_material", "args": {"node_id": "python_variables"}, "id": f"call-{number}"}
    model = FakeModel([TimeoutError(), AIMessage(content="", tool_calls=[call(1), call(2)]),
                       AIMessage(content="", tool_calls=[call(3), call(4)])])
    state = {"project_id": "demo_project", "current_node_id": "python_variables", "assessment_id": "current",
             "tree": [{"id": "python_basics", "prerequisite_ids": []}, {"id": "python_variables", "prerequisite_ids": ["python_basics"]}]}
    result = diagnosis.run_diagnosis_tool_loop(state, llm=model)
    assert len(model.messages) == 3
    assert result["tool_round_count"] == 2 and result["tool_call_count"] == 3
    assert sum(log["executed"] for log in result["tool_logs"]) == 3
    assert result["tool_logs"][-1]["result"]["error_type"] == "tool_limit_exceeded"


def test_invalid_diagnosis_never_saved_or_unlocks(monkeypatch, answers_for_quiz):
    model = FakeModel([final_result(evidence_ids=["forged"])] * 2)
    def governed(state):
        return diagnosis.generate_final_diagnosis(state, evidence_registry=diagnosis.build_current_assessment_evidence(state), llm=model)
    monkeypatch.setattr(diagnosis, "run_real_diagnosis", governed)
    graph = build_graph()
    config = {"configurable": {"thread_id": "bad-diagnosis"}, "recursion_limit": 30}
    graph.invoke({"project_id": "bad-diagnosis", "goal": "学习变量"}, config=config)
    result = graph.invoke(Command(resume={"action": "start_quiz"}), config=config)
    with pytest.raises(ModelOutputValidationError, match="forged"):
        graph.invoke(Command(resume={"action": "submit_answer", "answers": answers_for_quiz(result["quiz"])}), config=config)
    saved = graph.get_state(config)
    assert saved.next == ("diagnosis",)
    with repository_for_state(saved.values) as repo:
        record = repo.get_assessment(result["assessment_id"])
        assert record["evaluation"] is not None and record["diagnosis"] is None
        assert not repo.get_progress(project_id="bad-diagnosis", node_id="variables")["completed_at"]
    assert len(model.messages) == 2


@pytest.mark.parametrize("damage", ["missing", "duplicate", "identity", "nan", "over"])
def test_complete_evaluation_validator_and_advance_guard(damage, answers_for_quiz):
    graph = build_graph()
    config = {"configurable": {"thread_id": f"boundary-{damage}"}}
    graph.invoke({"goal": "变量"}, config=config)
    result = graph.invoke(Command(resume={"action": "start_quiz"}), config=config)
    quiz = assessment.AssessmentQuiz.model_validate(result["quiz"])
    evaluation = AssessmentEvaluation(assessment_id=quiz.assessment_id, question_results=[
        QuestionEvaluation(question_id=q.id, score=q.max_score, evidence="正确", feedback="正确") for q in quiz.questions
    ])
    if damage == "missing":
        evaluation.question_results.pop()
    elif damage == "duplicate":
        evaluation.question_results.append(evaluation.question_results[0])
    elif damage == "identity":
        evaluation.assessment_id = "wrong"
    else:
        evaluation.question_results[0].score = float("nan") if damage == "nan" else 1000.0
    with pytest.raises(ValueError):
        validate_and_score_evaluation(quiz, evaluation)
    assert not can_advance({**result, "evaluation": evaluation.model_dump(), "score_summary": {"percentage": 100.0}})


@pytest.mark.parametrize("damage", ["missing", "duplicate", "identity"])
def test_malformed_aggregate_evaluation_never_saved(monkeypatch, damage, answers_for_quiz):
    original = assessment.grade_quiz
    def malformed(quiz, answers):
        evaluation = original(quiz, answers)
        if damage == "missing":
            evaluation.question_results.pop()
        elif damage == "duplicate":
            evaluation.question_results.append(evaluation.question_results[0])
        else:
            evaluation.assessment_id = "wrong"
        return evaluation
    monkeypatch.setattr(assessment, "grade_quiz", malformed)
    graph = build_graph()
    config = {"configurable": {"thread_id": f"aggregate-{damage}"}, "recursion_limit": 30}
    graph.invoke({"goal": "变量", "project_id": f"aggregate-{damage}"}, config=config)
    result = graph.invoke(Command(resume={"action": "start_quiz"}), config=config)
    with pytest.raises(ValueError):
        graph.invoke(Command(resume={"action": "submit_answer", "answers": answers_for_quiz(result["quiz"])}), config=config)
    with repository_for_state(result) as repo:
        assert repo.get_assessment(result["assessment_id"])["evaluation"] is None
        assert not repo.get_progress(project_id=result["project_id"], node_id="variables")["completed_at"]


@pytest.mark.parametrize("action", ["remediate", "collect_more_evidence", "revisit_prerequisite", "advance"])
def test_round_limit_checked_after_advance_guard(action):
    state = {"current_node_id": "variables", "rounds_by_node": {"variables": 3},
             "diagnosis": {"recommended_action": action}}
    assert route_after_diagnosis(state) == "pause"


@pytest.mark.parametrize("pass_third", [False, True])
def test_third_round_pause_or_advance(mock_assessment_grade_llm, answers_for_quiz, pass_third):
    graph = build_graph()
    config = {"configurable": {"thread_id": f"third-{pass_third}"}, "recursion_limit": 30}
    result = graph.invoke({"goal": "变量"}, config=config)
    mock_assessment_grade_llm["score_ratio"] = 0.5
    for index in range(3):
        result = graph.invoke(Command(resume={"action": "start_quiz"}), config=config)
        if index == 2 and pass_third:
            mock_assessment_grade_llm["score_ratio"] = 1.0
        result = graph.invoke(Command(resume={"action": "submit_answer", "answers": answers_for_quiz(result["quiz"])}), config=config)
    assert result["rounds_by_node"]["variables"] == 3
    assert result["__interrupt__"][0].value["type"] == ("wait_learning" if pass_third else "pause")
    assert result["current_node_id"] == ("lists" if pass_third else "variables")


def test_pause_rest_resume_and_extend_once(tmp_path, monkeypatch, mock_assessment_grade_llm, answers_for_quiz):
    paths = {"learning_db_path": tmp_path / "business.sqlite", "checkpoint_db_path": tmp_path / "cp.sqlite"}
    with open_learning_session("pause", **paths) as session:
        assert session.config["recursion_limit"] == 30
        session.start("变量")
        mock_assessment_grade_llm["score_ratio"] = 0.5
        for _ in range(3):
            result = session.resume({"action": "start_quiz"})
            result = session.resume({"action": "submit_answer", "answers": answers_for_quiz(result["quiz"])})
        token = result["pending_input_id"]
    # 关闭连接后重新建立 Saver，restore 和休息均不允许调用任何 Agent。
    def forbidden(*args, **kwargs):
        raise AssertionError("暂停不应调用模型")
    with monkeypatch.context() as patch:
        for module, attr in [(tutor, "generate_tutor_content"), (assessment, "generate_quiz"), (diagnosis, "run_real_diagnosis")]:
            patch.setattr(module, attr, forbidden)
        with open_learning_session("pause", **paths) as session:
            restored = session.restore()
            assert restored["__interrupt__"][0].value["type"] == "pause"
            rested = session.resume({"action": "rest", "pending_input_id": token})
            assert rested["pending_input_id"] == token
            assert rested["round_limit_by_node"]["variables"] == 3
            invalid = session.resume({"action": "retry_3", "pending_input_id": "stale"})
            assert invalid["__interrupt__"][0].value["type"] == "pause"
    with open_learning_session("pause", **paths) as session:
        result = session.resume({"action": "retry_3", "pending_input_id": token})
        assert result["round_limit_by_node"]["variables"] == 6
        assert result["rounds_by_node"]["variables"] == 3
        replay = {**result, "pending_input_id": token, "user_event": {"action": "retry_3", "pending_input_id": token}}
        assert extend_round_limit_node(replay) == {}
        assert result["round_limit_by_node"]["lists"] == 3
    with open_learning_session("pause", **paths) as session:
        assert session.restore()["round_limit_by_node"]["variables"] == 6


def test_downstream_failure_retry_does_not_extend_again(tmp_path, monkeypatch, mock_assessment_grade_llm, answers_for_quiz):
    paths = {"learning_db_path": tmp_path / "business.sqlite", "checkpoint_db_path": tmp_path / "cp.sqlite"}
    with open_learning_session("extend-failure", **paths) as session:
        session.start("变量")
        mock_assessment_grade_llm["score_ratio"] = 0.5
        for _ in range(3):
            result = session.resume({"action": "start_quiz"})
            result = session.resume({"action": "submit_answer", "answers": answers_for_quiz(result["quiz"])})
        token = result["pending_input_id"]
        with monkeypatch.context() as patch:
            def fail(*args):
                raise RuntimeError("增加额度后的 Tutor 故障")
            patch.setattr(tutor, "generate_tutor_content", fail)
            with pytest.raises(RuntimeError):
                session.resume({"action": "retry_3", "pending_input_id": token})
        assert session.snapshot().next == ("tutor",)
        assert session.restore()["round_limit_by_node"]["variables"] == 6
    with open_learning_session("extend-failure", **paths) as session:
        result = session.retry()
        assert result["round_limit_by_node"]["variables"] == 6
        assert result["rounds_by_node"]["variables"] == 3
        assert result["credited_pause_input_ids"] == [token]


def test_tutor_only_receives_six_complete_current_node_rounds(monkeypatch):
    messages = [HumanMessage(content="old", additional_kwargs={"node_id": "other"}),
                AIMessage(content="other secret", additional_kwargs={"node_id": "other"})]
    for i in range(10):
        messages.extend([HumanMessage(content=f"question-{i}", additional_kwargs={"node_id": "variables"}),
                         AIMessage(content=f"answer-{i}", additional_kwargs={"node_id": "variables"})])
    messages.append(HumanMessage(content="incomplete-history"))
    model = FakeModel([AIMessage(content="教学")])
    monkeypatch.setattr(tutor, "get_llm", lambda: model)
    state = {"current_node_id": "variables", "tutor_messages": messages, "quiz": {"answer_key": "private"}}
    REAL_TUTOR(state, make_fake_plan().model_dump()["nodes"][0])
    received = model.messages[0]
    assert [m.content for m in received[:-1]] == [value for i in range(4, 10) for value in (f"question-{i}", f"answer-{i}")]
    assert "private" not in str(received)


def test_structured_logs_have_context_counts_and_no_sensitive_text(caplog, monkeypatch, answers_for_quiz):
    model = FakeModel([TimeoutError("sk-sensitive-test"), grade()])
    monkeypatch.setattr(assessment, "grade_short_answer", lambda q, a: REAL_GRADE(q, a, structured_llm=model))
    graph = build_graph()
    config = {"configurable": {"thread_id": "logs"}}
    graph.invoke({"goal": "变量", "project_id": "logs"}, config=config)
    result = graph.invoke(Command(resume={"action": "start_quiz"}), config=config)
    # 测试第一道评分的治理日志即可；后续题目继续使用同样合法替身。
    model.outcomes = iter([TimeoutError("sk-sensitive-test"), *[grade()] * 4])
    with caplog.at_level("INFO", logger="skilltree"):
        graph.invoke(Command(resume={"action": "submit_answer", "answers": answers_for_quiz(result["quiz"])}), config=config)
    records = [json.loads(r.message) for r in caplog.records if r.name == "skilltree"]
    attempts = [r for r in records if r["event"] == "model_attempt"]
    assert attempts[0]["project_id"] == "logs" and attempts[0]["node_id"] == "variables"
    assert attempts[0]["assessment_id"] == result["assessment_id"]
    assert attempts[0]["error_type"] == "TimeoutError"
    assert attempts[1]["request_count"] == 2 and attempts[1]["elapsed_ms"] >= 0
    assert attempts[0]["logical_call_id"] == attempts[1]["logical_call_id"]
    assert "sk-sensitive-test" not in caplog.text


def test_all_session_entrypoints_use_top_level_recursion_limit(tmp_path):
    class RecordingGraph:
        def __init__(self):
            self.state = SimpleNamespace(values={}, interrupts=[], next=())
            self.calls = []

        def get_state(self, config):
            return self.state

        def invoke(self, value, *, config, durability):
            self.calls.append((config, durability))
            return {}

    graph = RecordingGraph()
    session = LearningSession(graph, "limits", tmp_path / "business.sqlite", tmp_path / "checkpoint.sqlite")
    session.start("变量")
    graph.state = SimpleNamespace(values={"project_id": "limits"}, interrupts=["waiting"], next=("pause",))
    session.resume({"action": "rest"})
    graph.state = SimpleNamespace(values={"project_id": "limits"}, interrupts=[], next=("tutor",))
    session.retry()
    assert len(graph.calls) == 3
    for config, durability in graph.calls:
        assert config["recursion_limit"] == 30
        assert "recursion_limit" not in config["configurable"]
        assert durability == "sync"
