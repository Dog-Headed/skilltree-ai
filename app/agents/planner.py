import json
from uuid import uuid4

from langchain_core.exceptions import OutputParserException
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from pydantic import ValidationError

from app.models.schemas import TreePlan
from app.services.llm import (
    ModelCallBudget,
    ModelOutputValidationError,
    RepairContext,
    get_llm,
    invoke_with_shared_budget,
)
from app.state import LearningState
from app.services.observability import observed_node

def validate_plan_dag(plan: TreePlan) -> tuple[list[str], list[str]]:
    """
    校验技能规划是否构成合法 DAG。

    返回：
    1. topological_order：合法拓扑顺序
    2. start_nodes：一开始就可以学习的节点
    """

    nodes = plan.nodes

    # =========================
    # 1. 检查节点 ID 是否唯一
    # =========================

    node_ids = [node.id for node in nodes]

    if len(node_ids) != len(set(node_ids)):
        raise ValueError("技能规划中存在重复的节点 ID")

    node_id_set = set(node_ids)


    # =========================
    # 2. 检查 prerequisite
    # =========================

    for node in nodes:
        for prerequisite_id in node.prerequisite_ids:

            # 前置节点必须真实存在
            if prerequisite_id not in node_id_set:
                raise ValueError(
                    f"节点 {node.id} 引用了不存在的前置节点："
                    f"{prerequisite_id}"
                )

            # 不能依赖自己
            if prerequisite_id == node.id:
                raise ValueError(
                    f"节点 {node.id} 不能依赖自己"
                )


    # =========================
    # 3. 构建图
    # =========================

    # indegree 表示：
    # 一个节点还有多少个前置节点没有解决
    indegree = {
        node.id: 0
        for node in nodes
    }

    # adjacency 表示：
    # 当前节点完成以后，可以影响哪些后继节点
    adjacency = {
        node.id: []
        for node in nodes
    }

    for node in nodes:
        for prerequisite_id in node.prerequisite_ids:

            # prerequisite -> node
            adjacency[prerequisite_id].append(node.id)

            indegree[node.id] += 1


    # =========================
    # 4. 找一开始可以学习的节点
    # =========================

    start_nodes = [
        node_id
        for node_id, degree in indegree.items()
        if degree == 0
    ]


    # =========================
    # 5. 拓扑排序
    # =========================

    queue = start_nodes.copy()

    topological_order = []

    while queue:
        current = queue.pop(0)

        topological_order.append(current)

        for next_node in adjacency[current]:
            indegree[next_node] -= 1

            if indegree[next_node] == 0:
                queue.append(next_node)


    # =========================
    # 6. 检查有没有环
    # =========================

    if len(topological_order) != len(nodes):
        raise ValueError(
            "技能规划中存在循环依赖，无法形成合法 DAG"
        )

    return topological_order, start_nodes


PLANNER_PROMPT = """
你是一名学习路径规划专家。

请根据用户的学习目标，生成一份技能学习 DAG。

用户学习目标：
{goal}

要求：

1. 必须生成 8 到 12 个技能节点。
2. 每个节点必须包含：
   - id
   - title
   - description
   - objectives
   - prerequisite_ids
   - difficulty
   - estimated_minutes
3. 每个节点包含 1 到 3 个学习目标。
4. 每个学习目标必须有唯一 id 和 description。
5. prerequisite_ids 只能引用本规划中真实存在的节点。
6. 节点不能依赖自己。
7. 不能形成循环依赖。
8. 学习顺序应当由基础逐渐过渡到复杂内容。
9. id 使用简短、稳定的英文 snake_case。
10. 不要生成契约之外的额外字段。
11. 只输出 JSON，严格遵守以下 JSON Schema：
{schema}
"""


def validate_planner_output(plan: TreePlan) -> TreePlan:
    """将 DAG 业务错误归入可修复输出错误，程序错误继续向外抛出。"""
    try:
        validate_plan_dag(plan)
    except ValueError as exc:
        raise ModelOutputValidationError(
            f"Planner 业务校验失败：{exc}"
        ) from exc
    return plan


def build_planner_messages(
    *, goal: str, repair_context: RepairContext | None = None,
):
    messages = [
        SystemMessage(content="你是学习技能树规划 Agent，请按契约返回完整 JSON 学习计划。"),
        HumanMessage(content=PLANNER_PROMPT.format(
            goal=goal,
            schema=json.dumps(TreePlan.model_json_schema(), ensure_ascii=False),
        )),
    ]
    if repair_context is not None:
        repair_message = (
            "你上一次生成的学习计划未通过系统校验。\n\n"
            f"校验错误：\n{repair_context.error_message}\n\n"
        )
        if repair_context.previous_output is not None:
            previous_output = repair_context.previous_output
            if isinstance(previous_output, TreePlan):
                previous_output = previous_output.model_dump()
            repair_message += (
                "上一次输出：\n"
                + json.dumps(previous_output, ensure_ascii=False, default=str)
                + "\n\n"
            )
        repair_message += (
            "请修复这些具体问题，保持原学习目标不变。"
            "返回完整的修正版 TreePlan JSON，重新满足全部结构和 DAG 要求，不要解释。"
        )
        messages.append(HumanMessage(content=repair_message))
    return messages


def generate_plan(goal: str) -> TreePlan:
    structured_llm = get_llm().with_structured_output(
        TreePlan, method="json_mode",
    )

    def invoke_once(repair_context: RepairContext | None) -> TreePlan:
        messages = build_planner_messages(goal=goal, repair_context=repair_context)
        try:
            return structured_llm.invoke(messages)
        except (ValidationError, OutputParserException) as exc:
            raise ModelOutputValidationError(
                f"Planner 结构化输出校验失败：{exc}"
            ) from exc

    return invoke_with_shared_budget(
        invoke_fn=invoke_once,
        validate_fn=validate_planner_output,
        budget=ModelCallBudget(),
    )


@observed_node
def planner_node(state: LearningState, config: RunnableConfig | None = None):
    plan = generate_plan(state["goal"])
    _, start_nodes = validate_plan_dag(plan)
    project_id = (
        state.get("project_id")
        or (config or {}).get("configurable", {}).get("thread_id")
        or f"project_{uuid4().hex}"
    )
    # 仅返回通过全部校验的 State；业务写入留给后续 persist_plan 节点。
    return {
        "project_id": project_id,
        "tree": plan.model_dump()["nodes"],
        "current_node_id": start_nodes[0],
        "round_limit_by_node": {node.id: state.get("round_limit_by_node", {}).get(node.id, 3)
                                for node in plan.nodes},
    }
