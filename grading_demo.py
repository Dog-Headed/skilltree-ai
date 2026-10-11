from pprint import pprint
from uuid import uuid4

from app.agents.assessment import (
    assessment_prepare_node,
    assessment_generate_node,
    assessment_save_answers_node,
    assessment_grade_node,
)
from app.db.repository import repository_for_state


state = {
    "goal": "学习 Python for 循环",

    "tree": [
        {
            "id": "for_loops",
            "title": "for 循环",
            "description": "学习 Python 中 for 循环的基本用法。",
            "objectives": [
                {
                    "id": "loop_obj_1",
                    "description": "能够使用 for 循环遍历列表",
                },
                {
                    "id": "loop_obj_2",
                    "description": "能够使用循环完成累计求和",
                },
            ],
            "prerequisite_ids": [],
            "difficulty": "beginner",
            "estimated_minutes": 40,
        }
    ],

    "current_node_id": "for_loops",
}


print("\n" + "=" * 70)
print("生成试卷")
print("=" * 70)

state["project_id"] = f"grading_demo_{uuid4().hex}"
with repository_for_state(state) as repo:
    repo.create_project_with_tree(
        project_id=state["project_id"], goal=state["goal"], tree=state["tree"],
    )
state.update(assessment_prepare_node(state))
generated = assessment_generate_node(state)

pprint(
    generated["quiz"],
    sort_dicts=False,
)


# 把生成结果并回 State
state.update(generated)


# ============================================================
# 临时模拟用户回答
# ============================================================

answers = {}

for question in state["quiz"]["questions"]:
    print("\n题目：")
    print(question["prompt"])

    # 为了先验证评分链路，
    # 我们故意统一写一个普通答案
    answers[question["id"]] = (
        "我会使用 for 循环遍历列表，"
        "累计时先初始化 total = 0，"
        "然后每轮使用 total += item。"
    )


state["answers"] = answers
state.update(assessment_save_answers_node(state))


print("\n" + "=" * 70)
print("开始真实评分")
print("=" * 70)

result = assessment_grade_node(state)


print("\n逐题评价：")
pprint(
    result["evaluation"],
    sort_dicts=False,
)

print("\n程序计算总分：")
pprint(
    result["score_summary"],
    sort_dicts=False,
)
