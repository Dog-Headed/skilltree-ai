import copy
from pathlib import Path
import shutil

import pytest

from app.v3.contracts import NumericRules, QuestionResult
from day10_check_fixtures import ROOT, check_fixtures, read_json, validate_case, verify_reference


def load_case(subject, number):
    return read_json(next((ROOT / "evals" / "v3" / subject / "cases").glob(f"*_{number:02d}.json")))


def sections(subject):
    manifest = read_json(ROOT / "materials" / "v3" / subject / "manifest.json")
    return {(document["filename"], section["section_id"])
            for document in manifest["documents"] for section in document["sections"]}


def test_all_three_frozen_course_packs_have_36_pending_cases_and_no_model_runs():
    result = check_fixtures()
    assert result["case_count"] == result["pending_human_review"] == 36
    assert result["real_model_runs"] == 0
    assert result["formal_completion_enabled"] is False
    assert len(result["freeze_digest"]) == 64
    assert {(pack["debug"], pack["holdout"]) for pack in result["packs"]} == {(8, 4)}


def test_frozen_material_edit_is_rejected_even_if_case_data_is_unchanged(tmp_path):
    shutil.copytree(ROOT / "materials" / "v3", tmp_path / "materials" / "v3")
    shutil.copytree(ROOT / "evals" / "v3", tmp_path / "evals" / "v3")
    material = tmp_path / "materials" / "v3" / "english" / "teaching.md"
    material.write_text(material.read_text(encoding="utf-8") + "\nChanged later.\n", encoding="utf-8")
    with pytest.raises(ValueError, match="material hash"):
        check_fixtures(tmp_path)


@pytest.mark.parametrize("subject", ["python", "mathematics", "english"])
def test_content_error_candidate_is_structurally_valid_without_becoming_gold(subject):
    case = load_case(subject, 5)
    candidate = QuestionResult.model_validate(case["candidate_question_result"])
    assert candidate.score == candidate.max_score == 10.0
    assert case["human_expectation"]["grading_status"] == "needs_review"
    assert case["human_expectation"]["expected_passed"] is False
    assert case["human_expectation"]["review_status"] == "pending_user_review"


@pytest.mark.parametrize("subject", ["python", "mathematics", "english"])
def test_high_total_cannot_hide_failed_required_objective(subject):
    case = load_case(subject, 11)
    expected = case["human_expectation"]
    maximum = sum(question["max_score"] for question in case["questions"])
    awarded = sum(bounds[0] for bounds in expected["question_score_ranges"].values())
    assert awarded / maximum == 0.9
    assert expected["required_objective_outcomes"] == {"o1": True, "o2": False}
    assert expected["expected_passed"] is False


def test_reference_and_private_section_must_actually_exist():
    case = copy.deepcopy(load_case("python", 1))
    case["questions"][0]["source_refs"][0]["section_id"] = "fabricated-section"
    with pytest.raises(ValueError, match="section does not exist"):
        validate_case(case, sections("python"))


def test_fabricated_evidence_cannot_become_allowed_evidence():
    case = copy.deepcopy(load_case("mathematics", 1))
    case["human_expectation"]["allowed_evidence_ids"].append("answer:invented")
    with pytest.raises(ValueError, match="fabricated"):
        validate_case(case, sections("mathematics"))


def test_agent_draft_cannot_claim_a_human_approval():
    case = copy.deepcopy(load_case("english", 1))
    case["human_expectation"].update({"review_status": "approved", "reviewed_by": "agent"})
    with pytest.raises(ValueError, match="impersonate human approval"):
        validate_case(case, sections("english"))


def test_numeric_case_uses_actual_v3_numeric_rule_contract_and_exact_reference():
    case = load_case("mathematics", 9)
    question = case["questions"][0]
    assert NumericRules.model_validate(question["numeric_rules"]).expected == 5.0
    assert verify_reference(question) == "linear_equation_exact"
    wrong = copy.deepcopy(question)
    wrong["reference_verification"]["reference_numeric"] = "6"
    with pytest.raises(ValueError, match="Incorrect reference"):
        verify_reference(wrong)


def test_reference_checker_rejects_executable_expression_and_wrong_static_endpoint():
    equation = copy.deepcopy(load_case("mathematics", 1)["questions"][0])
    equation["reference_verification"]["a"] = "__import__('os')"
    with pytest.raises(ValueError, match="Unsafe reference"):
        verify_reference(equation)
    sequence = copy.deepcopy(load_case("python", 2)["questions"][0])
    sequence["reference_verification"]["reference_values"] = [1, 2, 3, 4, 5]
    with pytest.raises(ValueError, match="Incorrect static trace"):
        verify_reference(sequence)
