from pprint import pprint

from langgraph.types import Command

from app.graph import graph


# 同一段学习流程必须一直使用同一个 thread_id
config = {
    "recursion_limit": 30,
    "configurable": {
        "thread_id": "learning-demo-001"
    }
}


def show_result(title, result):
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)
    pprint(result, sort_dicts=False)


# ============================================================
# 第一次启动
# ============================================================

result = graph.invoke(
    {
        "goal": "学习 Python"
    },
    config=config,
)

show_result(
    "第一次启动：应该停在 wait_learning",
    result,
)


# ============================================================
# 第一次恢复：用户选择继续提问
# ============================================================

result = graph.invoke(
    Command(
        resume={
            "action": "ask",
            "message": "Python 变量到底是什么？"
        }
    ),
    config=config,
)

show_result(
    "第一次恢复：提问后应该再次停在 wait_learning",
    result,
)


# ============================================================
# 第二次恢复：用户选择开始测验
# ============================================================

result = graph.invoke(
    Command(
        resume={
            "action": "start_quiz"
        }
    ),
    config=config,
)

show_result(
    "第二次恢复：应该出题并停在 wait_answer",
    result,
)


# ============================================================
# 第三次恢复：用户提交答案
# ============================================================

result = graph.invoke(
    Command(
        resume={
            "action": "submit_answer",
            "answers": {
                "q1": "变量可以用来保存和引用数据。"
            }
        }
    ),
    config=config,
)

show_result(
    "第三次恢复：完成评分和 Diagnosis",
    result,
)
