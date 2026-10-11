import pytest
from langchain_core.exceptions import OutputParserException
from pydantic import ValidationError

import app.agents.planner as planner
from app.db.repository import LearningRepository
from app.models.schemas import TreePlan
from app.services.learning_session import open_learning_session
from app.services.llm import (
    ModelCallBudget, ModelOutputValidationError, invoke_with_shared_budget,
)
from tests.test_planner_validation import make_valid_data


# 保留真实入口；下面的接入测试会覆盖全局测试 fixture 中的模型替身。
REAL_GENERATE_PLAN = planner.generate_plan


@pytest.fixture
def valid_plan():
    return TreePlan.model_validate(make_valid_data())


@pytest.fixture
def invalid_plan(valid_plan):
    plan = valid_plan.model_copy(deep=True)
    plan.nodes[1].prerequisite_ids = ["ghost_node"]
    return plan


class FakePlannerRequester:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.repair_contexts = []

    @property
    def call_count(self):
        return len(self.repair_contexts)

    def __call__(self, repair_context):
        self.repair_contexts.append(repair_context)
        return self.outputs[self.call_count - 1]


class FakePlannerModel:
    def __init__(self, outcomes, before_call=None):
        self.outcomes = list(outcomes)
        self.messages = []
        self.before_call = before_call

    @property
    def call_count(self):
        return len(self.messages)

    def with_structured_output(self, schema, **kwargs):
        assert schema is TreePlan
        assert kwargs == {"method": "json_mode"}
        return self

    def invoke(self, messages):
        self.messages.append(messages)
        if self.before_call is not None:
            self.before_call()
        outcome = self.outcomes[self.call_count - 1]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def install_planner_model(monkeypatch, outcomes, *, before_call=None):
    model = FakePlannerModel(outcomes, before_call)
    budget = ModelCallBudget()
    monkeypatch.setattr(planner, "generate_plan", REAL_GENERATE_PLAN)
    monkeypatch.setattr(planner, "get_llm", lambda: model)
    monkeypatch.setattr(planner, "ModelCallBudget", lambda: budget)
    return model, budget


def test_planner_business_error_can_repair_once(valid_plan, invalid_plan):
    requester = FakePlannerRequester([invalid_plan, valid_plan])
    budget = ModelCallBudget()
    result = invoke_with_shared_budget(
        invoke_fn=requester, validate_fn=planner.validate_planner_output, budget=budget,
    )

    assert result == valid_plan
    assert requester.call_count == budget.request_count == 2
    assert budget.network_retry_count == 0
    assert budget.output_repair_count == 1
    assert requester.repair_contexts[0] is None
    repair_context = requester.repair_contexts[1]
    assert "ghost_node" in repair_context.error_message
    assert repair_context.previous_output is invalid_plan


def test_planner_business_error_twice_stops(valid_plan, invalid_plan):
    requester = FakePlannerRequester([invalid_plan, invalid_plan, valid_plan])
    budget = ModelCallBudget()
    with pytest.raises(ModelOutputValidationError, match="ghost_node"):
        invoke_with_shared_budget(
            invoke_fn=requester, validate_fn=planner.validate_planner_output, budget=budget,
        )

    assert requester.call_count == budget.request_count == 2
    assert budget.network_retry_count == 0
    assert budget.output_repair_count == 1


def test_real_planner_node_receives_specific_feedback_and_preserves_project(
    monkeypatch, valid_plan, invalid_plan,
):
    model, budget = install_planner_model(monkeypatch, [invalid_plan, valid_plan])
    goal = "学习 Python 的列表和循环"
    result = planner.planner_node(
        {"goal": goal}, config={"configurable": {"thread_id": "planner_repair"}},
    )

    assert result["project_id"] == "planner_repair"
    assert result["current_node_id"] == "node_1"
    assert result["tree"] == valid_plan.model_dump()["nodes"]
    assert model.call_count == budget.request_count == 2
    assert budget.output_repair_count == 1
    assert len(model.messages[0]) == 2
    assert len(model.messages[1]) == 3
    assert model.messages[1][:2] == model.messages[0]
    assert goal in model.messages[1][1].content
    assert "8 到 12" in model.messages[1][1].content
    assert '"nodes"' in model.messages[1][1].content
    repair_prompt = model.messages[1][-1].content
    assert "ghost_node" in repair_prompt
    assert "node_2" in repair_prompt
    assert "上一次输出" in repair_prompt
    assert "保持原学习目标不变" in repair_prompt


