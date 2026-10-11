import json

import pytest
from langchain_core.messages import AIMessage

import app.agents.diagnosis as diagnosis
from app.models.schemas import DiagnosisResult
from app.tools.executor import TOOL_REGISTRY


REAL_RUN_REAL_DIAGNOSIS = diagnosis.run_real_diagnosis


class ToolModel:
    def __init__(self, responses):
        self.responses = iter(responses)

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        return next(self.responses)


class RecordingFinalModel:
    def __init__(self, evidence_id="assessment:summary_test:q1"):
        self.messages = None
        self.evidence_id = evidence_id

    def with_structured_output(self, schema, *, method):
        assert method == "json_mode"
        return self

    def invoke(self, messages):
        self.messages = messages
        return DiagnosisResult(
            weak_points=["赋值理解薄弱"],
            evidence_ids=[self.evidence_id],
            recommended_action="remediate",
            reason="当前测评表明需要补弱。",
            review_node_id=None,
        )


def make_state():
    return {
        "project_id": "demo_project",
        "current_node_id": "python_variables",
        "tree": [
            {"id": "python_basics", "prerequisite_ids": []},
            {"id": "python_variables", "prerequisite_ids": ["python_basics"]},
        ],
        "assessment_id": "summary_test",
        "score_summary": {"percentage": 0.0},
        "evaluation": {
            "assessment_id": "summary_test",
            "question_results": [{
                "question_id": "q1", "score": 0.0,
                "error_tags": ["assignment_confusion"],
                "evidence": "混淆赋值与比较。", "feedback": "需要复习赋值。",
            }],
        },
    }


def request_tools(*ids, tool_name="get_learning_history"):
    return AIMessage(content="", tool_calls=[{
        "id": call_id, "name": tool_name,
        "args": {"node_id": "python_variables"}, "type": "tool_call",
    } for call_id in ids])


def read_section(model, start, end):
    prompt = model.messages[1].content
    return json.loads(prompt.split(start + "\n", 1)[1].split("\n\n" + end, 1)[0])


def summary_from(model):
    return read_section(model, "工具执行摘要（查询状态，不是学习证据）：", "本轮允许引用的证据：")


def evidence_from(model):
    return read_section(model, "本轮允许引用的证据：", "DiagnosisResult 的 JSON Schema：")


def test_empty_history_and_query_failure_reach_final_model_as_different_states(monkeypatch):
    models = []
    for failed in (False, True):
        def history_query(**kwargs):
            if failed:
                raise RuntimeError("历史数据库暂时不可用")
            return {"ok": True, "node_id": kwargs["node_id"], "records": [], "message": "无历史记录"}

        # 仅替换数据源和模型，实际运行工具执行器、证据注册和最终诊断校验。
        monkeypatch.setitem(TOOL_REGISTRY["get_learning_history"], "function", history_query)
        final_model = RecordingFinalModel()
        REAL_RUN_REAL_DIAGNOSIS(
            make_state(),
            tool_llm=ToolModel([request_tools("history_1"), AIMessage(content="查询结束")]),
            final_llm=final_model,
        )
        models.append(final_model)

    empty_summary, failed_summary = map(summary_from, models)
    assert empty_summary["calls"][0]["status"] == "empty"
    assert empty_summary["calls"][0]["ok"] is True
    assert empty_summary["calls"][0]["result_count"] == 0
    failure = failed_summary["calls"][0]
    assert failure["status"] == "failed"
    assert failure["ok"] is False
    assert failure["error_type"] == "tool_execution_error"
    assert failure["error"] == "历史数据库暂时不可用"
    assert models[0].messages[1].content != models[1].messages[1].content
    # 两种情况的有效学习证据完全一致；失败没有被伪装成学习证据。
    assert evidence_from(models[0]) == evidence_from(models[1])
    assert set(evidence_from(models[1])) == {"assessment:summary_test:q1"}


@pytest.mark.parametrize("over_budget", [False, True])
def test_final_model_receives_success_and_tool_budget_status(over_budget, tool_database):
    responses = [request_tools("material_1", "material_2", "material_3", tool_name="get_node_material")]
    responses.append(
        request_tools("material_4", tool_name="get_node_material")
        if over_budget else AIMessage(content="查询结束")
    )
    final_model = RecordingFinalModel()
    REAL_RUN_REAL_DIAGNOSIS(make_state(), tool_llm=ToolModel(responses), final_llm=final_model)
    summary = summary_from(final_model)
    assert summary["tool_call_count"] == 3
    assert summary["call_limit_reached"] is True
    assert [item["status"] for item in summary["calls"][:3]] == ["success"] * 3
    assert "material_python_variables_v1" in evidence_from(final_model)
    assert summary["stopped_reason"] == ("max_tool_rounds" if over_budget else "model_finished")
    assert summary["round_limit_reached"] is over_budget
    if over_budget:
        last_call = summary["calls"][-1]
        assert last_call["status"] == "limit_exceeded"
        assert last_call["executed"] is False
        assert last_call["error_type"] == "tool_limit_exceeded"
        assert "material_4" not in evidence_from(final_model)


def test_round_limit_is_reported_even_when_call_budget_remains():
    final_model = RecordingFinalModel()
    REAL_RUN_REAL_DIAGNOSIS(
        make_state(),
        tool_llm=ToolModel([request_tools("history_1"), request_tools("history_2")]),
        final_llm=final_model,
    )
    summary = summary_from(final_model)
    assert summary["tool_call_count"] == 2
    assert summary["call_limit_reached"] is False
    assert summary["round_limit_reached"] is True
    assert summary["stopped_reason"] == "max_tool_rounds"


def test_final_model_receives_no_calls_status():
    final_model = RecordingFinalModel()
    REAL_RUN_REAL_DIAGNOSIS(
        make_state(), tool_llm=ToolModel([AIMessage(content="现有证据充分")]), final_llm=final_model
    )
    summary = summary_from(final_model)
    assert summary["calls"] == []
    assert summary["tool_call_count"] == summary["tool_round_count"] == 0
    assert summary["stopped_reason"] == "model_finished"
    assert summary["call_limit_reached"] is summary["round_limit_reached"] is False


def test_failed_tool_call_cannot_be_cited_as_learning_evidence():
    final_model = RecordingFinalModel(evidence_id="failed_call")
    with pytest.raises(ValueError, match="不存在的证据 ID"):
        REAL_RUN_REAL_DIAGNOSIS(
            make_state(),
            tool_llm=ToolModel([
                request_tools("failed_call", tool_name="unknown_tool"), AIMessage(content="查询结束")
            ]),
            final_llm=final_model,
        )
    assert summary_from(final_model)["calls"][0]["status"] == "failed"
