from uuid import uuid4

from langgraph.types import Command

from app.graph import graph


def test_full_interrupt_flow(answers_for_quiz, mock_assessment_grade_llm):
    # 首轮低分触发真实 Diagnosis 补弱，复测时再切换为满分 Mock。
    mock_assessment_grade_llm["score_ratio"] = 0.6
    # 每次测试使用不同的 thread_id
    # 防止 InMemorySaver 里的旧状态干扰测试
    thread_id = f"test-{uuid4()}"

    config = {
        "configurable": {
            "thread_id": thread_id
        }
    }

    # ========================================================
    # 1. 第一次启动
    # ========================================================

    result = graph.invoke(
        {
            "goal": "学习 Python"
        },
        config=config,
    )

    # 应该停在 wait_learning
    assert "__interrupt__" in result

    interrupt_data = result["__interrupt__"][0].value

    assert interrupt_data["type"] == "wait_learning"
    assert "lesson" in result
    assert result["lesson"]
    assert "变量" in result["lesson"]

    # 此时还没开始测验，所以不能有 quiz / evaluation
    assert "quiz" not in result
    assert "evaluation" not in result


    # ========================================================
    # 2. 用户继续提问
    # ========================================================

    result = graph.invoke(
        Command(
            resume={
                "action": "ask",
                "message": "Python 变量到底是什么？"
            }
        ),
        config=config,
    )

    # 提问后 Tutor 执行，然后应该再次停回 wait_learning
    assert "__interrupt__" in result

    interrupt_data = result["__interrupt__"][0].value

    assert interrupt_data["type"] == "wait_learning"

    assert result["user_event"]["action"] == "ask"
    assert result["user_event"]["message"] == "Python 变量到底是什么？"

    # 仍然没有进入测验
    assert "quiz" not in result
    assert "evaluation" not in result


    # ========================================================
    # 3. 用户选择开始测验
    # ========================================================

    result = graph.invoke(
        Command(
            resume={
                "action": "start_quiz"
            }
        ),
        config=config,
    )

    # Assessment Generate 应该已经生成题目
    assert "quiz" in result

    # 新卷已清空上一轮数据，还没有评分结果。
    assert result["evaluation"] == {}
    assert result["answers"] == {}
    assert result["score_summary"] == {}
    assert len(result["quiz"]["questions"]) == 4

    # 应该停在 wait_answer
    assert "__interrupt__" in result

    interrupt_data = result["__interrupt__"][0].value

    assert interrupt_data["type"] == "wait_answer"


    # ========================================================
    # 4. 用户提交答案
    # ========================================================

    previous_assessment_id = result["assessment_id"]
    answers = answers_for_quiz(result["quiz"])

    result = graph.invoke(
        Command(
            resume={
                "action": "submit_answer",
                "answers": answers,
            }
        ),
        config=config,
    )

    # 答案成功写进 State
    assert result["answers"] == answers

    # Assessment Grade 已经执行
    assert result["evaluation"]["assessment_id"] == previous_assessment_id
    assert {
        item["question_id"] for item in result["evaluation"]["question_results"]
    } == set(answers)
    assert result["score_summary"] == {
        "total_score": 60.0,
        "total_max_score": 100.0,
        "percentage": 60.0,
    }

    # Diagnosis 已经执行
    assert "diagnosis" in result
    assert result["diagnosis"]["recommended_action"] == "remediate"

    # 最后成功进入 remediate 分支
    assert result["branch_result"] == "remediate：返回 Tutor 进行补弱"

    # 补弱后 Tutor 再次执行，闭环停在 wait_learning。
    assert result["lesson_mode"] == "remediate"
    assert len(result["tutor_messages"]) == 4
    assert result["__interrupt__"][0].value["type"] == "wait_learning"
    assert graph.get_state(config).next == ("wait_learning",)

    # ========================================================
    # 5. 补弱后重新出题，清空旧答案和评分
    # ========================================================
    result = graph.invoke(
        Command(resume={"action": "start_quiz"}),
        config=config,
    )
    assert result["__interrupt__"][0].value["type"] == "wait_answer"
    assert result["assessment_id"] != previous_assessment_id
    assert result["quiz"]["assessment_id"] == result["assessment_id"]
    assert result["answers"] == {}
    assert result["evaluation"] == {}
    assert result["score_summary"] == {}

    # ========================================================
    # 6. 新卷完整作答，通过真实评分、Diagnosis 和放行校验
    # ========================================================
    mock_assessment_grade_llm["score_ratio"] = 1.0
    assessment_id = result["assessment_id"]
    answers = answers_for_quiz(result["quiz"])
    result = graph.invoke(
        Command(resume={"action": "submit_answer", "answers": answers}),
        config=config,
    )
    assert result["answers"] == answers
    assert result["evaluation"]["assessment_id"] == assessment_id
    assert {
        item["question_id"] for item in result["evaluation"]["question_results"]
    } == set(answers)
    assert result["score_summary"]["percentage"] == 100.0
    assert result["diagnosis"]["recommended_action"] == "advance"
    assert result["branch_result"] == "advance：进入下一个学习节点"
    assert "__interrupt__" not in result
    assert graph.get_state(config).next == ()


