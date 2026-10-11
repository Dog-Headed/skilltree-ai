import json
import re
from copy import deepcopy
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command

import app.agents.assessment as assessment
import app.agents.tutor as tutor
from app.graph import graph
from app.models.schemas import AssessmentQuiz, SkillNode
from app.db.repository import repository_for_state


# 保存业务函数，避免通用测试夹具把需要验证的模型调用替换掉。
REAL_GENERATE_QUIZ = assessment.generate_quiz
REAL_GENERATE_TUTOR_CONTENT = tutor.generate_tutor_content


@pytest.fixture
def node():
    return SkillNode.model_validate(
        {
            "id": "for_loops",
            "title": "for 循环",
            "description": "遍历列表并累计求和。",
            "objectives": [
                {"id": "traverse", "description": "遍历列表"},
                {"id": "accumulate", "description": "累计求和"},
            ],
            "prerequisite_ids": [],
            "difficulty": "beginner",
            "estimated_minutes": 40,
        }
    )


def make_quiz(node, assessment_id, prefix):
    return AssessmentQuiz.model_validate(
        {
            "assessment_id": assessment_id,
            "node_id": node.id,
            "questions": [
                {
                    "id": f"q{index}",
                    "type": "short_answer",
                    "objective_id": node.objectives[(index - 1) % 2].id,
                    "prompt": f"{prefix}：练习 {index}",
                    "options": None,
                    "answer_key": f"SECRET_OLD_ANSWER_{index}",
                    "rubric": f"SECRET_OLD_RUBRIC_{index}",
                    "max_score": 25.0,
                }
                for index in range(1, 5)
            ],
        }
    )


def make_retest_state(node, prefix="旧题"):
    quiz = make_quiz(node, "assessment_previous", prefix).model_dump()
    state = {
        "project_id": "retest_project",
        "tree": [node.model_dump()],
        "current_node_id": node.id,
        "assessment_id": quiz["assessment_id"],
        "quiz": quiz,
        "answers": {"q1": "旧答案"},
        "evaluation": {
            "assessment_id": quiz["assessment_id"],
            "question_results": [
                {
                    "question_id": f"q{index}",
                    "score": 0.0 if index == 2 else 25.0,
                    "error_tags": ["accumulator_overwritten"] if index == 2 else [],
                    "evidence": "旧评分证据",
                    "feedback": "旧反馈",
                }
                for index in range(1, 5)
            ],
        },
        "diagnosis": {"weak_points": ["accumulator_overwritten"]},
        "score_summary": {"percentage": 75.0},
    }
    with repository_for_state(state) as repo:
        repo.create_project_with_tree(
            project_id=state["project_id"], goal="复测测试", tree=state["tree"]
        )
        repo.create_prepared_assessment(
            assessment_id=quiz["assessment_id"], project_id=state["project_id"],
            node_id=node.id, round_no=1,
        )
        repo.save_quiz_if_absent(assessment_id=quiz["assessment_id"], quiz=quiz)
        repo.save_answers_if_absent(
            assessment_id=quiz["assessment_id"],
            answers={question["id"]: question["answer_key"] for question in quiz["questions"]},
        )
        repo.save_evaluation_if_absent(assessment_id=quiz["assessment_id"], evaluation=state["evaluation"])
    # 稳定的本轮 ID 由准备节点先产生，旧题仍保留供复测上下文使用。
    state.update(assessment.assessment_prepare_node(state))
    return state


class RecordingQuizLLM:
    def __init__(self, node, prefixes, returned_id=None):
        self.node = node
        self.prefixes = prefixes
        self.returned_id = returned_id
        self.prompts = []
        self.messages = []

    def with_structured_output(self, schema, **kwargs):
        assert schema is AssessmentQuiz
        assert kwargs == {"method": "json_mode"}
        return self

    def invoke(self, messages):
        self.messages.append(messages)
        prompt = messages[1].content
        self.prompts.append(prompt)
        expected_id = re.search(r"assessment_id 必须严格使用：\s*(\S+)", prompt).group(1)
        prefix = self.prefixes[min(len(self.prompts) - 1, len(self.prefixes) - 1)]
        quiz = make_quiz(self.node, self.returned_id or expected_id, prefix)
        # 更换题目 ID 不能绕过旧题检查。
        for index, question in enumerate(quiz.questions, 1):
            question.id = f"new_q{index}"
        return quiz


def install_quiz_llm(monkeypatch, node, prefixes, returned_id=None):
    llm = RecordingQuizLLM(node, prefixes, returned_id)
    monkeypatch.setattr(assessment, "generate_quiz", REAL_GENERATE_QUIZ)
    monkeypatch.setattr(assessment, "get_llm", lambda: llm)
    return llm


def extract_retest_context(prompt):
    return json.JSONDecoder().raw_decode(prompt.split("复测上下文：", 1)[1].lstrip())[0]


