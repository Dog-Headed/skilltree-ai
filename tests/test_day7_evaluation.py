import json
from collections import Counter

import httpx
import pytest
from langchain_openai import ChatOpenAI

import evaluate_diagnosis as runner
from app.agents import diagnosis
from app.graph import can_advance
from app.models.schemas import AssessmentEvaluation, AssessmentQuiz, TreePlan, validate_and_score_evaluation


def test_twelve_cases_have_expected_distribution_and_explicit_review_status():
    debug, holdout = runner.load_cases("debug"), runner.load_cases("holdout")
    assert len(debug) == 8 and len(holdout) == 4
    cases = debug + holdout
    assert Counter(c["category"] for c in cases) == {
        "advance": 3, "remediate": 3, "critical_misconception": 2,
        "collect_more_evidence": 2, "prerequisite_issue": 2,
    }
    assert len({c["id"] for c in cases}) == 12
    for case in cases:
        state = case["state"]
        TreePlan.model_validate({"nodes": state["tree"]})
        score = validate_and_score_evaluation(AssessmentQuiz.model_validate(state["quiz"]), AssessmentEvaluation.model_validate(state["evaluation"]))
        assert score == pytest.approx(state["score_summary"])
        assert can_advance(state) == (case["category"] == "advance")
        status = case["human_expectation"]["review_status"]
        assert status in {"pending_user_review", "approved"}
        if status == "approved":
            assert case["human_expectation"]["reviewed_by"] and case["human_expectation"]["reviewed_at"]
        assert case["human_expectation"]["authored_by"] == "assistant_draft"
        assert case["state"]["answers"] and case["tool_context"]["completion_records"]


def test_fake_report_exercises_business_repair_without_claiming_gold_standard():
    report = runner.make_report(runner.load_cases("debug"), "fake", "debug")
    assert report["purpose"] == "infrastructure_smoke_only"
    assert report["metrics"]["official_action_agreement"] is None
    assert report["metrics"]["official_false_release_count"] is None
    assert report["metrics"]["accepted"]["numerator"] == 8
    assert report["metrics"]["provisional_action_agreement"]["numerator"] < 8
    for row in report["cases"]:
        assert row["final_request_count"] == 2
        assert row["output_repair_count"] == 1
        assert row["attempts"][0]["structure_valid"]
        assert not row["attempts"][0]["business_valid"]
        assert row["attempts"][1]["business_valid"]
        assert row["tool_summary"]["tool_call_count"] == 2
        assert row["tool_summary"]["tool_round_count"] == 1
        assert row["evidence_within_expected_allowlist"]
        assert all(request["usage"] is None for request in row["requests_and_available_usage"])
        if row["case_id"].startswith("prerequisite"):
            # 调用当前节点的历史工具不能充当查询对应前置节点的证据。
            assert row["required_tools_used"] and not row["required_tool_queries_used"]
    assert report["metrics"]["required_tool_queries_used"] == {"numerator": 0, "denominator": 2, "rate": 0.0}
    assert "金标准" in runner.markdown_report(report)


def test_tracking_model_reads_real_adapter_usage_without_network():
    # 验证真实适配器的 include_raw/parsing_error 路径，不访问真实服务。
    requests = []
    def respond(request):
        payload = json.loads(request.content)
        requests.append(payload)
        content = {"weak_points": [], "evidence_ids": ["assessment:test:q1"],
                   "recommended_action": "advance", "reason": "证据支持", "review_node_id": None}
        if len(requests) == 1:
            content["recommended_action"] = "illegal"
        return httpx.Response(200, json={
            "id": "test", "object": "chat.completion", "created": 0, "model": "fake-http",
            "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": json.dumps(content)}}],
            "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
        })
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        model = runner.TrackingModel(ChatOpenAI(model="fake-http", api_key="test-key", base_url="https://example.invalid/v1", http_client=client, max_retries=0))
        trace = []
        result = diagnosis.generate_final_diagnosis(
            {"current_node_id": "n", "tree": [{"id": "n", "prerequisite_ids": []}]},
            evidence_registry={"assessment:test:q1": {}}, llm=model, attempt_records=trace,
        )
    assert result.recommended_action == "advance"
    assert len(requests) == 2 and len(trace) == 2
    assert trace[0]["structure_valid"] is False and trace[1]["structure_valid"] is True
    assert all(record["usage"]["total_tokens"] == 18 for record in model.requests)


def test_pending_expectations_cannot_produce_official_real_metrics(monkeypatch):
    def fake_case(case, mode):
        return {"expectation_approved": False, "first_structure_valid": True, "final_structure_valid": True,
                "accepted": True, "output_repair_count": 0, "action_match_provisional": True,
                "false_release_provisional": False, "elapsed_ms": 1, "requests_and_available_usage": [],
                "evidence_within_expected_allowlist": True, "tools_within_expected_allowlist": True, "required_tools_used": True}
    monkeypatch.setattr(runner, "evaluate_case", fake_case)
    report = runner.make_report(runner.load_cases("debug"), "real", "debug")
    assert report["metrics"]["official_action_agreement"] is None
    assert report["metrics"]["official_false_release_count"] is None
