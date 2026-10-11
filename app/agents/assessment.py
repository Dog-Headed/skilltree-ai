import json
import math
import unicodedata
from uuid import uuid4

from langchain_core.exceptions import OutputParserException
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import ValidationError

from app.db.repository import repository_for_state, get_assessment_for_state
from app.models.schemas import (
    AssessmentQuiz, AssessmentEvaluation, QuestionEvaluation, ShortAnswerGrade,
    SkillNode, validate_quiz_against_node, validate_and_score_evaluation,
)
from app.services.llm import (
    ModelCallBudget, ModelOutputValidationError, RepairContext, get_llm,
    invoke_with_shared_budget,
)
from app.services.quiz_answers import normalize_choice_answer
from app.state import LearningState
from app.services.observability import observed_node


def get_current_node(state: LearningState) -> SkillNode:
    current_node_id = state["current_node_id"]

    for node_data in state["tree"]:
        if node_data["id"] == current_node_id:
            return SkillNode.model_validate(node_data)

    raise ValueError(
        f"找不到当前学习节点：{current_node_id}"
    )


def summarize_quiz(quiz: dict) -> dict:
    """复测只使用公开题面摘要，不传入旧卷答案或评分标准。"""
    return {
        "assessment_id": quiz.get("assessment_id"),
        "node_id": quiz.get("node_id"),
        "questions": [
            {key: question.get(key) for key in ("type", "objective_id", "prompt", "options")}
            for question in quiz.get("questions", [])
            if isinstance(question, dict) and isinstance(question.get("prompt"), str)
        ],
    }


def collect_previous_question_prompts(previous_quizzes: list[dict]) -> list[str]:
    prompts = []
    for record in previous_quizzes:
        quiz = record.get("quiz") or {}
        if not isinstance(quiz, dict):
            continue
        for question in quiz.get("questions", []):
            if isinstance(question, dict) and isinstance(question.get("prompt"), str):
                if question["prompt"].strip():
                    prompts.append(question["prompt"])
    return prompts


def normalize_question_prompt(prompt: str) -> str:
    return "".join(unicodedata.normalize("NFKC", prompt).split()).casefold()


def validate_assessment_output(
    quiz: AssessmentQuiz, *, node: SkillNode, assessment_id: str,
    previous_question_prompts: list[str],
) -> AssessmentQuiz:
    # 注入模型也必须完整经过结构边界，避免修改过的模型实例绕过 Schema。
    try:
        quiz = AssessmentQuiz.model_validate(quiz.model_dump())
    except ValidationError as exc:
        raise ModelOutputValidationError(f"Assessment 结构化输出失败：{exc}") from exc
    if quiz.assessment_id != assessment_id:
        raise ModelOutputValidationError(
            f"Assessment 业务校验失败：assessment_id {quiz.assessment_id!r} "
            f"与当前固定 assessment_id {assessment_id!r} 不一致。"
        )
    try:
        validate_quiz_against_node(quiz, node)
    except ValueError as exc:
        raise ModelOutputValidationError(f"Assessment 业务校验失败：{exc}") from exc

    required_objectives = {objective.id for objective in node.objectives}
    missing = required_objectives - {question.objective_id for question in quiz.questions}
    if missing:
        raise ModelOutputValidationError(f"试卷未覆盖当前节点的学习目标：{sorted(missing)}")
    seen_prompts = set()
    old_prompts = {normalize_question_prompt(prompt) for prompt in previous_question_prompts}
    for question in quiz.questions:
        normalized = normalize_question_prompt(question.prompt)
        if not normalized:
            raise ModelOutputValidationError(f"题目 {question.id} 的题面不能为空")
        if normalized in seen_prompts:
            raise ModelOutputValidationError(f"本次试卷中存在重复题：{question.prompt!r}")
        if normalized in old_prompts:
            raise ModelOutputValidationError(f"复测试卷重复了旧题：{question.prompt!r}")
        seen_prompts.add(normalized)
        if not math.isfinite(question.max_score) or question.max_score <= 0:
            raise ModelOutputValidationError(f"题目 {question.id} 的满分必须是有限正数")
        if not question.rubric.strip():
            raise ModelOutputValidationError(f"题目 {question.id} 的 rubric 不能为空")
        if question.type == "short_answer":
            if not isinstance(question.answer_key, str) or not question.answer_key.strip():
                raise ModelOutputValidationError(f"简答题 {question.id} 的 answer_key 必须是非空字符串")
            if question.options:
                raise ModelOutputValidationError(f"简答题 {question.id} 不应包含选择题 options")
        else:
            options = question.options or []
            if len(options) < 2 or any(not option.strip() for option in options):
                raise ModelOutputValidationError(f"选择题 {question.id} 必须有至少两个非空 options")
            if len({option.strip() for option in options}) != len(options):
                raise ModelOutputValidationError(f"选择题 {question.id} 的 options 不能重复")
            if question.type == "single_choice":
                if not isinstance(question.answer_key, str):
                    raise ModelOutputValidationError(f"单选题 {question.id} 的 answer_key 必须是字符串")
                keys = [question.answer_key]
            else:
                if not isinstance(question.answer_key, list) or not question.answer_key:
                    raise ModelOutputValidationError(f"多选题 {question.id} 的 answer_key 必须是非空列表")
                keys = question.answer_key
            answers = [normalize_choice_answer(key, options) for key in keys]
            if any(answer not in options for answer in answers) or len(set(answers)) != len(answers):
                raise ModelOutputValidationError(f"选择题 {question.id} 的 answer_key 必须唯一对应有效 options")
    return quiz


