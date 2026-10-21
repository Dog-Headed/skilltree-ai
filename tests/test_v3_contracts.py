"""V3 boundaries: ownership, permissions, identities, and actual answer evidence."""

from copy import deepcopy
from hashlib import sha256

import pytest
from pydantic import ValidationError

from app.v3.config import SERVER_LIMITS, ServerLimits
from app.v3.contracts import (
    AssessmentQuiz, EvaluationPolicy, EvaluationResult, LearningPlan,
    LearningProfile, NodeMaterialLink, PublicProjectView, PublicQuiz,
    PublicSource, SourceChunk, SourceDocument, validate_evaluation_context,
    validate_material_link,
)


def profile_data(**changes):
    return {"subject_label": "历史", "topic": "法国大革命", "goal": "解释经济压力与政治变革的关系", **changes}


def source_data(**changes):
    content = changes.pop("content", "背景\n税制改革推动政治讨论")
    return {"source_id": "source-1", "project_id": "project-1", "title": "历史背景", "source_description": "用户节选", "source_version": 1,
            "content": content, "content_hash": sha256(content.encode("utf-8")).hexdigest(), **changes}


def plan_data(**changes):
    node = {"node_id": "causes", "title": "背景因素", "description": "辨认背景因素", "estimated_minutes": 20,
            "objectives": [{"objective_id": "explain", "observable_outcome": "用原文解释税制与政治变革的关系",
                            "required_capability_ids": ["text_rubric"], "evidence_requirement": ["text_excerpt"], "source_chunk_ids": ["chunk-1"]}]}
    return {"project_id": "project-1", "draft_revision": 0, "nodes": [node], **changes}


def quiz_data():
    return {"project_id": "project-1", "node_id": "causes", "assessment_id": "assessment-1",
            "snapshot": {"profile_version": 1, "plan_version": 1, "policy_id": "history-policy", "policy_version": "1.0.0",
                         "source_manifest": [{"source_id": "source-1", "source_version": 1, "content_hash": "a" * 64}],
                         "evaluator_manifest": [{"evaluator_id": "text_rubric", "evaluator_version": "1.0.0"}]},
            "questions": [{"question_id": "q1", "objective_ids": ["explain"], "question_type": "text", "prompt": "说明税制的作用", "max_score": 10.0,
                           "evaluator_id": "text_rubric", "evaluator_version": "1.0.0", "answer_key": "私有答案说明",
                           "source_citations": [{"source_id": "source-1", "source_version": 1, "chunk_id": "chunk-1"}],
                           "rubric": [{"criterion_id": "connection", "description": "说明政治联系", "max_score": 10.0}]}]}


def result_data():
    quiz = quiz_data()
    return {"project_id": quiz["project_id"], "node_id": quiz["node_id"], "assessment_id": quiz["assessment_id"], "snapshot": quiz["snapshot"],
            "grading_status": "graded",
            "question_results": [{"question_id": "q1", "evaluator_id": "text_rubric", "evaluator_version": "1.0.0", "score": 8.0, "max_score": 10.0,
                                  "evidence_ids": ["e1"], "feedback": "因果联系明确",
                                  "criterion_results": [{"criterion_id": "connection", "score": 8.0, "max_score": 10.0, "evidence_ids": ["e1"]}]}],
            "objective_results": [{"objective_id": "explain", "score_ratio": 0.8, "evidence_ids": ["e1"]}],
            "evidence": [{"evidence_id": "e1", "question_id": "q1", "kind": "text_excerpt", "start": 0, "end": 4, "quote": "税制不公"}]}


@pytest.mark.parametrize("subject,topic", [("Python", "条件与循环"), ("数学", "一元一次方程"), ("英语", "一般过去时"), ("历史", "法国大革命")])
def test_subjects_are_open_text_and_self_report_is_not_assessed(subject, topic):
    profile = LearningProfile(**profile_data(subject_label=subject, topic=topic, prior_knowledge={"self_reported": ["我以前学过相关知识"]}))
    assert profile.subject_label == subject
    assert profile.prior_knowledge.assessed_evidence == []
    assert "completed" not in profile.model_dump()


@pytest.mark.parametrize("field,value", [("tools", ["exec"]), ("max_requests", 10000), ("code", "import os"), ("api_key", "secret")])
def test_model_or_upload_cannot_add_execution_or_budget_fields(field, value):
    with pytest.raises(ValidationError):
        LearningProfile(**profile_data(**{field: value}))


