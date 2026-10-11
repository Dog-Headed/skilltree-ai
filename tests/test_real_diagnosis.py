from langchain_core.messages import (
    AIMessage,
    ToolMessage,
)

import pytest

from app.models.schemas import (
    DiagnosisResult,
)

from app.agents.diagnosis import (
    run_diagnosis_tool_loop,
    generate_final_diagnosis,
    build_diagnosis_evidence_registry,
)


class FakeToolModel:
    def __init__(self, responses):
        self.responses = list(responses)
        self.received_messages = []

    def bind_tools(self, tools):
        self.tools = tools
        return self

    def invoke(self, messages):
        self.received_messages.append(
            list(messages)
        )

        return self.responses.pop(0)


class FakeStructuredModel:
    def __init__(self, result):
        self.result = result

    def with_structured_output(
        self,
        schema,
        *,
        method="json_schema",
    ):
        self.schema = schema
        self.method = method
        return self

    def invoke(self, messages):
        return self.result


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

        "assessment_id": (
            "assessment_test_001"
        ),

        "score_summary": {
            "total_score": 50.0,
            "total_max_score": 100.0,
            "percentage": 50.0,
        },

        "evaluation": {
            "assessment_id": (
                "assessment_test_001"
            ),

            "question_results": [
                {
                    "question_id": "q1",
                    "score": 0.0,
                    "error_tags": [
                        "assignment_confusion"
                    ],
                    "evidence": (
                        "学生混淆了 = 和 ==。"
                    ),
                    "feedback": (
                        "需要重新理解赋值。"
                    ),
                }
            ],
        },
    }


def test_unknown_tool_result_is_returned_to_model():
    fake_llm = FakeToolModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "delete_database",
                        "args": {},
                        "id": "call_bad_tool",
                        "type": "tool_call",
                    }
                ],
            ),

            AIMessage(
                content=(
                    "已收到工具失败信息。"
                )
            ),
        ]
    )

    result = run_diagnosis_tool_loop(
        make_state(),
        llm=fake_llm,
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

    content = tool_messages[0].content

    assert "unknown_tool" in content
    assert "delete_database" in content

    assert (
        tool_messages[0].tool_call_id
        == "call_bad_tool"
    )


def test_invalid_tool_arguments_are_returned():
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
                            "limit": 999,
                        },
                        "id": "call_bad_args",
                        "type": "tool_call",
                    }
                ],
            ),

            AIMessage(
                content="参数错误已收到。"
            ),
        ]
    )

    result = run_diagnosis_tool_loop(
        make_state(),
        llm=fake_llm,
    )

    log = result["tool_logs"][0]

    assert (
        log["result"]["ok"]
        is False
    )

    assert (
        log["result"]["error_type"]
        == "invalid_arguments"
    )


def test_foreign_node_is_rejected():
    fake_llm = FakeToolModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": (
                            "get_node_material"
                        ),
                        "args": {
                            "node_id": (
                                "other_project_node"
                            ),
                        },
                        "id": "call_foreign",
                        "type": "tool_call",
                    }
                ],
            ),

            AIMessage(
                content="访问失败。"
            ),
        ]
    )

    result = run_diagnosis_tool_loop(
        make_state(),
        llm=fake_llm,
    )

    assert (
        result["tool_logs"][0]
        ["result"]["error_type"]
        == "forbidden_node"
    )


@pytest.mark.parametrize("retry_tool", [False, True])
def test_tool_execution_failure_is_returned(
    monkeypatch,
    retry_tool,
):
    def fake_execute_tool_call(**kwargs):
        return {
            "ok": False,
            "tool": (
                "get_learning_history"
            ),
            "error_type": (
                "tool_execution_error"
            ),
            "error": "模拟数据库读取失败",
        }

    monkeypatch.setattr(
        "app.agents.diagnosis.execute_tool_call",
        fake_execute_tool_call,
    )

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
                        "id": "call_failure",
                        "type": "tool_call",
                    }
                ],
            ),

            AIMessage(
                content="" if retry_tool else "已知工具读取失败。",
                tool_calls=[
                    {
                        "name": "get_learning_history",
                        "args": {"node_id": "python_variables", "limit": 2},
                        "id": "call_retry",
                        "type": "tool_call",
                    }
                ] if retry_tool else [],
            ),
        ]
    )

    result = run_diagnosis_tool_loop(
        make_state(),
        llm=fake_llm,
    )

    tool_message = next(
        msg
        for msg in result["messages"]
        if isinstance(
            msg,
            ToolMessage,
        )
    )

    assert (
        "tool_execution_error"
        in tool_message.content
    )

    assert (
        "模拟数据库读取失败"
        in tool_message.content
    )
    assert len(fake_llm.received_messages) == 2
    assert tool_message in fake_llm.received_messages[1]
    assert tool_message.tool_call_id == "call_failure"
    assert result["tool_round_count"] == (2 if retry_tool else 1)
    assert result["tool_call_count"] == (2 if retry_tool else 1)
    assert result["stopped_reason"] == (
        "max_tool_rounds" if retry_tool else "model_finished"
    )


def test_fake_evidence_id_is_rejected():
    state = make_state()

    evidence_registry = {
        (
            "assessment:"
            "assessment_test_001:q1"
        ): {
            "source": (
                "current_assessment"
            ),
        }
    }

    fake_final_llm = FakeStructuredModel(
        DiagnosisResult(
            weak_points=[
                "变量赋值理解薄弱"
            ],

            evidence_ids=[
                "totally_fake_evidence"
            ],

            recommended_action=(
                "remediate"
            ),

            reason=(
                "模型尝试引用不存在证据"
            ),

            review_node_id=None,
        )
    )

    with pytest.raises(
        ValueError,
        match="不存在的证据",
    ):
        generate_final_diagnosis(
            state,
            evidence_registry=(
                evidence_registry
            ),
            llm=fake_final_llm,
        )

    assert fake_final_llm.method == "json_mode"


def test_valid_final_diagnosis_passes():
    state = make_state()

    evidence_id = (
        "assessment:"
        "assessment_test_001:q1"
    )

    evidence_registry = {
        evidence_id: {
            "source": (
                "current_assessment"
            ),
        }
    }

    fake_llm = FakeStructuredModel(
        DiagnosisResult(
            weak_points=[
                "变量赋值理解薄弱"
            ],

            evidence_ids=[
                evidence_id
            ],

            recommended_action=(
                "remediate"
            ),

            reason=(
                "当前测评显示赋值符号"
                "理解不稳定。"
            ),

            review_node_id=None,
        )
    )

    result = generate_final_diagnosis(
        state,
        evidence_registry=(
            evidence_registry
        ),
        llm=fake_llm,
    )

    assert fake_llm.method == "json_mode"

    assert (
        result.recommended_action
        == "remediate"
    )

    assert result.evidence_ids == [
        evidence_id
    ]