def build_assessment_messages(
    *, node: SkillNode, assessment_id: str, previous_question_prompts: list[str],
    repair_context: RepairContext | None = None, retest_context: dict | None = None,
):
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

    prompt += "\n此前已经使用过的题面（禁止重复）：\n" + json.dumps(
        previous_question_prompts, ensure_ascii=False,
    )
    messages = [
        SystemMessage(content="你是学习测评出题 Agent，请按完整契约返回 JSON 试卷。"),
        HumanMessage(content=prompt),
    ]
    if repair_context is not None:
        repair_prompt = (
            "你上一次生成的试卷没有通过系统校验。\n\n"
            f"具体错误：\n{repair_context.error_message}\n\n"
        )
        if repair_context.previous_output is not None:
            previous_output = repair_context.previous_output
            if isinstance(previous_output, AssessmentQuiz):
                previous_output = previous_output.model_dump()
            repair_prompt += (
                "上一次候选试卷：\n"
                + json.dumps(previous_output, ensure_ascii=False, default=str) + "\n\n"
            )
        repair_prompt += (
            f"请针对上述错误修复试卷，assessment_id 必须保持 {assessment_id!r}，"
            f"node_id 必须保持 {node.id!r}；"
            "遵守全部结构、学习目标和查重规则，返回完整的修正版 JSON 试卷，不要解释。"
        )
        messages.append(HumanMessage(content=repair_prompt))
    return messages


def generate_quiz_with_governance(
    *, node: SkillNode, assessment_id: str, previous_question_prompts: list[str],
    structured_llm=None, budget: ModelCallBudget | None = None,
    retest_context: dict | None = None,
) -> AssessmentQuiz:
    if structured_llm is None:
        structured_llm = get_llm().with_structured_output(AssessmentQuiz, method="json_mode")
    if budget is None:
        budget = ModelCallBudget()

    def invoke_once(repair_context: RepairContext | None) -> AssessmentQuiz:
        messages = build_assessment_messages(
            node=node, assessment_id=assessment_id,
            previous_question_prompts=previous_question_prompts,
            retest_context=retest_context, repair_context=repair_context,
        )
        try:
            return structured_llm.invoke(messages)
        except (ValidationError, OutputParserException) as exc:
            raise ModelOutputValidationError(f"Assessment 结构化输出失败：{exc}") from exc

    return invoke_with_shared_budget(
        invoke_fn=invoke_once,
        validate_fn=lambda quiz: validate_assessment_output(
            quiz, node=node, assessment_id=assessment_id,
            previous_question_prompts=previous_question_prompts,
        ),
        budget=budget,
    )


