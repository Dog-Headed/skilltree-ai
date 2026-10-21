import pytest
from pydantic import ValidationError

from app.v3.capabilities import (
    ChoiceExactItem,
    check_capabilities,
    check_profile_capabilities,
    evaluate_choice_exact,
    get_capability,
    list_capabilities,
    require_evaluator,
    validate_policy,
)
from app.v3.config import ServerLimits
from app.v3.contracts import LearningProfile
from app.v3.presets import (
    load_evaluation_policy,
    load_policy_draft,
    load_subject_preset,
    preset_for_subject,
    profile_from_preset,
    validate_subject_preset,
)


def choice_item(**changes):
    data = {
        "item_id": "q1",
        "objective_id": "objective_1",
        "question_type": "single_choice",
        "options": [{"option_id": "a", "text": "甲"}, {"option_id": "b", "text": "乙"}, {"option_id": "c", "text": "丙"}],
        "correct_option_ids": ["a"],
        "max_score": 10.0,
    }
    data.update(changes)
    return data


def test_choice_handler_really_runs_without_llm_and_scores_exact_answers():
    handler = require_evaluator("choice_exact", "1.0.0")
    correct = handler(choice_item(), "a")
    wrong = handler(choice_item(), "b")
    assert (correct.score, correct.correct, wrong.score, wrong.correct) == (10.0, True, 0.0, False)
    assert correct.item_id == "q1" and correct.objective_id == "objective_1"
    assert correct.evaluation_status == "valid"


def test_multiple_choice_order_does_not_matter_and_partial_answer_is_not_full_credit():
    item = choice_item(question_type="multiple_choice", correct_option_ids=["a", "c"])
    assert evaluate_choice_exact(item, ["c", "a"]).score == 10.0
    assert evaluate_choice_exact(item, ["a"]).score == 0.0
    assert evaluate_choice_exact(item, []).score == 0.0
    assert evaluate_choice_exact(item, ["a", "b", "c"]).score == 0.0


@pytest.mark.parametrize("question_type,answer", [
    ("single_choice", ["a"]), ("single_choice", True),
    ("single_choice", "unknown"), ("multiple_choice", "a"),
    ("multiple_choice", ["a", "a"]), ("multiple_choice", ["a", 1]),
])
def test_malformed_answers_are_rejected_rather_than_recorded_as_failure(question_type, answer):
    with pytest.raises(ValueError):
        evaluate_choice_exact(choice_item(question_type=question_type), answer)


@pytest.mark.parametrize("changes", [
    {"max_score": float("nan")}, {"max_score": float("inf")},
    {"max_score": -1.0}, {"correct_option_ids": ["missing"]},
    {"correct_option_ids": ["a", "b"]},
    {"options": [{"option_id": "a", "text": "甲"}, {"option_id": "a", "text": "乙"}]},
])
def test_invalid_choice_items_cannot_be_scored(changes):
    with pytest.raises(ValidationError):
        ChoiceExactItem.model_validate(choice_item(**changes))


@pytest.mark.parametrize("capabilities,material,mode,status", [
    (["choice_exact"], True, "formal", "supported"),
    (["text_explanation", "choice_exact"], True, "formal", "supported"),
    (["choice_exact"], False, "formal", "needs_material"),
    (["choice_exact"], True, "exploration", "exploration_only"),
    (["text_explanation"], True, "formal", "exploration_only"),
    ([], True, "formal", "exploration_only"),
    (["choice_exact", "numeric_scalar"], True, "formal", "supported"),
    (["text_rubric"], True, "formal", "supported"),
    (["numeric_scalar"], False, "formal", "needs_material"),
    (["text_rubric"], False, "formal", "needs_material"),
    (["code_execution"], True, "formal", "unsupported"),
    (["symbolic_proof"], True, "formal", "unsupported"),
    (["audio_input", "pronunciation"], True, "formal", "unsupported"),
    (["choice_exact", "uploaded.plugin"], True, "formal", "unsupported"),
])
def test_capability_states_depend_on_concrete_tasks_not_subject(capabilities, material, mode, status):
    result = check_capabilities(capabilities, has_material=material, learning_mode=mode)
    assert result.status == status
    assert result.formal_assessment_allowed is (status == "supported")


