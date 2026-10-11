from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.tools.history import get_learning_history
from app.tools.knowledge import (
    get_prerequisite_status,
    get_node_material,
)


# ============================================================
# 模型允许填写的 Tool 参数
# ============================================================


class LearningHistoryArgs(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
    )

    node_id: str
    limit: int = Field(
        default=3,
        ge=1,
        le=3,
    )


class NodeLookupArgs(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
    )

    node_id: str


@dataclass
class ToolExecutionContext:
    project_id: str
    allowed_node_ids: set[str]

    current_assessment_id: (
        str | None
    ) = None
    learning_db_path: str | Path | None = None


TOOL_REGISTRY = {
    "get_learning_history": {
        "args_model": LearningHistoryArgs,
        "function": get_learning_history,
    },

    "get_prerequisite_status": {
        "args_model": NodeLookupArgs,
        "function": get_prerequisite_status,
    },

    "get_node_material": {
        "args_model": NodeLookupArgs,
        "function": get_node_material,
    },
}


def execute_tool_call(
    *,
    tool_name: str,
    tool_args: dict[str, Any],
    context: ToolExecutionContext,
) -> dict[str, Any]:
    """
    校验并执行一次 Tool Call。

    模型只负责：
    - tool_name
    - tool_args

    程序负责：
    - 是否允许调用
    - 参数是否合法
    - 节点是否属于当前项目
    - 注入 project_id
    - 真正执行 Tool
    """

    # ========================================================
    # 1. 工具名称白名单
    # ========================================================

    tool_spec = TOOL_REGISTRY.get(
        tool_name
    )

    if tool_spec is None:
        return {
            "ok": False,
            "tool": tool_name,
            "error_type": "unknown_tool",
            "error": (
                f"不允许调用工具：{tool_name}"
            ),
        }

    # ========================================================
    # 2. 参数必须是字典
    # ========================================================

    if not isinstance(tool_args, dict):
        return {
            "ok": False,
            "tool": tool_name,
            "error_type": "invalid_arguments",
            "error": "工具参数必须是字典",
        }

    # ========================================================
    # 3. 使用 Pydantic 校验模型提供的参数
    # ========================================================

    args_model = tool_spec[
        "args_model"
    ]

    try:
        validated_args = (
            args_model.model_validate(
                tool_args
            )
        )

    except ValidationError as exc:
        return {
            "ok": False,
            "tool": tool_name,
            "error_type": "invalid_arguments",
            "error": str(exc),
        }

    # ========================================================
    # 4. 节点访问范围检查
    # ========================================================

    node_id = validated_args.node_id

    if (
        node_id
        not in context.allowed_node_ids
    ):
        return {
            "ok": False,
            "tool": tool_name,
            "error_type": "forbidden_node",
            "error": (
                "不允许访问当前项目之外的节点："
                f"{node_id}"
            ),
        }

    # ========================================================
    # 5. 程序注入 project_id
    #
    # 注意：
    # 不是模型传进来的。
    # ========================================================

    execution_args = (
        validated_args.model_dump()
    )

    execution_args["project_id"] = (
        context.project_id
    )
    execution_args["db_path"] = context.learning_db_path
    if tool_name == "get_learning_history":
        execution_args["exclude_assessment_id"] = context.current_assessment_id

    # ========================================================
    # 6. 真正执行 Tool
    # ========================================================

    tool_function = tool_spec[
        "function"
    ]

    try:
        result = tool_function(
            **execution_args
        )

    except Exception as exc:
        return {
            "ok": False,
            "tool": tool_name,
            "error_type": "tool_execution_error",
            "error": str(exc),
        }

    # ========================================================
    # 7. Tool 自身可能返回明确失败
    # ========================================================

    if not isinstance(result, dict):
        return {
            "ok": False,
            "tool": tool_name,
            "error_type": "invalid_tool_result",
            "error": (
                "工具返回值必须是字典"
            ),
        }
    return result
