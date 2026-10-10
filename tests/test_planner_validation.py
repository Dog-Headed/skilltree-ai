from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.models.schemas import TreePlan
from app.agents.planner import validate_plan_dag


def make_valid_data():
    """生成一份合法的 8 节点线性 DAG。"""

    return {
        "nodes": [
            {
                "id": f"node_{i}",
                "title": f"Python 知识点 {i}",
                "description": f"这是第 {i} 个 Python 基础知识点",
                "objectives": [
                    {
                        "id": f"node_{i}_obj_1",
                        "description": f"掌握知识点 {i} 的基本概念",
                    }
                ],
                "prerequisite_ids": (
                    []
                    if i == 1
                    else [f"node_{i - 1}"]
                ),
                "difficulty": "beginner",
                "estimated_minutes": 30,
            }
            for i in range(1, 9)
        ]
    }


def test_valid_dag_passes():
    data = make_valid_data()

    plan = TreePlan.model_validate(data)

    order, start_nodes = validate_plan_dag(plan)

    assert order == [
        "node_1",
        "node_2",
        "node_3",
        "node_4",
        "node_5",
        "node_6",
        "node_7",
        "node_8",
    ]

    assert start_nodes == ["node_1"]


def test_duplicate_node_id_is_rejected():
    data = make_valid_data()

    data["nodes"][1]["id"] = "node_1"

    plan = TreePlan.model_validate(data)

    with pytest.raises(
        ValueError,
        match="重复的节点 ID",
    ):
        validate_plan_dag(plan)


def test_missing_prerequisite_is_rejected():
    data = make_valid_data()

    data["nodes"][3]["prerequisite_ids"] = [
        "ghost_node"
    ]

    plan = TreePlan.model_validate(data)

    with pytest.raises(
        ValueError,
        match="不存在的前置节点",
    ):
        validate_plan_dag(plan)


def test_self_dependency_is_rejected():
    data = make_valid_data()

    data["nodes"][3]["prerequisite_ids"] = [
        "node_4"
    ]

    plan = TreePlan.model_validate(data)

    with pytest.raises(
        ValueError,
        match="不能依赖自己",
    ):
        validate_plan_dag(plan)


def test_cycle_is_rejected():
    data = make_valid_data()

    data["nodes"][0]["prerequisite_ids"] = [
        "node_2"
    ]

    data["nodes"][1]["prerequisite_ids"] = [
        "node_1"
    ]

    plan = TreePlan.model_validate(data)

    with pytest.raises(
        ValueError,
        match="循环依赖",
    ):
        validate_plan_dag(plan)


def test_node_count_out_of_range_is_rejected():
    data = make_valid_data()

    data["nodes"] = data["nodes"][:7]

    with pytest.raises(ValidationError):
        TreePlan.model_validate(data)


def test_objective_count_out_of_range_is_rejected():
    data = make_valid_data()

    data["nodes"][0]["objectives"] = []

    with pytest.raises(ValidationError):
        TreePlan.model_validate(data)