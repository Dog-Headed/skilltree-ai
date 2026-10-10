from langchain_core.messages import AIMessage, HumanMessage

from app.services.llm import get_llm
from app.state import LearningState


def get_current_node(state: LearningState) -> dict:
    current_node_id = state["current_node_id"]

    for node in state["tree"]:
        if node["id"] == current_node_id:
            return node

    raise ValueError(
        f"找不到当前学习节点：{current_node_id}"
    )


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
    # 场景 3：正常首次教学
    # =========================

    else:
        prompt = f"""
你是一名 Python 学习导师。

当前知识点：
{node["title"]}

知识点说明：
{node["description"]}

学习目标：
{node["objectives"]}

请进行第一次教学。

要求：
1. 先解释核心概念。
2. 给一个简单例子。
3. 最后给一个不计分的简短练习。
4. 不要生成正式测验。
5. 不要透露任何测验答案或评分标准。
"""

    messages = [
        *state.get("tutor_messages", []),
        HumanMessage(content=prompt),
    ]
    response = llm.invoke(messages)

    return response.content


def tutor_node(state: LearningState):
    node = get_current_node(state)

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
                HumanMessage(content=question)
            )

    lesson = generate_tutor_content(
        state,
        node,
    )

    new_messages.append(
        AIMessage(content=lesson)
    )

    return {
        "lesson": lesson,
        "tutor_messages": new_messages,
    }
