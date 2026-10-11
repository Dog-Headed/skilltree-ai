"""工具测试用的真实 SQLite 数据，不写入用户的业务数据库。"""
from app.db.repository import LearningRepository


def create_tool_project(repo, project_id="demo_project"):
    tree = []
    for node_id, prerequisites in (
        ("python_basics", []),
        ("python_variables", ["python_basics"]),
        ("python_for_loops", ["python_variables"]),
        ("python_lists", ["python_variables"]),
    ):
        tree.append({
            "id": node_id, "title": node_id, "description": "测试节点",
            "objectives": [{"id": f"{node_id}_obj", "description": "测试目标"}],
            "prerequisite_ids": prerequisites, "difficulty": "easy", "estimated_minutes": 20,
        })
    repo.create_project_with_tree(project_id=project_id, goal="工具验收", tree=tree)


def save_tool_assessment(repo: LearningRepository, assessment_id, *,
                         project_id="demo_project", node_id="python_variables", round_no=1):
    repo.create_prepared_assessment(
        assessment_id=assessment_id, project_id=project_id, node_id=node_id, round_no=round_no,
    )
    quiz = {
        "assessment_id": assessment_id, "node_id": node_id,
        "questions": [
            {"id": question_id, "type": "short_answer", "objective_id": f"{node_id}_obj",
             "prompt": f"测试题 {question_id}", "options": None,
             "answer_key": "私有参考答案", "rubric": "私有评分规则", "max_score": maximum}
            for question_id, maximum in (("q1", 10.0), ("q2", 30.0))
        ],
    }
    repo.save_quiz_if_absent(assessment_id=assessment_id, quiz=quiz)
    repo.save_answers_if_absent(assessment_id=assessment_id, answers={"q1": "作答" * 100, "q2": "另一个作答"})
    repo.save_evaluation_if_absent(assessment_id=assessment_id, evaluation={
        "assessment_id": assessment_id,
        "question_results": [
            {"question_id": "q1", "score": 0.0, "error_tags": ["assignment_confusion"],
             "evidence": "混淆赋值与比较", "feedback": "复习赋值"},
            {"question_id": "q2", "score": 15.0, "error_tags": ["assignment_confusion", "incorrect_output"],
             "evidence": "输出判断部分正确", "feedback": "追踪当前变量的值"},
        ],
    })
    repo.save_diagnosis_if_absent(assessment_id=assessment_id, diagnosis={
        "weak_points": ["变量与赋值"], "evidence_ids": [f"assessment:{assessment_id}:q1"],
        "recommended_action": "remediate", "reason": "需要补弱", "review_node_id": None,
    })
    return repo.get_assessment(assessment_id)
