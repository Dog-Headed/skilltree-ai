"""Read-only Day 10 fixture checks. Never run a model, execute answers, or bless gold labels."""

from __future__ import annotations

import argparse
from collections import Counter
from fractions import Fraction
from hashlib import sha256
import json
import math
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parent
SUBJECTS = {"python", "mathematics", "english"}
SCENARIOS = {
    "correct", "partial", "critical_misconception", "missing_evidence",
    "legal_structure_content_error", "ambiguous_or_miskeyed_item", "answer_prompt_injection",
    "prerequisite_issue", "equivalent_correct_variant", "prerequisite_contrast",
    "required_objective_failure", "source_conflict",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def safe_path(root, relative):
    root = Path(root).resolve()
    path = (root / relative).resolve()
    require(root in path.parents, "Fixture path escapes its root")
    return path


def bounded_fraction(value):
    require(isinstance(value, str) and len(value) <= 32
            and re.fullmatch(r"-?\d+(?:/\d+|\.\d+)?", value), "Unsafe reference numeric literal")
    try:
        result = Fraction(value)
    except (ValueError, ZeroDivisionError) as exc:
        raise ValueError("Invalid reference fraction") from exc
    require(abs(result) <= 100000, "Reference numeric literal exceeds fixture bounds")
    return result


def small_integer(value):
    require(type(value) is int and abs(value) <= 10000, "Invalid static witness integer")
    return value


def verify_reference(question):
    """Check only a pre-authored finite witness; this is not a production evaluator."""
    check = question.get("reference_verification")
    if not check:
        return "manual_agent_content_check_only"
    method = check["method"]
    if method == "linear_equation_exact":
        a, b, c, d = [bounded_fraction(check[key]) for key in ("a", "b", "c", "d")]
        require(a != c, "Reference equation must have a unique solution")
        result = (d - b) / (a - c)
        require(result == bounded_fraction(check["reference_numeric"]), "Incorrect reference equation solution")
        require(a * result + b == c * result + d, "Reference does not satisfy original equation")
        if question["question_type"] == "numeric_scalar":
            rules = question["numeric_rules"]
            require(bounded_fraction(question["reference_answer"]) == result, "Numeric answer differs from witness")
            require(Fraction(str(rules["expected"])) == result, "Frozen numeric rule differs from witness")
            require(rules["unit"] is None and rules["allowed_units"] == []
                    and rules["abs_tolerance"] == rules["rel_tolerance"] == 0.0, "Unexpected numeric unit/tolerance")
    elif method == "trusted_static_trace":
        kind = check["trace_kind"]
        if kind == "range":
            start, stop, step = [small_integer(check[key]) for key in ("start", "stop", "step")]
            require(step != 0, "Zero step is invalid")
            values = range(start, stop, step)
            require(len(values) <= 1000, "Static witness is too large")
            result = list(values)
        elif kind == "elements":
            require(isinstance(check["values"], list) and len(check["values"]) <= 100, "Invalid element witness")
            result = [small_integer(value) for value in check["values"]]
        elif kind in {"conditional", "constant_guard"}:
            operators = {"==": lambda a, b: a == b, ">": lambda a, b: a > b,
                         ">=": lambda a, b: a >= b, "<": lambda a, b: a < b, "<=": lambda a, b: a <= b}
            require(check["operator"] in operators, "Unregistered static comparison")
            value = small_integer(check["value"] if kind == "conditional" else check["initial"])
            boundary = small_integer(check["boundary"])
            condition = operators[check["operator"]](value, boundary)
            if kind == "conditional":
                result = [check["true_label"] if condition else check["false_label"]]
            else:
                update = small_integer(check["update"])
                require(not condition or update == 0, "Unsupported static loop witness")
                result = ["non_terminating" if condition else "zero_iterations"]
        else:
            raise ValueError("Unregistered static trace kind")
        require(result == check["reference_values"], "Incorrect static trace reference")
    elif method == "english_rule_check":
        sentence = check["reference_form"]
        verb = check.get("verb", check.get("base_verb", check.get("past_verb")))
        rule = check["rule"]
        if rule == "affirmative_past":
            allowed_past = {"visited", "studied", "played", "walked", "went"}
            require(verb in allowed_past and re.search(r"\b" + re.escape(verb) + r"\b", sentence), "Missing reference past verb")
        elif rule == "did_negative_base":
            require(verb in {"go", "visit", "see", "play"}, "Unregistered fixture base verb")
            require(re.search(r"\b(?:did not|didn't)\s+" + re.escape(verb) + r"\b", sentence, re.I), "Invalid reference did-negative")
        elif rule == "did_question_base":
            require(verb in {"finish", "visit"}, "Unregistered fixture question verb")
            require(re.search(r"(?:^|[,.]\s*)Did\s+[A-Za-z]+\s+" + re.escape(verb) + r"\b", sentence), "Invalid reference Did-question")
        elif rule == "three_sentence_forms":
            require("visited" in sentence and "did not watch" in sentence and "Did you cook" in sentence,
                    "Missing reference sentence form")
        else:
            raise ValueError("Unregistered English fixture rule")
    elif method == "not_uniquely_specified":
        require(bool(check.get("reason")), "Ambiguous reference requires an explanation")
    else:
        raise ValueError("Unregistered reference verification method")
    return method


def validate_case(case, sections):
    require(case["split"] in {"debug", "holdout"}, "Invalid frozen split")
    expectation = case["human_expectation"]
    require(expectation["review_status"] == "pending_user_review" and expectation["authored_by"] == "assistant_draft"
            and expectation["reviewed_by"] is None and expectation["reviewed_at"] is None,
            "Draft expectations must not impersonate human approval")
    require(not case["execution_readiness"]["formal_completion_allowed_now"], "Preparation fixtures cannot enable formal completion")
    questions = case["questions"]
    question_ids = {question["question_id"] for question in questions}
    require(len(question_ids) == len(questions) and question_ids == set(case["student_answers"]), "Question/answer identities mismatch")
    objective_ids = {item["objective_id"] for item in case["learning_context"]["current_objectives"]}
    evidence_ids = set()
    for evidence in case["answer_evidence"]:
        answer = case["student_answers"][evidence["question_id"]]
        require(answer[evidence["start"]:evidence["end"]] == evidence["quote"] and evidence["quote"], "Unlocatable answer evidence")
        require(evidence["evidence_id"] not in evidence_ids, "Duplicate answer evidence")
        evidence_ids.add(evidence["evidence_id"])
    for history in case["available_history"]:
        require(history["student_answer"] and history["question"], "Incomplete history witness")
        require(history["evidence_id"] not in evidence_ids, "Duplicate history evidence")
        evidence_ids.add(history["evidence_id"])
    require(set(expectation["allowed_evidence_ids"]) == evidence_ids, "Expected evidence may not be fabricated")
    review_node = expectation.get("review_node_id")
    require(review_node is None or review_node in {node["node_id"] for node in case["learning_context"]["prerequisite_nodes"]}, "Invalid prerequisite review target")
    methods = []
    for question in questions:
        require(question["prompt"] and question["reference_answer"] and question["acceptable_answers"], "Incomplete question/reference/variants")
        require(set(question["objective_ids"]) <= objective_ids, "Question refers to unknown objective")
        maximum = question["max_score"]
        require(math.isfinite(maximum) and maximum > 0, "Invalid question score")
        if question["question_type"] == "text":
            require(question["evaluator_id"] == "text_rubric", "Wrong text evaluator")
            rubric = question["rubric"]
            require(rubric and len({item["criterion_id"] for item in rubric}) == len(rubric), "Invalid rubric identities")
            require(abs(sum(item["max_score"] for item in rubric) - maximum) < 1e-8, "Rubric total differs from question maximum")
            require(all(item["description"] and item["evidence_requirement"] and item["scoring_guidance"] for item in rubric), "Incomplete operational rubric")
        else:
            require(question["question_type"] == question["evaluator_id"] == "numeric_scalar" and not question["rubric"], "Unsupported fixture question type")
        for reference in question["source_refs"]:
            require((reference["document"], reference["section_id"]) in sections, "Reference section does not exist")
        bounds = expectation["question_score_ranges"].get(question["question_id"])
        if bounds:
            require(len(bounds) == 2 and all(math.isfinite(value) for value in bounds)
                    and 0 <= bounds[0] <= bounds[1] <= maximum, "Invalid expected score range")
        methods.append(verify_reference(question))
    if expectation["grading_status"] != "graded":
        require(not expectation["expected_passed"] and not expectation["question_score_ranges"], "Uncertain/invalid case cannot pretend to be a completed grade")
    require(not case["policy_assumptions"]["uncertain_or_invalid_counts_as_failed_round"], "System uncertainty is not student failure")
    if "source_conflict" in case["scenario_tags"]:
        require(case.get("context_anomalies") and not expectation["expected_passed"], "Missing explicit conflict witness")
    if "required_objective_failure" in case["scenario_tags"]:
        require(expectation["total_ratio_if_scored"] >= 0.8 and not expectation["expected_passed"]
                and False in expectation["required_objective_outcomes"].values(), "Missing high-total mandatory-goal guard scenario")
    return methods


def check_fixtures(root=ROOT):
    root = Path(root).resolve()
    # This command verifies the immutable Day10 dataset, not every later pack.
    # New topics retain their own manifests and independent evaluation protocol.
    manifests = [root / "materials" / "v3" / subject / "manifest.json" for subject in sorted(SUBJECTS)]
    require(all(path.is_file() for path in manifests), "Expected the three initial course packs")
    summaries = []
    digest_items = []
    for manifest_path in manifests:
        manifest = read_json(manifest_path)
        require(manifest["review_status"] == "pending_user_review" and manifest["authored_by"] == "assistant_draft"
                and manifest["agent_fact_checked"]["human_approval"] is False, "Course pack has unapproved human-approval claim")
        require(manifest["frozen_before_model_execution"]["real_model_runs"] == 0, "Day 10 must preserve untouched pre-run fixtures")
        require({document["visibility"] for document in manifest["documents"]} == {"teaching", "assessment_private"}, "Missing teaching/private separation")
        sections = set()
        for document in manifest["documents"]:
            path = safe_path(manifest_path.parent, document["filename"])
            require(sha256(path.read_bytes()).hexdigest() == document["content_hash"], "Frozen material hash mismatch")
            text = path.read_text(encoding="utf-8")
            require("expected_action" not in text and "expected_passed" not in text, "Gold decisions may not leak into material text")
            lines = text.splitlines()
            for section in document["sections"]:
                start, end = section["line_start"], section["line_end"]
                require(1 <= start <= end <= len(lines) and lines[start - 1] == "## " + section["heading"], "Unstable material section location")
                identity = document["filename"], section["section_id"]
                require(identity not in sections, "Duplicate material section")
                sections.add(identity)
            digest_items.append((path.relative_to(root).as_posix(), document["content_hash"]))
        case_paths = {path.resolve() for path in (root / "evals" / "v3" / manifest_path.parent.name / "cases").glob("*.json")}
        require(len(case_paths) == len(manifest["cases"]) == 12, "Each subject needs exactly 12 frozen cases")
        seen = set()
        splits = Counter()
        tags = set()
        methods = Counter()
        for entry in manifest["cases"]:
            path = safe_path(root, entry["path"])
            require(path in case_paths and path not in seen, "Case missing, duplicated, or in the wrong pack")
            seen.add(path)
            require(sha256(path.read_bytes()).hexdigest() == entry["content_hash"], "Frozen case hash mismatch")
            case = read_json(path)
            require(case["case_id"] == entry["case_id"] and case["split"] == entry["split"], "Frozen case identity/split mismatch")
            methods.update(validate_case(case, sections))
            splits[case["split"]] += 1
            tags.update(case["scenario_tags"])
            digest_items.append((path.relative_to(root).as_posix(), entry["content_hash"]))
        require(splits == {"debug": 8, "holdout": 4} and tags == SCENARIOS, "Incorrect split or scenario coverage")
        digest_items.append((manifest_path.relative_to(root).as_posix(), sha256(manifest_path.read_bytes()).hexdigest()))
        summaries.append({"subject": manifest["subject_label"], "cases": 12, "debug": 8, "holdout": 4,
                          "review_status": "pending_user_review", "reference_check_methods": dict(methods)})
    return {"fixture_version": "3.0.0-day10-1", "packs": summaries, "case_count": 36,
            "pending_human_review": 36, "real_model_runs": 0, "formal_completion_enabled": False,
            "freeze_digest": sha256(json.dumps(sorted(digest_items), ensure_ascii=False).encode()).hexdigest(),
            "meaning": "Deterministic fixture integrity and finite reference witnesses only; not model quality or human gold approval"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    print(json.dumps(check_fixtures(args.root), ensure_ascii=False, indent=2))
