from copy import deepcopy

import pytest

from app.v3.guard import _score_ratio, decide_progress


def make_case(scores=(90.0, 10.0), prerequisites=None):
    snapshot = {"profile_version": 1, "plan_version": 1, "policy_id": "policy", "policy_version": "1",
                "source_manifest": [{"source_id": "source", "source_version": 1, "content_hash": "a" * 64}],
                "evaluator_manifest": [{"evaluator_id": "choice_exact", "evaluator_version": "1.0.0"}]}
    questions, results, evidence, answers, objectives, rules = [], [], [], {}, [], []
    for i, (score, maximum) in enumerate(zip(scores, (90.0, 10.0)), 1):
        qid, oid, eid = f"q{i}", f"o{i}", f"e{i}"
        answer = "A" if score == maximum else "B"
        answers[qid] = answer
        questions.append({"question_id": qid, "objective_ids": [oid], "question_type": "single_choice",
            "prompt": "选择符合材料的一项", "max_score": maximum, "evaluator_id": "choice_exact", "evaluator_version": "1.0.0",
            "source_citations": [{"source_id": "source", "source_version": 1, "chunk_id": "chunk"}],
            "options": [{"option_id": "A", "text": "正确"}, {"option_id": "B", "text": "错误"}], "answer_key": "A"})
        results.append({"question_id": qid, "evaluator_id": "choice_exact", "evaluator_version": "1.0.0",
                        "score": score, "max_score": maximum, "evidence_ids": [eid], "feedback": "逐题判断"})
        evidence.append({"evidence_id": eid, "question_id": qid, "kind": "choice", "selected_option_ids": [answer]})
        objectives.append({"objective_id": oid, "observable_outcome": "根据资料选择正确解释", "required": True,
                           "required_capability_ids": ["choice_exact"], "evidence_requirement": ["choice"], "source_chunk_ids": ["chunk"]})
        rules.append({"objective_id": oid, "evidence_kinds": ["choice"], "pass_threshold": 0.8})
    quiz = {"project_id": "project", "node_id": "current", "assessment_id": "assessment",
            "snapshot": snapshot, "questions": questions}
    evaluation = {"project_id": "project", "node_id": "current", "assessment_id": "assessment", "snapshot": deepcopy(snapshot),
        "grading_status": "graded", "question_results": results,
        # Intentionally overconfident model ratios; the guard must recalculate.
        "objective_results": [{"objective_id": f"o{i}", "score_ratio": 1.0, "evidence_ids": [f"e{i}"]} for i in (1, 2)],
        "evidence": evidence}
    return {"quiz": quiz, "evaluation": evaluation,
            "node": {"node_id": "current", "title": "通用节点", "description": "判断材料中的解释",
                     "estimated_minutes": 20, "objectives": objectives, "prerequisite_ids": prerequisites or []},
            "policy": {"policy_id": "policy", "policy_version": "1", "allowed_question_types": ["single_choice"],
                       "evaluators": [{"evaluator_id": "choice_exact", "evaluator_version": "1.0.0"}], "objective_rules": rules},
            "profile": {"subject_label": "开放主题", "topic": "材料解释", "goal": "根据材料选择正确解释"},
            "completed_node_ids": [], "answers": answers,
            "diagnosis": {"project_id": "project", "node_id": "current", "assessment_id": "assessment", "snapshot": deepcopy(snapshot),
                          "action": "advance", "reason": "模型建议推进", "evidence_ids": ["e1", "e2"], "review_node_id": None}}


def text_case(*, frozen_critical=False, severity=None):
    case = make_case(scores=(89.0, 10.0))
    q = case["quiz"]["questions"][0]
    q.update({"question_type": "text", "evaluator_id": "text_rubric", "options": [], "answer_key": "说明材料依据",
              "rubric": [{"criterion_id": "essential", "description": "解释必要联系", "max_score": 90.0, "critical": frozen_critical}]})
    case["quiz"]["snapshot"]["evaluator_manifest"].append({"evaluator_id": "text_rubric", "evaluator_version": "1.0.0"})
    case["evaluation"]["snapshot"] = deepcopy(case["quiz"]["snapshot"])
    case["diagnosis"]["snapshot"] = deepcopy(case["quiz"]["snapshot"])
    case["policy"]["allowed_question_types"].append("text")
    case["policy"]["evaluators"].append({"evaluator_id": "text_rubric", "evaluator_version": "1.0.0"})
    case["policy"]["objective_rules"][0]["evidence_kinds"] = ["text_excerpt"]
    case["node"]["objectives"][0].update({"required_capability_ids": ["text_rubric"], "evidence_requirement": ["text_excerpt"], "criterion_ids": ["essential"]})
    case["answers"]["q1"] = "依据不足"
    case["evaluation"]["evidence"][0] = {"evidence_id": "e1", "question_id": "q1", "kind": "text_excerpt", "quote": "依据不足", "start": 0, "end": 4}
    case["evaluation"]["question_results"][0].update({"evaluator_id": "text_rubric", "criterion_results": [
        {"criterion_id": "essential", "score": 89.0, "max_score": 90.0, "evidence_ids": ["e1"], "severity": severity}]})
    return case


