from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage
from langgraph.types import Command

import app.agents.planner as planner
import app.agents.tutor as tutor
from app.graph import build_graph, revisit_prerequisite_node
from app.models.schemas import DiagnosisResult, TreePlan


REAL_GENERATE_TUTOR_CONTENT = tutor.generate_tutor_content


@pytest.mark.parametrize("return_action", ["return_to_current", "start_quiz"])
def test_review_teaches_requested_prerequisite_then_returns_to_current(
    monkeypatch, answers_for_quiz, return_action
):
    # 保留 Planner 的契约和 DAG 校验，为复现案例使用指定节点 ID。
    plan_data = planner.generate_plan("测试计划").model_dump()
    names = {"variables": "python_basics", "lists": "python_variables"}
    for node in plan_data["nodes"]:
        node["id"] = names.get(node["id"], node["id"])
        node["prerequisite_ids"] = [names.get(item, item) for item in node["prerequisite_ids"]]
        if node["id"] == "python_basics":
            node["title"] = "Python 基础"
            node["objectives"][0]["description"] = "掌握执行顺序和 print 输出"
        elif node["id"] == "python_variables":
            node["title"] = "Python 变量"
            node["objectives"][0]["description"] = "掌握变量赋值"
    plan = TreePlan.model_validate(plan_data)
    monkeypatch.setattr(planner, "generate_plan", lambda goal: plan)

    prompts = []

    class TutorModel:
        def invoke(self, messages):
            prompts.append(messages[-1].content)
            return AIMessage(content=f"教学内容 {len(prompts)}")

    monkeypatch.setattr(tutor, "generate_tutor_content", REAL_GENERATE_TUTOR_CONTENT)
    monkeypatch.setattr(tutor, "get_llm", TutorModel)

    def request_review(state, **kwargs):
        return DiagnosisResult(
            weak_points=["执行顺序理解不清"],
            evidence_ids=[f"assessment:{state['assessment_id']}:q1"],
            recommended_action="revisit_prerequisite",
            reason="先复习执行顺序，再返回变量赋值。",
            review_node_id="python_basics",
        )

    monkeypatch.setattr("app.agents.diagnosis.run_real_diagnosis", request_review)
    graph = build_graph()
    config = {"configurable": {"thread_id": f"review-test-{uuid4()}"}}
    graph.invoke({"project_id": "demo_project", "goal": "学习 Python"}, config=config)
    graph.update_state(config, {"current_node_id": "python_variables"})
    result = graph.invoke(Command(resume={"action": "start_quiz"}), config=config)
    previous_quiz = result["quiz"]
    result = graph.invoke(
        Command(resume={"action": "submit_answer", "answers": answers_for_quiz(previous_quiz)}),
        config=config,
    )

    assert result["current_node_id"] == "python_variables"
    assert result["review_node_id"] == "python_basics"
    assert result["lesson_mode"] == "revisit"
    assert result["quiz"] == previous_quiz
    assert "Python 基础（python_basics）" in prompts[-1]
    assert "掌握执行顺序和 print 输出" in prompts[-1]
    assert "掌握变量赋值" not in prompts[-1]
    assert "return_to_current" in result["__interrupt__"][0].value["options"]

    # 复习期间的追问继续指向前置知识。
    result = graph.invoke(
        Command(resume={"action": "ask", "message": "再解释一下执行顺序"}), config=config
    )
    assert "Python 基础" in prompts[-1]
    assert "掌握执行顺序和 print 输出" in prompts[-1]
    assert result["current_node_id"] == "python_variables"
    old_evaluation = result["evaluation"]

    result = graph.invoke(Command(resume={"action": return_action}), config=config)
    assert result["current_node_id"] == "python_variables"
    assert result["project_id"] == "demo_project"
    assert result["review_node_id"] is None
    assert result["lesson_mode"] == "normal"
    if return_action == "return_to_current":
        assert graph.get_state(config).next == ("wait_learning",)
        assert "Python 变量" in prompts[-1]
        assert "掌握变量赋值" in prompts[-1]
        assert "前置知识复习已结束" in prompts[-1]
        assert result["quiz"] == previous_quiz
        assert result["evaluation"] == old_evaluation
        assert "return_to_current" not in result["__interrupt__"][0].value["options"]
        result = graph.invoke(Command(resume={"action": "start_quiz"}), config=config)

    # 无论先返回教学还是直接测验，都重新考核当前节点，不考核前置节点。
    assert graph.get_state(config).next == ("wait_answer",)
    assert result["quiz"]["node_id"] == "python_variables"
    assert result["quiz"]["assessment_id"] != previous_quiz["assessment_id"]
    assert result["evaluation"] == {}


@pytest.mark.parametrize("review_node_id", [None, "python_variables", "unknown_node"])
def test_review_requires_a_valid_prerequisite(review_node_id):
    state = {
        "current_node_id": "python_variables",
        "tree": [
            {"id": "python_basics", "prerequisite_ids": []},
            {"id": "python_variables", "prerequisite_ids": ["python_basics"]},
        ],
        "diagnosis": {"review_node_id": review_node_id},
    }
    with pytest.raises(ValueError, match="合法前置节点"):
        revisit_prerequisite_node(state)
