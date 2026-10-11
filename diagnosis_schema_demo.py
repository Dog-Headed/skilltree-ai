from app.models.schemas import (
    DiagnosisResult,
    validate_diagnosis_against_context,
    get_prerequisite_closure,
)


tree = [
    {
        "id": "python_basics",
        "prerequisite_ids": [],
    },
    {
        "id": "variables",
        "prerequisite_ids": [
            "python_basics",
        ],
    },
    {
        "id": "for_loops",
        "prerequisite_ids": [
            "variables",
        ],
    },
]


closure = get_prerequisite_closure(
    tree,
    "for_loops",
)

print(
    "前置闭包：",
    closure,
)


valid_evidence_ids = {
    "eval_q1",
    "eval_q2",
    "history_001",
}


# ============================================================
# Case 1：正常 remediate
# ============================================================

result = DiagnosisResult(
    weak_points=[
        "循环变量理解不完整",
    ],
    evidence_ids=[
        "eval_q2",
        "history_001",
    ],
    recommended_action="remediate",
    reason="当前题目和历史记录都显示同类错误。",
    review_node_id=None,
)

validate_diagnosis_against_context(
    result,
    valid_evidence_ids=valid_evidence_ids,
    prerequisite_closure=closure,
)

print("✅ Case 1 合法")


# ============================================================
# Case 2：正常 revisit
# ============================================================

result = DiagnosisResult(
    weak_points=[
        "变量基础不稳定",
    ],
    evidence_ids=[
        "eval_q1",
    ],
    recommended_action="revisit_prerequisite",
    reason="问题来自变量基础。",
    review_node_id="variables",
)

validate_diagnosis_against_context(
    result,
    valid_evidence_ids=valid_evidence_ids,
    prerequisite_closure=closure,
)

print("✅ Case 2 合法")


# ============================================================
# Case 3：伪造 evidence_id
# ============================================================

try:
    result = DiagnosisResult(
        weak_points=["循环理解错误"],
        evidence_ids=[
            "fake_evidence_999",
        ],
        recommended_action="remediate",
        reason="测试伪造证据。",
        review_node_id=None,
    )

    validate_diagnosis_against_context(
        result,
        valid_evidence_ids=valid_evidence_ids,
        prerequisite_closure=closure,
    )

except ValueError as exc:
    print(
        "✅ Case 3 正确拒绝：",
        exc,
    )


# ============================================================
# Case 4：非法前置节点
# ============================================================

try:
    result = DiagnosisResult(
        weak_points=[
            "循环基础问题",
        ],
        evidence_ids=[
            "eval_q1",
        ],
        recommended_action="revisit_prerequisite",
        reason="测试非法前置节点。",
        review_node_id="neural_network",
    )

    validate_diagnosis_against_context(
        result,
        valid_evidence_ids=valid_evidence_ids,
        prerequisite_closure=closure,
    )

except ValueError as exc:
    print(
        "✅ Case 4 正确拒绝：",
        exc,
    )