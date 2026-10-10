from pprint import pprint

from app.agents.tutor import tutor_node


base_state = {
    "goal": "学习 Python 循环",
    "tree": [
        {
            "id": "for_loops",
            "title": "for 循环",
            "description": "学习 Python 中 for 循环的基本用法。",
            "objectives": [
                {
                    "id": "loop_obj_1",
                    "description": "能够使用 for 遍历列表"
                },
                {
                    "id": "loop_obj_2",
                    "description": "能够使用循环完成累计求和"
                }
            ],
            "prerequisite_ids": [],
            "difficulty": "beginner",
            "estimated_minutes": 40
        }
    ],
    "current_node_id": "for_loops",
}


def show(title, result):
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)

    print("\nlesson：")
    print(result["lesson"])

    print("\ntutor_messages：")
    pprint(result["tutor_messages"], sort_dicts=False)


state = {
    **base_state,
    "lesson_mode": "normal",
}

result = tutor_node(state)

show(
    "场景 1：normal 首次教学",
    result
)
state = {
    **base_state,
    "lesson_mode": "normal",
    "user_event": {
        "action": "ask",
        "message": "为什么 for 循环里面的变量每一轮都会变化？"
    }
}

result = tutor_node(state)

show(
    "场景 2：用户继续提问",
    result
)
state = {
    **base_state,
    "lesson_mode": "remediate",
    "diagnosis": {
        "weak_points": [
            "循环中累计变量被覆盖",
            "没有正确使用 += 更新累计值"
        ],
        "recommended_action": "remediate",
        "reason": "学生在累计求和题中每轮都重新赋值。"
    }
}

result = tutor_node(state)

show(
    "场景 3：remediate 针对性补弱",
    result
)