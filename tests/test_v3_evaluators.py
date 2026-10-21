from copy import deepcopy
from hashlib import sha256

import pytest

from app.services.llm import ModelCallBudget, ModelOutputValidationError, ModelRequestFailedError
from app.v3.contracts import AssessmentQuiz, EvaluationPolicy, FrozenSnapshot, SkillNode
from app.v3.evaluators import evaluate_numeric_scalar, evaluate_text_rubric


class FakeModel:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def with_structured_output(self, schema, *, method):
        assert method == "json_mode"
        return self

    def invoke(self, messages):
        self.calls.append(messages)
        response = self.responses.pop(0)
        if isinstance(response, Exception): raise response
        return deepcopy(response)


def setup(types=("text",)):
    mapping = {"text": ("text_rubric", "text_excerpt"), "numeric_scalar": ("numeric_scalar", "numeric_result"), "single_choice": ("choice_exact", "choice"), "multiple_choice": ("choice_exact", "choice")}
    content = "变量保存值。长度以米或厘米表示。Yesterday I walked home. 过去事件用一般过去时。"
    digest = sha256(content.encode()).hexdigest()
    node = SkillNode(node_id="node", title="资料单元", description="选择、求值和解释", estimated_minutes=20, objectives=[{
        "objective_id": f"objective_{index}", "observable_outcome": f"解释或选择资料内容 {index}",
        "required_capability_ids": [mapping[kind][0]], "evidence_requirement": [mapping[kind][1]],
        "source_chunk_ids": ["chunk"], "criterion_ids": ["r1", "r2"] if kind == "text" else [],
    } for index, kind in enumerate(types)])
    evaluators = [{"evaluator_id": key, "evaluator_version": "1.0.0"} for key in dict.fromkeys(mapping[kind][0] for kind in types)]
    policy = EvaluationPolicy(policy_id="policy", policy_version="1.0.0", allowed_question_types=list(dict.fromkeys(types)), evaluators=evaluators,
        numeric_abs_tolerance=0.01 if "numeric_scalar" in types else 0.0,
        objective_rules=[{"objective_id": f"objective_{index}", "evidence_kinds": [mapping[kind][1]]} for index, kind in enumerate(types)])
    snapshot = FrozenSnapshot(profile_version=1, plan_version=1, policy_id=policy.policy_id, policy_version=policy.policy_version,
        source_manifest=[{"source_id": "source", "source_version": 1, "content_hash": digest}], evaluator_manifest=evaluators)
    questions, answers, contexts = [], {}, {}
    for index, kind in enumerate(types):
        question = {"question_id": f"q{index}", "objective_ids": [f"objective_{index}"], "question_type": kind,
            "prompt": f"根据资料完成第 {index} 题：{kind}", "max_score": 10.0, "evaluator_id": mapping[kind][0], "evaluator_version": "1.0.0",
            "source_citations": [{"source_id": "source", "source_version": 1, "chunk_id": "chunk"}]}
        if kind == "text":
            question.update(answer_key="Yesterday I walked home.", rubric=[{"criterion_id": "r1", "description": "使用过去时", "max_score": 5.0}, {"criterion_id": "r2", "description": "句子意思符合题意", "max_score": 5.0}])
            answers[f"q{index}"] = "Yesterday I walked home."
        elif kind == "numeric_scalar":
            question["numeric_rules"] = {"expected": 2.0, "abs_tolerance": 0.01}
            answers[f"q{index}"] = "2"
        else:
            question.update(options=[{"option_id": "a", "text": "变量保存值"}, {"option_id": "b", "text": "变量不保存值"}], answer_key="a" if kind == "single_choice" else ["a"])
            answers[f"q{index}"] = "a" if kind == "single_choice" else ["a"]
        questions.append(question)
        contexts[f"objective_{index}"] = {"project_id": "project", "node_id": "node", "objective_id": f"objective_{index}", "purpose": "assessment", "blocks": [{
            "citation": {"source_id": "source", "source_version": 1, "chunk_id": "chunk", "visibility": "teaching"},
            "content": content, "content_hash": digest, "source_content_hash": digest}]}
    quiz = AssessmentQuiz(project_id="project", node_id="node", assessment_id="assessment", snapshot=snapshot, questions=questions)
    return quiz, answers, node, policy, contexts


