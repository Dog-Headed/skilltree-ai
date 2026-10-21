"""只读公开投影：业务库决定进度，Checkpoint 决定当前等待画面。"""

from langchain_core.messages import AIMessage, HumanMessage

from app.agents.assessment import build_public_quiz
from app.models.schemas import AssessmentEvaluation, AssessmentQuiz, validate_and_score_evaluation
from app.models.web import ProjectView, PublicNode, PublicResult
from app.services.learner_feedback import LearnerFeedback


def public_results(repo, project_id, completed_ids, nodes):
    results = []
    validated = []
    titles = {node.id: node.title for node in nodes}
    for record in repo.list_project_evaluations(project_id):
        try:
            quiz = AssessmentQuiz.model_validate(record["quiz"])
            evaluation = AssessmentEvaluation.model_validate(record["evaluation"])
            summary = validate_and_score_evaluation(quiz, evaluation)
        except (ValueError, TypeError):
            # 旧演示中无效记录不是有效学习成绩。
            continue
        validated.append((record, quiz, evaluation, summary))
    records = [record for record, *_ in validated]
    for record, quiz, evaluation, summary in validated:
        questions = {question.id: question for question in quiz.questions}
        question_order = {question.id: number for number, question in enumerate(quiz.questions)}
        diagnosis = record["diagnosis"] or {}
        display = LearnerFeedback(nodes, records, record)
        reason, weak_points = display.diagnosis(diagnosis, completed=record["id"] in completed_ids)
        results.append(PublicResult(
            assessment_id=record["id"], node_id=record["node_id"],
            node_title=titles.get(record["node_id"], "知识节点"), **summary,
            question_results=[{
                "question_id": item.question_id, "prompt": questions[item.question_id].prompt,
                "score": item.score, "max_score": questions[item.question_id].max_score,
                "feedback": display.text(item.feedback), "evidence": display.text(item.evidence), "error_tags": item.error_tags,
            } for item in sorted(evaluation.question_results, key=lambda item: question_order[item.question_id])],
            weak_points=weak_points,
            recommended_action=diagnosis.get("recommended_action"), reason=reason,
            completed=record["id"] in completed_ids,
        ))
    return results


def build_project_view(session, repo, *, running=False):
    if repo.is_project_deleted(session.project_id):
        return None
    snapshot = session.snapshot()
    state = snapshot.values
    project = repo.get_project(session.project_id)
    if not state and project is None:
        return None
    tree = repo.get_tree(session.project_id) if project else state.get("tree", [])
    progress = {node["id"]: repo.get_progress(project_id=session.project_id, node_id=node["id"]) for node in tree}
    completed = {node_id for node_id, item in progress.items() if item and item["completed_at"]}
    completion_assessments = {item["completion_assessment_id"] for item in progress.values() if item and item["completed_at"]}
    nodes = [PublicNode(**{key: node[key] for key in (
        "id", "title", "description", "objectives", "prerequisite_ids", "difficulty", "estimated_minutes",
    )}, status=("completed" if node["id"] in completed else
               "learning" if node["id"] == state.get("current_node_id") else
               "available" if set(node["prerequisite_ids"]).issubset(completed) else "locked")) for node in tree]
    error = None
    actions = []
    retry_token = None
    wait_type = snapshot.interrupts[0].value.get("type") if snapshot.interrupts else None
    if running:
        page = "running"
    elif not state:
        page = "error"
        error = {"code": "checkpoint_missing", "message": "项目记录仍在，但找不到对应学习存档。请恢复原存档，或新建一个学习项目。"}
    elif state.get("project_completed"):
        page = "completed"
    elif wait_type and not state.get("pending_input_id"):
        page = "error"
        error = {"code": "legacy_checkpoint", "message": "这是升级前的学习存档，缺少网页操作所需的输入标识。已有成绩仍保留，可用原命令行继续，或新建网页学习项目。"}
    elif wait_type == "wait_learning":
        page = "learning"
        actions = ["ask", "start_quiz"]
        if state.get("lesson_mode") == "revisit":
            actions.append("return_to_current")
    elif wait_type == "wait_answer":
        page = "quiz"
        actions = ["submit_answer", "return_to_teaching"]
    elif wait_type == "pause":
        page = "paused"
        actions = ["rest", "retry_3"]
    else:
        page = "error"
        if snapshot.next:
            actions = ["retry"]
            retry_token = snapshot.config.get("configurable", {}).get("checkpoint_id")
            error = {"code": "execution_failed", "message": "这一步未能完成，已保留学习进度。可以重试当前步骤；若持续失败，请检查本地模型配置与网络连接。"}
        else:
            error = {"code": "invalid_state", "message": "学习流程未停在可继续的位置。已有成绩仍保留，请新建项目或检查本地存档。"}
    current = state.get("current_node_id")
    teaching = state.get("review_node_id") if state.get("lesson_mode") == "revisit" else current
    conversation = []
    # 公开的教学问答与工具消息严格分开；只取当前教学目标。
    for message in state.get("tutor_messages", []):
        if message.additional_kwargs.get("node_id", teaching) != teaching or not isinstance(message.content, str):
            continue
        if isinstance(message, HumanMessage):
            conversation.append({"role": "user", "content": message.content})
        elif isinstance(message, AIMessage) and not message.tool_calls:
            # 没有对应追问的新课程表示补弱/复习/重新教学；主阅读区从新课程开始。
            if conversation and conversation[-1]["role"] != "user":
                conversation = []
            conversation.append({"role": "assistant", "content": message.content})
    return ProjectView(
        project_id=session.project_id, goal=project["goal"] if project else state.get("goal", "学习项目"),
        display_name=repo.get_display_name(session.project_id),
        nodes=nodes, completed_count=len(completed), total_count=len(nodes), current_node_id=current,
        teaching_node_id=teaching, lesson_mode=state.get("lesson_mode", "normal"), page_state=page,
        pending_input_id=state.get("pending_input_id") if snapshot.interrupts else None,
        allowed_actions=actions, lesson=state.get("lesson", "") if page == "learning" else "",
        conversation=conversation if page == "learning" else [],
        quiz=build_public_quiz(state["quiz"]) if page == "quiz" and state.get("quiz") else None,
        answers=state.get("answers", {}) if page == "quiz" else {}, answer_error=state.get("answer_error", "") if page == "quiz" else "",
        results=public_results(repo, session.project_id, completion_assessments, nodes),
        rounds=state.get("rounds_by_node", {}).get(current, 0), round_limit=state.get("round_limit_by_node", {}).get(current, 3),
        error=error, retry_token=retry_token,
    )
