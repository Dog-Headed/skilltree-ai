from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt
from app.state import LearningState
from app.agents.planner import planner_node
from app.agents.tutor import tutor_node
from app.agents.diagnosis import diagnosis_node
from langgraph.checkpoint.memory import InMemorySaver
from app.agents.assessment import (
    assessment_generate_node,
    assessment_grade_node,
    build_public_quiz,
)
# =========================
# 四个 Diagnosis 分支节点
# =========================


def advance_node(state: LearningState):
    return {
        "branch_result": "advance：进入下一个学习节点"
    }


def remediate_node(
    state: LearningState,
):
    return {
        "branch_result": (
            "remediate：返回 Tutor 进行补弱"
        ),
        "lesson_mode": "remediate",
    }


def collect_more_evidence_node(state: LearningState):
    return {
        "branch_result": "collect_more_evidence：需要追加测评"
    }


def revisit_prerequisite_node(state: LearningState):
    return {
        "branch_result": "revisit_prerequisite：需要复习前置知识",
        "lesson_mode": "revisit",
    }


# =========================
# Conditional Edge 路由函数
# =========================

def route_after_diagnosis(state: LearningState):
    diagnosis = state.get("diagnosis", {})
    action = diagnosis.get("recommended_action")

    if action == "advance":
        if can_advance(state):
            return "advance"

        return "collect_more_evidence"

    if action == "remediate":
        return "remediate"

    if action == "collect_more_evidence":
        return "collect_more_evidence"

    if action == "revisit_prerequisite":
        return "revisit_prerequisite"

    # 非法 action 不允许默认为 advance
    return "invalid"


# =========================
# 非法行动节点
# =========================

def invalid_action_node(state: LearningState):
    return {
        "branch_result": "invalid：Diagnosis 返回了非法行动"
    }


def wait_learning_node(state: LearningState):
    user_event = interrupt(
        {
            "type": "wait_learning",
            "message": "请选择：继续提问 or 开始测验",
            "options": ["ask", "start_quiz"],
        }
    )

    # 防止 resume 传入字符串、数字、列表等非法类型
    if not isinstance(user_event, dict):
        return {
            "user_event": {
                "action": "invalid",
                "reason": "学习阶段输入必须是字典"
            }
        }

    return {
        "user_event": user_event
    }


def wait_answer_node(
    state: LearningState,
):
    public_quiz = build_public_quiz(
        state["quiz"]
    )

    user_event = interrupt(
        {
            "type": "wait_answer",
            "message": state.get("answer_error") or "请提交测验答案",
            "quiz": public_quiz,
        }
    )

    if not isinstance(user_event, dict):
        return {
            "user_event": {
                "action": "invalid",
                "reason": "答题阶段输入必须是字典",
            },
            "answer_error": "",
        }

    submitted_answers = user_event.get("answers")
    updates = {"user_event": user_event, "answer_error": ""}
    if user_event.get("action") == "submit_answer" and isinstance(submitted_answers, dict):
        # 同一轮允许分次补交；新试卷会在出题节点清空旧答案。
        answers = {**state.get("answers", {}), **submitted_answers}
        updates["user_event"] = {**user_event, "answers": answers}
        question_ids = {question["id"] for question in state["quiz"]["questions"]}
        updates["answers"] = {
            question_id: answer
            for question_id, answer in answers.items()
            if question_id in question_ids
        }

    return updates


def answer_submission_error(state: LearningState) -> str | None:
    user_event = state.get("user_event")
    if not isinstance(user_event, dict) or user_event.get("action") != "submit_answer":
        return "请使用 submit_answer 提交测验答案。"

    answers = user_event.get("answers")
    if not isinstance(answers, dict):
        return "答案必须是按题目 ID 填写的字典。"

    questions = state["quiz"]["questions"]
    question_ids = {question["id"] for question in questions}
    if set(answers) - question_ids:
        return "答案包含不属于当前试卷的题目 ID，请检查后重新提交。"

    missing = []
    for question in questions:
        answer = answers.get(question["id"])
        if question["type"] == "multiple_choice":
            valid = (
                isinstance(answer, list)
                and bool(answer)
                and all(isinstance(item, str) and item.strip() for item in answer)
            )
        else:
            valid = isinstance(answer, str) and bool(answer.strip())
        if not valid:
            missing.append(question["id"])

    if missing:
        return f"以下题目缺少有效答案：{', '.join(missing)}。请补交这些题目的答案。"

    return None


def route_after_learning(state: LearningState):
    user_event = state.get("user_event")

    if not isinstance(user_event, dict):
        return "invalid"

    action = user_event.get("action")

    if action == "ask":
        return "ask"

    if action == "start_quiz":
        return "start_quiz"

    return "invalid"


