"""Strict, versioned V3 business contracts and contextual integrity checks.

This module never invokes a model, writes a completion, or enables evaluators.
Capability availability and policy authorization are checked by the trusted
registry; existence, ownership, and immutable identities are checked with the
actual project context before persistence or use.
"""

from hashlib import sha256
from typing import Annotated, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.v3.config import CONTRACT_VERSION, DB_SCHEMA_VERSION, GRAPH_VERSION, SERVER_LIMITS

Identity = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")]
Text = Annotated[str, Field(min_length=1, max_length=4000)]
Version = Annotated[str, Field(min_length=1, max_length=64)]
ContentHash = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
QuestionType = Literal["single_choice", "multiple_choice", "text", "numeric_scalar"]
EvidenceKind = Literal["choice", "numeric_result", "text_excerpt"]
SourceVisibility = Literal["teaching", "assessment_private"]
MaterialPurpose = Literal["teaching", "assessment", "grading"]
GradingStatus = Literal["graded", "needs_review", "invalid_item"]
Severity = Literal["minor", "major", "critical"]
AssessmentStatus = Literal["prepared", "awaiting_answer", "submitted", "graded", "needs_review", "invalid_item", "abandoned"]
PublicState = Literal[
    "profile_review", "materials_required", "plan_review", "learning", "quiz",
    "assessment_review", "budget_exhausted", "exploring", "paused", "completed",
    "error", "running", "legacy_readonly",
]
PublicAction = Literal[
    "begin",
    "confirm_profile", "update_profile", "import_material", "adjust_scope",
    "choose_exploration", "replan", "confirm_plan", "adjust_plan", "ask",
    "start_quiz", "return_to_current", "submit_answer", "view_feedback",
    "annotate_dispute", "replace_assessment", "rest", "retry_3",
    "continue_with_new_budget", "retry", "return_to_teaching",
]

# The server may return a subset. Clients may not invent extra actions.
STATE_ACTIONS: dict[str, frozenset[str]] = {
    "profile_review": frozenset({"confirm_profile", "update_profile", "import_material", "rest"}),
    "materials_required": frozenset({"import_material", "adjust_scope", "choose_exploration", "replan", "rest"}),
    "plan_review": frozenset({"confirm_plan", "adjust_plan", "import_material", "replan", "rest"}),
    "learning": frozenset({"begin", "ask", "start_quiz", "return_to_current", "rest"}),
    "quiz": frozenset({"submit_answer", "return_to_teaching", "rest"}),
    "assessment_review": frozenset({"view_feedback", "annotate_dispute", "replace_assessment", "return_to_teaching", "rest"}),
    "budget_exhausted": frozenset({"continue_with_new_budget", "rest"}),
    "exploring": frozenset({"begin", "ask", "rest"}),
    "paused": frozenset({"rest", "retry_3", "return_to_teaching"}),
    "completed": frozenset(),
    "error": frozenset({"retry", "return_to_teaching", "replace_assessment", "rest"}),
    "running": frozenset(),
    "legacy_readonly": frozenset(),
}


class ContractModel(BaseModel):
    # Frozen prevents field replacement; nested lists still need validation at
    # each trust boundary. This also catches unvalidated model_copy updates.
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, revalidate_instances="always")


