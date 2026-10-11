import math
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)
# =========================
# Assessment Schema
# =========================


class AssessmentQuestion(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
    )

    # 题目唯一 ID
    id: str

    # 题目类型
    type: Literal[
        "single_choice",
        "multiple_choice",
        "short_answer",
    ]

    # 这道题在测哪个学习目标
    objective_id: str

    # 用户看到的题面
    prompt: str

    # 选择题选项；简答题可以为空
    options: list[str] | None = None

    # 系统内部标准答案
    answer_key: str | list[str]

    # 系统内部评分标准
    rubric: str

    # 本题满分
    max_score: float = Field(gt=0, allow_inf_nan=False)


class LearningObjective(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
    )

    id: str
    description: str


class SkillNode(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
    )

    id: str
    title: str
    description: str

    objectives: list[LearningObjective] = Field(
        min_length=1,
        max_length=3,
    )

    prerequisite_ids: list[str]

    difficulty: str
    estimated_minutes: int


class TreePlan(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
    )

    nodes: list[SkillNode] = Field(
        min_length=8,
        max_length=12,
    )


class AssessmentQuiz(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
    )

    assessment_id: str
    node_id: str

    questions: list[AssessmentQuestion] = Field(
        min_length=1,
    )

    @model_validator(mode="after")
    def validate_unique_question_ids(self):
        question_ids = [
            question.id
            for question in self.questions
        ]

        if len(question_ids) != len(set(question_ids)):
            raise ValueError(
                "试卷中存在重复的题目 ID"
            )

        return self


class QuestionEvaluation(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
    )

    question_id: str

    # 本题实际得分
    score: float = Field(ge=0, allow_inf_nan=False)

    # 比如：
    # accumulator_overwritten
    # wrong_loop_condition
    error_tags: list[str] = Field(default_factory=list)

    # 为什么这么评分
    evidence: str

    # 给用户看的具体反馈
    feedback: str


class ShortAnswerGrade(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
    )

    score: float = Field(ge=0, allow_inf_nan=False)
    error_tags: list[str] = Field(default_factory=list)
    evidence: str
    feedback: str


class AssessmentEvaluation(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
    )

    assessment_id: str

    question_results: list[QuestionEvaluation] = Field(
        min_length=1,
    )

    @model_validator(mode="after")
    def validate_unique_question_results(self):
        question_ids = [
            result.question_id
            for result in self.question_results
        ]

        if len(question_ids) != len(set(question_ids)):
            raise ValueError(
                "评价结果中存在重复的题目 ID"
            )

        return self


def validate_quiz_against_node(
    quiz: AssessmentQuiz,
    node: SkillNode,
) -> None:

    if quiz.node_id != node.id:
        raise ValueError(
            f"试卷节点 {quiz.node_id} "
            f"与当前节点 {node.id} 不一致"
        )

    valid_objective_ids = {
        objective.id
        for objective in node.objectives
    }

    for question in quiz.questions:
        if question.objective_id not in valid_objective_ids:
            raise ValueError(
                f"题目 {question.id} "
                f"引用了不属于当前节点的学习目标："
                f"{question.objective_id}"
            )


