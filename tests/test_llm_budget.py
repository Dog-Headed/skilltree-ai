import pytest
import app.services.llm as llm_service
from pydantic import (
    BaseModel,
    ValidationError,
)

from app.services.llm import (
    ModelBudgetExceededError,
    ModelCallBudget,
    ModelOutputValidationError,
    ModelRequestFailedError,
    RepairContext,
    get_llm,
    invoke_with_shared_budget,
)


class DemoOutput(BaseModel):
    value: int


class FakeSequenceRequester:
    def __init__(
        self,
        outcomes,
    ):
        self.outcomes = list(
            outcomes
        )

        self.call_count = 0

        self.repair_contexts = []

    def __call__(
        self,
        repair_context: (
            RepairContext | None
        ),
    ):
        self.repair_contexts.append(
            repair_context
        )

        outcome = self.outcomes[
            self.call_count
        ]

        self.call_count += 1

        if isinstance(
            outcome,
            Exception,
        ):
            raise outcome

        return outcome


def validate_demo_output(
    raw_output,
) -> DemoOutput:

    try:
        return (
            DemoOutput.model_validate_json(
                raw_output
            )
        )

    except ValidationError as exc:

        raise (
            ModelOutputValidationError(
                str(exc)
            )
        ) from exc


def test_timeout_invalid_json_then_repair_success():
    requester = (
        FakeSequenceRequester(
            [
                # HTTP 1
                TimeoutError(
                    "模拟超时"
                ),

                # HTTP 2
                '{"value":',

                # HTTP 3
                '{"value": 42}',
            ]
        )
    )

    budget = ModelCallBudget()

    result = (
        invoke_with_shared_budget(
            invoke_fn=requester,
            validate_fn=(
                validate_demo_output
            ),
            budget=budget,
        )
    )

    assert result.value == 42

    # ================================================
    # 真正 HTTP 请求总数
    # ================================================

    assert (
        requester.call_count
        == 3
    )

    assert (
        budget.request_count
        == 3
    )

    # ================================================
    # 第一次是网络重试
    # ================================================

    assert (
        budget.network_retry_count
        == 1
    )

    # ================================================
    # 第二次输出非法，所以修复一次
    # ================================================

    assert (
        budget.output_repair_count
        == 1
    )


    # 前两次是原始请求和网络重试，第三次必须携带原输出和校验原因。
    assert requester.repair_contexts[0] is None
    assert requester.repair_contexts[1] is None
    repair_context = requester.repair_contexts[2]
    assert repair_context is not None
    assert repair_context.previous_output == '{"value":'
    assert repair_context.error_message


def test_network_retry_during_repair_preserves_context():
    requester = FakeSequenceRequester([
        '{"value":', TimeoutError("修复请求超时"), '{"value": 42}',
    ])
    budget = ModelCallBudget()

    result = invoke_with_shared_budget(
        invoke_fn=requester, validate_fn=validate_demo_output, budget=budget,
    )

    assert result.value == 42
    assert requester.call_count == budget.request_count == 3
    assert budget.network_retry_count == budget.output_repair_count == 1
    repair_context = requester.repair_contexts[1]
    assert repair_context.previous_output == '{"value":'
    assert repair_context.error_message
    assert requester.repair_contexts[2] is repair_context


def test_total_budget_stops_repair_even_with_unused_repair_allowance():
    requester = FakeSequenceRequester([
        TimeoutError("模拟超时"), '{"value":', '{"value": 42}',
    ])
    budget = ModelCallBudget(max_requests=2)

    with pytest.raises(ModelOutputValidationError):
        invoke_with_shared_budget(
            invoke_fn=requester, validate_fn=validate_demo_output, budget=budget,
        )

    assert requester.call_count == budget.request_count == 2
    assert budget.network_retry_count == 1
    assert budget.output_repair_count == 0


def test_continuous_network_failure_stops_after_one_retry():
    last_error = ConnectionError("连接仍然失败")
    requester = FakeSequenceRequester([
        TimeoutError("模拟超时"), last_error, '{"value": 42}',
    ])
    budget = ModelCallBudget()

    with pytest.raises(ModelRequestFailedError) as captured:
        invoke_with_shared_budget(
            invoke_fn=requester, validate_fn=validate_demo_output, budget=budget,
        )

    assert captured.value.__cause__ is last_error
    assert requester.call_count == budget.request_count == 2
    assert budget.network_retry_count == 1
    assert budget.output_repair_count == 0


def test_reusing_exhausted_budget_never_invokes_requester_again():
    requester = FakeSequenceRequester(['{"value": 1}', '{"value": 2}'])
    budget = ModelCallBudget(max_requests=1)
    result = invoke_with_shared_budget(
        invoke_fn=requester, validate_fn=validate_demo_output, budget=budget,
    )
    assert result.value == 1

    with pytest.raises(ModelBudgetExceededError):
        invoke_with_shared_budget(
            invoke_fn=requester, validate_fn=validate_demo_output, budget=budget,
        )

    assert requester.call_count == budget.request_count == 1


