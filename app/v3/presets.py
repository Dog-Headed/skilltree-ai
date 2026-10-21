"""Strict, inert subject and policy examples for V3 course preparation.

Templates suggest learning data, never tools, call budgets or pass permissions.
Loading a policy draft does not activate it: activation requires server checking.
"""

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.v3.capabilities import get_capability, validate_evaluation_policy


_CONFIG_ROOT = Path(__file__).resolve().parents[2] / "configs" / "v3"
_PRESET_FILES = {
    "generic": "generic.json",
    "python": "python.json",
    "mathematics": "mathematics.json",
    "english": "english.json",
}
_POLICY_FILES = {
    "choice-foundation": "choice-foundation.json",
    "numeric-text-draft": "numeric-text-draft.json",
    "text-rubric-draft": "text-rubric-draft.json",
}
_SUBJECT_ALIASES = {
    "python": "python", "python编程": "python",
    "数学": "mathematics", "mathematics": "mathematics", "math": "mathematics",
    "英语": "english", "english": "english",
}


class SubjectPreset(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    preset_id: str = Field(min_length=1, max_length=80)
    preset_version: str = Field(min_length=1, max_length=30)
    subject_label: str = Field(min_length=1, max_length=120)
    topic: str = Field(min_length=1, max_length=300)
    bounded_goal: str = Field(min_length=1, max_length=2000)
    target_level: str = Field(min_length=1, max_length=300)
    teaching_style: str = Field(min_length=1, max_length=1000)
    scope_in: list[str] = Field(min_length=1, max_length=20)
    scope_out: list[str] = Field(default_factory=list, max_length=20)
    typical_tasks: list[str] = Field(min_length=1, max_length=20)
    common_misconceptions: list[str] = Field(default_factory=list, max_length=20)
    suggested_capabilities: list[str] = Field(min_length=1, max_length=20)
    suggested_policy_id: str = Field(min_length=1, max_length=80)
    limitations: list[str] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def validate_suggestions(self):
        for field in (self.scope_in, self.scope_out, self.typical_tasks, self.common_misconceptions, self.limitations):
            if any(not value.strip() or len(value) > 2000 for value in field):
                raise ValueError("模板文本须为有内容、长度受限的数据")
        if len(set(self.suggested_capabilities)) != len(self.suggested_capabilities):
            raise ValueError("模板能力身份不得重复")
        if any(get_capability(value) is None for value in self.suggested_capabilities):
            raise ValueError("模板引用了未知能力")
        if self.suggested_policy_id not in _POLICY_FILES:
            raise ValueError("模板引用了未知策略样例")
        return self


def validate_subject_preset(data: Any) -> SubjectPreset:
    return SubjectPreset.model_validate(data.model_dump() if isinstance(data, SubjectPreset) else data)


def load_subject_preset(preset_id: str = "generic") -> SubjectPreset:
    if preset_id not in _PRESET_FILES:
        raise ValueError("未知模板身份；开放学科请使用 generic 模板")
    data = json.loads((_CONFIG_ROOT / "subjects" / _PRESET_FILES[preset_id]).read_text(encoding="utf-8"))
    preset = validate_subject_preset(data)
    if preset.preset_id != preset_id:
        raise ValueError("模板文件与声明身份不一致")
    return preset


def preset_for_subject(subject_label: str) -> SubjectPreset:
    if not isinstance(subject_label, str) or not subject_label.strip():
        raise ValueError("学科名称不能为空")
    # This selects terminology data only. It never grants capability permission.
    return load_subject_preset(_SUBJECT_ALIASES.get(subject_label.strip().casefold(), "generic"))


def profile_from_preset(
    preset_id: str, *, goal: str | None = None, subject_label: str | None = None,
    learning_mode: str = "formal",
):
    from app.v3.contracts import LearningProfile

    preset = load_subject_preset(preset_id)
    return LearningProfile(
        subject_label=subject_label or preset.subject_label,
        topic=preset.topic,
        goal=goal or preset.bounded_goal,
        bounded_goal=preset.bounded_goal,
        target_level=preset.target_level,
        scope_in=list(preset.scope_in),
        scope_out=list(preset.scope_out),
        learning_mode=learning_mode,
        requested_capabilities=list(preset.suggested_capabilities),
    )


def load_policy_draft(policy_id: str):
    """Structural validation only; planned evaluator references remain drafts."""
    from app.v3.contracts import EvaluationPolicy

    if policy_id not in _POLICY_FILES:
        raise ValueError("未知策略样例身份")
    data = json.loads((_CONFIG_ROOT / "policies" / _POLICY_FILES[policy_id]).read_text(encoding="utf-8"))
    policy = EvaluationPolicy.model_validate(data)
    if policy.policy_id != policy_id:
        raise ValueError("策略文件与声明身份不一致")
    return policy


def load_evaluation_policy(policy_id: str = "choice-foundation"):
    """Load an example only if it passes current server capability and limits."""
    return validate_evaluation_policy(load_policy_draft(policy_id))
