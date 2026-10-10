from pprint import pprint

from app.models.schemas import (
    SkillNode,
    AssessmentQuiz,
    AssessmentEvaluation,
    validate_quiz_against_node,
    validate_and_score_evaluation,
)
from copy import deepcopy
from pydantic import ValidationError

node = SkillNode.model_validate(
    {
        "id": "for_loops",
        "title": "for 循环",
        "description": "学习 Python for 循环。",
        "objectives": [
            {
                "id": "loop_obj_1",
                "description": "能够使用 for 遍历列表",
            },
            {
                "id": "loop_obj_2",
                "description": "能够使用循环完成累加",
            },
        ],
        "prerequisite_ids": [],
        "difficulty": "beginner",
        "estimated_minutes": 40,
    }
)


quiz = AssessmentQuiz.model_validate(
    {
        "assessment_id": "assessment_001",
        "node_id": "for_loops",
        "questions": [
            {
                "id": "q1",
                "type": "short_answer",
                "objective_id": "loop_obj_1",
                "prompt": "如何使用 for 循环遍历列表？",
                "options": None,
                "answer_key": "使用 for item in items",
                "rubric": "正确说明基本遍历结构即可得满分",
                "max_score": 50.0,
            },
            {
                "id": "q2",
                "type": "short_answer",
                "objective_id": "loop_obj_2",
                "prompt": "如何用循环计算列表元素总和？",
                "options": None,
                "answer_key": "初始化累计变量并使用 += 更新",
                "rubric": "必须体现累计变量初始化和更新",
                "max_score": 50.0,
            },
        ],
    }
)


evaluation = AssessmentEvaluation.model_validate(
    {
        "assessment_id": "assessment_001",
        "question_results": [
            {
                "question_id": "q1",
                "score": 45.0,
                "error_tags": [],
                "evidence": "正确描述了 for item in items。",
                "feedback": "遍历方式掌握较好。",
            },
            {
                "question_id": "q2",
                "score": 35.0,
                "error_tags": [
                    "accumulator_update_unclear"
                ],
                "evidence": "提到了 total，但没有明确 +=。",
                "feedback": "需要强化累计变量更新。",
            },
        ],
    }
)


validate_quiz_against_node(
    quiz,
    node,
)

summary = validate_and_score_evaluation(
    quiz,
    evaluation,
)

print("\n校验成功")
pprint(summary)


def run_quiz_case(title, quiz_data, node):
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)

    try:
        quiz = AssessmentQuiz.model_validate(quiz_data)
        print("✅ Quiz Schema 校验通过")

        validate_quiz_against_node(
            quiz,
            node,
        )

        print("✅ 当前节点关系校验通过")

    except ValidationError as e:
        print("❌ Pydantic 拒绝")
        print(e)

    except ValueError as e:
        print("❌ 业务校验拒绝")
        print(e)


def run_evaluation_case(
    title,
    quiz,
    evaluation_data,
):
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)

    try:
        evaluation = AssessmentEvaluation.model_validate(
            evaluation_data
        )

        print("✅ Evaluation Schema 校验通过")

        summary = validate_and_score_evaluation(
            quiz,
            evaluation,
        )

        print("✅ 评分关系校验通过")
        print(summary)

    except ValidationError as e:
        print("❌ Pydantic 拒绝")
        print(e)

    except ValueError as e:
        print("❌ 业务校验拒绝")
        print(e)


quiz_data = quiz.model_dump()

bad_quiz = deepcopy(quiz_data)

bad_quiz["questions"][1]["id"] = "q1"

run_quiz_case(
    "1. 两道题使用相同 question_id",
    bad_quiz,
    node,
)

bad_quiz = deepcopy(quiz_data)

bad_quiz["questions"][0]["objective_id"] = "ghost_objective"

run_quiz_case(
    "2. 题目引用不属于当前节点的 objective",
    bad_quiz,
    node,
)

evaluation_data = evaluation.model_dump()
bad_evaluation = deepcopy(evaluation_data)

bad_evaluation["assessment_id"] = "assessment_999"

run_evaluation_case(
    "3. Evaluation 对应了错误的 assessment_id",
    quiz,
    bad_evaluation,
)


bad_evaluation = deepcopy(evaluation_data)

bad_evaluation["question_results"] = (
    bad_evaluation["question_results"][:1]
)

run_evaluation_case(
    "4. Evaluation 漏评一道题",
    quiz,
    bad_evaluation,
)


bad_evaluation = deepcopy(evaluation_data)

bad_evaluation["question_results"][0]["score"] = 100.0


bad_evaluation = deepcopy(evaluation_data)

bad_evaluation["question_results"][1]["question_id"] = "q1"

run_evaluation_case(
    "6. 同一道题被评分两次",
    quiz,
    bad_evaluation,
)