def test_valid_current_evaluation_can_advance_with_no_database_side_effects():
    case = make_case()
    before = deepcopy(case)
    decision = decide_progress(**case)
    assert decision.passed and decision.effective_action == "advance"
    assert case == before


def test_90_percent_total_cannot_hide_required_goal_zero_or_model_ratio_one():
    decision = decide_progress(**make_case(scores=(90.0, 0.0)))
    assert decision.passed is False
    assert decision.effective_action == "remediate"
    assert any("必要目标未达标：o2" in reason for reason in decision.reasons)


def test_policy_cannot_make_required_node_objective_optional():
    case = make_case(scores=(90.0, 0.0))
    case["policy"]["objective_rules"][1]["required"] = False
    assert decide_progress(**case).passed is False


@pytest.mark.parametrize("status", ["needs_review", "invalid_item"])
def test_uncertain_or_invalid_assessment_never_advances(status):
    case = make_case()
    case["evaluation"].update(grading_status=status, question_results=[], objective_results=[], evidence=[], uncertainty_reasons=["材料有冲突"])
    case["diagnosis"].update(action="collect_more_evidence", evidence_ids=[])
    decision = decide_progress(**case)
    assert not decision.passed and decision.effective_action == "assessment_review"


def test_exploration_and_missing_prerequisites_cannot_complete():
    case = make_case()
    case["profile"]["learning_mode"] = "exploration"
    assert not decide_progress(**case).passed
    case = make_case(prerequisites=["foundation"])
    assert not decide_progress(**case).passed
    case["completed_node_ids"] = ["foundation"]
    assert decide_progress(**case).passed


def test_nonadvance_diagnosis_retains_safe_recommendation_without_passing():
    case = make_case()
    case["diagnosis"]["action"] = "remediate"
    decision = decide_progress(**case)
    assert not decision.passed and decision.effective_action == "remediate"


@pytest.mark.parametrize("change", ["project", "snapshot", "evidence", "review"])
def test_invalid_identity_anchor_or_review_cannot_unlock(change):
    case = make_case(prerequisites=["foundation"])
    if change == "project":
        case["evaluation"]["project_id"] = "other_project"
    elif change == "snapshot":
        case["evaluation"]["snapshot"]["plan_version"] = 2
    elif change == "evidence":
        case["evaluation"]["evidence"][0]["selected_option_ids"] = ["B"]
    else:
        case["diagnosis"].update(action="revisit_prerequisite", review_node_id="ghost")
    with pytest.raises(ValueError):
        decide_progress(**case)


def test_advance_cannot_use_fabricated_diagnosis_evidence():
    case = make_case()
    case["diagnosis"]["evidence_ids"] = ["invented"]
    decision = decide_progress(**case)
    assert not decision.passed
    assert any("证据" in reason for reason in decision.reasons)


def test_duplicate_ids_for_same_answer_anchor_do_not_satisfy_two_evidence_requirement():
    case = make_case()
    duplicate = deepcopy(case["evaluation"]["evidence"][0])
    duplicate["evidence_id"] = "e1_duplicate"
    case["evaluation"]["evidence"].append(duplicate)
    case["evaluation"]["question_results"][0]["evidence_ids"].append("e1_duplicate")
    case["policy"]["objective_rules"][0]["min_evidence"] = 2
    decision = decide_progress(**case)
    assert not decision.passed and decision.effective_action == "collect_more_evidence"


def test_unavailable_evaluator_or_wrong_exact_choice_score_cannot_pass(monkeypatch):
    monkeypatch.setattr("app.v3.guard.is_evaluator_available", lambda *args: False)
    assert not decide_progress(**make_case()).passed
    monkeypatch.setattr("app.v3.guard.is_evaluator_available", lambda *args: True)
    case = make_case()
    case["answers"]["q2"] = "B"
    case["evaluation"]["evidence"][1]["selected_option_ids"] = ["B"]
    assert not decide_progress(**case).passed


def test_frozen_critical_standard_blocks_even_when_model_omits_severity():
    decision = decide_progress(**text_case(frozen_critical=True))
    assert not decision.passed
    assert any("冻结关键标准未全部满足" in reason for reason in decision.reasons)


def test_model_critical_severity_also_blocks_when_standard_is_not_marked_critical():
    decision = decide_progress(**text_case(severity="critical"))
    assert not decision.passed
    assert any("关键错误" in reason for reason in decision.reasons)


