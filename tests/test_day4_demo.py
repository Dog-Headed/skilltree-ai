import io
import runpy
import sys
from pathlib import Path

import pytest
from langgraph.types import Command

from app.graph import graph
from app.models.schemas import AssessmentQuiz


DEMO_PATH = Path(__file__).resolve().parents[1] / "day4_demo.py"


def test_multiline_answers_and_menu_retry(
    monkeypatch, mock_assessment_grade_llm
):
    def generate_mixed_quiz(node, assessment_id, *, retest_context=None):
        round_number = (
            len((retest_context or {}).get("previous_questions", [])) // 4 + 1
        )
        questions = [
            ("q1", "short_answer", "写出循环代码", None, "代码"),
            ("q2", "multiple_choice", "选择多个选项", ["A", "B", "C"], ["A", "C"]),
            ("q3", "single_choice", "选择一个选项", ["A", "B"], "B"),
            ("q4", "short_answer", "写出三行输出", None, "Python\n6\nTrue"),
        ]
        return AssessmentQuiz.model_validate(
            {
                "assessment_id": assessment_id,
                "node_id": node.id,
                "questions": [
                    {
                        "id": question_id,
                        "type": question_type,
                        "objective_id": node.objectives[0].id,
                        "prompt": f"{prompt}（第 {round_number} 轮）",
                        "options": options,
                        "answer_key": answer_key,
                        "rubric": "固定测试评分规则",
                        "max_score": 25.0,
                    }
                    for question_id, question_type, prompt, options, answer_key in questions
                ],
            }
        )

    monkeypatch.setattr(
        "app.agents.assessment.generate_quiz", generate_mixed_quiz
    )
    # 首轮补弱，第二轮通过；仍然执行真实图、中断和恢复。
    mock_assessment_grade_llm["score_ratio"] = 0.0
    round_input = (
        "for i in range(2):\n    print(i)\n\nEND\n"
        " A , , C , \n"
        " B \n"
        "Python\n6\nTrue\nEND\n"
    )
    stdin = io.StringIO(
        "学习 Python\n6\nTrue\n\nx\n1\n变量是什么？\n2\n"
        + round_input
        + "6\nTrue\n\nx\n1\n请解释输出\n2\n"
        + round_input
        + "后续输入\n"
    )
    monkeypatch.setattr(sys, "stdin", stdin)

    events = []
    submissions = []
    original_invoke = graph.invoke

    def track_invoke(event, *, config):
        if isinstance(event, Command):
            events.append(event.resume)
            if event.resume["action"] == "submit_answer":
                submissions.append(event.resume["answers"])
                if len(submissions) == 1:
                    # END 之后的菜单输入还未被消费。
                    assert stdin.getvalue()[stdin.tell():].startswith(
                        "6\nTrue\n\nx\n1\n请解释输出\n2\n"
                    )
                else:
                    mock_assessment_grade_llm["score_ratio"] = 1.0
        return original_invoke(event, config=config)

    monkeypatch.setattr(graph, "invoke", track_invoke)
    namespace = runpy.run_path(str(DEMO_PATH), run_name="__main__")

    expected_answers = {
        "q1": "for i in range(2):\n    print(i)\n",
        "q2": ["A", "C"],
        "q3": "B",
        "q4": "Python\n6\nTrue",
    }
    assert submissions == [expected_answers, expected_answers]
    assert [event["action"] for event in events] == [
        "ask", "start_quiz", "submit_answer",
        "ask", "start_quiz", "submit_answer",
    ]
    assert events[0]["message"] == "变量是什么？"
    assert events[3]["message"] == "请解释输出"
    assert namespace["result"]["score_summary"]["percentage"] == 100.0
    assert namespace["result"]["branch_result"].startswith("advance")
    assert graph.get_state(namespace["config"]).next == ()
    assert stdin.read() == "后续输入\n"


def test_eof_does_not_submit_unfinished_multiline_answer(monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO("学习 Python\n2\nPython\n6\nTrue\n"))
    events = []
    configs = []
    original_invoke = graph.invoke

    def track_invoke(event, *, config):
        configs.append(config)
        if isinstance(event, Command):
            events.append(event.resume["action"])
        return original_invoke(event, config=config)

    monkeypatch.setattr(graph, "invoke", track_invoke)

    with pytest.raises(EOFError):
        runpy.run_path(str(DEMO_PATH), run_name="__main__")

    assert events == ["start_quiz"]
    assert graph.get_state(configs[-1]).next == ("wait_answer",)


def test_partial_answers_retry_same_quiz_in_demo(monkeypatch, capsys):
    round_input = "答案\nEND\n" * 4
    monkeypatch.setattr(
        sys, "stdin", io.StringIO("学习 Python\n2\n" + round_input * 2 + "后续输入\n")
    )
    original_invoke = graph.invoke
    submissions = []

    def submit_partial_once(event, *, config):
        if isinstance(event, Command) and event.resume["action"] == "submit_answer":
            submissions.append(event.resume["answers"])
            if len(submissions) == 1:
                event = Command(
                    resume={
                        "action": "submit_answer",
                        "answers": {"q1": event.resume["answers"]["q1"]},
                    }
                )
        return original_invoke(event, config=config)

    monkeypatch.setattr(graph, "invoke", submit_partial_once)
    namespace = runpy.run_path(str(DEMO_PATH), run_name="__main__")

    assert len(submissions) == 2
    assert namespace["round_number"] == 1
    assert len(namespace["result"]["assessment_history"]) == 1
    assert namespace["result"]["score_summary"]["percentage"] == 100.0
    assert namespace["result"]["branch_result"].startswith("advance")
    assert "以下题目缺少有效答案：q2, q3, q4" in capsys.readouterr().out
    assert graph.get_state(namespace["config"]).next == ()