def test_strict_profile_rejects_bool_integer_and_empty_subject():
    with pytest.raises(ValidationError):
        LearningProfile(**profile_data(time_budget_minutes=True))
    with pytest.raises(ValidationError):
        LearningProfile(**profile_data(subject_label="   "))


def test_server_limits_are_frozen_and_reject_expansion():
    assert SERVER_LIMITS.max_operation_chain_requests == 24
    assert SERVER_LIMITS.max_logical_requests == 3
    assert SERVER_LIMITS.sdk_max_retries == 0
    with pytest.raises(ValidationError):
        SERVER_LIMITS.max_operation_requests = 100
    for override in ({"max_nodes": 21}, {"max_operation_requests": 13}, {"max_budget_extensions": 2}, {"sdk_max_retries": 1}, {"tools": ["exec"]}):
        with pytest.raises(ValidationError):
            ServerLimits(**override)


def test_unvalidated_copy_or_nested_list_mutation_is_rechecked_at_boundaries():
    profile = LearningProfile(**profile_data())
    tampered = profile.model_copy(update={"time_budget_minutes": True})
    with pytest.raises(ValidationError):
        LearningProfile.model_validate(tampered)
    plan = LearningPlan(**plan_data())
    plan.nodes[0].prerequisite_ids.append("ghost")
    with pytest.raises(ValidationError):
        LearningPlan.model_validate(plan)
    limits = SERVER_LIMITS.model_copy(update={"max_operation_requests": 100})
    with pytest.raises(ValidationError):
        ServerLimits.model_validate(limits)


@pytest.mark.parametrize("threshold", [float("nan"), float("inf"), -0.1, 1.1])
def test_policy_cannot_hide_nonfinite_or_out_of_range_threshold(threshold):
    with pytest.raises(ValidationError):
        EvaluationPolicy(policy_id="policy-1", policy_version="1", allowed_question_types=["single_choice"],
                         evaluators=[{"evaluator_id": "choice_exact", "evaluator_version": "1.0.0"}], total_pass_threshold=threshold)


def test_material_hash_and_size_use_actual_utf8_bytes():
    with pytest.raises(ValidationError):
        SourceDocument(**source_data(content_hash="0" * 64))
    # Under 128 Ki characters, but exceeds 128 Ki UTF-8 bytes.
    with pytest.raises(ValidationError):
        SourceDocument(**source_data(content="汉" * 43691))
    assert SourceDocument(**source_data()).trust_note == "用户提供，未独立核验"


def test_material_link_checks_real_project_version_and_private_permission():
    source = SourceDocument(**source_data())
    content = source.content.splitlines()[1]
    chunk = SourceChunk(chunk_id="chunk-1", project_id="project-1", source_id=source.source_id, source_version=1,
                        content=content, content_hash=sha256(content.encode()).hexdigest(), line_start=2, line_end=2)
    plan = LearningPlan(**plan_data())
    link = NodeMaterialLink(project_id="project-1", node_id="causes", objective_id="explain", chunk_id="chunk-1", purpose="teaching")
    args = {"project_id": "project-1", "plan": plan, "chunks": {"chunk-1": chunk}, "sources": {source.source_id: source}}
    validate_material_link(link, **args)
    for changed_source in (SourceDocument(**source_data(project_id="project-2")),
                           SourceDocument(**source_data(source_version=2)),
                           SourceDocument(**source_data(visibility="assessment_private"))):
        with pytest.raises(ValueError):
            validate_material_link(link, **{**args, "sources": {source.source_id: changed_source}})
    invalid_chunk = SourceChunk(**{**chunk.model_dump(), "line_start": 1, "line_end": 1})
    with pytest.raises(ValueError):
        validate_material_link(link, **{**args, "chunks": {"chunk-1": invalid_chunk}})


def test_public_source_refuses_private_material():
    assert PublicSource.from_document(SourceDocument(**source_data())).visibility == "teaching"
    with pytest.raises(ValueError):
        PublicSource.from_document(SourceDocument(**source_data(visibility="assessment_private")))


def test_small_plan_is_valid_and_ghost_dependency_or_cycle_is_rejected():
    plan = LearningPlan(**plan_data())
    assert len(plan.nodes) == 1
    data = plan_data()
    data["nodes"][0]["prerequisite_ids"] = ["ghost"]
    with pytest.raises(ValidationError):
        LearningPlan(**data)
    data = plan_data()
    second = deepcopy(data["nodes"][0])
    second["node_id"] = "second"
    second["objectives"][0]["objective_id"] = "explain-second"
    second["prerequisite_ids"] = ["causes"]
    data["nodes"][0]["prerequisite_ids"] = ["second"]
    data["nodes"].append(second)
    with pytest.raises(ValidationError):
        LearningPlan(**data)