@pytest.mark.parametrize(
    "bad_answers",
    [
        {"q1": "只答了一题"},
        {"q1": "   "},
        {"q1": None},
        {"q1": ["格式错误"]},
        {"ghost_question": "不是本卷的题目"},
        "不是答案字典",
    ],
)
def test_incomplete_answers_wait_and_allow_full_resubmission(bad_answers, answers_for_quiz):
    config = {"configurable": {"thread_id": f"incomplete-{uuid4()}"}}
    graph.invoke({"goal": "学习 Python"}, config=config)
    result = graph.invoke(Command(resume={"action": "start_quiz"}), config=config)
    quiz = deepcopy(result["quiz"])

    result = graph.invoke(
        Command(resume={"action": "submit_answer", "answers": bad_answers}), config=config
    )
    assert graph.get_state(config).next == ("wait_answer",)
    assert result["__interrupt__"][0].value["type"] == "wait_answer"
    assert result["quiz"] == quiz
    assert result["evaluation"] == {}
    assert result["score_summary"] == {}
    assert "diagnosis" not in result
    assert result["answer_error"]

    result = graph.invoke(
        Command(resume={"action": "submit_answer", "answers": answers_for_quiz(quiz)}),
        config=config,
    )
    assert result["score_summary"]["percentage"] == 100.0
    assert result["evaluation"]["assessment_id"] == quiz["assessment_id"]
    assert result["answer_error"] == ""
    assert result["branch_result"].startswith("advance")
    assert graph.get_state(config).next == ()


def test_remaining_answers_can_be_supplemented_after_malformed_event(answers_for_quiz):
    config = {"configurable": {"thread_id": f"supplement-{uuid4()}"}}
    graph.invoke({"goal": "学习 Python"}, config=config)
    result = graph.invoke(Command(resume={"action": "start_quiz"}), config=config)
    answers = answers_for_quiz(result["quiz"])
    assessment_id = result["assessment_id"]

    result = graph.invoke(
        Command(resume={"action": "submit_answer", "answers": {"q1": answers["q1"]}}),
        config=config,
    )
    assert result["answers"] == {"q1": answers["q1"]}
    assert "q2, q3, q4" in result["__interrupt__"][0].value["message"]

    result = graph.invoke(Command(resume="无效操作"), config=config)
    assert result["answers"] == {"q1": answers["q1"]}
    assert graph.get_state(config).next == ("wait_answer",)

    remaining = {key: value for key, value in answers.items() if key != "q1"}
    result = graph.invoke(
        Command(resume={"action": "submit_answer", "answers": remaining}), config=config
    )
    assert result["answers"] == answers
    assert result["evaluation"]["assessment_id"] == assessment_id
    assert result["score_summary"]["percentage"] == 100.0
    assert graph.get_state(config).next == ()


def test_invalid_action_cannot_save_answers(answers_for_quiz):
    config = {"configurable": {"thread_id": f"invalid-answer-action-{uuid4()}"}}
    graph.invoke({"goal": "学习 Python"}, config=config)
    result = graph.invoke(Command(resume={"action": "start_quiz"}), config=config)
    answers = answers_for_quiz(result["quiz"])

    result = graph.invoke(
        Command(resume={"action": "ask", "answers": answers}), config=config
    )
    assert result["answers"] == {}
    assert result["evaluation"] == {}
    assert graph.get_state(config).next == ("wait_answer",)

    result = graph.invoke(
        Command(resume={"action": "submit_answer", "answers": {"q1": answers["q1"]}}),
        config=config,
    )
    assert result["answers"] == {"q1": answers["q1"]}
    assert result["evaluation"] == {}
    assert graph.get_state(config).next == ("wait_answer",)


def test_retest_receives_old_questions_and_weak_objectives(monkeypatch, node):
    state = make_retest_state(node)
    llm = install_quiz_llm(monkeypatch, node, ["新情境"])
    result = assessment.assessment_generate_node(state)
    context = extract_retest_context(llm.prompts[0])

    assert {question["prompt"] for question in context["previous_questions"]} == {
        question["prompt"] for question in state["quiz"]["questions"]
    }
    assert context["weak_points"] == ["accumulator_overwritten"]
    assert context["focus_objective_ids"] == ["accumulate"]
    assert "SECRET_OLD_ANSWER" not in llm.prompts[0]
    assert "SECRET_OLD_RUBRIC" not in llm.prompts[0]
    assert result["assessment_id"] == result["quiz"]["assessment_id"]
    assert result["answers"] == result["evaluation"] == result["score_summary"] == {}
    assert len(result["assessment_history"]) == 2
    assert "answer_key" not in str(result["assessment_history"])
    assert "rubric" not in str(result["assessment_history"])


def test_fixed_model_repeating_old_quiz_is_rejected(monkeypatch, node):
    state = make_retest_state(node, prefix="Loop")
    unchanged = deepcopy(state)
    llm = install_quiz_llm(monkeypatch, node, ["  ＬＯＯＰ  "])

    with pytest.raises(ValueError, match="复测试卷重复了旧题"):
        assessment.assessment_generate_node(state)

    assert len(llm.prompts) == 2
    assert state == unchanged


