from app.tools.executor import (
    ToolExecutionContext,
    execute_tool_call,
)


def make_context():
    return ToolExecutionContext(
        project_id="demo_project",
        allowed_node_ids={
            "python_basics",
            "python_variables",
            "python_for_loops",
        },
    )


def test_valid_tool_call(tool_database):
    result = execute_tool_call(
        tool_name="get_learning_history",
        tool_args={
            "node_id": "python_variables",
            "limit": 2,
        },
        context=make_context(),
    )

    assert result["ok"] is True


def test_unknown_tool_rejected():
    result = execute_tool_call(
        tool_name="delete_database",
        tool_args={},
        context=make_context(),
    )

    assert result["ok"] is False
    assert (
        result["error_type"]
        == "unknown_tool"
    )


def test_invalid_limit_rejected():
    result = execute_tool_call(
        tool_name="get_learning_history",
        tool_args={
            "node_id": "python_variables",
            "limit": 100,
        },
        context=make_context(),
    )

    assert result["ok"] is False
    assert (
        result["error_type"]
        == "invalid_arguments"
    )


def test_foreign_node_rejected():
    result = execute_tool_call(
        tool_name="get_node_material",
        tool_args={
            "node_id": "foreign_node",
        },
        context=make_context(),
    )

    assert result["ok"] is False
    assert (
        result["error_type"]
        == "forbidden_node"
    )


def test_model_cannot_supply_project_id():
    result = execute_tool_call(
        tool_name="get_learning_history",
        tool_args={
            "node_id": "python_variables",
            "limit": 2,
            "project_id": "evil_project",
        },
        context=make_context(),
    )

    assert result["ok"] is False
    assert (
        result["error_type"]
        == "invalid_arguments"
    )
