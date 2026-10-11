"""真正退出进程后验证 pause；所有模型使用固定替身。"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import app.agents.assessment as assessment
import app.agents.diagnosis as diagnosis
import app.agents.planner as planner
import app.agents.tutor as tutor
from app.models.schemas import AssessmentQuiz, DiagnosisResult, ShortAnswerGrade, TreePlan
from app.services.learning_session import open_learning_session

phase, directory = sys.argv[1:]
directory = Path(directory)

def record(name):
    with (directory / "calls.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"phase": phase, "name": name}) + "\n")

def forbidden(*args, **kwargs):
    raise AssertionError("此恢复阶段不能调用模型")

def fake_plan(goal):
    record("planner")
    return TreePlan.model_validate({"nodes": [{
        "id": f"node_{i}", "title": "变量", "description": "赋值", "difficulty": "beginner",
        "estimated_minutes": 20, "objectives": [{"id": f"obj_{i}", "description": "赋值"}],
        "prerequisite_ids": [] if i == 0 else [f"node_{i-1}"],
    } for i in range(8)]})

def fake_tutor(state, node):
    record("tutor")
    return "变量教学"

def fake_quiz(node, assessment_id, *, retest_context=None):
    record("quiz")
    number = len((retest_context or {}).get("previous_questions", [])) + 1
    return AssessmentQuiz.model_validate({"assessment_id": assessment_id, "node_id": node.id, "questions": [{
        "id": "q1", "type": "short_answer", "objective_id": node.objectives[0].id,
        "prompt": f"解释赋值，第{number}套", "answer_key": "赋值", "rubric": "正确说明", "max_score": 100.0,
    }]})

def fake_grade(question, answer):
    record("grade")
    return ShortAnswerGrade(score=50.0, evidence="混淆赋值", feedback="补弱", error_tags=[])

def fake_diagnosis(state):
    record("diagnosis")
    return DiagnosisResult(weak_points=["赋值"], evidence_ids=[f"assessment:{state['assessment_id']}:q1"],
                           recommended_action="remediate", reason="只有50分")

for module in (planner, tutor, assessment, diagnosis):
    module.get_llm = forbidden
planner.generate_plan = fake_plan if phase == "begin" else forbidden
tutor.generate_tutor_content = fake_tutor if phase in {"begin", "extend"} else forbidden
assessment.generate_quiz = fake_quiz if phase == "begin" else forbidden
assessment.grade_short_answer = fake_grade if phase == "begin" else forbidden
diagnosis.run_real_diagnosis = fake_diagnosis if phase == "begin" else forbidden

with open_learning_session("day7-pause", learning_db_path=directory / "business.sqlite",
                           checkpoint_db_path=directory / "checkpoint.sqlite") as session:
    if phase == "begin":
        session.start("变量")
        for _ in range(3):
            session.resume({"action": "start_quiz"})
            session.resume({"action": "submit_answer", "answers": {"q1": "错误"}})
    elif phase in {"rest", "extend"}:
        state = session.restore()
        session.resume({"action": "rest" if phase == "rest" else "retry_3",
                        "pending_input_id": state["pending_input_id"]})
    elif phase != "inspect":
        raise ValueError(phase)
    snapshot = session.snapshot()
    print(json.dumps({"next": snapshot.next, "state": snapshot.values,
                      "interrupts": [item.value for item in snapshot.interrupts]}, default=str))