def generate_quiz(
    node: SkillNode, assessment_id: str, *, retest_context: dict | None = None,
) -> AssessmentQuiz:
    """保留出题入口，所有真实请求由同一个治理调用器执行。"""
    prompts = [
        question["prompt"]
        for question in (retest_context or {}).get("previous_questions", [])
        if isinstance(question.get("prompt"), str)
    ]
    return generate_quiz_with_governance(
        node=node, assessment_id=assessment_id, previous_question_prompts=prompts,
        retest_context=retest_context,
    )


def previous_quiz_summaries(state: LearningState, node: SkillNode, records: list[dict]) -> list[dict]:
    by_id = {}
    def add(quiz):
        if (
            isinstance(quiz, dict) and quiz.get("node_id") == node.id
            and quiz.get("assessment_id")
            and quiz["assessment_id"] != state["assessment_id"]
        ):
            by_id[quiz["assessment_id"]] = summarize_quiz(quiz)

    for quiz in state.get("assessment_history", []):
        add(quiz)
    add(state.get("quiz"))
    for record in reversed(records):
        add({**record["quiz"], "assessment_id": record["assessment_id"], "node_id": node.id})
    return list(by_id.values())


def build_retest_context(state: LearningState, node: SkillNode, history: list[dict]) -> dict | None:
    questions = [question for quiz in history for question in quiz["questions"]]
    if not questions:
        return None
    old_quiz = state.get("quiz") or {}
    evaluation = state.get("evaluation") or {}
    same_node = old_quiz.get("node_id") == node.id
    weak_points = (state.get("diagnosis") or {}).get("weak_points", []) if same_node else []
    focus_objectives = set()
    if same_node and evaluation.get("assessment_id") == old_quiz.get("assessment_id"):
        results = {result["question_id"]: result for result in evaluation.get("question_results", [])}
        for question in old_quiz.get("questions", []):
            result = results.get(question["id"])
            if result and (result["score"] < question["max_score"] or result.get("error_tags")):
                focus_objectives.add(question["objective_id"])
    return {
        "previous_questions": questions,
        "weak_points": weak_points,
        "focus_objective_ids": sorted(focus_objectives),
    }


