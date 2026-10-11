from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt
from langchain_core.messages import RemoveMessage
from langgraph.graph.message import REMOVE_ALL_MESSAGES

from app.db.repository import repository_for_state
from app.state import LearningState
from app.agents.planner import planner_node, validate_plan_dag
from app.agents.tutor import tutor_node
from app.agents.diagnosis import diagnosis_node
from app.models.schemas import TreePlan, get_prerequisite_closure
from langgraph.checkpoint.memory import InMemorySaver
from app.agents.assessment import (
    assessment_generate_node,
    assessment_grade_node,
    assessment_prepare_node,
    build_public_quiz, assessment_save_answers_node,
)
# =========================
# 四个 Diagnosis 分支节点
# =========================
from pathlib import Path
from uuid import uuid4

PROJECT_ROOT = (
    Path(__file__).resolve().parents[1]
)

CHECKPOINT_DB_PATH = (
    PROJECT_ROOT
    / "data"
    / "checkpoints.sqlite"
)
def persist_plan_node(
    state: LearningState,
):
    project_id = state.get(
        "project_id"
    )

    goal = state.get(
        "goal"
    )

    tree = state.get(
        "tree"
    )

    current_node_id = state.get(
        "current_node_id"
    )

    if not project_id:
        raise ValueError(
            "persist_plan 缺少 project_id"
        )

    if not goal:
        raise ValueError(
            "persist_plan 缺少 goal"
        )

    if not isinstance(tree, list) or not tree:
        raise ValueError(
            "persist_plan 缺少合法 tree"
        )

    plan = TreePlan.model_validate({"nodes": tree})
    validate_plan_dag(plan)
    if current_node_id not in {node.id for node in plan.nodes}:
        raise ValueError("persist_plan 的当前节点不在规划中")

    with repository_for_state(state) as repo:

        existing = repo.get_project(
            project_id
        )

        # 第一次执行
        if existing is None:
            repo.create_project_with_tree(
                project_id=project_id,
                goal=goal,
                tree=tree,
            )

        # 重试时已经存在
        else:
            if existing["goal"] != goal:
                raise ValueError(
                    "已有 Project 的 goal "
                    "与当前 State 不一致"
                )

            stored_tree = repo.get_tree(
                project_id
            )

            if stored_tree != tree:
                raise ValueError(
                    "已有 Skill Tree "
                    "与当前 State 不一致"
                )

        if current_node_id:
            repo.mark_node_started(
                project_id=project_id,
                node_id=current_node_id,
            )

    # 只固定业务计划，不增加其他 State 更新。
    return {}
def record_node_completion(state: LearningState):
    if not can_advance(state):
        raise ValueError("当前测评不满足节点完成条件")
    with repository_for_state(state) as repo:
        repo.mark_node_completed(
            project_id=state["project_id"],
            node_id=state[
                "current_node_id"
            ],
            assessment_id=state[
                "assessment_id"
            ],
        )


def advance_node(state: LearningState):
    """先固定完成事实，再选拓扑序中第一个前置全部完成的节点。"""
    record_node_completion(state)
    order, _ = validate_plan_dag(TreePlan.model_validate({"nodes": state["tree"]}))
    node_map = {node["id"]: node for node in state["tree"]}
    with repository_for_state(state) as repo:
        completed = {
            node_id for node_id in order
            if (progress := repo.get_progress(project_id=state["project_id"], node_id=node_id))
            and progress["completed_at"]
        }
        next_node_id = next((
            node_id for node_id in order if node_id not in completed
            and set(node_map[node_id]["prerequisite_ids"]).issubset(completed)
        ), None)
        if next_node_id is None and len(completed) != len(order):
            raise ValueError("项目仍有未完成节点，但没有可学习的节点")
        if next_node_id is not None:
            repo.mark_node_started(project_id=state["project_id"], node_id=next_node_id)
    return {
        "branch_result": "advance：进入下一个学习节点" if next_node_id else "advance：全部学习节点已完成",
        "last_assessment_id": state["assessment_id"],
        "last_completed_node_id": state["current_node_id"],
        "current_node_id": next_node_id, "project_completed": next_node_id is None,
        "review_node_id": None, "lesson_mode": "normal", "lesson": "",
        "tutor_messages": [RemoveMessage(id=REMOVE_ALL_MESSAGES)],
        "assessment_id": None, "assessment_round_no": 0, "assessment_history": [],
        "quiz": {}, "answers": {}, "evaluation": {}, "diagnosis": {},
        "score_summary": {}, "answer_error": "", "user_event": {},
    }