def route_after_answer(state: LearningState):
    if answer_submission_error(state) is None:
        return "submit_answer"

    return "invalid"


def invalid_answer_event_node(state: LearningState):
    return {
        "branch_result": "invalid_answer_event：未提交有效答案",
        "answer_error": answer_submission_error(state),
    }


def invalid_learning_event_node(state: LearningState):
    return {
        "branch_result": "invalid_learning_event：用户操作非法"
    }
def can_advance(state: LearningState) -> bool:
    quiz = state.get("quiz", {})
    evaluation = state.get("evaluation", {})
    score_summary = state.get(
        "score_summary",
        {},
    )

    questions = quiz.get("questions", [])
    question_results = evaluation.get(
        "question_results",
        [],
    )

    # 1. 必须真的完成评分
    if not questions or not question_results:
        return False

    question_ids = {
        question["id"]
        for question in questions
    }

    result_ids = {
        result["question_id"]
        for result in question_results
    }

    if question_ids != result_ids:
        return False

    # 2. 必须覆盖当前节点所有学习目标
    current_node_id = state[
        "current_node_id"
    ]

    current_node = next(
        (
            node
            for node in state["tree"]
            if node["id"] == current_node_id
        ),
        None,
    )

    if current_node is None:
        return False

    required_objectives = {
        objective["id"]
        for objective
        in current_node["objectives"]
    }

    covered_objectives = {
        question["objective_id"]
        for question in questions
    }

    if not required_objectives.issubset(
        covered_objectives
    ):
        return False

    # 3. 不能有关键错误
    critical_tags = {
        "critical_error",
        "fundamental_misunderstanding",
    }

    for result in question_results:
        tags = set(
            result.get("error_tags", [])
        )

        if tags & critical_tags:
            return False

    # 4. 百分制必须 >= 80
    percentage = score_summary.get(
        "percentage",
        0,
    )

    if percentage < 80:
        return False

    return True


def build_graph(checkpointer=None):
    """注册完整闭环后再编译；测试也使用相同的节点和路由。"""
    builder = StateGraph(LearningState)

    builder.add_node("planner", planner_node)
    builder.add_node("tutor", tutor_node)
    builder.add_node("assessment_generate", assessment_generate_node)
    builder.add_node("assessment_grade", assessment_grade_node)
    builder.add_node("diagnosis", diagnosis_node)
    builder.add_node("wait_learning", wait_learning_node)
    builder.add_node("wait_answer", wait_answer_node)
    builder.add_node("advance", advance_node)
    builder.add_node("remediate", remediate_node)
    builder.add_node("collect_more_evidence", collect_more_evidence_node)
    builder.add_node("revisit_prerequisite", revisit_prerequisite_node)
    builder.add_node("invalid", invalid_action_node)
    builder.add_node("invalid_learning_event", invalid_learning_event_node)
    builder.add_node("invalid_answer_event", invalid_answer_event_node)

    builder.add_edge(START, "planner")
    builder.add_edge("planner", "tutor")
    builder.add_edge("tutor", "wait_learning")
    builder.add_edge("assessment_generate", "wait_answer")
    builder.add_edge("assessment_grade", "diagnosis")

    builder.add_conditional_edges(
        "wait_learning",
        route_after_learning,
        {
            "ask": "tutor",
            "start_quiz": "assessment_generate",
            "invalid": "invalid_learning_event",
        },
    )
    builder.add_conditional_edges(
        "wait_answer",
        route_after_answer,
        {
            "submit_answer": "assessment_grade",
            "invalid": "invalid_answer_event",
        },
    )
    builder.add_conditional_edges(
        "diagnosis",
        route_after_diagnosis,
        {
            "advance": "advance",
            "remediate": "remediate",
            "collect_more_evidence": "collect_more_evidence",
            "revisit_prerequisite": "revisit_prerequisite",
            "invalid": "invalid",
        },
    )

    builder.add_edge("advance", END)
    builder.add_edge("invalid", END)
    builder.add_edge("remediate", "tutor")
    builder.add_edge("collect_more_evidence", "assessment_generate")
    builder.add_edge("revisit_prerequisite", "tutor")
    builder.add_edge("invalid_learning_event", "wait_learning")
    builder.add_edge("invalid_answer_event", "wait_answer")

    if checkpointer is None:
        checkpointer = InMemorySaver()

    return builder.compile(checkpointer=checkpointer)


memory = InMemorySaver()
graph = build_graph(checkpointer=memory)
