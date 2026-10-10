from pprint import pprint

from app.agents.planner import planner_node


state = {
    "goal": "学习 Python 的列表和循环"
}


result = planner_node(state)


print("\n" + "=" * 70)
print("Planner 生成结果")
print("=" * 70)

pprint(
    result,
    sort_dicts=False,
)