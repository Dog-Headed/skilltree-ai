import json
import unicodedata
from uuid import uuid4

from app.services.llm import get_llm
from app.state import LearningState
from app.models.schemas import (
    AssessmentQuiz,
    AssessmentEvaluation,
    QuestionEvaluation,
    ShortAnswerGrade,
    SkillNode,
    validate_quiz_against_node,
    validate_and_score_evaluation,
)


def get_current_node(state: LearningState) -> SkillNode:
    current_node_id = state["current_node_id"]

    for node_data in state["tree"]:
        if node_data["id"] == current_node_id:
            return SkillNode.model_validate(node_data)

    raise ValueError(
        f"找不到当前学习节点：{current_node_id}"
    )


def generate_quiz(
    node: SkillNode,
    assessment_id: str,
    *,
    retest_context: dict | None = None,
) -> AssessmentQuiz:
    llm = get_llm()

    structured_llm = llm.with_structured_output(
        AssessmentQuiz,
        method="json_mode",
    )

    prompt = f"""
你是一名 Python 学习测评设计专家。

当前知识节点：
{node.title}

节点说明：
{node.description}

学习目标：
{[
    {
        "id": objective.id,
        "description": objective.description,
    }
    for objective in node.objectives
]}

请生成一份测验。

要求：

1. assessment_id 必须严格使用：
   {assessment_id}

2. node_id 必须严格使用：
   {node.id}

3. 默认生成 4 道题。

4. 必须覆盖当前节点全部学习目标。

5. 每道题必须包含：
   - id
   - type
   - objective_id
   - prompt
   - options
   - answer_key
   - rubric
   - max_score

6. type 只能使用：
   single_choice
   multiple_choice
   short_answer

7. 每道题只能引用当前节点真实存在的 objective_id。

8. question id 必须唯一。

9. answer_key 和 rubric 要足够明确，
   供系统后续评分使用。

10. 不要生成契约之外的额外字段。

11. 只输出 JSON，严格遵守以下 JSON Schema：
{json.dumps(AssessmentQuiz.model_json_schema(), ensure_ascii=False)}

12. 如果以下复测上下文不为空，这是同一节点的新一轮测验。
    必须覆盖全部学习目标，并优先验证 focus_objective_ids 对应的薄弱目标。
    根据 weak_points 设计新的应用情境、数据或推理任务。
    previous_questions 是已经出过的题目，禁止直接重复。
    只更换题目 ID、选项顺序、标点或空白不算新题。

复测上下文：
{json.dumps(retest_context, ensure_ascii=False)}
"""

    quiz = structured_llm.invoke(prompt)

    return quiz


def summarize_quiz(quiz: dict) -> dict:
    """复测只需要旧题摘要，不传入旧卷答案或评分标准。"""
    return {
        "assessment_id": quiz["assessment_id"],
        "node_id": quiz["node_id"],
        "questions": [
            {
                "type": question["type"],
                "objective_id": question["objective_id"],
                "prompt": question["prompt"],
                "options": question.get("options"),
            }
            for question in quiz["questions"]
        ],
    }


def normalize_question_prompt(prompt: str) -> str:
    return "".join(unicodedata.normalize("NFKC", prompt).split()).casefold()


def assessment_generate_node(
    state: LearningState,
):
    node = get_current_node(state)

    assessment_id = (
        f"assessment_{uuid4().hex[:12]}"
    )

    history = list(state.get("assessment_history", []))
    previous_quiz = state.get("quiz", {})
    if previous_quiz and not any(
        entry["assessment_id"] == previous_quiz["assessment_id"]
        for entry in history
    ):
        history.append(summarize_quiz(previous_quiz))

    previous_questions = [
        question
        for entry in history
        if entry["node_id"] == node.id
        for question in entry["questions"]
    ]
    previous_prompts = {
        normalize_question_prompt(question["prompt"])
        for question in previous_questions
    }

    retest_context = None
    if previous_questions:
        weak_objectives = set()
        weak_points = []
        if previous_quiz.get("node_id") == node.id:
            weak_points = state.get("diagnosis", {}).get("weak_points", [])
            evaluation = state.get("evaluation", {})
            if evaluation.get("assessment_id") == previous_quiz["assessment_id"]:
                question_map = {
                    question["id"]: question
                    for question in previous_quiz["questions"]
                }
                for result in evaluation.get("question_results", []):
                    question = question_map.get(result["question_id"])
                    if question and (
                        result["score"] < question["max_score"] * 0.8
                        or result.get("error_tags")
                    ):
                        weak_objectives.add(question["objective_id"])

        retest_context = {
            "purpose": "验证补弱后的掌握情况，使用新题检验能否独立应用所学知识。",
            "previous_questions": previous_questions,
            "weak_points": weak_points,
            "focus_objective_ids": [
                objective.id
                for objective in node.objectives
                if not weak_objectives or objective.id in weak_objectives
            ],
        }

    # 重复旧题时有限次重新生成；失败的试卷不能进入 State。
    for attempt in range(3):
        quiz = generate_quiz(node, assessment_id, retest_context=retest_context)
        if quiz.assessment_id != assessment_id:
            raise ValueError(
                f"模型返回的 assessment_id {quiz.assessment_id} "
                f"与本轮生成的 ID {assessment_id} 不一致"
            )

        validate_quiz_against_node(quiz, node)
        repeated = [
            question.prompt
            for question in quiz.questions
            if normalize_question_prompt(question.prompt) in previous_prompts
        ]
        if not repeated:
            break
        if attempt == 2:
            raise ValueError("复测试卷重复了旧题，重新生成三次后仍不合格。")
        retest_context = {
            **retest_context,
            "retry_feedback": "上一份试卷存在重复旧题，请重新设计题目。",
            "repeated_prompts": repeated,
        }

    quiz_data = quiz.model_dump()
    history.append(summarize_quiz(quiz_data))

    return {
        "assessment_id": assessment_id,
        "quiz": quiz_data,
        "assessment_history": history,

        # 新的一轮测验开始：
        # 清空上一轮答案和评价
        "answers": {},
        "answer_error": "",
        "evaluation": {},
        "score_summary": {},
    }