@pytest.mark.parametrize("subject", ["Python", "数学", "英语", "尚未接入的新文字主题"])
def test_open_subject_profiles_do_not_need_a_subject_enum(subject):
    profile = LearningProfile(
        subject_label=subject, topic="资料内的概念识别", goal="根据资料识别正确陈述",
        requested_capabilities=["choice_exact"],
    )
    assert check_capabilities(profile, has_material=True).status == "supported"
    assert check_profile_capabilities(profile.model_dump(), has_material=False).status == "needs_material"
    assert profile.prior_knowledge.assessed_evidence == []


def test_public_registry_matches_implemented_handlers_and_keeps_unsupported_tasks_blocked():
    capabilities = {row["capability_id"]: row for row in list_capabilities()}
    assert capabilities["choice_exact"]["formal_assessment_available"] is True
    for capability_id in ("numeric_scalar", "text_rubric"):
        assert capabilities[capability_id]["availability"] == "available"
        assert capabilities[capability_id]["formal_assessment_available"] is True
        assert callable(require_evaluator(capability_id, "1.0.0"))
        with pytest.raises(ValueError):
            require_evaluator(capability_id, "future")
    for capability_id in ("code_execution", "symbolic_proof"):
        assert capabilities[capability_id]["availability"] == "unsupported"
        assert not capabilities[capability_id]["formal_assessment_available"]
        with pytest.raises(ValueError, match="尚未实装|版本不可用"):
            require_evaluator(capability_id, "1.0.0")
    with pytest.raises(ValueError):
        require_evaluator("choice_exact", "future")
    assert get_capability("__import__('os')") is None
    assert all("handler" not in row for row in capabilities.values())


@pytest.mark.parametrize("preset_id", ["generic", "python", "mathematics", "english"])
def test_templates_use_actual_capabilities_and_still_need_material_and_confirmation(preset_id):
    preset = load_subject_preset(preset_id)
    profile = profile_from_preset(preset_id)
    assert preset.preset_id == preset_id
    assert profile.requested_capabilities == preset.suggested_capabilities
    assert check_capabilities(profile, has_material=True).status == "supported"
    assert check_capabilities(profile, has_material=False).status == "needs_material"
    assert check_capabilities(profile.requested_capabilities, has_material=True, learning_mode="exploration").formal_assessment_allowed is False


def test_new_subject_uses_generic_template_without_permission_side_effects():
    preset = preset_for_subject("一个尚未参与调试的文字主题")
    assert preset.preset_id == "generic"
    profile = profile_from_preset("generic", subject_label="一个尚未参与调试的文字主题")
    assert profile.subject_label == "一个尚未参与调试的文字主题"
    assert check_capabilities(profile, has_material=True).status == "supported"
    assert check_capabilities(profile, has_material=False).formal_assessment_allowed is False
    with pytest.raises(ValueError):
        load_subject_preset("../../.env")
    with pytest.raises(ValueError):
        load_policy_draft("../../.env")


@pytest.mark.parametrize("key,value", [
    ("python_import", "os.system"), ("tools", ["execute_code"]),
    ("model_endpoint", "https://evil.invalid"), ("max_requests", 999),
    ("server_limits", {"max_output_repairs": 999}),
    ("evaluation_policy", {"total_pass_threshold": 0.0}),
])
def test_templates_cannot_add_execution_or_override_permissions(key, value):
    draft = load_subject_preset("generic").model_dump()
    draft[key] = value
    with pytest.raises(ValidationError):
        validate_subject_preset(draft)


def test_template_cannot_register_an_unknown_capability():
    draft = load_subject_preset("generic").model_dump()
    draft["suggested_capabilities"].append("custom_tools.execute")
    with pytest.raises(ValidationError):
        validate_subject_preset(draft)


