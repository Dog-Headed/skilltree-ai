from pprint import pprint

from app.tools.executor import (
    ToolExecutionContext,
    execute_tool_call,
)


context = ToolExecutionContext(
    project_id="demo_project",

    allowed_node_ids={
        "python_basics",
        "python_variables",
        "python_for_loops",
    },
)


def run_case(title, name, args):
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)

    result = execute_tool_call(
        tool_name=name,
        tool_args=args,
        context=context,
    )

    pprint(
        result,
        sort_dicts=False,
    )


# ============================================================
# 1. 正常调用
# ============================================================

run_case(
    "Case 1：正常查询历史",
    "get_learning_history",
    {
        "node_id": "python_variables",
        "limit": 2,
    },
)


# ============================================================
# 2. 模型请求不存在的工具
# ============================================================

run_case(
    "Case 2：非法工具",
    "delete_database",
    {},
)


# ============================================================
# 3. limit 越界
# ============================================================

run_case(
    "Case 3：limit 越界",
    "get_learning_history",
    {
        "node_id": "python_variables",
        "limit": 999,
    },
)


# ============================================================
# 4. 访问当前项目外节点
# ============================================================

run_case(
    "Case 4：非法节点",
    "get_node_material",
    {
        "node_id": "secret_other_project_node",
    },
)


# ============================================================
# 5. 模型偷偷提供 project_id
# ============================================================

run_case(
    "Case 5：模型尝试控制 project_id",
    "get_learning_history",
    {
        "node_id": "python_variables",
        "limit": 2,
        "project_id": "hacked_project",
    },
)


# ============================================================
# 6. 正常材料查询
# ============================================================

run_case(
    "Case 6：正常查询材料",
    "get_node_material",
    {
        "node_id": "python_variables",
    },
)