from types import SimpleNamespace

import pytest

from app.services.learner_feedback import LearnerFeedback


@pytest.fixture
def feedback():
    nodes = [SimpleNamespace(id="setup_environment", title="搭建 Python 运行环境", objectives=[
        SimpleNamespace(id="obj_setup_environment_1", description="安装并配置编辑器与解释器"),
    ])]
    record = {"id": "assessment_current", "round_no": 2,
              "quiz": {"questions": [{"id": "q_r2_setup_env_03", "objective_id": "obj_setup_environment_1", "max_score": 5}]},
              "evaluation": {"question_results": [{"question_id": "q_r2_setup_env_03", "score": 4, "error_tags": ["missing_python_extension"]}]}}
    history = {"id": "assessment_previous", "round_no": 1,
               "quiz": {"questions": [{"id": "q_setup_env_02", "objective_id": "obj_setup_environment_1", "max_score": 5}]}}
    return LearnerFeedback(nodes, [record, history], record)


def test_current_and_historical_evidence_become_readable_question_references(feedback):
    text = feedback.text("assessment:assessment_current:q_r2_setup_env_03 说明当前遗漏；q_setup_env_02 的错误已修正。")
    assert "第1题的作答" in text and "第1轮的第1题" in text
    assert "assessment:" not in text and "q_setup" not in text


def test_preserves_python_examples_and_real_error_names(feedback):
    code = "```python\nq_unknown = 1\nprint(total_score)\n```"
    text = feedback.text("注意 SyntaxError 与 NameError；示例：" + code + "\n继续练习。")
    assert code in text and "SyntaxError" in text and "NameError" in text
    assert feedback.text("输出 print(q_r2_setup_env_03)，注意 print(total_score)。") == "输出 print(q_r2_setup_env_03)，注意 print(total_score)。"


def test_unknown_legacy_identifiers_do_not_return_as_unreadable_codes(feedback):
    text = feedback.text("obj_removed_2 尚需巩固，q_old_variant_05 的作答不完整。")
    assert "该学习目标" in text and "相关题目" in text
    assert "obj_removed" not in text and "q_old" not in text


def test_coded_weak_point_uses_known_learning_objective_instead(feedback):
    reason, weak_points = feedback.diagnosis({"weak_points": ["legacy_unknown_tag"], "recommended_action": "remediate", "reason": "需要补弱。"})
    assert weak_points == ["需要巩固：安装并配置编辑器与解释器"]


def test_audit_only_diagnosis_has_a_readable_action_fallback(feedback):
    reason, weak_points = feedback.diagnosis({"weak_points": [], "recommended_action": "collect_more_evidence", "reason": "工具调用达到上限，calls 为空。"})
    assert "追加测评" in reason and "调用" not in reason and not weak_points


def test_python_error_name_can_be_a_learning_weak_point(feedback):
    _, weak_points = feedback.diagnosis({"weak_points": ["NameError"], "reason": "需要识别具体报错。"})
    assert weak_points == ["NameError"]
