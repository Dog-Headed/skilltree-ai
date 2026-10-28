from copy import deepcopy

import pytest

from app.services.llm import ModelCallBudget, ModelOutputValidationError
from app.v3 import assessment
from app.v3.capabilities import check_capabilities, require_evaluator, validate_policy
from app.v3.contracts import AssessmentQuiz, EvaluationPolicy, PublicQuiz, SkillNode, validate_evaluation_context
from tests.test_v3_evaluators import FakeModel, setup, text_batch


def generate(model, quiz, node, policy, contexts, **kwargs):
    return assessment.generate_quiz(project_id=quiz.project_id, node=node, assessment_id=quiz.assessment_id,
        snapshot=quiz.snapshot, policy=policy, contexts=contexts, llm=model, **kwargs)


def test_mixed_quiz_generation_uses_real_registered_evaluators_and_private_answer_contract():
    quiz, answers, node, policy, contexts = setup(("single_choice", "numeric_scalar", "text"))
    model = FakeModel(quiz.model_dump())
    result = generate(model, quiz, node, policy, contexts)
    assert result == quiz and len(model.calls) == 1
    assert check_capabilities(["numeric_scalar", "text_rubric"], has_material=True).formal_assessment_allowed
    assert callable(require_evaluator("numeric_scalar", "1.0.0")) and callable(require_evaluator("text_rubric", "1.0.0"))
    public = PublicQuiz.from_private(result).model_dump()
    text = str(public)
    assert "answer_key" not in text and "rubric" not in text and "numeric_rules" not in text and "source_citations" not in text


def test_prompt_explicitly_preserves_every_frozen_evidence_kind():
    import json
    quiz, _, node, policy, contexts = setup(('single_choice', 'numeric_scalar', 'text'))
    messages, _ = assessment.quiz_generation_messages(project_id=quiz.project_id, node=node,
        assessment_id=quiz.assessment_id, snapshot=quiz.snapshot, policy=policy, contexts=contexts)
    data = json.loads(messages[1].content.split('\n', 1)[1])
    assert {entry['objective_id']: set(entry['evidence_kinds']) for entry in data['required_coverage']} == {
        objective.objective_id: set(objective.evidence_requirement) for objective in node.objectives if objective.required}
    assert 'answer_key为null' in messages[0].content


def test_missing_coverage_identifies_objective_and_evidence_to_repair():
    quiz, _, node, policy, contexts = setup(('single_choice', 'numeric_scalar', 'text'))
    bad = quiz.model_copy(update={'questions': quiz.questions[:-1]})
    with pytest.raises(ValueError, match='objective_id=objective_2.*missing_evidence_kinds=.*text_excerpt'):
        assessment.validate_quiz(bad, node=node, policy=policy, contexts=contexts)


def test_numeric_generation_schema_lists_only_executable_units():
    import json
    from app.v3.evaluators import UNIT_RULES
    quiz, _, node, policy, contexts = setup(('numeric_scalar',))
    messages,_=assessment.quiz_generation_messages(project_id=quiz.project_id,node=node,
        assessment_id=quiz.assessment_id,snapshot=quiz.snapshot,policy=policy,contexts=contexts)
    payload=json.loads(messages[1].content.split('\n',1)[1])
    rules=payload['schema']['$defs']['NumericRules']['properties']
    assert set(rules['unit']['anyOf'][0]['enum'])==set(UNIT_RULES)
    assert set(rules['allowed_units']['items']['enum'])==set(UNIT_RULES)
    assert '元' not in payload['supported_numeric_units']
    assert 'unit=null、allowed_units=[]' in messages[0].content


def test_request_identities_are_literal_constraints_with_actionable_parser_errors():
    from app.services.llm import compact_parse_error
    from pydantic import ValidationError
    quiz, _, _, _, _=setup(('single_choice',))
    schema=assessment._quiz_output_contract(quiz.project_id,quiz.node_id,quiz.assessment_id,quiz.snapshot,'previous')
    raw=quiz.model_dump();raw.update(project_id='wrong_project',assessment_id='wrong_assessment',previous_assessment_id=None)
    with pytest.raises(ValidationError) as caught:schema.model_validate(raw)
    error=compact_parse_error(caught.value)
    assert quiz.project_id in error and quiz.assessment_id in error and 'previous' in error
    assert all(issue['type']=='literal_error' for issue in caught.value.errors())
    raw.update(project_id=quiz.project_id,assessment_id=quiz.assessment_id,previous_assessment_id='previous')
    assert schema.model_validate(raw).snapshot==quiz.snapshot
    definition=schema.model_json_schema()['properties']
    assert definition['snapshot']['const']==quiz.snapshot.model_dump()


