import json

from app.models.schemas import TreePlan
from app.services.llm import get_llm
from app.state import LearningState


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


def generate_plan(goal: str) -> TreePlan:
    llm = get_llm()

    structured_llm = llm.with_structured_output(
        TreePlan,
        method="json_mode",
    )

    plan = structured_llm.invoke(
        PLANNER_PROMPT.format(
            goal=goal,
            schema=json.dumps(TreePlan.model_json_schema(), ensure_ascii=False),
        )
    )

    return plan


def planner_node(state: LearningState):
    goal = state["goal"]

    # 1. 让真实模型生成结构化规划
    plan = generate_plan(goal)

    # 2. 检查节点关系是否合法
    topological_order, start_nodes = validate_plan_dag(plan)

    # 3. 理论上合法 DAG 至少应该存在一个起点
    if not start_nodes:
        raise ValueError("技能规划不存在可开始学习的节点")

    # 4. 选择拓扑顺序中的第一个节点开始
    current_node_id = topological_order[0]

    # 5. 仍然只返回自己修改的 State 字段
    return {
        "tree": [
            node.model_dump()
            for node in plan.nodes
        ],
        "current_node_id": current_node_id,
    }
