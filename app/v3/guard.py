"""Pure V3 progress decision: immutable facts and server rules outrank model advice."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from .capabilities import get_capability, is_evaluator_available
from .config import SERVER_LIMITS
from .contracts import (
    AssessmentQuiz, ContractModel, EvaluationPolicy, EvaluationResult, LearningProfile,
    ObjectivePolicy, SkillNode, Text, validate_evaluation_context,
)
from .diagnosis import DiagnosisDecision
from .evaluators import evaluate_numeric_scalar


class GuardDecision(ContractModel):
    passed: bool
    effective_action: Literal["advance", "remediate", "revisit_prerequisite", "collect_more_evidence", "assessment_review"]
    reasons: list[Text] = Field(min_length=1, max_length=100)


def _evidence_anchor(evidence):
    # Different IDs for the same physical answer excerpt do not make two facts.
    return (evidence.question_id, evidence.kind, evidence.start, evidence.end, evidence.quote,
            tuple(sorted(evidence.selected_option_ids)), evidence.numeric_value)


def _score_ratio(parts):
    """Normalize finite components before summing, avoiding overflow/NaN gates."""
    if not parts:
        return 0.0
    scale = max(maximum for _, maximum in parts)
    return sum(score / scale for score, _ in parts) / sum(maximum / scale for _, maximum in parts)


def decide_progress(*, quiz, evaluation, node, policy, profile, completed_node_ids,
                    diagnosis, answers) -> GuardDecision:
    quiz = AssessmentQuiz.model_validate(quiz)
    evaluation = EvaluationResult.model_validate(evaluation)
    node = SkillNode.model_validate(node)
    policy = EvaluationPolicy.model_validate(policy)
    profile = LearningProfile.model_validate(profile)
    diagnosis = DiagnosisDecision.model_validate(diagnosis)
    validate_evaluation_context(evaluation, quiz=quiz, answers=answers)
    if quiz.node_id != node.node_id:
        raise ValueError("守卫节点与冻结试卷不一致")
    if (diagnosis.project_id, diagnosis.node_id, diagnosis.assessment_id, diagnosis.snapshot) != (
            quiz.project_id, quiz.node_id, quiz.assessment_id, quiz.snapshot):
        raise ValueError("诊断身份或冻结版本不一致")
    if diagnosis.review_node_id is not None and diagnosis.review_node_id not in node.prerequisite_ids:
        raise ValueError("诊断指定非法先修回顾节点")
    if (policy.policy_id, policy.policy_version) != (quiz.snapshot.policy_id, quiz.snapshot.policy_version):
        raise ValueError("守卫策略不是冻结策略")
    if profile.profile_version != quiz.snapshot.profile_version:
        raise ValueError("学习档案不是本轮冻结版本")
    if policy.total_pass_threshold < SERVER_LIMITS.min_total_pass_threshold or any(
            rule.pass_threshold < SERVER_LIMITS.min_objective_pass_threshold for rule in policy.objective_rules):
        raise ValueError("策略不能降低服务端通过门槛")
    if policy.numeric_abs_tolerance > SERVER_LIMITS.max_numeric_absolute_tolerance or policy.numeric_rel_tolerance > SERVER_LIMITS.max_numeric_relative_tolerance:
        raise ValueError("数值策略容差超过服务端上限")
    if not isinstance(completed_node_ids, list) or any(not isinstance(identity, str) for identity in completed_node_ids):
        raise ValueError("完成节点必须来自服务端身份列表")
    questions = {question.question_id: question for question in quiz.questions}
    results = {item.question_id: item for item in evaluation.question_results}
    objectives = {item.objective_id: item for item in node.objectives}
    if any(not set(question.objective_ids) <= objectives.keys() for question in quiz.questions):
        raise ValueError("冻结试卷引用未知节点目标")
    frozen_evaluators = {(item.evaluator_id, item.evaluator_version) for item in quiz.snapshot.evaluator_manifest}
    frozen_sources = {(item.source_id, item.source_version) for item in quiz.snapshot.source_manifest}
    policy_evaluators = {(item.evaluator_id, item.evaluator_version) for item in policy.evaluators}
    for question in quiz.questions:
        reference = question.evaluator_id, question.evaluator_version
        if reference not in frozen_evaluators or reference not in policy_evaluators or question.question_type not in policy.allowed_question_types:
            raise ValueError("题型或评价器不属于冻结策略与清单")
        if any((citation.source_id, citation.source_version) not in frozen_sources for citation in question.source_citations):
            raise ValueError("题目引用了冻结清单之外的资料版本")
        if question.question_type == "numeric_scalar" and (
                question.numeric_rules.abs_tolerance > policy.numeric_abs_tolerance or
                question.numeric_rules.rel_tolerance > policy.numeric_rel_tolerance):
            raise ValueError("数值题容差超过冻结策略")

    reasons = []
    if profile.learning_mode != "formal":
        reasons.append("探索学习不能产生正式通过或依赖解锁记录。")
    if evaluation.grading_status != "graded":
        return GuardDecision(passed=False, effective_action="assessment_review", reasons=reasons + [
            "本轮评价状态为" + evaluation.grading_status + "，不得参与正式推进或计作有效失败轮次。",
            *evaluation.uncertainty_reasons])
    if not set(node.prerequisite_ids) <= set(completed_node_ids):
        reasons.append("当前节点先修尚未完成。")
    current_evidence = {item.evidence_id: item for item in evaluation.evidence}
    if diagnosis.action == "advance" and not set(diagnosis.evidence_ids) <= current_evidence.keys():
        reasons.append("推进建议引用了当前评价之外的证据，不能用历史替代本轮证明。")
    if diagnosis.action == "advance" and not set(diagnosis.evidence_ids) & current_evidence.keys():
        reasons.append("推进建议缺少当前评价的作答证据。")
    for question in quiz.questions:
        if not is_evaluator_available(question.evaluator_id, question.evaluator_version):
            reasons.append("冻结评价器尚未可运行：" + question.evaluator_id + "@" + question.evaluator_version)
        result = results[question.question_id]
        if question.question_type in {"single_choice", "multiple_choice"}:
            answer = answers[question.question_id]
            selected = [answer] if isinstance(answer, str) else answer
            correct = [question.answer_key] if isinstance(question.answer_key, str) else question.answer_key
            expected_score = question.max_score if set(selected) == set(correct) else 0.0
            if result.score != expected_score:
                reasons.append("选择题结果与冻结答案键的确定性判断不一致：" + question.question_id)
        elif question.question_type == "numeric_scalar":
            # A persisted/cached score is not a substitute for the actual
            # numeric answer. Recompute without HTTP or executing expressions.
            numeric = evaluate_numeric_scalar(question, answers[question.question_id])
            if numeric.grading_status != "graded" or numeric.result is None:
                raise ValueError("数值评价无法由冻结规则和实际作答重现，需要系统复核")
            if result.score != numeric.result.score:
                raise ValueError("数值评分与冻结规则的确定性判断不一致")
            expected_value = numeric.evidence[0].numeric_value
            if any(current_evidence[identity].numeric_value != expected_value for identity in result.evidence_ids):
                raise ValueError("数值证据与实际作答的受限解析结果不一致")
        frozen_criteria = {item.criterion_id: item for item in question.rubric}
        for criterion in result.criterion_results:
            if criterion.severity in {*policy.critical_severities, "critical"}:
                reasons.append("存在阻断性的关键错误：" + criterion.criterion_id)
            if getattr(frozen_criteria[criterion.criterion_id], "critical", False) and criterion.score < criterion.max_score - 1e-9:
                reasons.append("冻结关键标准未全部满足：" + criterion.criterion_id)

    rules = {rule.objective_id: rule for rule in policy.objective_rules}
    objective_ratios = {}
    objective_weights = {}
    missing_evidence = False
    for identity, objective in objectives.items():
        rule = rules.get(identity) or ObjectivePolicy(objective_id=identity, required=objective.required,
                                                      evidence_kinds=list(objective.evidence_requirement))
        required = objective.required or rule.required
        relevant = [question for question in quiz.questions if identity in question.objective_ids]
        contributions = []
        references = set()
        known_criteria = {criterion.criterion_id for question in relevant for criterion in question.rubric}
        if not set(objective.criterion_ids) <= known_criteria:
            raise ValueError("节点目标引用不存在或不属于该目标的冻结标准")
        for question in relevant:
            result = results[question.question_id]
            if objective.criterion_ids:
                selected = [criterion for criterion in result.criterion_results if criterion.criterion_id in objective.criterion_ids]
                contributions.extend((criterion.score, criterion.max_score) for criterion in selected)
                references.update(identity for criterion in selected for identity in criterion.evidence_ids)
            else:
                # A single aggregate mark cannot prove separate goals inside a
                # multi-goal text answer without a frozen criterion mapping.
                if len(question.objective_ids) > 1 and question.rubric:
                    if required:
                        reasons.append("多目标文字题缺少按目标冻结的分项映射：" + identity)
                    continue
                contributions.append((result.score, result.max_score))
                references.update(result.evidence_ids)
        ratio = _score_ratio(contributions)
        objective_ratios[identity] = ratio
        if relevant or required:
            objective_weights[identity] = rule.weight
        for capability_id in objective.required_capability_ids:
            capability = get_capability(capability_id)
            if required and (capability is None or capability.availability != "available"):
                reasons.append("必要目标所需能力尚不可用：" + capability_id)
        evidence = [current_evidence[reference] for reference in references]
        distinct = {_evidence_anchor(item) for item in evidence}
        kinds = {item.kind for item in evidence}
        expected_kinds = set(rule.evidence_kinds) | set(objective.evidence_requirement)
        lacks = len(relevant) < rule.min_items or len(distinct) < rule.min_evidence or not expected_kinds <= kinds
        if required and lacks:
            missing_evidence = True
            reasons.append("必要目标题目或规定证据不足：" + identity)
        if required and ratio + 1e-9 < rule.pass_threshold:
            reasons.append("必要目标未达标：" + identity + "（服务端重算" + format(ratio, ".3f") + "）")
    for item in evaluation.objective_results:
        related = [question for question in quiz.questions if item.objective_id in question.objective_ids]
        known = {criterion.criterion_id for question in related for criterion in question.rubric}
        if not set(item.criterion_ids) <= known:
            raise ValueError("评价目标声称使用了不存在的分项标准")
    total_ratio = _score_ratio([(result.score, result.max_score) for result in evaluation.question_results])
    if total_ratio + 1e-9 < policy.total_pass_threshold:
        reasons.append("总分未达标（服务端重算" + format(total_ratio, ".3f") + "）。")
    # Explicit policy weights are also enforced; a model cannot replace these
    # with its own objective_results.score_ratio field.
    if objective_weights:
        scale = max(objective_weights.values())
        weighted = sum(objective_ratios[identity] * (weight / scale) for identity, weight in objective_weights.items()) / sum(weight / scale for weight in objective_weights.values())
        if weighted + 1e-9 < policy.total_pass_threshold:
            reasons.append("策略加权目标总分未达标（服务端重算" + format(weighted, ".3f") + "）。")
    if diagnosis.action != "advance":
        reasons.append("诊断建议继续学习或补充证据，当前不形成正式通过。")
    if not reasons:
        return GuardDecision(passed=True, effective_action="advance", reasons=["当前有效评价满足冻结策略、全部必要目标、真实证据及先修约束。"])
    if missing_evidence:
        effective_action = "collect_more_evidence"
    elif diagnosis.action == "advance":
        effective_action = "remediate"
    else:
        effective_action = diagnosis.action
    return GuardDecision(passed=False, effective_action=effective_action, reasons=reasons)
