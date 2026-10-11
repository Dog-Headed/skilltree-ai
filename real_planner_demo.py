from pprint import pprint

from langgraph.types import Command

from app.graph import graph


config = {
    "recursion_limit": 30,
    "configurable": {
        "thread_id": "real-planner-demo-001"
    }
}


def show_interrupt(result):
    interrupts = result.get("__interrupt__", [])

    if not interrupts:
        print("当前没有 interrupt")
        return

    print("\n当前暂停点：")
    pprint(interrupts[0].value, sort_dicts=False)


# ============================================================
# 1. 真实 Planner 开始规划
# ============================================================

print("\n" + "=" * 70)
print("第一次运行：真实 Planner → Tutor → wait_learning")
print("=" * 70)

result = graph.invoke(
    {
        "goal": "学习 Python 的列表和循环"
    },
    config=config,
)

print("\n生成的 current_node_id：")
print(result["current_node_id"])

print("\n生成的技能节点数量：")
print(len(result["tree"]))

print("\n前几个技能节点：")
pprint(
    result["tree"][:3],
    sort_dicts=False,
)

show_interrupt(result)


# ============================================================
# 验收第一次暂停
# ============================================================

assert "__interrupt__" in result
assert result["__interrupt__"][0].value["type"] == "wait_learning"

print("\n✅ 真实 Planner 已成功进入 wait_learning")


# ============================================================
# 2. 恢复：用户选择开始测验
# ============================================================

print("\n" + "=" * 70)
print("第二次运行：start_quiz → Assessment → wait_answer")
print("=" * 70)

result = graph.invoke(
    Command(
        resume={
            "action": "start_quiz"
        }
    ),
    config=config,
)

print("\n生成的 quiz：")
pprint(
    result["quiz"],
    sort_dicts=False,
)

show_interrupt(result)


# ============================================================
# 验收第二次暂停
# ============================================================

assert "__interrupt__" in result
assert result["__interrupt__"][0].value["type"] == "wait_answer"

print("\n✅ 开始测验后已成功进入 wait_answer")
print("\n🎉 Day 3 真实 Planner 整图验收通过")
