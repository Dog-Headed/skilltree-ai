from pprint import pprint

from app.tools.history import (
    get_learning_history,
)

from app.tools.knowledge import (
    get_prerequisite_status,
    get_node_material,
)


PROJECT_ID = "demo_project"


print("\n" + "=" * 70)
print("1. 查询学习历史")
print("=" * 70)

result = get_learning_history(
    project_id=PROJECT_ID,
    node_id="python_variables",
    limit=2,
)

pprint(result, sort_dicts=False)


print("\n" + "=" * 70)
print("2. 查询无历史节点")
print("=" * 70)

result = get_learning_history(
    project_id=PROJECT_ID,
    node_id="python_for_loops",
    limit=3,
)

pprint(result, sort_dicts=False)


print("\n" + "=" * 70)
print("3. 查询前置节点状态")
print("=" * 70)

result = get_prerequisite_status(
    project_id=PROJECT_ID,
    node_id="python_for_loops",
)

pprint(result, sort_dicts=False)


print("\n" + "=" * 70)
print("4. 查询节点材料")
print("=" * 70)

result = get_node_material(
    project_id=PROJECT_ID,
    node_id="python_variables",
)

pprint(result, sort_dicts=False)


print("\n" + "=" * 70)
print("5. limit 越界")
print("=" * 70)

result = get_learning_history(
    project_id=PROJECT_ID,
    node_id="python_variables",
    limit=100,
)

pprint(result, sort_dicts=False)


print("\n" + "=" * 70)
print("6. 未登记材料")
print("=" * 70)

result = get_node_material(
    project_id=PROJECT_ID,
    node_id="fake_node",
)

pprint(result, sort_dicts=False)