def build_public_quiz(
    quiz: dict,
) -> dict:
    public_questions = []

    for question in quiz["questions"]:
        public_questions.append(
            {
                "id": question["id"],
                "type": question["type"],
                "objective_id": question[
                    "objective_id"
                ],
                "prompt": question["prompt"],
                "options": question["options"],
                "max_score": question["max_score"],
            }
        )

    return {
        "assessment_id": quiz[
            "assessment_id"
        ],
        "node_id": quiz["node_id"],
        "questions": public_questions,
    }



def grade_short_answer(
    question: dict,
    user_answer: str,
) -> ShortAnswerGrade:
    llm = get_llm()

    structured_llm = llm.with_structured_output(
        ShortAnswerGrade,
        method="json_mode",
    )

    prompt = f"""
你是一名严格但清晰的 Python 学习测评评分员。

题目：
{question["prompt"]}

学生答案：
{user_answer}

标准答案：
{question["answer_key"]}

评分标准：
{question["rubric"]}

本题满分：
{question["max_score"]}

请严格按照已经给定的评分标准进行评价。

要求：
1. score 必须在 0 到本题满分之间。
2. error_tags 使用简短英文 snake_case。
3. evidence 要指出学生答案中实际出现了什么。
4. feedback 要具体说明哪里正确、哪里需要改进。
5. 不要因为表达方式不同而机械判错。
6. 不要修改评分标准。
7. 只输出 JSON，严格遵守以下 JSON Schema：
{json.dumps(ShortAnswerGrade.model_json_schema(), ensure_ascii=False)}
"""

    result = structured_llm.invoke(prompt)

    return result


def grade_objective_question(
    question: dict,
    user_answer,
) -> QuestionEvaluation:

    question_type = question["type"]
    answer_key = question["answer_key"]
    max_score = question["max_score"]

    # =========================
    # 单选题
    # =========================

    if question_type == "single_choice":
        correct = user_answer == answer_key

    # =========================
    # 多选题
    # =========================

    elif question_type == "multiple_choice":
        if not isinstance(user_answer, list):
            correct = False
        else:
            correct = (
                set(user_answer)
                == set(answer_key)
            )

    else:
        raise ValueError(
            f"题目 {question['id']} "
            f"不是客观题"
        )

    if correct:
        return QuestionEvaluation(
            question_id=question["id"],
            score=max_score,
            error_tags=[],
            evidence="用户答案与标准答案一致。",
            feedback="回答正确。",
        )

    return QuestionEvaluation(
        question_id=question["id"],
        score=0.0,
        error_tags=["incorrect_answer"],
        evidence="用户答案与标准答案不一致。",
        feedback="回答不正确，请重新检查相关概念。",
    )


def grade_short_answer_question(
    question: dict,
    user_answer,
) -> QuestionEvaluation:

    if not isinstance(user_answer, str):
        user_answer = str(user_answer)

    llm_result = grade_short_answer(
        question,
        user_answer,
    )

    # 重要：
    # 不相信 LLM 的 score 一定合法
    if llm_result.score > question["max_score"]:
        raise ValueError(
            f"题目 {question['id']} 的模型评分 "
            f"{llm_result.score} 超过满分 "
            f"{question['max_score']}"
        )

    return QuestionEvaluation(
        question_id=question["id"],
        score=llm_result.score,
        error_tags=llm_result.error_tags,
        evidence=llm_result.evidence,
        feedback=llm_result.feedback,
    )


def assessment_grade_node(
    state: LearningState,
):
    quiz = AssessmentQuiz.model_validate(
        state["quiz"]
    )

    answers = state.get("answers", {})

    if not isinstance(answers, dict):
        raise ValueError(
            "answers 必须是字典"
        )

    question_results = []

    for question_model in quiz.questions:
        question = question_model.model_dump()

        question_id = question["id"]

        if question_id not in answers:
            raise ValueError(
                f"缺少题目 {question_id} 的答案"
            )

        user_answer = answers[question_id]

        # 客观题
        if question["type"] in {
            "single_choice",
            "multiple_choice",
        }:
            result = grade_objective_question(
                question,
                user_answer,
            )

        # 简答题
        elif question["type"] == "short_answer":
            result = grade_short_answer_question(
                question,
                user_answer,
            )

        else:
            raise ValueError(
                f"不支持的题型：{question['type']}"
            )

        question_results.append(result)

    evaluation = AssessmentEvaluation(
        assessment_id=quiz.assessment_id,
        question_results=question_results,
    )

    # =========================
    # 最终确定性校验 + 程序算总分
    # =========================

    score_summary = (
        validate_and_score_evaluation(
            quiz,
            evaluation,
        )
    )

    return {
        "evaluation": evaluation.model_dump(),
        "score_summary": score_summary,
    }