def test_question_metadata_uses_only_frozen_objectives_criteria_evaluators_and_sources():
    from pydantic import ValidationError
    from app.services.llm import compact_parse_error
    quiz, _, node, policy, contexts=setup(('text',))
    schema=assessment._quiz_output_contract(quiz.project_id,quiz.node_id,quiz.assessment_id,quiz.snapshot,None,
        node=node,policy=policy,contexts=contexts)
    good=quiz.model_dump();assert schema.model_validate(good).questions[0].rubric
    bad=deepcopy(good);question=bad['questions'][0]
    question['objective_ids']=['forged_objective'];question['rubric'][0]['criterion_id']='renamed'
    question['source_citations'][0]['chunk_id']='forged_chunk';question['evaluator_version']='future'
    with pytest.raises(ValidationError) as caught:schema.model_validate(bad)
    error=compact_parse_error(caught.value)
    assert all(key in error for key in ('objective_ids','criterion_id','chunk_id','evaluator_version'))


@pytest.mark.parametrize('field', ['previous_assessment_id','assessment_id','snapshot'])
def test_identity_repair_identifies_changed_field_and_retains_frozen_values(field):
    quiz, _, node, policy, contexts=setup(('single_choice',))
    valid=quiz.model_dump();bad=deepcopy(valid)
    if field=='snapshot':bad[field]['policy_version']='old'
    else:bad[field]='wrong_identity'
    model=FakeModel(bad,valid)
    assert generate(model,quiz,node,policy,contexts)==quiz
    error=model.calls[1][-1].content
    assert ('snapshot.policy_version' if field=='snapshot' else field) in error


def test_unsupported_currency_unit_is_repaired_without_adding_conversion_support():
    quiz, _, node, policy, contexts=setup(('numeric_scalar',))
    bad=quiz.model_dump();bad['questions'][0]['numeric_rules'].update(unit='元',allowed_units=['元'])
    model=FakeModel(bad,quiz.model_dump());budget=ModelCallBudget()
    assert generate(model,quiz,node,policy,contexts,budget=budget)==quiz
    assert budget.request_count==2 and budget.output_repair_count==1


@pytest.mark.parametrize("defect", ["identity", "snapshot", "reference_answer", "score", "coverage", "citation", "evaluator", "duplicate", "numeric_for_explanation", "frozen_criterion_id"])
def test_generation_business_errors_get_one_repair(defect):
    quiz, answers, node, policy, contexts = setup(("single_choice", "numeric_scalar", "text"))
    valid = quiz.model_dump(); bad = deepcopy(valid)
    if defect == "identity": bad["assessment_id"] = "forged"
    elif defect == "snapshot": bad["snapshot"]["policy_version"] = "old"
    elif defect == "reference_answer": bad["questions"][2]["answer_key"] = None
    elif defect == "score": bad["questions"][1]["max_score"] = float("nan")
    elif defect == "coverage": bad["questions"].pop()
    elif defect == "citation": bad["questions"][0]["source_citations"][0]["chunk_id"] = "ghost"
    elif defect == "evaluator": bad["questions"][0]["evaluator_version"] = "future"
    elif defect == "duplicate": bad["questions"][1]["prompt"] = bad["questions"][0]["prompt"]
    elif defect == "numeric_for_explanation": bad["questions"][1]["objective_ids"] = ["objective_2"]
    elif defect == "frozen_criterion_id": bad["questions"][2]["rubric"][0]["criterion_id"] = "new_model_criterion"
    budget = ModelCallBudget(); model = FakeModel(bad, valid)
    assert generate(model, quiz, node, policy, contexts, budget=budget) == quiz
    assert budget.request_count == 2 and budget.output_repair_count == 1
    if defect == "frozen_criterion_id":
        system = model.calls[0][0].content
        assert "逐字保留" in system and "窄目标可以只有1题" in system
        assert assessment.QUIZ_PROMPT_VERSION == "v3-day11-quiz-2"


def test_continuous_invalid_quiz_exits_after_two_calls_without_a_quiz_result():
    quiz, answers, node, policy, contexts = setup()
    bad = quiz.model_dump(); bad["questions"][0]["answer_key"] = None
    model = FakeModel(bad, bad, quiz.model_dump())
    with pytest.raises(ModelOutputValidationError): generate(model, quiz, node, policy, contexts)
    assert len(model.calls) == 2


def test_history_duplicates_use_same_shared_repair_budget():
    quiz, answers, node, policy, contexts = setup(("single_choice",))
    repaired = quiz.model_dump(); repaired["questions"][0]["prompt"] += "请选择变量保存值的正确选项。"
    model = FakeModel(quiz.model_dump(), repaired)
    result = generate(model, quiz, node, policy, contexts, previous_question_prompts=[quiz.questions[0].prompt])
    assert result.questions[0].prompt == repaired["questions"][0]["prompt"] and len(model.calls) == 2


