"""Durable model cost is reserved in real SQLite before every attempt."""

from copy import deepcopy
import json
from uuid import uuid4

import pytest
from langchain_core.messages import HumanMessage
from pydantic import Field

from app.services.llm import ModelOutputValidationError, ModelRequestFailedError, invoke_with_shared_budget
from app.v3.contracts import ContractModel, LearningProfile
from app.v3.model_tasks import LogicalTaskExhausted, run_model_task
from app.v3.repository import BudgetExhaustedError, ConflictError, V3Repository
from app.v3.runtime_storage import initialize_learning_storage
from app.v3.storage import V3Paths, initialize_storage


class Reply(ContractModel):
    text: str = Field(min_length=1)
    score: float = Field(default=1.0, ge=0, le=1, allow_inf_nan=False)


class FakeModel:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.messages = []

    def invoke(self, messages):
        self.messages.append(messages)
        item = self.answers.pop(0)
        if isinstance(item, BaseException):
            raise item
        return deepcopy(item)


def callback(model, budget):
    def invoke(repair):
        messages = [HumanMessage(content="返回合法教学数据")]
        if repair:
            messages.append(HumanMessage(content=repair.error_message))
        return model.invoke(messages)

    def validate(raw):
        try:
            return Reply.model_validate(raw)
        except ValueError as exc:
            raise ModelOutputValidationError(str(exc)) from exc

    return invoke_with_shared_budget(invoke_fn=invoke, validate_fn=validate, budget=budget)


@pytest.fixture
def task_store(tmp_path):
    paths = initialize_storage(V3Paths(tmp_path / "v3"))
    initialize_learning_storage(paths)
    with V3Repository(paths) as repo:
        project = repo.create_project(uuid4(), LearningProfile(subject_label="通用", topic="文字", goal="阅读解释"))
        operation = repo.create_operation(project["id"], uuid4(), kind="tutor")
    return paths, project["id"], operation


def run(store, model, *, key="tutor:node:request", input_data=None, operation=None, selected_callback=callback):
    paths, project_id, root = store
    return run_model_task(paths, project_id, (operation or root)["operation_id"], key,
                          {"node": "node", "contract_version": "3.0.0"} if input_data is None else input_data,
                          Reply, selected_callback, llm=model)


def state(store, key="tutor:node:request"):
    paths, project_id, operation = store
    with V3Repository(paths) as repo:
        task = dict(repo.conn.execute("SELECT * FROM model_tasks WHERE project_id=? AND task_key=?", (project_id, key)).fetchone())
        return task, repo.get_operation(project_id, operation["operation_id"])


def test_network_and_output_repair_share_three_durable_requests(task_store):
    model = FakeModel(TimeoutError("temporary"), {"text": "", "score": float("nan")}, {"text": "fixed"})
    assert run(task_store, model).text == "fixed"
    task, operation = state(task_store)
    assert (task["requests"], task["network_retries"], task["output_repairs"]) == (3, 1, 1)
    assert operation["reserved_requests"] == 3 and task["status"] == "completed"
    assert len(model.messages) == 3
    assert len(task["repair_json"]) < 1200
    assert isinstance(json.loads(task["repair_json"]), dict)


def test_continuous_network_failure_cannot_get_an_extra_attempt_after_restart(task_store):
    model = FakeModel(TimeoutError("first"), TimeoutError("second"))
    with pytest.raises(ModelRequestFailedError):
        run(task_store, model)
    task, operation = state(task_store)
    assert task["requests"] == operation["reserved_requests"] == 2 and task["network_retries"] == 1
    restarted = FakeModel({"text": "should not call"})
    with pytest.raises(LogicalTaskExhausted):
        run(task_store, restarted)
    assert restarted.messages == []
    assert state(task_store)[0]["requests"] == 2


def test_continuous_invalid_output_stops_across_new_connections(task_store):
    with pytest.raises(ModelOutputValidationError):
        run(task_store, FakeModel({"text": ""}, {"text": ""}))
    task, operation = state(task_store)
    assert task["requests"] == operation["reserved_requests"] == 2 and task["output_repairs"] == 1
    with pytest.raises(LogicalTaskExhausted):
        run(task_store, FakeModel({"text": "must not retry"}))
    assert state(task_store)[0]["result_json"] is None


def test_committed_reservation_is_not_refunded_after_process_exit_before_http(task_store):
    model = FakeModel({"text": "unused"})

    def crash_before_http(tracked, budget):
        budget.consume_request()
        raise SystemExit("process exited after reservation")

    with pytest.raises(SystemExit):
        run(task_store, model, selected_callback=crash_before_http)
    task, operation = state(task_store)
    assert model.messages == [] and task["requests"] == operation["reserved_requests"] == 1
    assert task["status"] == "pending"
    assert run(task_store, FakeModel({"text": "recovered"})).text == "recovered"
    assert state(task_store)[0]["requests"] == 2


def test_repair_allowance_and_safe_bad_output_context_survive_hard_restart(task_store):
    model = FakeModel({"text": "invalid", "score": float("inf")}, SystemExit("crash during repair request"))
    with pytest.raises(SystemExit):
        run(task_store, model)
    task, operation = state(task_store)
    assert (task["requests"], task["output_repairs"], operation["reserved_requests"]) == (2, 1, 2)
    assert "inf" in task["repair_json"].lower()
    resumed = FakeModel({"text": "repaired after restart"})
    assert run(task_store, resumed).text == "repaired after restart"
    assert "恢复时保留的上次输出错误" in resumed.messages[0][-1].content
    assert state(task_store)[0]["requests"] == 3


