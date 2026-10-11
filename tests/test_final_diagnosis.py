import json

import httpx
import pytest
from langchain_openai import ChatOpenAI

from app.agents.diagnosis import generate_final_diagnosis
from app.models.schemas import DiagnosisResult


@pytest.fixture
def diagnosis_context():
    state = {
        "current_node_id": "python_variables",
        "tree": [
            {"id": "python_basics", "prerequisite_ids": []},
            {"id": "python_variables", "prerequisite_ids": ["python_basics"]},
            {"id": "python_for_loops", "prerequisite_ids": ["python_variables"]},
        ],
        "score_summary": {"percentage": 50.0},
        "evaluation": {"assessment_id": "test_001", "question_results": []},
    }
    evidence = {
        "assessment:test_001:q1": {
            "source": "assessment",
            "node_id": "python_variables",
            "evidence": "学生把赋值和相等比较混淆。",
        }
    }
    return state, evidence


def invoke_with_mock_api(state, evidence, response_data, requests):
    # 使用真正的 ChatOpenAI 序列化和 JSON 解析，只替换 HTTP 接口。
    def handle_request(request):
        payload = json.loads(request.content)
        requests.append(payload)
        if payload.get("response_format") != {"type": "json_object"}:
            return httpx.Response(
                400,
                json={
                    "error": {
                        "message": "This response_format type is unavailable now",
                        "type": "invalid_request_error",
                    }
                },
            )
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-test-diagnosis",
                "object": "chat.completion",
                "created": 0,
                "model": "test-model",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(response_data, ensure_ascii=False),
                        },
                    }
                ],
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handle_request)) as client:
        llm = ChatOpenAI(
            model="test-model",
            api_key="test-key",
            base_url="https://example.invalid/v1",
            http_client=client,
            max_retries=0,
        )
        return generate_final_diagnosis(state, evidence_registry=evidence, llm=llm)


def make_response(action="remediate", review_node_id=None):
    return {
        "weak_points": ["assignment_confusion"],
        "evidence_ids": ["assessment:test_001:q1"],
        "recommended_action": action,
        "reason": "真实测评证据表明学生尚未掌握赋值。",
        "review_node_id": review_node_id,
    }


@pytest.mark.parametrize(
    "action, review_node_id",
    [("remediate", None), ("revisit_prerequisite", "python_basics")],
)
def test_final_diagnosis_uses_supported_json_output_and_validates_result(
    diagnosis_context, action, review_node_id
):
    state, evidence = diagnosis_context
    requests = []
    response = make_response(action, review_node_id)
    diagnosis = invoke_with_mock_api(state, evidence, response, requests)

    assert isinstance(diagnosis, DiagnosisResult)
    assert diagnosis.model_dump() == response
    assert len(requests) == 1
    messages = requests[0]["messages"]
    assert "JSON" in messages[0]["content"]
    schema = messages[1]["content"].split("DiagnosisResult 的 JSON Schema：\n", 1)[1]
    assert json.loads(schema) == DiagnosisResult.model_json_schema()


@pytest.mark.parametrize(
    "response, error",
    [
        (
            {**make_response(), "evidence_ids": ["invented_evidence"]},
            "不存在的证据 ID",
        ),
        (
            make_response("revisit_prerequisite", "python_for_loops"),
            "前置闭包",
        ),
    ],
)
def test_json_output_still_rejects_invalid_evidence_and_review_nodes(
    diagnosis_context, response, error
):
    state, evidence = diagnosis_context
    with pytest.raises(ValueError, match=error):
        invoke_with_mock_api(state, evidence, response, [])