def test_repeated_question_repair_identifies_every_reused_prompt():
    quiz, _, node, policy, contexts=setup(('single_choice','numeric_scalar'))
    bad=quiz.model_dump();valid=deepcopy(bad)
    for question in valid['questions']:question['prompt']+='请选择或计算第二个例子的结果。'
    model=FakeModel(bad,valid)
    result=generate(model,quiz,node,policy,contexts,previous_question_prompts=[q.prompt for q in quiz.questions])
    assert result.questions[0].prompt==valid['questions'][0]['prompt']
    repair=model.calls[1][-1].content
    assert 'question_ids' in repair and all(q.question_id in repair for q in quiz.questions)


def test_contexts_must_be_actual_owned_frozen_blocks_before_model_call():
    quiz, answers, node, policy, contexts = setup()
    for mutate in ("project", "source_version", "body", "purpose"):
        bad = deepcopy(contexts)
        if mutate == "project": bad["objective_0"]["project_id"] = "other"
        elif mutate == "source_version": bad["objective_0"]["blocks"][0]["citation"]["source_version"] = 2
        elif mutate == "body": bad["objective_0"]["blocks"][0]["content"] = "tampered"
        elif mutate == "purpose": bad["objective_0"]["purpose"] = "teaching"
        model = FakeModel()
        with pytest.raises(ValueError): generate(model, quiz, node, policy, bad)
        assert model.calls == []


def test_choice_and_numeric_evaluation_use_zero_model_calls_and_server_ratios():
    quiz, answers, node, policy, contexts = setup(("single_choice", "numeric_scalar"))
    answers["q1"] = "3"
    model = FakeModel()
    result = assessment.evaluate_quiz(quiz=quiz, answers=answers, policy=policy, node=node, contexts=contexts, llm=model)
    assert result.grading_status == "graded" and model.calls == []
    assert [item.score_ratio for item in result.objective_results] == [1.0, 0.0]
    validate_evaluation_context(result, quiz=quiz, answers=answers)


def test_mixed_evaluation_batches_all_text_once_and_does_not_trust_model_target_ratios():
    quiz, answers, node, policy, contexts = setup(("single_choice", "numeric_scalar", "text", "text"))
    batch = text_batch(quiz, answers); batch["questions"][0]["criteria"][0]["score"] = 0.0
    model = FakeModel(batch)
    result = assessment.evaluate_quiz(quiz=quiz, answers=answers, policy=policy, node=node, contexts=contexts, llm=model)
    assert result.grading_status == "graded" and len(model.calls) == 1
    assert [item.score_ratio for item in result.objective_results] == [1.0, 1.0, 0.5, 1.0]
    assert len(result.question_results) == 4
    validate_evaluation_context(result, quiz=quiz, answers=answers)


@pytest.mark.parametrize("answer", ["NaN", "1+1", "2 unknown", ""])
def test_unparseable_numeric_does_not_create_zero_objective_or_pass_evidence(answer):
    quiz, answers, node, policy, contexts = setup(("numeric_scalar",))
    answers["q0"] = answer; model = FakeModel()
    result = assessment.evaluate_quiz(quiz=quiz, answers=answers, policy=policy, node=node, contexts=contexts, llm=model)
    assert result.grading_status == "needs_review" and result.question_results == [] and result.objective_results == []
    assert model.calls == []


def test_bad_reference_is_invalid_item_and_missing_context_is_review_not_student_failure():
    quiz, answers, node, policy, contexts = setup()
    bad = quiz.model_dump(); bad["questions"][0]["answer_key"] = None
    result = assessment.evaluate_quiz(quiz=bad, answers=answers, policy=policy, node=node, contexts=contexts, llm=FakeModel())
    assert result.grading_status == "invalid_item" and result.question_results == []
    missing = assessment.evaluate_quiz(quiz=quiz, answers=answers, policy=policy, node=node, llm=FakeModel())
    assert missing.grading_status == "needs_review" and missing.uncertainty_reasons


def test_forged_scores_or_evidence_never_produce_an_evaluation_result():
    quiz, answers, node, policy, contexts = setup()
    batch = text_batch(quiz, answers); batch["questions"][0]["criteria"][0]["anchors"][0]["quote"] = "forged"
    model = FakeModel(batch, batch)
    with pytest.raises(ModelOutputValidationError):
        assessment.evaluate_quiz(quiz=quiz, answers=answers, policy=policy, node=node, contexts=contexts, llm=model)
    assert len(model.calls) == 2