def text_batch(quiz, answers):
    return {"project_id": quiz.project_id, "node_id": quiz.node_id, "assessment_id": quiz.assessment_id, "snapshot": quiz.snapshot.model_dump(),
        "grading_status": "graded", "questions": [{"question_id": question.question_id, "evaluator_id": "text_rubric", "evaluator_version": "1.0.0",
        "max_score": question.max_score, "criteria": [{"criterion_id": criterion.criterion_id, "score": criterion.max_score,
        "max_score": criterion.max_score, "anchors": [{"quote": answers[question.question_id], "start": 0, "end": len(answers[question.question_id])}]} for criterion in question.rubric],
        "feedback": "作答符合冻结量规。"} for question in quiz.questions if question.question_type == "text"]}


@pytest.mark.parametrize("answer,expected_score", [("2", 10.0), ("+2.0", 10.0), (" 2e0 ", 10.0), ("2.009", 10.0), ("2.02", 0.0), ("-2", 0.0)])
def test_numeric_grammar_and_frozen_tolerance_are_deterministic(answer, expected_score):
    quiz, *_ = setup(("numeric_scalar",))
    result = evaluate_numeric_scalar(quiz.questions[0], answer)
    assert result.grading_status == "graded" and result.result.score == expected_score
    assert result.evidence[0].quote == answer


@pytest.mark.parametrize("answer", ["NaN", "Infinity", "inf", "1e9999", "1e-9999", "1+1", "2/1", "__import__('os')", "2 unknown", "2,0", "", True])
def test_unparseable_or_nonfinite_numeric_answer_needs_review_without_zero_score(answer):
    quiz, *_ = setup(("numeric_scalar",))
    result = evaluate_numeric_scalar(quiz.questions[0], answer)
    assert result.grading_status == "needs_review"
    assert result.result is None and result.evidence == []


def test_frozen_unit_whitelist_and_trusted_conversions():
    quiz, *_ = setup(("numeric_scalar",))
    question = quiz.questions[0].model_dump()
    question["numeric_rules"] = {"expected": 2.0, "unit": "m", "allowed_units": ["m", "cm"], "abs_tolerance": 0.0}
    assert evaluate_numeric_scalar(question, "200 cm").result.score == 10.0
    assert evaluate_numeric_scalar(question, "2 m").result.score == 10.0
    assert evaluate_numeric_scalar(question, "2000 mm").grading_status == "needs_review"
    assert evaluate_numeric_scalar(question, "2").grading_status == "needs_review"
    question["numeric_rules"]["allowed_units"].append("s")
    assert evaluate_numeric_scalar(question, "2 s").grading_status == "invalid_item"


def test_unknown_frozen_unit_is_invalid_item_not_student_failure():
    quiz, *_ = setup(("numeric_scalar",))
    question = quiz.questions[0].model_dump(); question["numeric_rules"] = {"expected": 2.0, "unit": "arbitrary", "allowed_units": ["arbitrary"]}
    result = evaluate_numeric_scalar(question, "2 arbitrary")
    assert result.grading_status == "invalid_item" and result.result is None


def test_text_batch_checks_real_answer_anchors_and_server_sums_scores():
    quiz, answers, *_ = setup()
    batch = text_batch(quiz, answers); batch["questions"][0]["criteria"][0]["score"] = 2.0
    model = FakeModel(batch)
    result = evaluate_text_rubric(quiz=quiz, answers=answers, llm=model)
    assert result.results[0].score == 7.0 and len(model.calls) == 1
    assert len(result.evidence) == 1  # One repeated excerpt is not two pieces of evidence.
    assert result.evidence[0].quote == answers["q0"]