def test_multigoal_text_cannot_reuse_one_aggregate_mark_for_every_required_goal():
    case = text_case()
    case["quiz"]["questions"][0]["objective_ids"] = ["o1", "o2"]
    case["node"]["objectives"][0]["criterion_ids"] = []
    decision = decide_progress(**case)
    assert not decision.passed
    assert any("分项映射" in reason for reason in decision.reasons)


def test_question_cannot_cite_an_unfrozen_source_version():
    case = make_case()
    case["quiz"]["questions"][0]["source_citations"][0]["source_version"] = 2
    with pytest.raises(ValueError, match="资料版本"):
        decide_progress(**case)


def test_finite_large_scores_do_not_overflow_the_total_or_turn_thresholds_into_nan():
    assert _score_ratio([(1e308, 1e308), (0.0, 1e308)]) == 0.5
    assert _score_ratio([(1e308, 1e308), (1e308, 1e308)]) == 1.0


def numeric_case(answer="2", numeric_value=2.0, score=90.0):
    case = make_case(scores=(score, 10.0))
    question = case["quiz"]["questions"][0]
    question.update(question_type="numeric_scalar", evaluator_id="numeric_scalar", options=[], answer_key=None,
                    numeric_rules={"expected": 2.0, "abs_tolerance": 0.0})
    case["quiz"]["snapshot"]["evaluator_manifest"].append({"evaluator_id": "numeric_scalar", "evaluator_version": "1.0.0"})
    case["evaluation"]["snapshot"] = deepcopy(case["quiz"]["snapshot"])
    case["diagnosis"]["snapshot"] = deepcopy(case["quiz"]["snapshot"])
    case["policy"]["allowed_question_types"].append("numeric_scalar")
    case["policy"]["evaluators"].append({"evaluator_id": "numeric_scalar", "evaluator_version": "1.0.0"})
    case["policy"]["objective_rules"][0]["evidence_kinds"] = ["numeric_result"]
    case["node"]["objectives"][0].update(required_capability_ids=["numeric_scalar"], evidence_requirement=["numeric_result"])
    case["answers"]["q1"] = answer
    case["evaluation"]["evidence"][0] = {"evidence_id": "e1", "question_id": "q1", "kind": "numeric_result", "quote": answer, "numeric_value": numeric_value}
    case["evaluation"]["question_results"][0]["evaluator_id"] = "numeric_scalar"
    return case


def test_numeric_correct_answer_can_advance_and_wrong_answer_with_real_zero_fails_normally():
    assert decide_progress(**numeric_case()).passed
    decision = decide_progress(**numeric_case(answer="0", numeric_value=0.0, score=0.0))
    assert not decision.passed
    assert any("必要目标未达标" in reason for reason in decision.reasons)


def test_numeric_wrong_answer_cannot_advance_using_forged_full_score():
    with pytest.raises(ValueError, match="数值评分"):
        decide_progress(**numeric_case(answer="0", numeric_value=0.0, score=90.0))


def test_numeric_answer_provenance_does_not_allow_a_forged_parsed_value():
    with pytest.raises(ValueError, match="数值证据"):
        decide_progress(**numeric_case(answer="2", numeric_value=999.0))


@pytest.mark.parametrize("answer", ["NaN", "Infinity", "1+1", "2 unknown"])
def test_unparseable_numeric_answer_with_forged_graded_result_requires_system_review(answer):
    with pytest.raises(ValueError, match="无法.*重现"):
        decide_progress(**numeric_case(answer=answer, numeric_value=0.0))


@pytest.mark.parametrize("field,value", [("numeric_abs_tolerance", 0.010001), ("numeric_rel_tolerance", 0.000001001)])
def test_guard_independently_rejects_policy_tolerance_over_server_cap(field, value):
    case = numeric_case(); case["policy"][field] = value
    with pytest.raises(ValueError, match="服务端上限"):
        decide_progress(**case)


@pytest.mark.parametrize("field,value", [("abs_tolerance", 0.01), ("rel_tolerance", 0.000001)])
def test_guard_rejects_question_tolerance_above_frozen_exact_policy(field, value):
    case = numeric_case(); case["quiz"]["questions"][0]["numeric_rules"][field] = value
    with pytest.raises(ValueError, match="冻结策略"):
        decide_progress(**case)


def test_guard_recomputes_valid_frozen_unit_conversion_without_model_calls():
    case = numeric_case(answer="200 cm")
    case["quiz"]["questions"][0]["numeric_rules"].update(unit="m", allowed_units=["m", "cm"])
    assert decide_progress(**case).passed


def test_guard_accepts_only_explicit_policy_tolerance_within_server_cap():
    case = numeric_case(answer="2.005", numeric_value=2.005)
    case["policy"]["numeric_abs_tolerance"] = 0.01
    case["quiz"]["questions"][0]["numeric_rules"]["abs_tolerance"] = 0.01
    assert decide_progress(**case).passed
