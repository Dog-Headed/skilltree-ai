from langchain_core.messages import AIMessage, HumanMessage

from app.services.llm import get_llm, ModelOutputValidationError, invoke_with_shared_budget
from app.services.observability import observed_node
from app.state import LearningState
from app.models.schemas import get_prerequisite_closure


def get_teaching_node(state: LearningState) -> dict:
    node_id = state["current_node_id"]
    if state.get("lesson_mode") == "revisit":
        node_id = state.get("review_node_id") or state.get("diagnosis", {}).get("review_node_id")
        if node_id not in get_prerequisite_closure(state["tree"], state["current_node_id"]):
            raise ValueError(f"复习目标不是当前节点的合法前置节点：{node_id}")

    for node in state["tree"]:
        if node["id"] == node_id:
            return node

    raise ValueError(
        f"找不到教学节点：{node_id}"
    )


def recent_complete_tutor_rounds(messages, node_id, limit=6):
    rounds = []
    pending = []
    for message in messages:
        if message.additional_kwargs.get("node_id", node_id) != node_id:
            continue
        if isinstance(message, HumanMessage):
            pending.append(message)
        elif isinstance(message, AIMessage):
            rounds.append([*pending, message])
            pending = []
    return [message for turn in rounds[-limit:] for message in turn]


def generate_tutor_content(
    state: LearningState,
    node: dict,
) -> str:
    llm = get_llm()

    user_event = state.get("user_event", {})
    lesson_mode = state.get("lesson_mode", "normal")

    # =========================
    # 场景 1：用户继续提问
    # =========================

    if (
        isinstance(user_event, dict)
        and user_event.get("action") == "ask"
    ):
        question = user_event.get("message", "")

        prompt = f"""
你是一名 Python 学习导师。

当前知识点：
{node["title"]}

学习目标：
{node["objectives"]}

用户刚刚提问：
{question}

请针对用户的问题直接解释。
要求：
1. 回答清晰、简洁。
2. 必要时给一个小例子。
3. 不要提前透露任何测验答案或评分标准。
"""

    # =========================
    # 场景 2：Diagnosis 要求补弱
    # =========================

    elif lesson_mode == "remediate":
        diagnosis = state.get("diagnosis", {})

        weak_points = diagnosis.get(
            "weak_points",
            [],
        )

        prompt = f"""
你是一名 Python 学习导师。

当前知识点：
{node["title"]}

学习目标：
{node["objectives"]}

学生刚刚完成测验，发现薄弱点：
{weak_points}

请针对这些薄弱点重新教学。

要求：
1. 不要从头重复整章内容。
2. 重点解释学生刚才暴露的问题。
3. 给一个新的例子。
4. 最后给一个很短的思考练习。
5. 不要泄露之前或下一轮测验的标准答案和评分标准。
"""

    # =========================
    # 场景 3：复习诊断指定的前置节点
    # =========================

    elif lesson_mode == "revisit":
        diagnosis = state.get("diagnosis", {})
        prompt = f"""
你是一名 Python 学习导师。

本次复习的前置知识点：
{node["title"]}（{node["id"]}）

知识点说明：
{node["description"]}

本次复习的学习目标：
{node["objectives"]}

诊断指出的问题：
{diagnosis.get("weak_points", [])}
{diagnosis.get("reason", "")}

复习后将返回的当前考核节点：
{state["current_node_id"]}

请针对上述前置知识的学习目标进行复习，说明它如何支撑当前考核节点。
给一个新的简单例子和不计分的练习，让学生可以继续提问或结束复习。
不要生成正式测验，不要透露任何测验答案或评分标准。
"""

    # =========================
    # 场景 4：正常教学或复习后接续当前节点
    # =========================

    else:
        teaching_task = (
            "前置知识复习已结束，请接续当前节点教学，用新例子解释两者的衔接。"
            if user_event.get("action") == "return_to_current"
            else "请进行第一次教学。"
        ) if isinstance(user_event, dict) else "请进行第一次教学。"
        prompt = f"""
你是一名 Python 学习导师。

当前知识点：
{node["title"]}

知识点说明：
{node["description"]}

学习目标：
{node["objectives"]}

{teaching_task}

要求：
1. 先解释核心概念。
2. 给一个简单例子。
3. 最后给一个不计分的简短练习。
4. 不要生成正式测验。
5. 不要透露任何测验答案或评分标准。
"""

    messages = [
        *recent_complete_tutor_rounds(state.get("tutor_messages", []), node["id"]),
        HumanMessage(content=prompt),
    ]
    def invoke_once(repair_context):
        request_messages = list(messages)
        if repair_context is not None:
            request_messages.append(HumanMessage(content="请返回非空的 Markdown 教学内容。"))
        return llm.invoke(request_messages)

    def validate_response(response):
        if not isinstance(response.content, str) or not response.content.strip():
            raise ModelOutputValidationError("Tutor 必须返回非空的教学文本")
        return response

    response = invoke_with_shared_budget(invoke_fn=invoke_once, validate_fn=validate_response, operation="tutor")

    return response.content


@observed_node
def tutor_node(state: LearningState):
    node = get_teaching_node(state)

    user_event = state.get("user_event", {})

    new_messages = []

    # 用户追问时，把问题记进教学对话历史
    if (
        isinstance(user_event, dict)
        and user_event.get("action") == "ask"
    ):
        question = user_event.get("message", "")

        if question:
            new_messages.append(
                HumanMessage(content=question, additional_kwargs={"node_id": node["id"]})
            )

    lesson = generate_tutor_content(
        state,
        node,
    )

    new_messages.append(
        AIMessage(content=lesson, additional_kwargs={"node_id": node["id"]})
    )

    return {
        "lesson": lesson,
        "tutor_messages": new_messages,
    }