def test_invalid_learning_input_does_not_crash():
    thread_id = f"invalid-{uuid4()}"

    config = {
        "configurable": {
            "thread_id": thread_id
        }
    }

    # 先跑到 wait_learning
    graph.invoke(
        {
            "goal": "学习 Python"
        },
        config=config,
    )

    # 故意传字符串，而不是 dict
    result = graph.invoke(
        Command(
            resume="这不是合法的用户事件"
        ),
        config=config,
    )

    assert result["branch_result"] == (
        "invalid_learning_event：用户操作非法"
    )


def test_invalid_learning_input_can_retry():
    thread_id = f"retry-learning-{uuid4()}"

    config = {
        "configurable": {
            "thread_id": thread_id
        }
    }

    # 先启动，停在 wait_learning
    result = graph.invoke(
        {
            "goal": "学习 Python"
        },
        config=config,
    )

    assert result["__interrupt__"][0].value["type"] == "wait_learning"

    # 故意传非法输入
    result = graph.invoke(
        Command(
            resume="这不是合法事件"
        ),
        config=config,
    )

    # 不能结束，应该重新停回 wait_learning
    assert "__interrupt__" in result
    assert result["__interrupt__"][0].value["type"] == "wait_learning"

    # 同一个 thread_id 再提交正确输入
    result = graph.invoke(
        Command(
            resume={
                "action": "start_quiz"
            }
        ),
        config=config,
    )

    # 应该正常进入出题，并停在 wait_answer
    assert "quiz" in result
    assert result["__interrupt__"][0].value["type"] == "wait_answer"
    assert result["evaluation"] == {}
    assert result["answers"] == {}


def test_invalid_answer_can_retry(answers_for_quiz):
    thread_id = f"retry-answer-{uuid4()}"

    config = {
        "configurable": {
            "thread_id": thread_id
        }
    }

    # 启动 -> wait_learning
    graph.invoke(
        {
            "goal": "学习 Python"
        },
        config=config,
    )

    # 开始测验 -> wait_answer
    result = graph.invoke(
        Command(
            resume={
                "action": "start_quiz"
            }
        ),
        config=config,
    )

    assert result["__interrupt__"][0].value["type"] == "wait_answer"
    assessment_id = result["assessment_id"]

    # 故意提交空答案
    result = graph.invoke(
        Command(
            resume={
                "action": "submit_answer",
                "answers": {}
            }
        ),
        config=config,
    )

    # 不允许评分，也不能结束，要重新等待答案
    assert "__interrupt__" in result
    assert result["__interrupt__"][0].value["type"] == "wait_answer"
    assert result["evaluation"] == {}
    assert result["answers"] == {}
    assert result["score_summary"] == {}
    assert "diagnosis" not in result
    assert result["assessment_id"] == assessment_id

    # 再提交有效答案
    answers = answers_for_quiz(result["quiz"])
    result = graph.invoke(
        Command(
            resume={
                "action": "submit_answer",
                "answers": answers,
            }
        ),
        config=config,
    )

    # 这次才能评分和诊断
    assert result["answers"] == answers
    assert result["evaluation"]["assessment_id"] == assessment_id
    assert {
        item["question_id"] for item in result["evaluation"]["question_results"]
    } == set(answers)
    assert result["score_summary"]["percentage"] == 100.0
    assert result["diagnosis"]["recommended_action"] == "advance"
    assert result["branch_result"] == "advance：进入下一个学习节点"
    assert "__interrupt__" not in result
    assert graph.get_state(config).next == ()
