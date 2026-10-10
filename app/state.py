# app/state.py

from typing import Any
from typing_extensions import TypedDict
from typing import Any, Annotated, Literal
from typing_extensions import TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages

class LearningState(TypedDict, total=False):
    # 用户想学什么
    goal: str

    # Planner 生成的知识树
    tree: list[dict[str, Any]]

    # 当前正在学习哪个知识点
    current_node_id: str

    # Tutor 生成的课程内容
    lesson: str

    # Assessment 生成的试卷
    quiz: dict[str, Any]

    # 用户提交的答案
    answers: dict[str, Any]
    # 答案不完整时继续等待，并向用户显示补交提示。
    answer_error: str

    # Assessment 的评分结果
    evaluation: dict[str, Any]

    # Diagnosis 的诊断结果
    diagnosis: dict[str, Any]
    # 用来观察 Conditional Edge 最终走到了哪条分支
    branch_result: str
    # 仅用于当前阶段测试 Diagnosis 的不同分支
    test_action: str
    user_event: dict[str, Any]
    # Tutor 当前教学模式
    lesson_mode: Literal[
        "normal",
        "remediate",
        "revisit",
    ]

    # Tutor 与用户的教学对话记录
    tutor_messages: Annotated[
        list[AnyMessage],
        add_messages,
    ]
    assessment_id: str
    # 已接受的试卷摘要，供后续复测避开旧题；不保存答案和评分标准。
    assessment_history: list[dict[str, Any]]
    # 程序计算出的本轮总分信息
    score_summary: dict[str, float]