def test_repeated_quiz_is_regenerated_before_it_is_accepted(monkeypatch, node):
    state = make_retest_state(node)
    llm = install_quiz_llm(monkeypatch, node, ["旧题", "新的应用题"])
    result = assessment.assessment_generate_node(state)

    assert len(llm.prompts) == 2
    assert "复测试卷重复了旧题" in llm.messages[1][-1].content
    assert all("新的应用题" in question["prompt"] for question in result["quiz"]["questions"])
    assert len(result["assessment_history"]) == 2


def test_retest_also_avoids_questions_from_earlier_rounds(monkeypatch, node):
    state = make_retest_state(node, prefix="最近一轮")
    older = make_quiz(node, "assessment_first", "第一轮").model_dump()
    state["assessment_history"] = [
        assessment.summarize_quiz(older),
        assessment.summarize_quiz(state["quiz"]),
    ]
    llm = install_quiz_llm(monkeypatch, node, ["第一轮", "第三轮新题"])
    result = assessment.assessment_generate_node(state)

    assert len(llm.prompts) == 2
    assert len(extract_retest_context(llm.prompts[0])["previous_questions"]) == 8
    assert len(result["assessment_history"]) == 3
    assert len(state["assessment_history"]) == 2


def test_questions_from_another_node_do_not_trigger_retest(monkeypatch, node):
    other_node = node.model_copy(deep=True)
    other_node.id = "another_node"
    quiz = make_quiz(other_node, "assessment_other_node", "旧题").model_dump()
    state = {
        "project_id": "retest_project", "tree": [node.model_dump(), other_node.model_dump()],
        "current_node_id": node.id, "quiz": quiz,
    }
    with repository_for_state(state) as repo:
        repo.create_project_with_tree(project_id=state["project_id"], goal="节点隔离", tree=state["tree"])
        repo.create_prepared_assessment(
            assessment_id=quiz["assessment_id"], project_id=state["project_id"],
            node_id=other_node.id, round_no=1,
        )
        repo.save_quiz_if_absent(assessment_id=quiz["assessment_id"], quiz=quiz)
    state.update(assessment.assessment_prepare_node(state))
    llm = install_quiz_llm(monkeypatch, node, ["旧题"])
    result = assessment.assessment_generate_node(state)

    assert len(llm.prompts) == 1
    assert extract_retest_context(llm.prompts[0]) is None
    assert result["quiz"]["node_id"] == node.id


@pytest.mark.parametrize("returned_id", ["assessment_wrong", "assessment_previous"])
def test_wrong_assessment_id_cannot_enter_state(monkeypatch, node, returned_id):
    state = make_retest_state(node)
    unchanged = deepcopy(state)
    llm = install_quiz_llm(monkeypatch, node, ["新题"], returned_id=returned_id)

    with pytest.raises(ValueError, match="assessment_id.*不一致"):
        assessment.assessment_generate_node(state)

    assert len(llm.prompts) == 2
    assert state == unchanged


@pytest.mark.parametrize("mode", ["ask", "remediate"])
def test_tutor_sends_history_to_model_without_duplicating_saved_messages(monkeypatch, node, mode):
    captured = []

    class RecordingTutorLLM:
        def invoke(self, messages):
            captured.append(messages)
            return AIMessage(content="刚才的例子中 total += item 表示累加。")

    monkeypatch.setattr(tutor, "generate_tutor_content", REAL_GENERATE_TUTOR_CONTENT)
    monkeypatch.setattr(tutor, "get_llm", RecordingTutorLLM)
    history = [
        HumanMessage(content="能用一个求和例子说明吗？"),
        AIMessage(content="先初始化 total = 0，再遍历 items 执行 total += item。"),
    ]
    state = {
        "tree": [node.model_dump()],
        "current_node_id": node.id,
        "tutor_messages": history,
        "user_event": {"action": "ask", "message": "再解释一下刚才那个例子"}
        if mode == "ask" else {"action": "submit_answer"},
        "lesson_mode": "remediate" if mode == "remediate" else "normal",
        "diagnosis": {"weak_points": ["accumulator_overwritten"]},
    }
    result = tutor.tutor_node(state)

    assert len(captured) == 1
    assert captured[0][:-1] == history
    assert isinstance(captured[0][-1], HumanMessage)
    assert len(history) == 2
    assert result["tutor_messages"][-1].content == result["lesson"]
    if mode == "ask":
        assert "再解释一下刚才那个例子" in captured[0][-1].content
        assert len(result["tutor_messages"]) == 2
        assert result["tutor_messages"][0].content == "再解释一下刚才那个例子"
    else:
        assert "accumulator_overwritten" in captured[0][-1].content
        assert len(result["tutor_messages"]) == 1