@observed_node
def assessment_generate_node(state: LearningState):
    assessment_id = state.get("assessment_id")
    if not assessment_id:
        raise ValueError("出题前缺少 assessment_id，请先执行 assessment_prepare")
    if not state.get("project_id"):
        raise ValueError("出题阶段缺少 project_id")
    node = get_current_node(state)
    with repository_for_state(state) as repo:
        existing = repo.get_assessment(assessment_id)
        round_no = state.get("assessment_round_no") or (
            existing["round_no"] if existing else repo.next_assessment_round(
                project_id=state["project_id"], node_id=node.id,
            )
        )
        assessment = repo.create_prepared_assessment(
            assessment_id=assessment_id, project_id=state["project_id"],
            node_id=node.id, round_no=round_no,
        )
        records = repo.list_previous_quizzes(
            project_id=state["project_id"], node_id=node.id,
            exclude_assessment_id=assessment_id, limit=3,
        ) if assessment["quiz"] is None else []

    history = previous_quiz_summaries(state, node, records)
    if assessment["quiz"] is not None:
        # 固定结果优先复用，不再次查询历史、不重新调用模型，也不覆盖原卷。
        quiz = AssessmentQuiz.model_validate(assessment["quiz"])
        validate_assessment_output(
            quiz, node=node, assessment_id=assessment_id, previous_question_prompts=[],
        )
    else:
        context = build_retest_context(state, node, history)
        previous_prompts = collect_previous_question_prompts([{"quiz": quiz} for quiz in history])
        quiz = generate_quiz(node, assessment_id, retest_context=context)
        # 注入的出题函数也须通过业务边界；此处不另起重试循环。
        validate_assessment_output(
            quiz, node=node, assessment_id=assessment_id,
            previous_question_prompts=previous_prompts,
        )
        with repository_for_state(state) as repo:
            get_assessment_for_state(repo, state)
            saved = repo.save_quiz_if_absent(assessment_id=assessment_id, quiz=quiz.model_dump())
            quiz = AssessmentQuiz.model_validate(saved["quiz"])
    history.append(summarize_quiz(quiz.model_dump()))
    updates = {
        "assessment_id": assessment_id, "assessment_round_no": round_no,
        "quiz": quiz.model_dump(), "answers": {}, "evaluation": {},
        "score_summary": {}, "answer_error": "", "assessment_history": history,
        "lesson_mode": "normal", "review_node_id": None,
    }
    return updates


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
    *, structured_llm=None, budget: ModelCallBudget | None = None,
) -> ShortAnswerGrade:
    if structured_llm is None:
        structured_llm = get_llm().with_structured_output(ShortAnswerGrade, method="json_mode")

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

    def invoke_once(repair_context):
        messages = [HumanMessage(content=prompt)]
        if repair_context is not None:
            messages.append(HumanMessage(content=(
                "上一次评分未通过校验：\n" + repair_context.error_message
                + "\n请保持原题、答案和 rubric，返回完整修正版 JSON。"
            )))
        try:
            return structured_llm.invoke(messages)
        except (ValidationError, OutputParserException) as exc:
            raise ModelOutputValidationError(f"评分结构化输出失败：{exc}") from exc

    def validate_once(raw):
        try:
            result = ShortAnswerGrade.model_validate(
                raw.model_dump() if isinstance(raw, ShortAnswerGrade) else raw
            )
        except ValidationError as exc:
            raise ModelOutputValidationError(f"评分结构校验失败：{exc}") from exc
        if not math.isfinite(result.score) or not 0 <= result.score <= question["max_score"]:
            raise ModelOutputValidationError(
                f"题目 {question['id']} 得分 {result.score} 必须在 0 到 {question['max_score']} 之间"
            )
        return result

    return invoke_with_shared_budget(
        invoke_fn=invoke_once, validate_fn=validate_once, budget=budget,
        operation="short_answer_grade",
    )


