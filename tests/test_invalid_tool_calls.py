"""真实 ChatOpenAI 适配器解析损坏 arguments；HTTP 和工具执行使用替身。"""
import json

import httpx
import pytest
from langchain_openai import ChatOpenAI

from app.agents import diagnosis
from app.services.llm import ModelOutputValidationError

REAL_RUN = diagnosis.run_real_diagnosis


def state():
    return {"project_id": "invalid-tools", "current_node_id": "python_for_loops",
            "assessment_id": "test", "tree": [
                {"id": "python_variables", "prerequisite_ids": []},
                {"id": "python_for_loops", "prerequisite_ids": ["python_variables"]},
            ]}


def tool(arguments, call_id="call-history"):
    return {"id": call_id, "type": "function", "function": {
        "name": "get_learning_history", "arguments": arguments,
    }}


def completion(calls):
    return {"id": "test", "object": "chat.completion", "created": 0, "model": "mock-tools",
            "choices": [{"index": 0, "finish_reason": "tool_calls" if calls else "stop",
                         "message": {"role": "assistant", "content": "" if calls else "证据收集结束",
                                     **({"tool_calls": calls} if calls else {})}}]}


@pytest.mark.parametrize("mixed", [False, True])
def test_broken_tool_arguments_repaired_before_any_tool_execution(monkeypatch, mixed):
    requests, executions = [], []
    damaged = [tool('{"node_id":', "bad")]
    if mixed:
        damaged.insert(0, tool('{"node_id":"python_for_loops"}', "valid-but-rejected"))
    responses = [completion(damaged), completion([tool('{"node_id":"python_for_loops"}')]), completion([])]

    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=responses[len(requests)-1])

    def execute(**kwargs):
        assert len(requests) == 2  # 第一次消息即使有部分合法调用也不能执行。
        executions.append(kwargs)
        return {"ok": True, "tool": kwargs["tool_name"], "records": [], "status": "no_history"}

    monkeypatch.setattr(diagnosis, "execute_tool_call", execute)
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        model = ChatOpenAI(model="mock-tools", api_key="test-key", base_url="https://example.invalid/v1",
                           http_client=client, timeout=45, max_retries=0)
        result = diagnosis.run_diagnosis_tool_loop(state(), llm=model)
    assert len(requests) == 3 and len(executions) == 1
    assert "invalid_tool_calls" in requests[1]["messages"][-1]["content"]
    assert result["tool_call_count"] == result["tool_round_count"] == 1
    assert result["tool_logs"][0]["tool_call_id"] == "call-history"
    assert result["stopped_reason"] == "model_finished"


def test_continuously_broken_tool_arguments_stop_without_final_diagnosis(monkeypatch):
    requests = []
    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=completion([tool('{"node_id":')]))

    def forbidden(**kwargs):
        raise AssertionError("损坏调用不能执行工具，也不能进入最终诊断")

    class ForbiddenFinal:
        def with_structured_output(self, *args, **kwargs):
            forbidden()

    monkeypatch.setattr(diagnosis, "execute_tool_call", forbidden)
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        model = ChatOpenAI(model="mock-tools", api_key="test-key", base_url="https://example.invalid/v1",
                           http_client=client, timeout=45, max_retries=0)
        with pytest.raises(ModelOutputValidationError, match="invalid_tool_calls"):
            REAL_RUN(state(), tool_llm=model, final_llm=ForbiddenFinal())
    assert len(requests) == 2
    assert "invalid_tool_calls" in requests[1]["messages"][-1]["content"]
