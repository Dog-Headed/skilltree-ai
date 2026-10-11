import io
import runpy
import sys
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

import app.agents.diagnosis as diagnosis
from app.agents.assessment import grade_objective_question
from app.models.schemas import AssessmentQuiz, DiagnosisResult
from app.services.quiz_answers import display_option


REAL_RUN_REAL_DIAGNOSIS = diagnosis.run_real_diagnosis
DEMO_PATH = Path(__file__).resolve().parents[1] / "day4_demo.py"


@pytest.mark.parametrize("first_choice", ["A", "D"])
def test_day4_keeps_project_context_through_real_diagnosis(
    monkeypatch, capsys, first_choice
):
    def generate_mixed_quiz(node, assessment_id, *, retest_context=None):
        round_number = len((retest_context or {}).get("previous_questions", [])) // 4 + 1
        definitions = [
            ("single_choice", "选择正确赋值", ["score = 42", "score = '42'", "42 = score", "score == 42"], "score = 42"),
            ("multiple_choice", "选择基本数据类型", ["3.14", "'hello'", "True", "[1, 2, 3]"], ["3.14", "'hello'", "True"]),
            ("single_choice", "选择缩进的作用", ["仅为了美观", "划分代码块", "必须使用 Tab", "必须为两格"], "划分代码块"),
            ("short_answer", "解释代码输出", None, "big\ndone\nend"),
        ]
        return AssessmentQuiz.model_validate(
            {
                "assessment_id": assessment_id,
                "node_id": node.id,
                "questions": [
                    {
                        "id": f"q{index}",
                        "type": kind,
                        "objective_id": node.objectives[0].id,
                        "prompt": f"{prompt}（练习 {round_number}）",
                        "options": options,
                        "answer_key": key,
                        "rubric": "本题满分 25 分。",
                        "max_score": 25.0,
                    }
                    for index, (kind, prompt, options, key) in enumerate(definitions, 1)
                ],
            }
        )

    project_ids = []

    def run_with_model_doubles(state, **kwargs):
        # 只替换两个模型，真实执行上下文、工具、证据池和最终校验均照常运行。
        project_ids.append(state.get("project_id"))

        class ToolModel:
            def __init__(self):
                self.calls = 0

            def bind_tools(self, tools):
                return self

            def invoke(self, messages):
                self.calls += 1
                if self.calls == 1:
                    return AIMessage(
                        content="",
                        tool_calls=[{
                            "name": "get_learning_history",
                            "args": {"node_id": state["current_node_id"], "limit": 1},
                            "id": "history_call",
                            "type": "tool_call",
                        }],
                    )
                return AIMessage(content="已读取工具结果，结合当前测评进行诊断。")

        class FinalModel:
            def with_structured_output(self, schema, *, method):
                assert method == "json_mode"
                return self

            def invoke(self, messages):
                passed = state["score_summary"]["percentage"] >= 80
                return DiagnosisResult(
                    weak_points=[] if passed else ["变量赋值需要巩固"],
                    evidence_ids=[f"assessment:{state['assessment_id']}:q1"],
                    recommended_action="advance" if passed else "remediate",
                    reason="根据当前逐题测评结果决定是否通过。",
                    review_node_id=None,
                )

        return REAL_RUN_REAL_DIAGNOSIS(
            state, tool_llm=ToolModel(), final_llm=FinalModel()
        )

    monkeypatch.setattr("app.agents.assessment.generate_quiz", generate_mixed_quiz)
    monkeypatch.setattr(diagnosis, "run_real_diagnosis", run_with_model_doubles)
    remaining_answers = "A,B,C\nB\nbig\ndone\nend\nEND\n"
    user_input = "\n2\n" + first_choice + "\n" + remaining_answers
    if first_choice == "D":
        user_input += "2\nA\n" + remaining_answers
    monkeypatch.setattr(sys, "stdin", io.StringIO(user_input))

    namespace = runpy.run_path(str(DEMO_PATH), run_name="__main__")
    result = namespace["result"]
    expected_project_id = namespace["config"]["configurable"]["thread_id"]
    assert project_ids == [expected_project_id] * (2 if first_choice == "D" else 1)
    assert result["project_id"] == expected_project_id
    assert result["answers"]["q1"] == "score = 42"
    assert result["answers"]["q2"] == ["3.14", "'hello'", "True"]
    assert result["answers"]["q3"] == "划分代码块"
    assert result["score_summary"]["percentage"] == 100.0
    assert result["branch_result"].startswith("advance")
    output = capsys.readouterr().out
    assert "A. score = 42" in output
    assert "B. 划分代码块" in output


@pytest.mark.parametrize(
    "kind, options, key, answer, expected_score",
    [
        ("single_choice", ["score = 42", "score == 42"], "score = 42", "a", 25.0),
        ("single_choice", ["score = 42", "score == 42"], "A", "score = 42", 25.0),
        ("single_choice", ["script.py", "hello.py"], "hello.py", "B", 25.0),
        ("single_choice", ["A. score = 42", "B. score == 42"], "A", "score = 42", 25.0),
        ("single_choice", ["A. score = 42", "B. score == 42"], "score = 42", "B", 0.0),
        ("multiple_choice", ["3.14", "'hello'", "True", "[1, 2, 3]"], ["3.14", "'hello'", "True"], ["C", "A", "B"], 25.0),
        ("multiple_choice", ["A. 3.14", "B. 'hello'", "C. True"], ["A", "C"], ["3.14", "True"], 25.0),
        ("multiple_choice", ["3.14", "True", "[1, 2, 3]"], ["3.14", "True"], ["A"], 0.0),
    ],
)
def test_choice_letters_and_option_text_receive_the_same_grade(
    kind, options, key, answer, expected_score
):
    result = grade_objective_question(
        {"id": "q1", "type": kind, "options": options, "answer_key": key, "max_score": 25.0},
        answer,
    )
    assert result.score == expected_score


def test_filename_option_receives_a_visible_letter_label():
    assert display_option(3, "hello.py") == "D. hello.py"