def finish_day4_demo_node(state: LearningState):
    # Day 4 用单节点闭环讲解；Day 6 默认继续学习整棵树。
    record_node_completion(state)
    return {"branch_result": "advance：进入下一个学习节点"}


def route_after_advance(state: LearningState):
    return "done" if state.get("project_completed") else "learn"


def remediate_node(
    state: LearningState,
):
    return {
        "branch_result": (
            "remediate：返回 Tutor 进行补弱"
        ),
        "lesson_mode": "remediate",
        "review_node_id": None,
    }


def collect_more_evidence_node(state: LearningState):
    return {
        "branch_result": "collect_more_evidence：需要追加测评"
    }


def revisit_prerequisite_node(state: LearningState):
    review_node_id = state.get("diagnosis", {}).get("review_node_id")
    if review_node_id not in get_prerequisite_closure(state["tree"], state["current_node_id"]):
        raise ValueError(f"复习目标不是当前节点的合法前置节点：{review_node_id}")
    return {
        "branch_result": "revisit_prerequisite：需要复习前置知识",
        "lesson_mode": "revisit",
        "review_node_id": review_node_id,
    }


def return_to_current_node(state: LearningState):
    return {
        "branch_result": "return_to_current：前置知识复习结束，返回当前学习节点",
        "lesson_mode": "normal",
        "review_node_id": None,
    }


def route_after_review(state: LearningState):
    return "start_quiz" if state["user_event"]["action"] == "start_quiz" else "learn"


# =========================
# Conditional Edge 路由函数
# =========================

def route_after_diagnosis(state: LearningState):
    diagnosis = state.get("diagnosis", {})
    action = diagnosis.get("recommended_action")

    if action == "advance" and can_advance(state):
        return "advance"

    if action not in {"advance", "remediate", "collect_more_evidence", "revisit_prerequisite"}:
        return "invalid"

    node_id = state["current_node_id"]
    if state.get("rounds_by_node", {}).get(node_id, 0) >= state.get("round_limit_by_node", {}).get(node_id, 3):
        return "pause"

    if action == "advance":

        return "collect_more_evidence"

    if action == "remediate":
        return "remediate"

    if action == "collect_more_evidence":
        return "collect_more_evidence"

    if action == "revisit_prerequisite":
        return "revisit_prerequisite"

    # 非法 action 不允许默认为 advance
    return "invalid"


def prepare_pause_node(state: LearningState):
    return {"pending_input_id": f"pause_{uuid4().hex}", "user_event": {},
            "branch_result": "pause：本节点已达到测评轮数上限"}


def pause_node(state: LearningState):
    # interrupt 节点从头重跑；这里没有模型调用、写库或增加额度。
    node_id = state["current_node_id"]
    event = interrupt({
        "type": "pause", "message": "本节点已达到测评轮数上限，请选择休息或再试 3 轮。",
        "options": ["rest", "retry_3"], "pending_input_id": state["pending_input_id"],
        "rounds": state.get("rounds_by_node", {}).get(node_id, 0),
        "round_limit": state.get("round_limit_by_node", {}).get(node_id, 3),
    })
    if (not isinstance(event, dict) or event.get("pending_input_id") != state["pending_input_id"]
            or event.get("action") not in {"rest", "retry_3"}):
        event = {"action": "invalid"}
    return {"user_event": event}


def route_after_pause(state: LearningState):
    return "extend" if state.get("user_event", {}).get("action") == "retry_3" else "stay"