@pytest.mark.parametrize("defect", ["assessment", "snapshot", "missing_question", "duplicate_question", "score", "criterion", "max_score", "quote", "offset", "objective_ratio"])
def test_text_output_errors_share_one_repair(defect):
    quiz, answers, *_ = setup()
    valid = text_batch(quiz, answers); bad = deepcopy(valid)
    item = bad["questions"][0]; criterion = item["criteria"][0]
    if defect == "assessment": bad["assessment_id"] = "forged"
    elif defect == "snapshot": bad["snapshot"]["profile_version"] = 9
    elif defect == "missing_question": bad["questions"] = []
    elif defect == "duplicate_question": bad["questions"].append(deepcopy(item))
    elif defect == "score": criterion["score"] = float("inf")
    elif defect == "criterion": criterion["criterion_id"] = "ghost"
    elif defect == "max_score": criterion["max_score"] = 999.0
    elif defect == "quote": criterion["anchors"][0]["quote"] = "fabricated"
    elif defect == "offset": criterion["anchors"][0]["end"] = 999
    elif defect == "objective_ratio": bad["objective_results"] = [{"objective_id": "forged", "score_ratio": 1.0}]
    model = FakeModel(bad, valid)
    budget = ModelCallBudget()
    assert evaluate_text_rubric(quiz=quiz, answers=answers, llm=model, budget=budget).grading_status == "graded"
    assert (budget.request_count, budget.output_repair_count) == (2, 1)


def test_repeated_forged_evidence_stops_and_returns_no_evaluation():
    quiz, answers, *_ = setup(); bad = text_batch(quiz, answers)
    bad["questions"][0]["criteria"][0]["anchors"][0]["quote"] = "not in answer"
    model = FakeModel(bad, bad, text_batch(quiz, answers))
    with pytest.raises(ModelOutputValidationError): evaluate_text_rubric(quiz=quiz, answers=answers, llm=model)
    assert len(model.calls) == 2


def test_text_network_and_output_errors_share_three_requests():
    quiz, answers, *_ = setup(); valid = text_batch(quiz, answers); bad = deepcopy(valid); bad["questions"] = []
    model = FakeModel(TimeoutError(), bad, valid); budget = ModelCallBudget()
    assert evaluate_text_rubric(quiz=quiz, answers=answers, llm=model, budget=budget).grading_status == "graded"
    assert (budget.request_count, budget.network_retry_count, budget.output_repair_count) == (3, 1, 1)


@pytest.mark.parametrize("status", ["needs_review", "invalid_item"])
def test_text_can_report_uncertainty_or_invalid_item_without_faking_scores(status):
    quiz, answers, *_ = setup(); batch = text_batch(quiz, answers)
    batch.update(grading_status=status, questions=[], uncertainty_reasons=["资料冲突，无法确定唯一评价依据。"])
    result = evaluate_text_rubric(quiz=quiz, answers=answers, llm=FakeModel(batch))
    assert result.grading_status == status and result.results == [] and result.reasons


def test_blank_text_answer_produces_missing_evidence_without_model_call():
    quiz, answers, *_ = setup(); answers["q0"] = ""
    model = FakeModel()
    result = evaluate_text_rubric(quiz=quiz, answers=answers, llm=model)
    assert result.grading_status == "needs_review" and model.calls == []


def test_critical_frozen_criterion_cannot_be_downgraded_by_model():
    quiz, answers, *_ = setup(); raw = quiz.model_dump()
    raw["questions"][0]["rubric"][0]["critical"] = True
    quiz = AssessmentQuiz.model_validate(raw)
    batch = text_batch(quiz, answers); batch["questions"][0]["criteria"][0].update(score=4.0, severity="minor")
    result = evaluate_text_rubric(quiz=quiz, answers=answers, llm=FakeModel(batch))
    assert result.results[0].criterion_results[0].severity == "critical"
