from copy import deepcopy

from pydantic import ValidationError

from app.models.schemas import TreePlan


valid_data = {
    "nodes": [
        {
            "id": f"node_{i}",
            "title": f"Python 知识点 {i}",
            "description": f"这是第 {i} 个 Python 基础知识点",
            "objectives": [
                {
                    "id": f"node_{i}_obj_1",
                    "description": f"掌握知识点 {i} 的基本概念"
                }
            ],
            "prerequisite_ids": (
                []
                if i == 1
                else [f"node_{i - 1}"]
            ),
            "difficulty": "beginner",
            "estimated_minutes": 30
        }
        for i in range(1, 9)
    ]
}


def run_case(title, data):
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)

    try:
        TreePlan.model_validate(data)
        print("✅ 校验通过")
    except ValidationError as e:
        print("❌ 校验拒绝")
        print(e)


# 1. 合法数据
run_case(
    "1. 合法数据",
    deepcopy(valid_data)
)


# 2. 缺少必填字段
data = deepcopy(valid_data)
del data["nodes"][0]["title"]

run_case(
    "2. 缺少 title",
    data
)


# 3. 类型错误
data = deepcopy(valid_data)
data["nodes"][0]["estimated_minutes"] = "30"

run_case(
    "3. estimated_minutes 使用字符串",
    data
)


# 4. 出现额外字段
data = deepcopy(valid_data)
data["nodes"][0]["magic_score"] = 100

run_case(
    "4. 出现额外字段 magic_score",
    data
)


# 5. 节点数量不足
data = deepcopy(valid_data)
data["nodes"] = data["nodes"][:7]

run_case(
    "5. 只有 7 个节点",
    data
)


# 6. 学习目标数量为 0
data = deepcopy(valid_data)
data["nodes"][0]["objectives"] = []

run_case(
    "6. objectives 数量为 0",
    data
)

from app.agents.planner import validate_plan_dag


plan = TreePlan.model_validate(valid_data)

order, start_nodes = validate_plan_dag(plan)

print("\n拓扑顺序：")
print(order)

print("\n初始可学习节点：")
print(start_nodes)

from copy import deepcopy

from pydantic import ValidationError

from app.models.schemas import TreePlan
from app.agents.planner import validate_plan_dag


def run_dag_case(title, data):
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)

    try:
        # 第一关：Pydantic
        plan = TreePlan.model_validate(data)
        print("✅ Pydantic 字段校验通过")

        # 第二关：DAG
        order, start_nodes = validate_plan_dag(plan)

        print("✅ DAG 校验通过")
        print("拓扑顺序：", order)
        print("初始可学习节点：", start_nodes)

    except ValidationError as e:
        print("❌ Pydantic 拒绝")
        print(e)

    except ValueError as e:
        print("❌ DAG 校验拒绝")
        print(e)

data = deepcopy(valid_data)

data["nodes"][1]["id"] = "node_1"

run_dag_case(
    "1. 两个节点使用相同 ID",
    data
)


data = deepcopy(valid_data)

data["nodes"][3]["prerequisite_ids"] = [
    "ghost_node"
]

run_dag_case(
    "2. 引用不存在的前置节点",
    data
)


data = deepcopy(valid_data)

data["nodes"][3]["prerequisite_ids"] = [
    "node_4"
]

run_dag_case(
    "3. 节点依赖自己",
    data
)



data = deepcopy(valid_data)

data["nodes"][0]["prerequisite_ids"] = [
    "node_2"
]

data["nodes"][1]["prerequisite_ids"] = [
    "node_1"
]

run_dag_case(
    "4. node_1 和 node_2 循环依赖",
    data
)