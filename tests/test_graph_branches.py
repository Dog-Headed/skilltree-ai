from uuid import uuid4

import pytest
from langgraph.types import Command

import app.graph as graph_module


@pytest.fixture
def branch_graph(monkeypatch):
    # 只控制诊断建议；评分、can_advance、路由和后续节点都用业务实现。
    real_diagnosis_node = graph_module.diagnosis_node

    def controlled_diagnosis_node(state):
        update = real_diagnosis_node(state)
        update["diagnosis"]["recommended_action"] = state["test_action"]
        return update

    monkeypatch.setattr(graph_module, "diagnosis_node", controlled_diagnosis_node)
    return graph_module.build_graph()


def run_to_diagnosis(graph, test_action, answers_for_quiz):
    config = {
        "configurable": {
            "thread_id": f"branch-test-{uuid4()}"
        }
    }

    result = graph.invoke(
        {"goal": "学习 Python", "test_action": test_action},
        config=config,
    )
    assert result["__interrupt__"][0].value["type"] == "wait_learning"

    result = graph.invoke(
        Command(resume={"action": "start_quiz"}),
        config=config,
    )
    assert result["__interrupt__"][0].value["type"] == "wait_answer"
    assert len(result["quiz"]["questions"]) == 4
    assert result["answers"] == {}
    assert result["evaluation"] == {}
    assert result["score_summary"] == {}

    quiz = result["quiz"]
    answers = answers_for_quiz(quiz)
    result = graph.invoke(
        Command(resume={"action": "submit_answer", "answers": answers}),
        config=config,
    )
    return result, config, quiz, answers


@pytest.mark.parametrize(
    "action, expected_result, expected_wait, lesson_mode",
    [
        ("advance", "advance：进入下一个学习节点", None, None),
        ("remediate", "remediate：返回 Tutor 进行补弱", "wait_learning", "remediate"),
        (
            "collect_more_evidence",
            "collect_more_evidence：需要追加测评",
            "wait_answer",
            None,
        ),
        (
            "revisit_prerequisite",
            "revisit_prerequisite：需要复习前置知识",
            "wait_learning",
            "revisit",
        ),
    ],
)
def test_four_valid_branches(
    action, expected_result, expected_wait, lesson_mode, branch_graph, answers_for_quiz
):
    result, config, previous_quiz, answers = run_to_diagnosis(
        branch_graph, action, answers_for_quiz
    )

    assert result["diagnosis"]["recommended_action"] == action
    assert result["branch_result"] == expected_result

    if expected_wait is None:
        assert "__interrupt__" not in result
        assert branch_graph.get_state(config).next == ()
    else:
        assert result["__interrupt__"][0].value["type"] == expected_wait
        assert branch_graph.get_state(config).next == (expected_wait,)

    if action == "collect_more_evidence":
        assert result["assessment_id"] != previous_quiz["assessment_id"]
        assert result["quiz"]["assessment_id"] == result["assessment_id"]
        assert len(result["quiz"]["questions"]) == 4
        assert result["answers"] == {}
        assert result["evaluation"] == {}
        assert result["score_summary"] == {}
    else:
        assert result["answers"] == answers
        assert result["evaluation"]["assessment_id"] == previous_quiz["assessment_id"]
        assert {
            item["question_id"] for item in result["evaluation"]["question_results"]
        } == set(answers)
        assert result["score_summary"]["percentage"] == 100.0

    if lesson_mode is not None:
        assert result["lesson_mode"] == lesson_mode
        # 首次 Tutor 和诊断后的 Tutor 各留下了一条教学消息。
        assert len(result["tutor_messages"]) == 2
        assert result["lesson"] == result["tutor_messages"][-1].content


def test_invalid_action_must_not_advance(branch_graph, answers_for_quiz):
    result, config, _, _ = run_to_diagnosis(
        branch_graph, "fly_to_moon", answers_for_quiz
    )
    assert result["diagnosis"]["recommended_action"] == "fly_to_moon"
    assert result["branch_result"] == "invalid：Diagnosis 返回了非法行动"
    assert "__interrupt__" not in result
    assert branch_graph.get_state(config).next == ()


@pytest.mark.parametrize(
    "score_ratio, error_tags",
    [
        (0.6, []),
        (1.0, ["critical_error"]),
        (1.0, ["fundamental_misunderstanding"]),
    ],
)
def test_advance_recommendation_must_pass_guard(
    score_ratio, error_tags, branch_graph, answers_for_quiz, mock_assessment_grade_llm
):
    mock_assessment_grade_llm.update(
        score_ratio=score_ratio, error_tags=error_tags
    )
    result, config, previous_quiz, _ = run_to_diagnosis(
        branch_graph, "advance", answers_for_quiz
    )

    assert result["diagnosis"]["recommended_action"] == "advance"
    assert result["branch_result"] == "collect_more_evidence：需要追加测评"
    assert result["__interrupt__"][0].value["type"] == "wait_answer"
    assert branch_graph.get_state(config).next == ("wait_answer",)
    assert result["assessment_id"] != previous_quiz["assessment_id"]
    assert result["answers"] == {}
    assert result["evaluation"] == {}
    assert result["score_summary"] == {}