def test_policy_objective_references_cannot_be_ambiguous_across_nodes():
    data = plan_data()
    second = deepcopy(data["nodes"][0])
    second["node_id"] = "second"
    data["nodes"].append(second)
    with pytest.raises(ValidationError, match="项目内目标身份"):
        LearningPlan(**data)


def test_question_type_is_separate_from_evaluator_and_public_quiz_has_no_answer():
    quiz = AssessmentQuiz(**quiz_data())
    assert quiz.questions[0].question_type == "text"
    assert quiz.questions[0].evaluator_id == "text_rubric"
    public = PublicQuiz.from_private(quiz).model_dump()
    question = public["questions"][0]
    assert set(question) == {"question_id", "objective_ids", "question_type", "prompt", "max_score", "options"}
    assert "私有答案说明" not in str(public)
    assert "rubric" not in question


def test_valid_evaluation_is_anchored_in_the_actual_answer():
    result = EvaluationResult(**result_data())
    quiz = AssessmentQuiz(**quiz_data())
    validate_evaluation_context(result, quiz=quiz, answers={"q1": "税制不公引发政治讨论"})
    with pytest.raises(ValueError, match="实际作答"):
        validate_evaluation_context(result, quiz=quiz, answers={"q1": "无关回答"})


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1.0, 11.0])
def test_invalid_score_never_becomes_a_valid_evaluation(value):
    data = result_data()
    data["question_results"][0]["score"] = value
    with pytest.raises(ValidationError):
        EvaluationResult(**data)


def test_grading_rejects_forged_evidence_missing_objective_wrong_snapshot_and_identity():
    quiz = AssessmentQuiz(**quiz_data())
    data = result_data()
    data["question_results"][0]["evidence_ids"] = ["forged"]
    with pytest.raises(ValidationError, match="不存在"):
        EvaluationResult(**data)
    for change in (lambda value: value.update(objective_results=[]),
                   lambda value: value.update(assessment_id="another-assessment"),
                   lambda value: value["snapshot"].update(plan_version=2),
                   lambda value: value["question_results"][0].update(max_score=100.0)):
        data = result_data()
        change(data)
        with pytest.raises(ValueError):
            validate_evaluation_context(EvaluationResult(**data), quiz=quiz, answers={"q1": "税制不公"})


@pytest.mark.parametrize("status", ["needs_review", "invalid_item"])
def test_uncertain_evaluation_records_reason_without_inventing_a_score(status):
    data = result_data()
    data.update(grading_status=status, question_results=[], objective_results=[], evidence=[], uncertainty_reasons=["资料冲突，尚不能评价"])
    assert EvaluationResult(**data).question_results == []
    data["uncertainty_reasons"] = []
    with pytest.raises(ValidationError):
        EvaluationResult(**data)


def test_public_actions_require_state_and_stable_pending_identity():
    base = {"project_id": "project-1", "thread_id": "project-1", "profile": profile_data()}
    view = PublicProjectView(**base, allowed_actions=["confirm_profile"], pending_input_id="pending-1")
    assert view.page_state == "profile_review"
    for change in ({"allowed_actions": ["start_quiz"], "pending_input_id": "pending-1"},
                   {"allowed_actions": ["confirm_profile"]},
                   {"thread_id": "changed-thread"},
                   {"page_state": "legacy_readonly", "allowed_actions": ["retry"], "retry_token": "token"},
                   {"page_state": "plan_review", "requires_replan": True, "allowed_actions": ["confirm_plan"], "pending_input_id": "pending-1"}):
        with pytest.raises(ValidationError):
            PublicProjectView(**{**base, **change})


def test_exploration_never_exposes_formal_assessment_action_and_retry_needs_token():
    base = {"project_id": "project-1", "thread_id": "project-1", "profile": profile_data(learning_mode="exploration"), "pending_input_id": "pending-1"}
    assert PublicProjectView(**base, page_state="exploring", allowed_actions=["ask"]).page_state == "exploring"
    with pytest.raises(ValidationError):
        PublicProjectView(**base, page_state="learning", allowed_actions=["start_quiz"])
    with pytest.raises(ValidationError):
        PublicProjectView(**base, page_state="budget_exhausted", allowed_actions=["continue_with_new_budget"])
    assert PublicProjectView(**base, page_state="budget_exhausted", allowed_actions=["continue_with_new_budget"], retry_token="retry-1")