def _unique(values, label: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{label}不允许重复")


class PriorAssessmentEvidence(ContractModel):
    project_id: Identity
    node_id: Identity
    assessment_id: Identity
    objective_id: Identity
    summary: Text


class PriorKnowledge(ContractModel):
    self_reported: list[Text] = Field(default_factory=list, max_length=20)
    assessed_evidence: list[PriorAssessmentEvidence] = Field(default_factory=list, max_length=20)


class LanguagePreference(ContractModel):
    teaching: str = Field(default="zh-CN", min_length=1, max_length=64)
    answering: str = Field(default="zh-CN", min_length=1, max_length=64)


class LearningProfile(ContractModel):
    subject_label: str = Field(min_length=1, max_length=128)
    topic: str = Field(min_length=1, max_length=256)
    goal: Text
    bounded_goal: Text | None = None
    prior_knowledge: PriorKnowledge = Field(default_factory=PriorKnowledge)
    target_level: str = Field(default="入门", min_length=1, max_length=128)
    language: LanguagePreference = Field(default_factory=LanguagePreference)
    time_budget_minutes: int = Field(default=120, gt=0, le=10080)
    session_minutes: int = Field(default=30, gt=0, le=480)
    scope_in: list[Text] = Field(default_factory=list, max_length=20)
    scope_out: list[Text] = Field(default_factory=list, max_length=20)
    learning_mode: Literal["formal", "exploration"] = "formal"
    requested_capabilities: list[Identity] = Field(default_factory=list, max_length=20)
    profile_version: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def validate_profile(self):
        if any(not value.strip() for value in (self.subject_label, self.topic, self.goal, self.target_level)):
            raise ValueError("学习主题和目标不能只包含空白")
        if self.bounded_goal is not None and not self.bounded_goal.strip():
            raise ValueError("确认范围不能只包含空白")
        if self.session_minutes > self.time_budget_minutes:
            raise ValueError("单次时长不得大于项目总预算")
        _unique(self.requested_capabilities, "请求能力")
        return self


class EvaluatorRef(ContractModel):
    evaluator_id: Identity
    evaluator_version: Version


class ObjectivePolicy(ContractModel):
    objective_id: Identity
    required: bool = True
    min_items: int = Field(default=1, ge=1, le=10)
    min_evidence: int = Field(default=1, ge=1, le=10)
    weight: float = Field(default=1.0, gt=0, allow_inf_nan=False)
    pass_threshold: float = Field(default=0.8, ge=0, le=1, allow_inf_nan=False)
    evidence_kinds: list[EvidenceKind] = Field(default_factory=lambda: ["choice"], min_length=1, max_length=3)


class EvaluationPolicy(ContractModel):
    policy_id: Identity
    policy_version: Version
    allowed_question_types: list[QuestionType] = Field(min_length=1, max_length=4)
    evaluators: list[EvaluatorRef] = Field(min_length=1, max_length=10)
    objective_rules: list[ObjectivePolicy] = Field(default_factory=list, max_length=100)
    total_pass_threshold: float = Field(default=0.8, ge=0, le=1, allow_inf_nan=False)
    numeric_abs_tolerance: float = Field(default=0.0, ge=0, allow_inf_nan=False)
    numeric_rel_tolerance: float = Field(default=0.0, ge=0, le=1, allow_inf_nan=False)
    critical_severities: list[Severity] = Field(default_factory=lambda: ["critical"], max_length=3)
    max_effective_rounds: int = Field(default=3, ge=1, le=3)
    max_round_extensions: int = Field(default=1, ge=0, le=1)
    extension_rounds: int = Field(default=3, ge=1, le=3)
    max_replacements: int = Field(default=2, ge=0, le=2)
    uncertain_handling: Literal["pause_review"] = "pause_review"
    missing_evidence_handling: Literal["collect_more_evidence", "pause_review"] = "collect_more_evidence"
    invalid_item_handling: Literal["replace_or_pause", "pause_review"] = "replace_or_pause"

    @model_validator(mode="after")
    def validate_policy_ids(self):
        _unique(self.allowed_question_types, "允许题型")
        _unique([ref.evaluator_id for ref in self.evaluators], "评价器")
        _unique([rule.objective_id for rule in self.objective_rules], "策略目标")
        _unique(self.critical_severities, "关键错误严重性")
        return self


class SourceRef(ContractModel):
    source_id: Identity
    source_version: int = Field(ge=1)
    content_hash: ContentHash


class SourceCitation(ContractModel):
    source_id: Identity
    source_version: int = Field(ge=1)
    chunk_id: Identity


class SourceDocument(ContractModel):
    source_id: Identity
    project_id: Identity
    title: str = Field(min_length=1, max_length=256)
    source_description: Text
    source_version: int = Field(ge=1)
    content: str = Field(min_length=1)
    content_hash: ContentHash
    trust_note: Text = "用户提供，未独立核验"
    visibility: SourceVisibility = "teaching"

    @model_validator(mode="after")
    def validate_content(self):
        raw = self.content.encode("utf-8")
        if len(raw) > SERVER_LIMITS.max_file_bytes:
            raise ValueError("资料超过服务端单文件字节上限")
        if sha256(raw).hexdigest() != self.content_hash:
            raise ValueError("资料内容哈希不匹配")
        return self


class SourceChunk(ContractModel):
    chunk_id: Identity
    project_id: Identity
    source_id: Identity
    source_version: int = Field(ge=1)
    content: str = Field(min_length=1)
    content_hash: ContentHash
    heading: str | None = Field(default=None, max_length=256)
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_chunk(self):
        if self.line_end < self.line_start:
            raise ValueError("片段结束行早于开始行")
        raw = self.content.encode("utf-8")
        if len(raw) > SERVER_LIMITS.max_file_bytes:
            raise ValueError("片段超过服务端大小上限")
        if sha256(raw).hexdigest() != self.content_hash:
            raise ValueError("片段内容哈希不匹配")
        return self


class NodeMaterialLink(ContractModel):
    project_id: Identity
    node_id: Identity
    objective_id: Identity
    chunk_id: Identity
    purpose: MaterialPurpose


class LearningObjective(ContractModel):
    objective_id: Identity
    observable_outcome: Text
    required_capability_ids: list[Identity] = Field(min_length=1, max_length=20)
    evidence_requirement: list[EvidenceKind] = Field(min_length=1, max_length=3)
    required: bool = True
    source_chunk_ids: list[Identity] = Field(default_factory=list, max_length=20)
    criterion_ids: list[Identity] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_objective(self):
        if self.observable_outcome.strip() in {"熟练掌握", "深入理解", "掌握", "理解"}:
            raise ValueError("学习目标需要可观察行为，不能只有笼统掌握描述")
        _unique(self.required_capability_ids, "目标所需能力")
        _unique(self.source_chunk_ids, "目标来源片段")
        _unique(self.criterion_ids, "量规标准")
        return self


class SkillNode(ContractModel):
    node_id: Identity
    title: str = Field(min_length=1, max_length=256)
    description: Text
    objectives: list[LearningObjective] = Field(min_length=1, max_length=5)
    prerequisite_ids: list[Identity] = Field(default_factory=list, max_length=19)
    estimated_minutes: int = Field(gt=0, le=480)

    @model_validator(mode="after")
    def validate_node(self):
        _unique([objective.objective_id for objective in self.objectives], "节点内目标身份")
        _unique(self.prerequisite_ids, "依赖节点")
        if self.node_id in self.prerequisite_ids:
            raise ValueError("节点不能依赖自己")
        return self


class LearningPlan(ContractModel):
    project_id: Identity
    plan_version: int = Field(default=1, ge=1)
    draft_revision: int = Field(ge=0)
    nodes: list[SkillNode] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def validate_dag(self):
        _unique([node.node_id for node in self.nodes], "计划节点")
        # Policy and assessment references use objective_id without node_id;
        # therefore identities must also be unambiguous within this project.
        _unique([objective.objective_id for node in self.nodes for objective in node.objectives], "项目内目标身份")
        nodes = {node.node_id: node for node in self.nodes}
        remaining = {key: set(node.prerequisite_ids) for key, node in nodes.items()}
        if any(not prerequisites <= nodes.keys() for prerequisites in remaining.values()):
            raise ValueError("依赖了计划中不存在的节点")
        visited = set()
        while remaining:
            ready = {key for key, prerequisites in remaining.items() if prerequisites <= visited}
            if not ready:
                raise ValueError("技能计划包含依赖环")
            visited.update(ready)
            remaining = {key: prerequisites for key, prerequisites in remaining.items() if key not in ready}
        return self


class FrozenSnapshot(ContractModel):
    profile_version: int = Field(ge=1)
    plan_version: int = Field(ge=1)
    policy_id: Identity
    policy_version: Version
    source_manifest: list[SourceRef] = Field(min_length=1, max_length=100)
    evaluator_manifest: list[EvaluatorRef] = Field(min_length=1, max_length=10)
    contract_version: Literal["3.0.0"] = CONTRACT_VERSION

    @model_validator(mode="after")
    def validate_manifest(self):
        _unique([ref.source_id for ref in self.source_manifest], "冻结来源")
        _unique([ref.evaluator_id for ref in self.evaluator_manifest], "冻结评价器")
        return self


class ChoiceOption(ContractModel):
    option_id: Identity
    text: Text


class NumericRules(ContractModel):
    expected: float = Field(allow_inf_nan=False)
    unit: str | None = Field(default=None, max_length=32)
    allowed_units: list[str] = Field(default_factory=list, max_length=10)
    abs_tolerance: float = Field(default=0.0, ge=0, allow_inf_nan=False)
    rel_tolerance: float = Field(default=0.0, ge=0, le=1, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_units(self):
        _unique(self.allowed_units, "允许单位")
        if self.unit is not None and self.unit not in self.allowed_units:
            raise ValueError("参考值单位必须在冻结单位白名单中")
        return self


class RubricCriterion(ContractModel):
    criterion_id: Identity
    description: Text
    max_score: float = Field(gt=0, allow_inf_nan=False)
    acceptable_alternatives: list[Text] = Field(default_factory=list, max_length=20)
    critical: bool = False


class AssessmentQuestion(ContractModel):
    question_id: Identity
    objective_ids: list[Identity] = Field(min_length=1, max_length=5)
    question_type: QuestionType
    prompt: Text
    max_score: float = Field(gt=0, allow_inf_nan=False)
    evaluator_id: Identity
    evaluator_version: Version
    source_citations: list[SourceCitation] = Field(min_length=1, max_length=20)
    options: list[ChoiceOption] = Field(default_factory=list, max_length=20)
    answer_key: str | list[Identity] | None = None
    numeric_rules: NumericRules | None = None
    rubric: list[RubricCriterion] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_question(self):
        _unique(self.objective_ids, "题目目标")
        option_ids = [option.option_id for option in self.options]
        _unique(option_ids, "选项身份")
        if self.question_type in {"single_choice", "multiple_choice"}:
            if len(option_ids) < 2:
                raise ValueError("选择题需要至少两个不同选项")
            keys = [self.answer_key] if isinstance(self.answer_key, str) else self.answer_key
            if not keys or not set(keys) <= set(option_ids):
                raise ValueError("选择题答案键必须属于实际选项")
            _unique(keys, "正确选项")
            if self.question_type == "single_choice" and not isinstance(self.answer_key, str):
                raise ValueError("单选题答案键必须为一个选项ID")
            if self.question_type == "multiple_choice" and not isinstance(self.answer_key, list):
                raise ValueError("多选题答案键必须为选项ID列表")
        elif self.options:
            raise ValueError("文字与数值题不应带选择题选项")
        if self.question_type == "numeric_scalar" and self.numeric_rules is None:
            raise ValueError("数值题需要冻结数值、单位和容差规则")
        if self.question_type != "numeric_scalar" and self.numeric_rules is not None:
            raise ValueError("只有数值题允许数值规则")
        if self.question_type == "text":
            if not self.rubric:
                raise ValueError("文字题需要可执行分项量规")
            if abs(sum(criterion.max_score for criterion in self.rubric) - self.max_score) > 1e-9:
                raise ValueError("分项量规满分与本题满分不一致")
        _unique([criterion.criterion_id for criterion in self.rubric], "分项量规身份")
        return self


class AssessmentQuiz(ContractModel):
    project_id: Identity
    node_id: Identity
    assessment_id: Identity
    snapshot: FrozenSnapshot
    questions: list[AssessmentQuestion] = Field(min_length=1, max_length=10)
    previous_assessment_id: Identity | None = None

    @model_validator(mode="after")
    def validate_question_ids(self):
        _unique([question.question_id for question in self.questions], "试卷题目")
        if self.previous_assessment_id == self.assessment_id:
            raise ValueError("新测验不能关联自身作为前一测验")
        return self


class AnswerEvidence(ContractModel):
    evidence_id: Identity
    question_id: Identity
    kind: EvidenceKind
    quote: str | None = Field(default=None, max_length=4000)
    start: int | None = Field(default=None, ge=0)
    end: int | None = Field(default=None, ge=0)
    selected_option_ids: list[Identity] = Field(default_factory=list, max_length=20)
    numeric_value: float | None = Field(default=None, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_location(self):
        if self.kind == "text_excerpt":
            if self.start is None or self.end is None or not self.quote or self.end <= self.start:
                raise ValueError("文字证据必须有非空原文和有效起止位置")
        if self.kind == "choice" and not self.selected_option_ids:
            raise ValueError("选择证据必须记录实际选项")
        if self.kind == "numeric_result" and self.numeric_value is None:
            raise ValueError("数值证据必须有有限数值")
        _unique(self.selected_option_ids, "作答证据选项")
        return self


class CriterionResult(ContractModel):
    criterion_id: Identity
    score: float = Field(ge=0, allow_inf_nan=False)
    max_score: float = Field(gt=0, allow_inf_nan=False)
    evidence_ids: list[Identity] = Field(default_factory=list, max_length=20)
    severity: Severity | None = None
    subject_tags: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_score(self):
        if self.score > self.max_score:
            raise ValueError("分项得分超过满分")
        return self


class QuestionResult(ContractModel):
    question_id: Identity
    evaluator_id: Identity
    evaluator_version: Version
    score: float = Field(ge=0, allow_inf_nan=False)
    max_score: float = Field(gt=0, allow_inf_nan=False)
    evidence_ids: list[Identity] = Field(min_length=1, max_length=20)
    criterion_results: list[CriterionResult] = Field(default_factory=list, max_length=20)
    feedback: Text

    @model_validator(mode="after")
    def validate_score(self):
        if self.score > self.max_score:
            raise ValueError("本题得分超过满分")
        _unique(self.evidence_ids, "题目证据")
        _unique([result.criterion_id for result in self.criterion_results], "量规结果")
        return self


class ObjectiveResult(ContractModel):
    objective_id: Identity
    score_ratio: float = Field(ge=0, le=1, allow_inf_nan=False)
    evidence_ids: list[Identity] = Field(min_length=1, max_length=20)
    criterion_ids: list[Identity] = Field(default_factory=list, max_length=20)


class EvaluationResult(ContractModel):
    project_id: Identity
    node_id: Identity
    assessment_id: Identity
    snapshot: FrozenSnapshot
    grading_status: GradingStatus
    question_results: list[QuestionResult] = Field(default_factory=list, max_length=10)
    objective_results: list[ObjectiveResult] = Field(default_factory=list, max_length=5)
    evidence: list[AnswerEvidence] = Field(default_factory=list, max_length=100)
    uncertainty_reasons: list[Text] = Field(default_factory=list, max_length=20)
    missing_evidence: list[Text] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_result(self):
        _unique([result.question_id for result in self.question_results], "评价题目")
        _unique([result.objective_id for result in self.objective_results], "评价目标")
        _unique([item.evidence_id for item in self.evidence], "作答证据身份")
        if self.grading_status == "graded" and (not self.question_results or self.uncertainty_reasons or self.missing_evidence):
            raise ValueError("有效评价必须有完整题目结果且不能仍有不确定或缺失证据")
        if self.grading_status != "graded" and not self.uncertainty_reasons:
            raise ValueError("非有效评价必须明确记录异常原因")
        evidence_ids = {item.evidence_id for item in self.evidence}
        references = [identity for result in self.question_results for identity in result.evidence_ids]
        references += [identity for result in self.objective_results for identity in result.evidence_ids]
        references += [identity for result in self.question_results for criterion in result.criterion_results for identity in criterion.evidence_ids]
        if not set(references) <= evidence_ids:
            raise ValueError("结果引用了不存在的作答证据")
        return self


class PublicQuestion(ContractModel):
    question_id: Identity
    objective_ids: list[Identity]
    question_type: QuestionType
    prompt: Text
    max_score: float = Field(gt=0, allow_inf_nan=False)
    options: list[ChoiceOption]


class PublicQuiz(ContractModel):
    assessment_id: Identity
    node_id: Identity
    questions: list[PublicQuestion]

    @classmethod
    def from_private(cls, quiz: AssessmentQuiz):
        return cls(assessment_id=quiz.assessment_id, node_id=quiz.node_id, questions=[
            PublicQuestion(**question.model_dump(include={"question_id", "objective_ids", "question_type", "prompt", "max_score", "options"}))
            for question in quiz.questions
        ])


class PublicSource(ContractModel):
    source_id: Identity
    source_version: int = Field(ge=1)
    title: str
    source_description: str
    trust_note: str
    visibility: Literal["teaching"] = "teaching"

    @classmethod
    def from_document(cls, source: SourceDocument):
        if source.visibility != "teaching":
            raise ValueError("私有测评资料不可投影为公开教学资料")
        return cls(**source.model_dump(include={"source_id", "source_version", "title", "source_description", "trust_note", "visibility"}))


class PublicProjectView(ContractModel):
    project_id: Identity
    thread_id: Identity
    profile: LearningProfile
    page_state: PublicState = "profile_review"
    allowed_actions: list[PublicAction] = Field(default_factory=list)
    pending_input_id: Identity | None = None
    retry_token: Identity | None = None
    draft_revision: int = Field(default=0, ge=0)
    requires_replan: bool = False
    db_schema_version: Literal["v3-day10-2"] = DB_SCHEMA_VERSION
    graph_version: Literal["v3-day10-preparation"] = GRAPH_VERSION
    contract_version: Literal["3.0.0"] = CONTRACT_VERSION
    quiz: PublicQuiz | None = None

    @model_validator(mode="after")
    def validate_permissions(self):
        if self.thread_id != self.project_id:
            raise ValueError("V3项目必须始终使用 project_id = thread_id")
        _unique(self.allowed_actions, "公开动作")
        if not set(self.allowed_actions) <= STATE_ACTIONS[self.page_state]:
            raise ValueError("公开动作不属于当前状态允许范围")
        retry_actions = {"retry", "continue_with_new_budget"}
        if set(self.allowed_actions) & retry_actions and not self.retry_token:
            raise ValueError("技术重试或预算追加必须有retry_token")
        if set(self.allowed_actions) - retry_actions - {'begin'} and not self.pending_input_id:
            raise ValueError("用户动作必须绑定pending_input_id")
        if self.requires_replan and "confirm_plan" in self.allowed_actions:
            raise ValueError("过期计划不得公开确认动作")
        if self.profile.learning_mode == "exploration" and (self.quiz is not None or "start_quiz" in self.allowed_actions):
            raise ValueError("探索项目不具有正式测评权限")
        return self


def validate_material_link(link: NodeMaterialLink, *, project_id: str, plan: LearningPlan,
                           chunks: Mapping[str, SourceChunk], sources: Mapping[str, SourceDocument]) -> None:
    """A valid-looking ID is insufficient: check actual ownership and version."""
    link = NodeMaterialLink.model_validate(link)
    plan = LearningPlan.model_validate(plan)
    if link.project_id != project_id or plan.project_id != project_id:
        raise ValueError("资料绑定跨项目")
    nodes = {node.node_id: node for node in plan.nodes}
    node = nodes.get(link.node_id)
    if node is None or link.objective_id not in {objective.objective_id for objective in node.objectives}:
        raise ValueError("资料绑定引用未知节点或目标")
    chunk = chunks.get(link.chunk_id)
    if chunk is None or chunk.project_id != project_id:
        raise ValueError("资料片段不存在或归属其它项目")
    chunk = SourceChunk.model_validate(chunk)
    source = sources.get(chunk.source_id)
    if source is None or source.project_id != project_id or source.source_version != chunk.source_version:
        raise ValueError("资料来源归属或版本不匹配")
    source = SourceDocument.model_validate(source)
    if source.visibility == "assessment_private" and link.purpose == "teaching":
        raise ValueError("私有测评片段不得绑定教学用途")
    lines = source.content.splitlines()
    if chunk.line_end > len(lines) or "\n".join(lines[chunk.line_start - 1:chunk.line_end]) != chunk.content:
        raise ValueError("资料片段无法在来源行号范围定位")


def validate_evaluation_context(result: EvaluationResult, *, quiz: AssessmentQuiz,
                                answers: Mapping[str, str | list[str]]) -> None:
    """Validate identities, frozen standards, coverage, and real answer anchors.

    Passing this function is not a pass decision. The future deterministic
    policy guard must also check necessary objectives, critical errors, history
    and prerequisites before recording a completion.
    """
    result = EvaluationResult.model_validate(result)
    quiz = AssessmentQuiz.model_validate(quiz)
    if (result.project_id, result.node_id, result.assessment_id) != (quiz.project_id, quiz.node_id, quiz.assessment_id):
        raise ValueError("评价与试卷项目、节点或测验身份不一致")
    if result.snapshot != quiz.snapshot:
        raise ValueError("评价不符合本轮冻结版本")
    questions = {question.question_id: question for question in quiz.questions}
    if set(answers) != questions.keys():
        raise ValueError("实际答案漏题或包含未知题目")
    actual = {item.question_id: item for item in result.question_results}
    if not actual.keys() <= questions.keys() or (result.grading_status == "graded" and actual.keys() != questions.keys()):
        raise ValueError("评价漏题或包含未知题目")
    for question_id, item in actual.items():
        question = questions[question_id]
        if item.max_score != question.max_score or (item.evaluator_id, item.evaluator_version) != (question.evaluator_id, question.evaluator_version):
            raise ValueError("评分上限或评价器与冻结题目不一致")
        criteria = {criterion.criterion_id: criterion for criterion in question.rubric}
        if result.grading_status == "graded" and {criterion.criterion_id for criterion in item.criterion_results} != criteria.keys():
            raise ValueError("评价漏掉分项量规或引用了未知标准")
        for criterion in item.criterion_results:
            if criterion.criterion_id not in criteria or criterion.max_score != criteria[criterion.criterion_id].max_score:
                raise ValueError("分项满分与冻结量规不一致")
        if item.criterion_results and abs(sum(criterion.score for criterion in item.criterion_results) - item.score) > 1e-9:
            raise ValueError("题目得分与量规分项得分不一致")
    evidence = {item.evidence_id: item for item in result.evidence}
    for item in result.evidence:
        if item.question_id not in questions:
            raise ValueError("证据指向不存在的题目")
        expected_kind = {"single_choice": "choice", "multiple_choice": "choice", "text": "text_excerpt", "numeric_scalar": "numeric_result"}[questions[item.question_id].question_type]
        if item.kind != expected_kind:
            raise ValueError("证据形式不符合冻结题目的作答形式")
        answer = answers[item.question_id]
        if item.kind == "text_excerpt":
            if not isinstance(answer, str) or answer[item.start:item.end] != item.quote or item.end > len(answer):
                raise ValueError("文字证据不能定位到实际作答")
        elif item.kind == "choice":
            selected = [answer] if isinstance(answer, str) else answer
            if set(item.selected_option_ids) != set(selected) or not set(selected) <= {option.option_id for option in questions[item.question_id].options}:
                raise ValueError("选择证据与实际作答不一致")
        else:
            # Numeric evaluators parse the frozen unit grammar. This contract
            # verifies provenance; it must not execute an answer as Python.
            if not isinstance(answer, str) or item.quote != answer:
                raise ValueError("数值证据必须保留完整实际作答文本")
    for item in result.question_results:
        if any(evidence[identity].question_id != item.question_id for identity in item.evidence_ids):
            raise ValueError("题目结果串用了其它题的作答证据")
        for criterion in item.criterion_results:
            if any(evidence[identity].question_id != item.question_id for identity in criterion.evidence_ids):
                raise ValueError("分项评分串用了其它题的作答证据")
    objective_ids = {identity for question in quiz.questions for identity in question.objective_ids}
    if result.grading_status == "graded" and {item.objective_id for item in result.objective_results} != objective_ids:
        raise ValueError("有效评价漏掉本卷目标结果")
    for item in result.objective_results:
        if item.objective_id not in objective_ids:
            raise ValueError("目标结果包含未知目标")
        if any(item.objective_id not in questions[evidence[identity].question_id].objective_ids for identity in item.evidence_ids):
            raise ValueError("目标结果串用了无关题目证据")