def test_existing_policy_examples_activate_only_with_current_implemented_versions():
    ready = load_evaluation_policy()
    assert ready.evaluators[0].evaluator_id == "choice_exact"
    for policy_id in ("numeric-text-draft", "text-rubric-draft"):
        assert load_policy_draft(policy_id).policy_id == policy_id
        assert load_evaluation_policy(policy_id).policy_id == policy_id
        changed = load_policy_draft(policy_id).model_dump()
        changed["evaluators"][-1]["evaluator_version"] = "future"
        with pytest.raises(ValueError, match="版本不可用"):
            validate_policy(changed)


@pytest.mark.parametrize("change", [
    {"total_pass_threshold": 0.1},
    {"critical_severities": []},
    {"evaluators": [{"evaluator_id": "uploaded_tool", "evaluator_version": "1.0.0"}]},
    {"evaluators": [{"evaluator_id": "choice_exact", "evaluator_version": "0.1.0"}]},
    {"allowed_question_types": ["text"]},
])
def test_policy_cannot_lower_server_standards_or_use_unavailable_handlers(change):
    policy = load_policy_draft("choice-foundation").model_dump()
    policy.update(change)
    with pytest.raises(ValueError):
        validate_policy(policy)


def test_policy_validates_each_objective_threshold_and_evidence_kind():
    policy = load_policy_draft("choice-foundation").model_dump()
    policy["objective_rules"][0]["pass_threshold"] = 0.2
    with pytest.raises(ValueError, match="目标通过底线"):
        validate_policy(policy)
    policy["objective_rules"][0]["pass_threshold"] = 0.8
    policy["objective_rules"][0]["evidence_kinds"] = ["text_excerpt"]
    with pytest.raises(ValueError, match="不能验证"):
        validate_policy(policy)


def test_trusted_server_can_tighten_limits_but_draft_dictionary_cannot_replace_them():
    policy = load_policy_draft("choice-foundation")
    stricter = ServerLimits(max_effective_rounds=2)
    with pytest.raises(ValueError, match="max_effective_rounds"):
        validate_policy(policy, limits=stricter)
    with pytest.raises(ValueError, match="可信 ServerLimits"):
        validate_policy(policy, limits={"min_total_pass_threshold": 0.0})
    with pytest.raises(ValidationError):
        ServerLimits(max_operation_requests=999)


def test_typed_copies_and_mutable_nested_lists_are_revalidated_at_authorization_boundary():
    item = ChoiceExactItem.model_validate(choice_item())
    invalid_item = item.model_copy(update={"correct_option_ids": ["missing"]})
    with pytest.raises(ValidationError):
        evaluate_choice_exact(invalid_item, "a")
    policy = load_policy_draft("choice-foundation")
    invalid_rule = policy.objective_rules[0].model_copy(update={"weight": float("nan")})
    policy.objective_rules[0] = invalid_rule
    with pytest.raises(ValidationError):
        validate_policy(policy)
    preset = load_subject_preset("generic")
    preset.suggested_capabilities.append("uploaded.run_code")
    with pytest.raises(ValidationError):
        validate_subject_preset(preset)


@pytest.mark.parametrize("identity_length", [81, 128])
def test_choice_handler_accepts_shared_contract_identity_and_text_limits(identity_length):
    option_id = "a" * identity_length
    item = choice_item(
        item_id="q" * identity_length,
        objective_id="o" * identity_length,
        options=[{"option_id": option_id, "text": "甲" * 4000}, {"option_id": "b", "text": "乙"}],
        correct_option_ids=[option_id],
    )
    result = evaluate_choice_exact(item, option_id)
    assert result.score == 10.0
    assert result.item_id == item["item_id"]
    assert result.objective_id == item["objective_id"]


def test_policy_revalidates_trusted_limits_created_with_unchecked_model_copy():
    limits = ServerLimits().model_copy(update={"max_operation_requests": 999})
    with pytest.raises(ValidationError):
        validate_policy(load_policy_draft("choice-foundation"), limits=limits)
