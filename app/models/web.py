"""浏览器公开契约。内部 State 和私有试卷不属于此模型。"""

from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


class WebModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateProject(WebModel):
    goal: str = Field(min_length=2, max_length=500)
    request_id: UUID = Field(default_factory=uuid4)

    @field_validator("goal")
    @classmethod
    def clean_goal(cls, value):
        if len(value.strip()) < 2:
            raise ValueError("请输入至少两个字的学习目标")
        return value.strip()


class ResumeProject(WebModel):
    pending_input_id: str = Field(min_length=1, max_length=128)
    action: Literal["ask", "start_quiz", "return_to_current", "submit_answer",
                    "return_to_teaching", "rest", "retry_3"]
    message: str | None = Field(default=None, max_length=4000)
    answers: dict[str, str | list[str]] | None = None


class RetryProject(WebModel):
    retry_token: str = Field(min_length=1, max_length=128)


class Objective(WebModel):
    id: str
    description: str


class PublicNode(WebModel):
    id: str
    title: str
    description: str
    objectives: list[Objective]
    prerequisite_ids: list[str]
    difficulty: str
    estimated_minutes: int
    status: Literal["completed", "learning", "available", "locked"]


class PublicQuestion(WebModel):
    id: str
    type: Literal["single_choice", "multiple_choice", "short_answer"]
    objective_id: str
    prompt: str
    options: list[str] | None
    max_score: float


class PublicQuiz(WebModel):
    assessment_id: str
    node_id: str
    questions: list[PublicQuestion]


class PublicTurn(WebModel):
    role: Literal["user", "assistant"]
    content: str


class PublicFeedback(WebModel):
    question_id: str
    prompt: str
    score: float
    max_score: float
    feedback: str
    evidence: str
    error_tags: list[str]


class PublicResult(WebModel):
    assessment_id: str
    node_id: str
    node_title: str
    total_score: float
    total_max_score: float
    percentage: float
    question_results: list[PublicFeedback]
    weak_points: list[str]
    recommended_action: str | None
    reason: str
    completed: bool


class PublicError(WebModel):
    code: str
    message: str


class ProjectView(WebModel):
    project_id: str
    goal: str
    nodes: list[PublicNode]
    completed_count: int
    total_count: int
    current_node_id: str | None
    teaching_node_id: str | None
    lesson_mode: str
    page_state: Literal["learning", "quiz", "paused", "completed", "error", "running"]
    pending_input_id: str | None
    allowed_actions: list[str]
    lesson: str
    conversation: list[PublicTurn]
    quiz: PublicQuiz | None
    answers: dict[str, str | list[str]]
    answer_error: str
    results: list[PublicResult]
    rounds: int
    round_limit: int
    error: PublicError | None
    retry_token: str | None


class ProjectSummary(WebModel):
    project_id: str
    goal: str
    completed_count: int
    total_count: int
    page_state: str
