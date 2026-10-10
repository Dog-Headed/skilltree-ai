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
    max_score: float = Field(gt=0)


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
    score: float = Field(ge=0)

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

    score: float = Field(ge=0)
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
    if result_question_ids != quiz_question_ids:
        raise ValueError(
            "评价结果没有完整对应本次试卷题目"
        )

    total_score = 0.0
    total_max_score = 0.0

    for result in evaluation.question_results:
        question = question_map[result.question_id]

        if result.score > question.max_score:
            raise ValueError(
                f"题目 {result.question_id} 得分 "
                f"{result.score} 超过满分 "
                f"{question.max_score}"
            )

        total_score += result.score
        total_max_score += question.max_score

    percentage = (
        total_score / total_max_score * 100
    )

    return {
        "total_score": total_score,
        "total_max_score": total_max_score,
        "percentage": percentage,
    }