def test_repaired_plan_is_persisted_only_after_all_validation(
    tmp_path, monkeypatch, valid_plan, invalid_plan,
):
    business_path = tmp_path / "learning.sqlite"
    checked_before_requests = []

    def check_not_persisted():
        with LearningRepository(business_path) as repo:
            assert repo.get_project("repaired_plan") is None
            assert repo.get_tree("repaired_plan") == []
            checked_before_requests.append(True)

    model, budget = install_planner_model(
        monkeypatch, [invalid_plan, valid_plan], before_call=check_not_persisted,
    )
    with open_learning_session(
        "repaired_plan", learning_db_path=business_path,
        checkpoint_db_path=tmp_path / "checkpoints.sqlite",
    ) as session:
        result = session.start("学习 Python")
        assert session.snapshot().next == ("wait_learning",)
        assert result["project_id"] == "repaired_plan"
        assert result["tree"] == valid_plan.model_dump()["nodes"]
    assert checked_before_requests == [True, True]
    assert model.call_count == budget.request_count == 2
    with LearningRepository(business_path) as repo:
        assert repo.get_tree("repaired_plan") == valid_plan.model_dump()["nodes"]


def test_failed_repair_never_reaches_business_persistence(
    tmp_path, monkeypatch, valid_plan, invalid_plan,
):
    model, budget = install_planner_model(
        monkeypatch, [invalid_plan, invalid_plan, valid_plan],
    )
    business_path = tmp_path / "learning.sqlite"
    with open_learning_session(
        "failed_plan", learning_db_path=business_path,
        checkpoint_db_path=tmp_path / "checkpoints.sqlite",
    ) as session:
        with pytest.raises(ModelOutputValidationError, match="ghost_node"):
            session.start("学习 Python")
        snapshot = session.snapshot()
        assert snapshot.next == ("planner",)
        assert not snapshot.values.get("tree")
    assert model.call_count == budget.request_count == 2
    assert budget.output_repair_count == 1
    with LearningRepository(business_path) as repo:
        assert repo.get_project("failed_plan") is None
        assert repo.get_tree("failed_plan") == []
        assert repo.get_progress(project_id="failed_plan", node_id="node_1") is None


@pytest.mark.parametrize("failure_type", ["json", "pydantic"])
def test_structured_parse_failure_uses_same_repair_budget(
    monkeypatch, valid_plan, failure_type,
):
    if failure_type == "json":
        failure = OutputParserException('非法 JSON：{"nodes":', llm_output='{"nodes":')
    else:
        with pytest.raises(ValidationError) as captured:
            TreePlan.model_validate({"nodes": []})
        failure = captured.value

    model, budget = install_planner_model(monkeypatch, [failure, valid_plan])
    assert planner.generate_plan("学习 Python") == valid_plan
    assert model.call_count == budget.request_count == 2
    assert budget.network_retry_count == 0
    assert budget.output_repair_count == 1
    assert "Planner 结构化输出校验失败" in model.messages[1][-1].content
    assert str(failure) in model.messages[1][-1].content


def test_timeout_then_business_error_then_repair_uses_three_requests(
    monkeypatch, valid_plan, invalid_plan,
):
    model, budget = install_planner_model(
        monkeypatch, [TimeoutError("超时"), invalid_plan, valid_plan],
    )
    assert planner.generate_plan("学习 Python") == valid_plan
    assert model.call_count == budget.request_count == 3
    assert budget.network_retry_count == budget.output_repair_count == 1
    assert model.messages[0] == model.messages[1]
    assert "ghost_node" in model.messages[2][-1].content


@pytest.mark.parametrize("parse_first", [True, False])
def test_parse_and_business_failures_share_one_repair_allowance(
    monkeypatch, valid_plan, invalid_plan, parse_first,
):
    parse_error = OutputParserException("非法 JSON")
    failures = [parse_error, invalid_plan] if parse_first else [invalid_plan, parse_error]
    model, budget = install_planner_model(monkeypatch, [*failures, valid_plan])
    with pytest.raises(ModelOutputValidationError):
        planner.generate_plan("学习 Python")
    assert model.call_count == budget.request_count == 2
    assert budget.network_retry_count == 0
    assert budget.output_repair_count == 1


def test_programming_error_is_not_reclassified_as_repairable_output(
    monkeypatch, valid_plan,
):
    model, budget = install_planner_model(monkeypatch, [valid_plan, valid_plan])
    error = RuntimeError("Validator 程序错误")

    def broken_validator(plan):
        raise error

    monkeypatch.setattr(planner, "validate_plan_dag", broken_validator)
    with pytest.raises(RuntimeError) as captured:
        planner.generate_plan("学习 Python")
    assert captured.value is error
    assert model.call_count == budget.request_count == 1
    assert budget.network_retry_count == budget.output_repair_count == 0
