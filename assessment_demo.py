from pprint import pprint
from uuid import uuid4

from app.agents.assessment import (
    assessment_prepare_node,
    assessment_generate_node,
    build_public_quiz,
)
from app.db.repository import repository_for_state


# ============================================================
# 模拟当前正在学习的节点
# ============================================================

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

    # 模拟上一轮可能留下来的旧数据，
    # 用来验证生成新试卷后是否真的被清空
    "answers": {
        "old_q1": "上一轮答案"
    },

    "evaluation": {
        "score": 60
    },
}


# ============================================================
# 1. 调用真实 Assessment 生成试卷
# ============================================================

print("\n" + "=" * 70)
print("开始生成真实试卷")
print("=" * 70)

state["project_id"] = f"assessment_demo_{uuid4().hex}"
with repository_for_state(state) as repo:
    repo.create_project_with_tree(
        project_id=state["project_id"], goal=state["goal"], tree=state["tree"],
    )
state.update(assessment_prepare_node(state))
result = assessment_generate_node(state)


# ============================================================
# 2. 查看基本信息
# ============================================================

print("\nassessment_id：")
print(result["assessment_id"])

print("\n题目数量：")
print(len(result["quiz"]["questions"]))

print("\n新一轮 answers：")
print(result["answers"])

print("\n新一轮 evaluation：")
print(result["evaluation"])


# ============================================================
# 3. 查看系统内部完整试卷
# ============================================================

print("\n" + "=" * 70)
print("系统内部完整 Quiz")
print("=" * 70)

pprint(
    result["quiz"],
    sort_dicts=False,
)


# ============================================================
# 4. 生成用户可见的公开试卷
# ============================================================

public_quiz = build_public_quiz(
    result["quiz"]
)

print("\n" + "=" * 70)
print("用户看到的 Public Quiz")
print("=" * 70)

pprint(
    public_quiz,
    sort_dicts=False,
)


# ============================================================
# 5. 自动验收
# ============================================================

assert len(result["quiz"]["questions"]) == 4

assert result["assessment_id"]

# 新试卷生成后，旧答案和旧评价必须清空
assert result["answers"] == {}
assert result["evaluation"] == {}

# 内部试卷应该保留答案和评分标准
for question in result["quiz"]["questions"]:
    assert "answer_key" in question
    assert "rubric" in question

# 公开试卷绝对不能泄露答案和评分标准
for question in public_quiz["questions"]:
    assert "answer_key" not in question
    assert "rubric" not in question


print("\n" + "=" * 70)
print("✅ Assessment Step 3 验收通过")
print("✅ 成功生成 4 道题")
print("✅ assessment_id 已生成")
print("✅ 旧 answers / evaluation 已清空")
print("✅ 内部 Quiz 保留 answer_key / rubric")
print("✅ Public Quiz 未泄露答案和评分标准")
print("=" * 70)
