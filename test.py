from app.agents.planner import planner_node
from app.agents.tutor import tutor_node
from app.agents.assessment import (
    assessment_generate_node,
    assessment_grade_node,
)
from app.agents.diagnosis import diagnosis_node


def print_state(title, state):
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)
    print(state)


state = {
    "goal": "学习 Python"
}

print_state("初始 State", state)

state.update(planner_node(state))
print_state("Planner 执行后", state)

state.update(tutor_node(state))
print_state("Tutor 执行后", state)

state.update(assessment_generate_node(state))
print_state("Assessment 出题后", state)

state["answers"] = {
    "q1": "我不知道"
}
print_state("用户提交答案后", state)

state.update(assessment_grade_node(state))
print_state("Assessment 评分后", state)

state.update(diagnosis_node(state))
print_state("Diagnosis 诊断后", state)