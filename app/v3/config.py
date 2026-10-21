"""Trusted deployment configuration. Never load this from prompts or materials."""

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

DB_SCHEMA_VERSION = "v3-day10-2"
GRAPH_VERSION = "v3-day10-preparation"
CONTRACT_VERSION = "3.0.0"
LIMITS_VERSION = "day11-1"

V3_DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "v3"
V3_BUSINESS_DB = V3_DATA_DIR / "learning.sqlite"
V3_CHECKPOINT_DB = V3_DATA_DIR / "checkpoints.sqlite"


class ServerLimits(BaseModel):
    """Only trusted server code may select limits or tool permissions.

    User/profile/policy/template models have no limits override or executable
    tool configuration field. A trusted deployment change gets a new version.
    """

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, revalidate_instances="always")

    limits_version: str = LIMITS_VERSION
    max_nodes: int = Field(default=20, ge=1, le=20)
    max_objectives_per_node: int = Field(default=5, ge=1, le=5)
    default_min_nodes: int = Field(default=3, ge=1, le=20)
    default_max_nodes: int = Field(default=12, ge=1, le=20)
    max_questions_per_assessment: int = Field(default=10, ge=1, le=10)
    default_min_questions: int = Field(default=4, ge=1, le=10)
    default_max_questions: int = Field(default=6, ge=1, le=10)
    max_file_bytes: int = Field(default=128 * 1024, ge=1, le=128 * 1024)
    max_project_material_bytes: int = Field(default=1024 * 1024, ge=1, le=1024 * 1024)
    max_context_characters: int = Field(default=24000, ge=1, le=24000)
    max_operation_requests: int = Field(default=12, ge=1, le=12)
    max_budget_extensions: int = Field(default=1, ge=0, le=1)
    max_logical_requests: int = Field(default=3, ge=1, le=3)
    max_network_retries: int = Field(default=1, ge=0, le=1)
    max_output_repairs: int = Field(default=1, ge=0, le=1)
    max_effective_rounds: int = Field(default=3, ge=1, le=3)
    max_round_extensions: int = Field(default=1, ge=0, le=1)
    max_extension_rounds: int = Field(default=3, ge=1, le=3)
    max_replacements: int = Field(default=2, ge=0, le=2)
    max_clarification_rounds: int = Field(default=2, ge=0, le=2)
    max_tool_rounds: int = Field(default=2, ge=0, le=2)
    max_tool_executions: int = Field(default=3, ge=0, le=3)
    tutor_history_turns: int = Field(default=6, ge=0, le=6)
    model_timeout_seconds: float = Field(default=45.0, gt=0, le=45, allow_inf_nan=False)
    sdk_max_retries: int = Field(default=0, ge=0, le=0)
    min_total_pass_threshold: float = Field(default=0.8, ge=0, le=1, allow_inf_nan=False)
    min_objective_pass_threshold: float = Field(default=0.8, ge=0, le=1, allow_inf_nan=False)
    max_numeric_absolute_tolerance: float = Field(default=0.01, ge=0, le=0.01, allow_inf_nan=False)
    max_numeric_relative_tolerance: float = Field(default=0.000001, ge=0, le=0.000001, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_defaults(self):
        if not self.default_min_nodes <= self.default_max_nodes <= self.max_nodes:
            raise ValueError("默认规划范围必须位于服务端节点上限内")
        if not self.default_min_questions <= self.default_max_questions <= self.max_questions_per_assessment:
            raise ValueError("默认题数范围必须位于服务端单卷上限内")
        if self.max_file_bytes > self.max_project_material_bytes:
            raise ValueError("单文件上限不得大于项目资料总量上限")
        if self.max_logical_requests > self.max_operation_requests:
            raise ValueError("逻辑任务请求上限不得大于操作请求上限")
        return self

    @property
    def max_operation_chain_requests(self) -> int:
        return self.max_operation_requests * (1 + self.max_budget_extensions)


SERVER_LIMITS = ServerLimits()