def test_get_llm_disables_hidden_retries_and_sets_request_timeout(monkeypatch):
    captured = {}
    model = object()

    def fake_chat_openai(**kwargs):
        captured.update(kwargs)
        return model

    for name, value in {
        "LLM_MODEL": "test-model",
        "LLM_API_KEY": "test-key",
        "LLM_BASE_URL": "https://example.invalid/v1",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr("app.services.llm.ChatOpenAI", fake_chat_openai)

    # 调用导入时保留的原函数，构造器使用替身，不访问真实模型。
    assert get_llm().model.model is model
    assert captured == {
        "model": "test-model", "api_key": "test-key",
        "base_url": "https://example.invalid/v1", "temperature": 0,
        "timeout": 45, "max_retries": 0,
    }

def test_shared_budget_never_exceeds_three_requests():
    requester = (
        FakeSequenceRequester(
            [
                TimeoutError(
                    "模拟超时"
                ),

                '{"value":',

                '{"value":',

                # 如果出现第 4 次请求，
                # 就说明我们的预算系统坏了
                '{"value": 999}',
            ]
        )
    )

    budget = ModelCallBudget()

    with pytest.raises(
        ModelOutputValidationError
    ):
        invoke_with_shared_budget(
            invoke_fn=requester,
            validate_fn=(
                validate_demo_output
            ),
            budget=budget,
        )

    assert (
        requester.call_count
        == 3
    )

    assert (
        budget.request_count
        == 3
    )

    assert (
        budget.network_retry_count
        == 1
    )

    assert (
        budget.output_repair_count
        == 1
    )
def test_timeout_then_success_retries_once():

    requester = (
        FakeSequenceRequester(
            [
                TimeoutError(
                    "第一次超时"
                ),

                '{"value": 42}',
            ]
        )
    )

    budget = ModelCallBudget()

    result = (
        invoke_with_shared_budget(
            invoke_fn=requester,
            validate_fn=(
                validate_demo_output
            ),
            budget=budget,
        )
    )

    assert result.value == 42

    assert requester.call_count == 2

    assert budget.request_count == 2

    assert (
        budget.network_retry_count
        == 1
    )

    assert (
        budget.output_repair_count
        == 0
    )

def test_consecutive_network_errors_stop_after_one_retry():

    requester = (
        FakeSequenceRequester(
            [
                TimeoutError(
                    "第一次超时"
                ),

                ConnectionError(
                    "第二次仍然失败"
                ),

                # 永远不应该执行
                '{"value": 999}',
            ]
        )
    )

    budget = ModelCallBudget()

    with pytest.raises(
        ModelRequestFailedError
    ):
        invoke_with_shared_budget(
            invoke_fn=requester,
            validate_fn=(
                validate_demo_output
            ),
            budget=budget,
        )

    assert requester.call_count == 2

    assert budget.request_count == 2

    assert (
        budget.network_retry_count
        == 1
    )

    assert (
        budget.output_repair_count
        == 0
    )

def test_authentication_error_does_not_retry(
    monkeypatch,
):

    class FakeAuthenticationError(
        Exception
    ):
        pass

    monkeypatch.setattr(
        llm_service,
        "NON_RETRYABLE_MODEL_ERRORS",
        (
            FakeAuthenticationError,
        ),
    )

    requester = (
        FakeSequenceRequester(
            [
                FakeAuthenticationError(
                    "401 Unauthorized"
                ),

                # 绝不能调用
                '{"value": 999}',
            ]
        )
    )

    budget = ModelCallBudget()

    with pytest.raises(
        ModelRequestFailedError
    ):
        invoke_with_shared_budget(
            invoke_fn=requester,
            validate_fn=(
                validate_demo_output
            ),
            budget=budget,
        )

    assert requester.call_count == 1

    assert budget.request_count == 1

    assert (
        budget.network_retry_count
        == 0
    )

    assert (
        budget.output_repair_count
        == 0
    )


def test_bad_request_does_not_retry(
    monkeypatch,
):

    class FakeBadRequestError(
        Exception
    ):
        pass

    monkeypatch.setattr(
        llm_service,
        "NON_RETRYABLE_MODEL_ERRORS",
        (
            FakeBadRequestError,
        ),
    )

    requester = (
        FakeSequenceRequester(
            [
                FakeBadRequestError(
                    "400 Bad Request"
                ),

                '{"value": 999}',
            ]
        )
    )

    budget = ModelCallBudget()

    with pytest.raises(
        ModelRequestFailedError
    ):
        invoke_with_shared_budget(
            invoke_fn=requester,
            validate_fn=(
                validate_demo_output
            ),
            budget=budget,
        )

    assert requester.call_count == 1

    assert budget.request_count == 1

    assert (
        budget.network_retry_count
        == 0
    )