def grade_objective_question(
    question: dict,
    user_answer,
) -> QuestionEvaluation:

    question_type = question["type"]
    answer_key = question["answer_key"]
    max_score = question["max_score"]
    options = question.get("options") or []

    # =========================
    # 单选题
    # =========================

    if question_type == "single_choice":
        correct = (
            normalize_choice_answer(user_answer, options)
            == normalize_choice_answer(answer_key, options)
        )

    # =========================
    # 多选题
    # =========================

    elif question_type == "multiple_choice":
        if not isinstance(user_answer, list) or not all(
            isinstance(answer, str) for answer in user_answer
        ):
            correct = False
        else:
            correct = (
                {normalize_choice_answer(answer, options) for answer in user_answer}
                == {
                    normalize_choice_answer(answer, options)
                    for answer in (answer_key if isinstance(answer_key, list) else [answer_key])
                }
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


@observed_node
def assessment_grade_node(
    state: LearningState,
):
    assessment_id = state.get(
        "assessment_id"
    )

    if not assessment_id:
        raise ValueError(
            "评分阶段缺少 assessment_id"
        )

    with repository_for_state(state) as repo:

        assessment = get_assessment_for_state(repo, state)

        if assessment is None:
            raise ValueError(
                "数据库中找不到当前测验"
            )

        quiz = AssessmentQuiz.model_validate(
            assessment["quiz"]
        )

        # ================================================
        # 已经评过分：
        # 不重新调用评分模型
        # ================================================

        if (
            assessment["evaluation"]
            is not None
        ):
            evaluation = (
                AssessmentEvaluation.model_validate(
                    assessment["evaluation"]
                )
            )

        else:
            answers = assessment[
                "answers"
            ]

            if answers is None:
                raise ValueError(
                    "数据库中没有本轮答案"
                )

            evaluation = grade_quiz(
                quiz,
                answers,
            )

            # 包括注入的评分器：重新做结构校验，不能绕过有限数值等契约。
            evaluation = AssessmentEvaluation.model_validate(evaluation.model_dump())

            # 先验证逐题结果和总分，非法评分不能落库成为不可覆盖的事实。
            validate_and_score_evaluation(quiz, evaluation)
            saved = (
                repo.save_evaluation_if_absent(
                    assessment_id=assessment_id,
                    evaluation=(
                        evaluation.model_dump()
                    ),
                )
            )

            evaluation = (
                AssessmentEvaluation.model_validate(
                    saved["evaluation"]
                )
            )

        # ================================================
        # 总分始终由程序重新计算
        # 不需要单独再存 score_summary
        # ================================================

        score_summary = (
            validate_and_score_evaluation(
                quiz,
                evaluation,
            )
        )

        graded_rounds = (
            repo.count_graded_assessments(
                project_id=(
                    assessment["project_id"]
                ),
                node_id=(
                    assessment["node_id"]
                ),
            )
        )

    rounds_by_node = dict(
        state.get(
            "rounds_by_node",
            {},
        )
    )

    rounds_by_node[
        assessment["node_id"]
    ] = graded_rounds

    return {
        "evaluation": (
            evaluation.model_dump()
        ),
        "score_summary": (
            score_summary
        ),
        "rounds_by_node": (
            rounds_by_node
        ),
    }


def grade_quiz(
    quiz: AssessmentQuiz,
    answers: dict,
) -> AssessmentEvaluation:

    question_results = []

    for question_model in quiz.questions:
        question = (
            question_model.model_dump()
        )

        question_id = question["id"]

        if question_id not in answers:
            raise ValueError(
                f"缺少题目 {question_id} 的答案"
            )

        user_answer = answers[
            question_id
        ]

        if question["type"] in {
            "single_choice",
            "multiple_choice",
        }:
            result = grade_objective_question(
                question,
                user_answer,
            )

        elif (
            question["type"]
            == "short_answer"
        ):
            result = (
                grade_short_answer_question(
                    question,
                    user_answer,
                )
            )

        else:
            raise ValueError(
                "不支持题型："
                f"{question['type']}"
            )

        question_results.append(
            result
        )

    return AssessmentEvaluation(
        assessment_id=(
            quiz.assessment_id
        ),
        question_results=(
            question_results
        ),
    )
def assessment_prepare_node(state: LearningState):
    """先把本轮 ID 写入 Checkpoint，再允许出题节点产生业务事实。"""
    if not state.get("project_id"):
        raise ValueError("准备测验时缺少 project_id")
    with repository_for_state(state) as repo:
        round_no = repo.next_assessment_round(
            project_id=state["project_id"], node_id=state["current_node_id"]
        )
    # 保留旧卷、评价和诊断供出题节点构造复测上下文，新卷固定后再清空答案。
    return {
        "assessment_id": f"assessment_{uuid4().hex[:12]}",
        "assessment_round_no": round_no,
    }


def assessment_save_answers_node(
    state: LearningState,
):
    assessment_id = state.get(
        "assessment_id"
    )

    if not assessment_id:
        raise ValueError(
            "缺少 assessment_id"
        )

    answers = state.get(
        "answers"
    )

    if not isinstance(answers, dict):
        raise ValueError(
            "缺少合法 answers"
        )

    with repository_for_state(state) as repo:
        get_assessment_for_state(repo, state)
        saved = repo.save_answers_if_absent(
            assessment_id=assessment_id,
            answers=answers,
        )

    return {
        "answers": saved["answers"]
    }
