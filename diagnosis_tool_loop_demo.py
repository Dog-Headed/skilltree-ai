from pprint import pprint

from app.agents.diagnosis import (
    run_diagnosis_tool_loop,
)


state = {
    "project_id": "demo_project",

    "current_node_id": (
        "python_variables"
    ),

    "tree": [
        {
            "id": "python_basics",
            "prerequisite_ids": [],
        },
        {
            "id": "python_variables",
            "prerequisite_ids": [
                "python_basics",
            ],
        },
        {
            "id": "python_for_loops",
            "prerequisite_ids": [
                "python_variables",
            ],
        },
    ],

    "score_summary": {
        "total_score": 55.0,
        "total_max_score": 100.0,
        "percentage": 55.0,
    },

    "evaluation": {
        "assessment_id": (
            "assessment_demo_001"
        ),

        "question_results": [
            {
                "question_id": "q1",
                "score": 0.0,
                "error_tags": [
                    "assignment_confusion",
                ],
                "evidence": (
                    "学生把 = 和 == 混淆。"
                ),
                "feedback": (
                    "需要重新理解赋值。"
                ),
            },

            {
                "question_id": "q2",
                "score": 5.0,
                "error_tags": [
                    "incorrect_output",
                ],
                "evidence": (
                    "print 输出判断错误。"
                ),
                "feedback": (
                    "需要检查表达式求值。"
                ),
            },
        ],
    },
}


print(
    "\n"
    + "=" * 70
)

print(
    "真实 Diagnosis Tool Loop"
)

print(
    "=" * 70
)


result = (
    run_diagnosis_tool_loop(
        state
    )
)


print(
    "\n工具调用轮数：",
    result["tool_round_count"],
)

print(
    "工具调用次数：",
    result["tool_call_count"],
)

print(
    "停止原因：",
    result["stopped_reason"],
)


print(
    "\n"
    + "=" * 70
)

print(
    "模型实际选择的工具"
)

print(
    "=" * 70
)


if not result["tool_logs"]:
    print(
        "模型认为当前证据已经足够，"
        "没有请求额外工具。"
    )


for log in result["tool_logs"]:
    print(
        "\nRound：",
        log["round"],
    )

    print(
        "Tool：",
        log["tool_name"],
    )

    print(
        "Args："
    )

    pprint(
        log["tool_args"],
        sort_dicts=False,
    )

    print(
        "tool_call_id：",
        log["tool_call_id"],
    )

    print(
        "Result："
    )

    pprint(
        log["result"],
        sort_dicts=False,
    )