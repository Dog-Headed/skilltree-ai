import pytest

from app.models.schemas import TreePlan
from app.models.schemas import AssessmentQuiz
from app.models.schemas import ShortAnswerGrade


@pytest.fixture(autouse=True)
def block_real_llm(monkeypatch):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("测试必须使用 LLM Mock，不能调用真实模型")

    for module in (
        "app.services.llm",
        "app.agents.planner",
        "app.agents.tutor",
        "app.agents.assessment",
    ):
        monkeypatch.setattr(f"{module}.get_llm", fail_if_called)


@pytest.fixture
def answers_for_quiz():
    def make_answers(quiz):
        return {
            question["id"]: question["answer_key"]
            for question in quiz["questions"]
        }

    return make_answers


def make_fake_plan() -> TreePlan:
    data = {
        "nodes": [
            {
                "id": "variables",
                "title": "变量",
                "description": "学习 Python 变量基础。",
                "objectives": [
                    {
                        "id": "variables_obj_1",
                        "description": "理解变量的基本作用。",
                    }
                ],
                "prerequisite_ids": [],
                "difficulty": "beginner",
                "estimated_minutes": 20,
            },
            {
                "id": "lists",
                "title": "列表",
                "description": "学习 Python 列表。",
                "objectives": [
                    {
                        "id": "lists_obj_1",
                        "description": "掌握列表基本操作。",
                    }
                ],
                "prerequisite_ids": ["variables"],
                "difficulty": "beginner",
                "estimated_minutes": 25,
            },
            {
                "id": "for_loops",
                "title": "for 循环",
                "description": "学习 for 循环。",
                "objectives": [
                    {
                        "id": "for_obj_1",
                        "description": "能够使用 for 循环。",
                    }
                ],
                "prerequisite_ids": ["lists"],
                "difficulty": "beginner",
                "estimated_minutes": 30,
            },
            {
                "id": "while_loops",
                "title": "while 循环",
                "description": "学习 while 循环。",
                "objectives": [
                    {
                        "id": "while_obj_1",
                        "description": "能够使用 while 循环。",
                    }
                ],
                "prerequisite_ids": ["variables"],
                "difficulty": "beginner",
                "estimated_minutes": 30,
            },
            {
                "id": "conditions",
                "title": "条件判断",
                "description": "学习 if 条件判断。",
                "objectives": [
                    {
                        "id": "conditions_obj_1",
                        "description": "掌握基本条件判断。",
                    }
                ],
                "prerequisite_ids": ["variables"],
                "difficulty": "beginner",
                "estimated_minutes": 25,
            },
            {
                "id": "loop_control",
                "title": "循环控制",
                "description": "学习 break 和 continue。",
                "objectives": [
                    {
                        "id": "loop_control_obj_1",
                        "description": "掌握循环控制语句。",
                    }
                ],
                "prerequisite_ids": ["for_loops"],
                "difficulty": "easy",
                "estimated_minutes": 30,
            },
            {
                "id": "nested_loops",
                "title": "嵌套循环",
                "description": "学习嵌套循环。",
                "objectives": [
                    {
                        "id": "nested_obj_1",
                        "description": "能够编写简单嵌套循环。",
                    }
                ],
                "prerequisite_ids": ["for_loops"],
                "difficulty": "medium",
                "estimated_minutes": 35,
            },
            {
                "id": "practice",
                "title": "综合练习",
                "description": "综合应用前面的知识。",
                "objectives": [
                    {
                        "id": "practice_obj_1",
                        "description": "完成基础综合练习。",
                    }
                ],
                "prerequisite_ids": [
                    "loop_control",
                    "nested_loops",
                ],
                "difficulty": "medium",
                "estimated_minutes": 45,
            },
        ]
    }

    return TreePlan.model_validate(data)


@pytest.fixture(autouse=True)
def mock_planner_llm(monkeypatch):
    def fake_generate_plan(goal: str):
        return make_fake_plan()

    monkeypatch.setattr(
        "app.agents.planner.generate_plan",
        fake_generate_plan,
    )


@pytest.fixture(autouse=True)
def mock_tutor_llm(monkeypatch):

    def fake_generate_tutor_content(
        state,
        node,
    ):
        return (
            f"这是关于 {node['title']} 的固定测试教学内容。"
        )

    monkeypatch.setattr(
        "app.agents.tutor.generate_tutor_content",
        fake_generate_tutor_content,
    )

@pytest.fixture(autouse=True)
def mock_assessment_generate_llm(
    monkeypatch,
):
    def fake_generate_quiz(
        node,
        assessment_id,
        *,
        retest_context=None,
    ):
        round_number = (
            len((retest_context or {}).get("previous_questions", [])) // 4 + 1
        )
        return AssessmentQuiz.model_validate(
            {
                "assessment_id": assessment_id,
                "node_id": node.id,
                "questions": [
                    {
                        "id": "q1",
                        "type": "short_answer",
                        "objective_id": node.objectives[
                            0
                        ].id,
                        "prompt": f"固定测试题 1（第 {round_number} 轮）",
                        "options": None,
                        "answer_key": "固定答案 1",
                        "rubric": "固定评分规则 1",
                        "max_score": 25.0,
                    },
                    {
                        "id": "q2",
                        "type": "short_answer",
                        "objective_id": node.objectives[
                            0
                        ].id,
                        "prompt": f"固定测试题 2（第 {round_number} 轮）",
                        "options": None,
                        "answer_key": "固定答案 2",
                        "rubric": "固定评分规则 2",
                        "max_score": 25.0,
                    },
                    {
                        "id": "q3",
                        "type": "short_answer",
                        "objective_id": node.objectives[
                            0
                        ].id,
                        "prompt": f"固定测试题 3（第 {round_number} 轮）",
                        "options": None,
                        "answer_key": "固定答案 3",
                        "rubric": "固定评分规则 3",
                        "max_score": 25.0,
                    },
                    {
                        "id": "q4",
                        "type": "short_answer",
                        "objective_id": node.objectives[
                            0
                        ].id,
                        "prompt": f"固定测试题 4（第 {round_number} 轮）",
                        "options": None,
                        "answer_key": "固定答案 4",
                        "rubric": "固定评分规则 4",
                        "max_score": 25.0,
                    },
                ],
            }
        )

    monkeypatch.setattr(
        "app.agents.assessment.generate_quiz",
        fake_generate_quiz,
    )


@pytest.fixture(autouse=True)
def mock_assessment_grade_llm(
    monkeypatch,
):
    grading = {"score_ratio": 1.0, "error_tags": []}

    def fake_grade_short_answer(
        question,
        user_answer,
    ):
        return ShortAnswerGrade(
            score=question["max_score"] * grading["score_ratio"],
            error_tags=grading["error_tags"],
            evidence="固定测试证据",
            feedback="固定测试反馈",
        )

    monkeypatch.setattr(
        "app.agents.assessment.grade_short_answer",
        fake_grade_short_answer,
    )

    return grading