def validate_and_score_evaluation(
    quiz: AssessmentQuiz,
    evaluation: AssessmentEvaluation,
) -> dict[str, float]:

    # 必须是同一轮测验
    if evaluation.assessment_id != quiz.assessment_id:
        raise ValueError(
            "评价的 assessment_id 与当前试卷不一致"
        )

    question_map = {
        question.id: question
        for question in quiz.questions
    }

    quiz_question_ids = set(question_map)

    result_question_ids = {
        result.question_id
        for result in evaluation.question_results
    }

    # 必须恰好把这一轮所有题都评完
    if (result_question_ids != quiz_question_ids
            or len(evaluation.question_results) != len(quiz.questions)):
        raise ValueError(
            "评价结果没有完整对应本次试卷题目"
        )

    total_score = 0.0
    total_max_score = 0.0

    for result in evaluation.question_results:
        question = question_map[result.question_id]

        if (not math.isfinite(result.score) or result.score < 0
                or not math.isfinite(question.max_score) or question.max_score <= 0):
            raise ValueError(f"题目 {result.question_id} 的分数必须是合法有限数值")

        if result.score > question.max_score:
            raise ValueError(
                f"题目 {result.question_id} 得分 "
                f"{result.score} 超过满分 "
                f"{question.max_score}"
            )

        total_score += result.score
        total_max_score += question.max_score

    if not math.isfinite(total_score) or not math.isfinite(total_max_score):
        raise ValueError("总分必须是有限数值")

    percentage = (
        total_score / total_max_score * 100
    )

    return {
        "total_score": total_score,
        "total_max_score": total_max_score,
        "percentage": percentage,
    }


class DiagnosisResult(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
    )

    weak_points: list[str] = Field(
        default_factory=list
    )

    evidence_ids: list[str] = Field(
        min_length=1
    )

    recommended_action: Literal[
        "advance",
        "remediate",
        "collect_more_evidence",
        "revisit_prerequisite",
    ]

    reason: str = Field(
        min_length=1
    )

    review_node_id: str | None = None

    @model_validator(mode="after")
    def validate_action_fields(self):
        # evidence_id 不允许重复
        if len(self.evidence_ids) != len(
            set(self.evidence_ids)
        ):
            raise ValueError(
                "evidence_ids 不能重复"
            )

        # revisit_prerequisite 必须指定复习节点
        if (
            self.recommended_action
            == "revisit_prerequisite"
            and self.review_node_id is None
        ):
            raise ValueError(
                "选择 revisit_prerequisite 时，"
                "必须提供 review_node_id"
            )

        # 其他 action 不应该偷偷携带 review_node_id
        if (
            self.recommended_action
            != "revisit_prerequisite"
            and self.review_node_id is not None
        ):
            raise ValueError(
                "只有 revisit_prerequisite "
                "可以提供 review_node_id"
            )

        return self


def validate_diagnosis_against_context(
    diagnosis: DiagnosisResult,
    *,
    valid_evidence_ids: set[str],
    prerequisite_closure: set[str],
) -> None:
    """
    校验 DiagnosisResult 中引用的外部证据和节点关系。
    """

    # ========================================================
    # 1. 所有 evidence_id 必须真实存在
    # ========================================================

    unknown_evidence_ids = (
        set(diagnosis.evidence_ids)
        - valid_evidence_ids
    )

    if unknown_evidence_ids:
        raise ValueError(
            "Diagnosis 引用了不存在的证据 ID："
            f"{sorted(unknown_evidence_ids)}"
        )

    # ========================================================
    # 2. revisit_prerequisite 时，只能回到前置闭包中的节点
    # ========================================================

    if (
        diagnosis.recommended_action
        == "revisit_prerequisite"
    ):
        review_node_id = diagnosis.review_node_id

        if review_node_id not in prerequisite_closure:
            raise ValueError(
                "review_node_id 不属于当前节点的"
                "前置闭包："
                f"{review_node_id}"
            )


def get_prerequisite_closure(
    tree: list[dict],
    current_node_id: str,
) -> set[str]:
    """
    返回当前节点所有直接 / 间接前置节点。
    """

    node_map = {
        node["id"]: node
        for node in tree
    }

    if current_node_id not in node_map:
        raise ValueError(
            f"当前节点不存在：{current_node_id}"
        )

    closure: set[str] = set()

    stack = list(
        node_map[current_node_id].get(
            "prerequisite_ids",
            [],
        )
    )

    while stack:
        node_id = stack.pop()

        if node_id in closure:
            continue

        if node_id not in node_map:
            raise ValueError(
                f"前置节点不存在：{node_id}"
            )

        closure.add(node_id)

        stack.extend(
            node_map[node_id].get(
                "prerequisite_ids",
                [],
            )
        )

    return closure
