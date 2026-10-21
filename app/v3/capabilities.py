"""Trusted, code-owned V3 capabilities. Configuration cannot install handlers.

Day 11 adds a restricted scalar evaluator and quoted, frozen text rubrics.
V2's Python grader is deliberately not reused. Modality/execution gaps remain.
"""

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.v3.contracts import Identity, Text


EVALUATOR_VERSION = "1.0.0"


class CapabilityCheck(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    status: Literal["supported", "needs_material", "exploration_only", "unsupported"]
    formal_assessment_allowed: bool
    requested_capability_ids: list[str]
    unavailable_capability_ids: list[str]
    reasons: list[str]


class ChoiceOption(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    option_id: Identity
    text: Text


class ChoiceExactItem(BaseModel):
    """Private evaluator input; correct_option_ids must never enter a public DTO."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    item_id: Identity
    objective_id: Identity
    question_type: Literal["single_choice", "multiple_choice"]
    options: list[ChoiceOption] = Field(min_length=2, max_length=20)
    correct_option_ids: list[Identity] = Field(min_length=1, max_length=20)
    max_score: float = Field(gt=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_choices(self):
        option_ids = [option.option_id for option in self.options]
        if len(set(option_ids)) != len(option_ids):
            raise ValueError("选择题选项身份不得重复")
        if len(set(self.correct_option_ids)) != len(self.correct_option_ids):
            raise ValueError("标准答案不得重复")
        if not set(self.correct_option_ids).issubset(option_ids):
            raise ValueError("标准答案必须引用存在的选项")
        if self.question_type == "single_choice" and len(self.correct_option_ids) != 1:
            raise ValueError("单选题必须恰有一个标准答案")
        return self


class ChoiceExactResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    item_id: str
    objective_id: str
    evaluator_id: Literal["choice_exact"] = "choice_exact"
    evaluator_version: str = EVALUATOR_VERSION
    evaluation_status: Literal["valid"] = "valid"
    score: float = Field(ge=0, allow_inf_nan=False)
    max_score: float = Field(gt=0, allow_inf_nan=False)
    correct: bool
    selected_option_ids: list[str]


def evaluate_choice_exact(
    item: ChoiceExactItem | dict[str, Any], answer: str | list[str]
) -> ChoiceExactResult:
    """All-or-nothing exact selection; no LLM, import, expression or code execution.

    Invalid answer shape is rejected instead of being recorded as student failure.
    This score alone is not permission to pass a node or unlock dependencies.
    """
    # Pydantic's frozen setting does not freeze nested lists or validate model_copy.
    item = ChoiceExactItem.model_validate(item.model_dump() if isinstance(item, ChoiceExactItem) else item)
    if item.question_type == "single_choice":
        if not isinstance(answer, str):
            raise ValueError("单选答案必须是选项身份字符串")
        selected = [answer]
    else:
        if not isinstance(answer, list) or not all(isinstance(value, str) for value in answer):
            raise ValueError("多选答案必须是选项身份字符串列表")
        selected = list(answer)
    if len(set(selected)) != len(selected):
        raise ValueError("答案不得包含重复选项")
    if not set(selected).issubset(option.option_id for option in item.options):
        raise ValueError("答案包含不存在的选项")
    correct = set(selected) == set(item.correct_option_ids)
    return ChoiceExactResult(
        item_id=item.item_id,
        objective_id=item.objective_id,
        score=item.max_score if correct else 0.0,
        max_score=item.max_score,
        correct=correct,
        selected_option_ids=selected,
    )


@dataclass(frozen=True)
class CapabilityDefinition:
    capability_id: str
    version: str
    kind: Literal["teaching", "evaluation", "modality", "execution"]
    input_types: tuple[str, ...]
    task_description: str
    output_contract: str
    availability: Literal["available", "planned", "unsupported"]
    limitations: tuple[str, ...]
    evaluator_id: str | None = None

    def public_dict(self) -> dict[str, Any]:
        # Explicit whitelist: callable handlers and private answers cannot leak.
        return {
            "capability_id": self.capability_id,
            "version": self.version,
            "kind": self.kind,
            "input_types": list(self.input_types),
            "task_description": self.task_description,
            "output_contract": self.output_contract,
            "availability": self.availability,
            "evaluator_id": self.evaluator_id,
            "formal_assessment_available": is_evaluator_available(self.evaluator_id, self.version),
            "limitations": list(self.limitations),
        }


def _definition(
    capability_id: str,
    kind: Literal["teaching", "evaluation", "modality", "execution"],
    availability: Literal["available", "planned", "unsupported"],
    description: str,
    inputs: tuple[str, ...],
    output: str,
    limitations: tuple[str, ...],
    evaluator_id: str | None = None,
) -> CapabilityDefinition:
    return CapabilityDefinition(
        capability_id, EVALUATOR_VERSION, kind, inputs, description, output,
        availability, limitations, evaluator_id,
    )


_CAPABILITIES = MappingProxyType({
    entry.capability_id: entry
    for entry in (
        _definition("text_explanation", "teaching", "available", "文字讲解", ("text",), "text", ("依据当前目标、绑定资料和最近对话提供文字讲解。", "探索讲解不形成正式通过记录。")),
        _definition("text_question_answer", "teaching", "available", "文字问答", ("text",), "text", ("支持文字提问；只保留当前节点最近六轮完整问答作为教学上下文。", "普通问答不能代替正式评价。")),
        _definition("choice_exact", "evaluation", "available", "单选与多选精确匹配", ("single_choice", "multiple_choice"), "ChoiceExactResult", ("仅验证所选选项。", "题目与答案依据须由正式计划及资料校验保证。", "多选采用全对得分，不给部分分。"), "choice_exact"),
        _definition("numeric_scalar", "evaluation", "available", "受限数值与单位评价", ("numeric_scalar",), "ItemEvaluation", ("只解析有限十进制/科学记数与冻结白名单单位；不执行表达式。", "支持代码固定的长度、时间、质量与百分比单位；未知单位或解析失败进入复核。", "不验证符号证明或完整推导。"), "numeric_scalar"),
        _definition("text_rubric", "evaluation", "available", "冻结量规文字评价", ("text",), "TextEvaluation", ("模型依据冻结参考答案、分项量规与实际作答原文评价，保留误判可能。", "结构或伪造证据最多修复一次；不确定和无效题目暂停复核。", "有引用不代表资料必然支持结论；不代替代码执行或符号证明。"), "text_rubric"),
        _definition("code_execution", "execution", "unsupported", "执行任意程序与测试", ("code",), "execution_evidence", ("尚无隔离代码沙箱。",)),
        _definition("symbolic_proof", "evaluation", "unsupported", "数学符号证明与等价验证", ("text",), "proof_evidence", ("普通文字评分不能冒充形式验证。",)),
        _definition("audio_input", "modality", "unsupported", "接收音频", ("audio",), "audio", ("V3.0 仅支持文字输入。",)),
        _definition("audio_output", "modality", "unsupported", "输出音频", ("text",), "audio", ("V3.0 仅支持文字输出。",)),
        _definition("pronunciation", "evaluation", "unsupported", "发音评价", ("audio",), "pronunciation_evidence", ("不得用文字题替代实际发音评价。",)),
        _definition("image_input", "modality", "unsupported", "接收与评价图像", ("image",), "image_evidence", ("V3.0 不支持图像评价。",)),
        _definition("experiment_observation", "evaluation", "unsupported", "实验或操作过程评价", ("observation",), "process_evidence", ("没有过程证据接收与验证能力。",)),
    )
})

# The only executable registration is reviewed Python code in this module.
from app.v3.evaluators import evaluate_numeric_scalar, evaluate_text_rubric

_EVALUATOR_HANDLERS = MappingProxyType({
    ("choice_exact", EVALUATOR_VERSION): evaluate_choice_exact,
    ("numeric_scalar", EVALUATOR_VERSION): evaluate_numeric_scalar,
    ("text_rubric", EVALUATOR_VERSION): evaluate_text_rubric,
})


def get_capability(capability_id: str) -> CapabilityDefinition | None:
    return _CAPABILITIES.get(capability_id)


def list_capabilities() -> list[dict[str, Any]]:
    return [entry.public_dict() for entry in _CAPABILITIES.values()]


def is_evaluator_available(evaluator_id: str | None, evaluator_version: str) -> bool:
    if evaluator_id is None:
        return False
    entry = _CAPABILITIES.get(evaluator_id)
    return bool(
        entry and entry.kind == "evaluation" and entry.availability == "available"
        and (evaluator_id, evaluator_version) in _EVALUATOR_HANDLERS
    )


def get_evaluator_handler(evaluator_id: str, evaluator_version: str) -> Callable[..., Any]:
    if not is_evaluator_available(evaluator_id, evaluator_version):
        raise ValueError(f"评价器尚未实装或版本不可用：{evaluator_id}@{evaluator_version}")
    return _EVALUATOR_HANDLERS[(evaluator_id, evaluator_version)]


def check_capabilities(
    requested_capability_ids: Any, *, has_material: bool,
    learning_mode: Literal["formal", "exploration"] = "formal",
) -> CapabilityCheck:
    """Check concrete required abilities, independent of the subject label.

    has_material means the caller has already checked suitable, bound evidence;
    merely uploading a file must not set it true in later course preparation.
    """
    if not isinstance(requested_capability_ids, list):
        from app.v3.contracts import LearningProfile

        profile = LearningProfile.model_validate(requested_capability_ids.model_dump() if isinstance(requested_capability_ids, LearningProfile) else requested_capability_ids)
        requested_capability_ids = profile.requested_capabilities
        learning_mode = profile.learning_mode
    if not all(isinstance(value, str) and value for value in requested_capability_ids):
        raise ValueError("能力请求必须是非空身份字符串列表")
    if type(has_material) is not bool or learning_mode not in ("formal", "exploration"):
        raise ValueError("能力检查参数不合法")
    ids = list(dict.fromkeys(requested_capability_ids))
    unknown = [value for value in ids if value not in _CAPABILITIES]
    unsupported = [value for value in ids if value in _CAPABILITIES and _CAPABILITIES[value].availability == "unsupported"]
    planned = [value for value in ids if value in _CAPABILITIES and _CAPABILITIES[value].availability == "planned"]
    unavailable = unknown + unsupported + planned
    reasons: list[str] = []
    if unknown or unsupported:
        status = "unsupported"
        reasons.append("所需输入、执行或评价能力未知或不受支持：" + ", ".join(unknown + unsupported))
    elif planned:
        status = "exploration_only"
        reasons.append("所需评价器尚未实装，只能选择标注清楚的文字探索：" + ", ".join(planned))
    elif learning_mode == "exploration":
        status = "exploration_only"
        reasons.append("探索模式不生成正式测评通过或依赖解锁记录。")
    elif not any(_CAPABILITIES[value].kind == "evaluation" and is_evaluator_available(_CAPABILITIES[value].evaluator_id, _CAPABILITIES[value].version) for value in ids):
        status = "exploration_only"
        reasons.append("未指定已实装评价能力；文字讲解不能代替正式测评。")
    elif not has_material:
        status = "needs_material"
        reasons.append("评价器可用，但尚无经检查可覆盖目标的资料与答案依据。")
    else:
        status = "supported"
        reasons.append("所需评价器已实装且资料条件满足；正式计划仍须校验并确认。")
    return CapabilityCheck(
        status=status, formal_assessment_allowed=status == "supported",
        requested_capability_ids=ids, unavailable_capability_ids=unavailable, reasons=reasons,
    )


def check_profile_capabilities(profile: Any, *, has_material: bool) -> CapabilityCheck:
    # Import locally to keep the static registry independent of graph/runtime.
    from app.v3.contracts import LearningProfile

    validated = LearningProfile.model_validate(profile.model_dump() if isinstance(profile, LearningProfile) else profile)
    return check_capabilities(validated.requested_capabilities, has_material=has_material, learning_mode=validated.learning_mode)


def validate_evaluation_policy(policy: Any, *, limits: Any = None):
    """Validate data proposals against trusted capabilities and server standards."""
    from app.v3.config import SERVER_LIMITS, ServerLimits
    from app.v3.contracts import EvaluationPolicy

    if limits is not None and not isinstance(limits, ServerLimits):
        raise ValueError("服务器上限必须来自可信 ServerLimits 配置，不能从模型或模板字典加载")
    limits = ServerLimits.model_validate(SERVER_LIMITS if limits is None else limits)
    validated = EvaluationPolicy.model_validate(policy.model_dump() if isinstance(policy, EvaluationPolicy) else policy)
    if validated.total_pass_threshold < limits.min_total_pass_threshold:
        raise ValueError("策略不能降低服务端总分通过底线")
    if any(rule.pass_threshold < limits.min_objective_pass_threshold for rule in validated.objective_rules):
        raise ValueError("策略不能降低服务端目标通过底线")
    if validated.numeric_abs_tolerance > limits.max_numeric_absolute_tolerance:
        raise ValueError("数值策略绝对容差不能超过服务端上限")
    if validated.numeric_rel_tolerance > limits.max_numeric_relative_tolerance:
        raise ValueError("数值策略相对容差不能超过服务端上限")
    for field, upper in (
        ("max_effective_rounds", limits.max_effective_rounds),
        ("max_round_extensions", limits.max_round_extensions),
        ("extension_rounds", limits.max_extension_rounds),
        ("max_replacements", limits.max_replacements),
    ):
        if getattr(validated, field) > upper:
            raise ValueError(f"策略不能扩大服务端上限：{field}")
    if "critical" not in validated.critical_severities:
        raise ValueError("策略不得取消关键错误阻断")
    evaluator_ids: set[str] = set()
    for reference in validated.evaluators:
        get_evaluator_handler(reference.evaluator_id, reference.evaluator_version)
        evaluator_ids.add(reference.evaluator_id)
    # Type compatibility is code-owned, not declared by uploaded configuration.
    compatible = {"single_choice": "choice_exact", "multiple_choice": "choice_exact", "text": "text_rubric", "numeric_scalar": "numeric_scalar"}
    for question_type in validated.allowed_question_types:
        if compatible[question_type] not in evaluator_ids:
            raise ValueError(f"题型没有对应的已实装评价器：{question_type}")
    evidence_evaluators = {"choice": "choice_exact", "numeric_result": "numeric_scalar", "text_excerpt": "text_rubric"}
    for rule in validated.objective_rules:
        if any(evidence_evaluators[kind] not in evaluator_ids for kind in rule.evidence_kinds):
            raise ValueError("评价策略不能验证所要求的证据形式：缺少已实装的对应评价器")
        if any(not any(compatible[question_type] == evidence_evaluators[kind] for question_type in validated.allowed_question_types) for kind in rule.evidence_kinds):
            raise ValueError("评价策略允许的题型不能产生所要求的证据形式")
    return validated


# Shared repository/course-preparation names; both retain the same server checks.
validate_policy = validate_evaluation_policy
require_evaluator = get_evaluator_handler