def test_large_escaped_invalid_output_keeps_restart_feedback_bounded_and_valid_json(task_store):
    bad = {"text": '"\\\x00' * 2000, "score": float("nan")}
    with pytest.raises(SystemExit):
        run(task_store, FakeModel(bad, SystemExit("restart after repair was reserved")))
    task, _ = state(task_store)
    assert len(task["repair_json"]) <= 1000
    assert json.loads(task["repair_json"])["preview_truncated"]
    assert run(task_store, FakeModel({"text": "recovered"})).text == "recovered"


def test_restart_does_not_reset_already_used_network_retry(task_store):
    with pytest.raises(SystemExit):
        run(task_store, FakeModel(TimeoutError("first"), SystemExit("after second reservation")))
    task, _ = state(task_store)
    assert task["requests"] == 2 and task["network_retries"] == 1
    model = FakeModel(TimeoutError("remaining request failed"), {"text": "forbidden fourth request"})
    with pytest.raises(ModelRequestFailedError):
        run(task_store, model)
    assert len(model.messages) == 1 and state(task_store)[0]["requests"] == 3


def test_completed_cached_result_does_not_build_model_or_call_callback_or_write(task_store):
    assert run(task_store, FakeModel({"text": "saved"})).text == "saved"
    paths, _, _ = task_store
    before = paths.learning.read_bytes()

    def must_not_construct_model():
        pytest.fail("Cache hit constructed a model")

    def must_not_call(*args):
        pytest.fail("Cache hit reran the callback")

    assert run(task_store, must_not_construct_model, selected_callback=must_not_call).text == "saved"
    assert paths.learning.read_bytes() == before


def test_changed_input_or_operation_family_conflicts_before_model_even_for_cache(task_store):
    run(task_store, FakeModel({"text": "saved"}))
    paths, project_id, _ = task_store
    with V3Repository(paths) as repo:
        unrelated = repo.create_operation(project_id, uuid4(), kind="tutor")
    model = FakeModel({"text": "must not overwrite"})
    with pytest.raises(ConflictError, match="input"):
        run(task_store, model, input_data={"node": "different-node"})
    with pytest.raises(ConflictError, match="family"):
        run(task_store, model, operation=unrelated)
    assert model.messages == [] and state(task_store)[0]["requests"] == 1


def test_completed_operation_cannot_reserve_new_request_but_can_read_existing_cache(task_store):
    run(task_store, FakeModel({"text": "saved"}))
    paths, project_id, operation = task_store
    with V3Repository(paths) as repo:
        with repo.transaction():
            repo.conn.execute("UPDATE model_operations SET status='completed' WHERE operation_id=?", (operation["operation_id"],))
    assert run(task_store, FakeModel()).text == "saved"
    model = FakeModel({"text": "forbidden"})
    with pytest.raises(ConflictError, match="Completed"):
        run(task_store, model, key="another-task")
    assert model.messages == []
    assert state(task_store, "another-task")[0]["requests"] == 0


def test_explicit_operation_extension_continues_same_task_without_resetting_its_budget(task_store):
    paths, project_id, root = task_store
    with V3Repository(paths) as repo:
        for _ in range(11):
            repo.reserve_model_request(project_id, root["operation_id"])
    first = FakeModel({"text": ""}, {"text": "must wait for new operation budget"})
    with pytest.raises(BudgetExhaustedError):
        run(task_store, first)
    task, operation = state(task_store)
    assert len(first.messages) == 1 and task["requests"] == 1 and task["output_repairs"] == 1
    assert operation["reserved_requests"] == 12 and operation["status"] == "budget_exhausted"
    request_id = uuid4()
    with V3Repository(paths) as repo:
        child = repo.create_operation(project_id, request_id, kind="tutor", parent_operation_id=root["operation_id"], retry_token=root["retry_token"])
        assert repo.create_operation(project_id, request_id, kind="tutor", parent_operation_id=root["operation_id"], retry_token=root["retry_token"]) == child
    resumed = FakeModel({"text": "fixed after explicit continuation"})
    assert run(task_store, resumed, operation=child).text == "fixed after explicit continuation"
    assert state(task_store)[0]["requests"] == 2 and state(task_store)[0]["output_repairs"] == 1
    assert "恢复时保留" in resumed.messages[0][-1].content


def test_twelve_plus_twelve_requests_have_one_idempotent_continuation_and_no_hidden_reset(task_store):
    paths, project_id, root = task_store
    for index in range(12):
        run(task_store, FakeModel({"text": f"task-{index}"}), key=f"step-{index}")
    blocked = FakeModel({"text": "not yet"})
    with pytest.raises(BudgetExhaustedError):
        run(task_store, blocked, key="step-12")
    assert blocked.messages == []
    with V3Repository(paths) as repo:
        child = repo.create_operation(project_id, uuid4(), kind="tutor", parent_operation_id=root["operation_id"], retry_token=root["retry_token"])
    for index in range(12, 24):
        run(task_store, FakeModel({"text": f"task-{index}"}), key=f"step-{index}", operation=child)
    with pytest.raises(BudgetExhaustedError):
        run(task_store, FakeModel(), key="step-24", operation=child)
    with V3Repository(paths) as repo:
        assert repo.conn.execute("SELECT SUM(reserved_requests) FROM model_operations WHERE project_id=?", (project_id,)).fetchone()[0] == 24
        for parent in (root, child):
            with pytest.raises(ConflictError):
                repo.create_operation(project_id, uuid4(), kind="tutor", parent_operation_id=parent["operation_id"], retry_token=parent["retry_token"])