def test_policy_cannot_get_text_or_numeric_evidence_from_choice_only_evaluator():
    quiz, answers, node, policy, contexts = setup(("single_choice",))
    raw = policy.model_dump(); raw["objective_rules"][0]["evidence_kinds"] = ["text_excerpt"]
    with pytest.raises(ValueError): validate_policy(raw)


def test_one_high_total_text_score_cannot_mask_failure_of_a_separate_required_objective():
    quiz, answers, node, policy, contexts = setup(("text", "text"))
    raw_node = node.model_dump(); raw_node["objectives"][0]["criterion_ids"] = ["r1"]; raw_node["objectives"][1]["criterion_ids"] = ["r2"]
    node = SkillNode.model_validate(raw_node)
    raw = quiz.model_dump(); raw["questions"] = raw["questions"][:1]; question = raw["questions"][0]
    question["objective_ids"] = ["objective_0", "objective_1"]
    question["rubric"][0]["max_score"] = 9.0; question["rubric"][1]["max_score"] = 1.0
    quiz = AssessmentQuiz.model_validate(raw); answers = {"q0": answers["q0"]}
    batch = text_batch(quiz, answers); batch["questions"][0]["criteria"][1]["score"] = 0.0
    result = assessment.evaluate_quiz(quiz=quiz, answers=answers, policy=policy, node=node, contexts=contexts, llm=FakeModel(batch))
    assert result.question_results[0].score == 9.0
    assert [item.score_ratio for item in result.objective_results] == [1.0, 0.0]


def test_same_question_ids_in_different_assessments_have_distinct_evidence_identity():
    quiz, answers, node, policy, contexts = setup(("numeric_scalar",))
    first = assessment.evaluate_quiz(quiz=quiz, answers=answers, policy=policy, node=node, contexts=contexts)
    raw = quiz.model_dump(); raw["assessment_id"] = "other_assessment"
    second = assessment.evaluate_quiz(quiz=raw, answers=answers, policy=policy, node=node, contexts=contexts)
    assert first.evidence[0].evidence_id != second.evidence[0].evidence_id


@pytest.mark.parametrize("field,value", [("numeric_abs_tolerance", 0.010001), ("numeric_rel_tolerance", 0.000001001)])
def test_policy_numeric_tolerance_cannot_exceed_trusted_server_caps(field, value):
    quiz, answers, node, policy, contexts = setup(("numeric_scalar",))
    raw = policy.model_dump(); raw[field] = value
    with pytest.raises(ValueError, match="容差"):
        validate_policy(raw)


def test_numeric_policy_allows_server_boundary_but_defaults_are_exact():
    quiz, answers, node, policy, contexts = setup(("numeric_scalar",))
    raw = policy.model_dump(); raw.update(numeric_abs_tolerance=0.01, numeric_rel_tolerance=0.000001)
    assert validate_policy(raw).numeric_rel_tolerance == 0.000001
    raw.pop("numeric_abs_tolerance"); raw.pop("numeric_rel_tolerance")
    exact = EvaluationPolicy.model_validate(raw)
    assert exact.numeric_abs_tolerance == exact.numeric_rel_tolerance == 0.0
    with pytest.raises(ValueError, match="frozen policy"):
        assessment.validate_quiz(quiz, node=node, policy=exact, contexts=contexts)


@pytest.mark.parametrize("field", ["abs_tolerance", "rel_tolerance"])
def test_model_cannot_add_tolerance_even_within_server_cap_and_gets_one_repair(field):
    quiz, answers, node, policy, contexts = setup(("numeric_scalar",))
    raw_policy = policy.model_dump(); raw_policy.update(numeric_abs_tolerance=0.0, numeric_rel_tolerance=0.0)
    exact = EvaluationPolicy.model_validate(raw_policy)
    valid = quiz.model_dump(); valid["questions"][0]["numeric_rules"]["abs_tolerance"] = 0.0
    bad = deepcopy(valid); bad["questions"][0]["numeric_rules"][field] = 0.01 if field == "abs_tolerance" else 0.000001
    model = FakeModel(bad, valid); budget = ModelCallBudget()
    generated = generate(model, quiz, node, exact, contexts, budget=budget)
    assert generated.questions[0].numeric_rules.abs_tolerance == 0.0
    assert generated.questions[0].numeric_rules.rel_tolerance == 0.0
    assert (budget.request_count, budget.output_repair_count) == (2, 1)
    repeated = FakeModel(bad, bad)
    with pytest.raises(ModelOutputValidationError):
        generate(repeated, quiz, node, exact, contexts)
    assert len(repeated.calls) == 2
    invalid = assessment.evaluate_quiz(quiz=bad, answers=answers, node=node, policy=exact, contexts=contexts, llm=FakeModel())
    assert invalid.grading_status == "invalid_item" and invalid.question_results == []
