from langchain_core.messages import (
    AIMessage,
    ToolMessage,
)

from app.agents.diagnosis import (
    run_diagnosis_tool_loop,
)


class FakeToolModel:
    def __init__(self, responses):
        self.responses = list(
            responses
        )

    def bind_tools(self, tools):
        self.tools = tools
        return self

    def invoke(self, messages):
        return self.responses.pop(0)


def make_state():
    return {
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
        ],

        "score_summary": {
            "percentage": 50.0
        },

        "evaluation": {
            "assessment_id": "test_001",
            "question_results": [],
        },
    }


def test_tool_result_uses_matching_call_id():
    fake_llm = FakeToolModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": (
                            "get_learning_history"
                        ),
                        "args": {
                            "node_id": (
                                "python_variables"
                            ),
                            "limit": 2,
                        },
                        "id": "call_history_001",
                        "type": "tool_call",
                    }
                ],
            ),

            AIMessage(
                content=(
                    "现有证据已经足够。"
                )
            ),
        ]
    )

    result = (
        run_diagnosis_tool_loop(
            make_state(),
            llm=fake_llm,
        )
    )

    tool_messages = [
        message
        for message in result["messages"]
        if isinstance(
            message,
            ToolMessage,
        )
    ]

    assert len(tool_messages) == 1

    assert (
        tool_messages[0].tool_call_id
        == "call_history_001"
    )


def test_tool_call_limit_is_enforced():
    first_round = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "get_node_material",
                "args": {
                    "node_id": (
                        "python_variables"
                    )
                },
                "id": "call_1",
                "type": "tool_call",
            },
            {
                "name": "get_node_material",
                "args": {
                    "node_id": (
                        "python_variables"
                    )
                },
                "id": "call_2",
                "type": "tool_call",
            },
            {
                "name": "get_node_material",
                "args": {
                    "node_id": (
                        "python_variables"
                    )
                },
                "id": "call_3",
                "type": "tool_call",
            },
        ],
    )

    second_round = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "get_node_material",
                "args": {
                    "node_id": (
                        "python_variables"
                    )
                },
                "id": "call_4",
                "type": "tool_call",
            }
        ],
    )

    fake_llm = FakeToolModel(
        [
            first_round,
            second_round,
        ]
    )

    result = (
        run_diagnosis_tool_loop(
            make_state(),
            llm=fake_llm,
        )
    )

    assert (
        result["tool_call_count"]
        == 3
    )

    fourth_log = (
        result["tool_logs"][-1]
    )

    assert (
        fourth_log["result"][
            "error_type"
        ]
        == "tool_limit_exceeded"
    )