def extend_round_limit_node(state: LearningState):
    input_id = state.get("pending_input_id")
    credited = list(state.get("credited_pause_input_ids", []))
    if input_id in credited:
        return {}
    event = state.get("user_event", {})
    if not input_id or event.get("pending_input_id") != input_id or event.get("action") != "retry_3":
        raise ValueError("增加测评额度必须来自当前暂停点的主动选择")
    node_id = state["current_node_id"]
    limits = dict(state.get("round_limit_by_node", {}))
    limits[node_id] = limits.get(node_id, 3) + 3
    return {"round_limit_by_node": limits, "credited_pause_input_ids": [*credited, input_id],
            "user_event": {}, "pending_input_id": None}


# =========================
# 非法行动节点
# =========================

def invalid_action_node(state: LearningState):
    return {
        "branch_result": "invalid：Diagnosis 返回了非法行动"
    }


def wait_learning_node(state: LearningState):
    revisiting = state.get("lesson_mode") == "revisit"
    user_event = interrupt(
        {
            "type": "wait_learning",
            "pending_input_id": state.get("pending_input_id"),
            "message": "请选择：继续复习提问、返回当前节点学习，或开始当前节点测验"
            if revisiting else "请选择：继续提问 or 开始测验",
            "options": ["ask", "start_quiz", "return_to_current"]
            if revisiting else ["ask", "start_quiz"],
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
            "pending_input_id": state.get("pending_input_id"),
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
        if state.get("lesson_mode") == "revisit":
            return "return_to_current"
        return "start_quiz"

    if action == "return_to_current" and state.get("lesson_mode") == "revisit":
        return "return_to_current"

    return "invalid"


def route_after_answer(state: LearningState):
    if state.get("user_event", {}).get("action") == "return_to_teaching":
        return "return_to_teaching"
    if answer_submission_error(state) is None:
        return "submit_answer"

    return "invalid"


def prepare_learning_input_node(state: LearningState):
    """独立提交输入身份；interrupt 重跑和只读恢复不会更换身份。"""
    return {"pending_input_id": f"learning_{uuid4().hex}"}


def prepare_answer_input_node(state: LearningState):
    return {"pending_input_id": f"answer_{uuid4().hex}"}


def abandon_quiz_node(state: LearningState):
    """先幂等放弃原卷，再清空答题现场；下次出题使用新身份。"""
    with repository_for_state(state) as repo:
        repo.abandon_assessment(
            project_id=state["project_id"], assessment_id=state["assessment_id"],
        )
    return {"assessment_id": None, "quiz": {}, "answers": {}, "answer_error": "",
            "evaluation": {}, "score_summary": {}, "lesson_mode": "normal",
            "review_node_id": None, "user_event": {}, "pending_input_id": None}


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

    if question_ids != result_ids or len(question_results) != len(questions):
        return False

    # 最后一道推进边界也检查分数，避免损坏 State 或非有限数误解锁。
    import math
    scores = []
    maxima = []
    question_map = {question["id"]: question for question in questions}
    if evaluation.get("assessment_id") != quiz.get("assessment_id"):
        return False
    if state.get("assessment_id") is not None and state["assessment_id"] != quiz.get("assessment_id"):
        return False
    for result in question_results:
        score = result.get("score")
        maximum = question_map[result["question_id"]].get("max_score")
        if (isinstance(score, bool) or isinstance(maximum, bool)
                or not isinstance(score, (int, float)) or not isinstance(maximum, (int, float))
                or not math.isfinite(score) or not math.isfinite(maximum)
                or maximum <= 0 or not 0 <= score <= maximum):
            return False
        scores.append(score)
        maxima.append(maximum)

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
    if not math.isfinite(sum(scores)) or not math.isfinite(sum(maxima)):
        return False
    percentage = sum(scores) / sum(maxima) * 100

    if percentage < 80:
        return False

    return True


def build_graph(checkpointer=None, *, stop_after_advance=False):
    """注册完整闭环后再编译；测试也使用相同的节点和路由。"""
    builder = StateGraph(LearningState)

    builder.add_node("planner", planner_node)
    builder.add_node("persist_plan", persist_plan_node)
    builder.add_node("tutor", tutor_node)
    builder.add_node("assessment_generate", assessment_generate_node)
    builder.add_node("assessment_grade", assessment_grade_node)
    builder.add_node("diagnosis", diagnosis_node)
    builder.add_node("wait_learning", wait_learning_node)
    builder.add_node("wait_answer", wait_answer_node)
    builder.add_node("prepare_learning_input", prepare_learning_input_node)
    builder.add_node("prepare_answer_input", prepare_answer_input_node)
    builder.add_node("abandon_quiz", abandon_quiz_node)
    builder.add_node("advance", finish_day4_demo_node if stop_after_advance else advance_node)
    builder.add_node("remediate", remediate_node)
    builder.add_node("collect_more_evidence", collect_more_evidence_node)
    builder.add_node("revisit_prerequisite", revisit_prerequisite_node)
    builder.add_node("return_to_current", return_to_current_node)
    builder.add_node("invalid", invalid_action_node)
    builder.add_node("invalid_learning_event", invalid_learning_event_node)
    builder.add_node("invalid_answer_event", invalid_answer_event_node)
    builder.add_node("prepare_pause", prepare_pause_node)
    builder.add_node("pause", pause_node)
    builder.add_node("extend_round_limit", extend_round_limit_node)
    builder.add_edge("prepare_pause", "pause")
    builder.add_conditional_edges("pause", route_after_pause, {"stay": "pause", "extend": "extend_round_limit"})
    builder.add_conditional_edges("extend_round_limit", route_after_diagnosis, {
        "advance": "advance", "remediate": "remediate", "collect_more_evidence": "collect_more_evidence",
        "revisit_prerequisite": "revisit_prerequisite", "pause": "prepare_pause", "invalid": "invalid",
    })
    builder.add_node(
        "assessment_prepare",
        assessment_prepare_node,
    )
    builder.add_node(
        "assessment_save_answers",
        assessment_save_answers_node,
    )
    builder.add_edge(
        "assessment_save_answers",
        "assessment_grade",
    )
    builder.add_edge(START, "planner")
    builder.add_edge("planner", "persist_plan")
    builder.add_edge("persist_plan", "tutor")
    builder.add_edge("tutor", "prepare_learning_input")
    builder.add_edge("prepare_learning_input", "wait_learning")
    builder.add_edge("assessment_generate", "prepare_answer_input")
    builder.add_edge("prepare_answer_input", "wait_answer")
    builder.add_edge("abandon_quiz", "tutor")
    builder.add_edge("assessment_grade", "diagnosis")

    builder.add_conditional_edges(
        "wait_learning",
        route_after_learning,
        {
            "ask": "tutor",
            "start_quiz": "assessment_prepare",
            "return_to_current": "return_to_current",
            "invalid": "invalid_learning_event",
        },
    )
    builder.add_conditional_edges(
        "wait_answer",
        route_after_answer,
        {
            "submit_answer": "assessment_save_answers",
            "return_to_teaching": "abandon_quiz",
            "invalid": "invalid_answer_event",
        },
    )
    builder.add_conditional_edges(
        "diagnosis",
        route_after_diagnosis,
        {
            "advance": "advance",
            "pause": "prepare_pause",
            "remediate": "remediate",
            "collect_more_evidence": "collect_more_evidence",
            "revisit_prerequisite": "revisit_prerequisite",
            "invalid": "invalid",
        },
    )

    if stop_after_advance:
        builder.add_edge("advance", END)
    else:
        builder.add_conditional_edges("advance", route_after_advance, {"learn": "tutor", "done": END})
    builder.add_edge("invalid", END)
    builder.add_edge("remediate", "tutor")
    builder.add_edge("collect_more_evidence", "assessment_prepare")
    builder.add_edge("assessment_prepare", "assessment_generate")
    builder.add_edge("revisit_prerequisite", "tutor")
    builder.add_conditional_edges(
        "return_to_current",
        route_after_review,
        {"learn": "tutor", "start_quiz": "assessment_prepare"},
    )
    builder.add_edge("invalid_learning_event", "wait_learning")
    builder.add_edge("invalid_answer_event", "prepare_answer_input")

    if checkpointer is None:
        checkpointer = InMemorySaver()

    return builder.compile(checkpointer=checkpointer)


memory = InMemorySaver()
graph = build_graph(checkpointer=memory, stop_after_advance=True)
