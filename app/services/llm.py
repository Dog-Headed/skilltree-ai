"""模型配置，以及单次逻辑调用共享的请求、网络重试和输出修复预算。"""

import os
import json
from time import perf_counter
from uuid import uuid4
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, TypeVar

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from app.services.observability import log_event
from openai import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    InternalServerError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
)


ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(dotenv_path=ENV_PATH)

T = TypeVar("T")


def compact_parse_error(error):
    """Actionable schema diagnostics without raw completions or private inputs."""
    current = error
    for _ in range(8):
        if current is None:
            break
        if hasattr(current, 'errors'):
            issues = current.errors(include_input=False, include_url=False)
            return json.dumps({'schema_errors': [
                {'field': '.'.join(map(str, issue['loc'])), 'type': issue['type'], 'message': issue['msg'][:180]}
                for issue in issues[:12]], 'instruction': 'Return the complete corrected JSON. Preserve all supplied identities and frozen values.'}, ensure_ascii=False)
        if isinstance(current, json.JSONDecodeError):
            detail = {'json_error': current.msg, 'line': current.lineno, 'column': current.colno,
                      'instruction': 'Return complete valid JSON with correctly escaped string values and no surrounding commentary.'}
            if current.msg == 'Invalid \\escape' and current.doc[current.pos:current.pos + 1] == '\\':
                # Only the two-character escape token, never the completion or
                # nearby learner content. A position alone cannot guide repair.
                detail['invalid_escape'] = current.doc[current.pos:current.pos + 2]
                detail['instruction'] = (r'A literal backslash in a JSON string must be doubled; '
                    r'for example, the C token \0 is written "\\0" in JSON. '
                    'Preserve the intended content and return one complete valid JSON object.')
            return json.dumps(detail)
        current = current.__cause__
    return 'Structured JSON did not match the supplied schema. Return one complete JSON object, preserving the supplied identities and frozen values.'


class ModelBudgetExceededError(RuntimeError):
    """总请求预算已耗尽，不能再调用模型。"""


class ModelRequestFailedError(RuntimeError):
    """暂时性网络错误耗尽网络重试额度或总请求额度。"""


class ModelOutputValidationError(ValueError):
    """模型输出未通过校验，可在预算内携带错误信息修复。"""


@dataclass
class ModelCallBudget:
    max_requests: int = 3
    max_network_retries: int = 1
    max_output_repairs: int = 1

    request_count: int = 0
    network_retry_count: int = 0
    output_repair_count: int = 0

    def consume_request(self) -> None:
        if self.request_count >= self.max_requests:
            raise ModelBudgetExceededError(
                "模型 HTTP 请求预算已耗尽："
                f"{self.request_count}/{self.max_requests}"
            )
        self.request_count += 1


@dataclass
class RepairContext:
    previous_output: Any
    error_message: str


RETRYABLE_MODEL_ERRORS = (
    APITimeoutError,
    APIConnectionError,
    InternalServerError,
    RateLimitError,
    # 方便使用不依赖 SDK 的请求替身验证预算。
    TimeoutError,
    ConnectionError,
)
NON_RETRYABLE_MODEL_ERRORS = (
    AuthenticationError,
    PermissionDeniedError,
    BadRequestError,
    NotFoundError,
)


def invoke_with_shared_budget(
    *,
    invoke_fn: Callable[
        [RepairContext | None],
        Any,
    ],
    validate_fn: Callable[
        [Any],
        T,
    ],
    budget: ModelCallBudget | None = None,
    operation: str = "model",
) -> T:
    """调用解析阶段与独立校验阶段的输出错误共用一次修复额度。"""

    if budget is None:
        budget = ModelCallBudget()

    logical_call_id = uuid4().hex

    def record_attempt(started, error_type=None):
        log_event(
            "model_attempt", logical_call_id=logical_call_id, operation=operation,
            request_count=budget.request_count, network_retry_count=budget.network_retry_count,
            output_repair_count=budget.output_repair_count,
            elapsed_ms=round((perf_counter() - started) * 1000, 3),
            error_type=error_type, outcome="error" if error_type else "success",
        )

    repair_context: (
        RepairContext | None
    ) = None

    while True:

        # ====================================================
        # 所有真实 HTTP 调用都先消耗总预算
        # ====================================================

        budget.consume_request()

        raw_output = None
        started = perf_counter()

        try:
            raw_output = invoke_fn(
                repair_context
            )

        # ====================================================
        # 确定性请求错误：绝不重试
        # ====================================================

        except NON_RETRYABLE_MODEL_ERRORS as exc:

            record_attempt(started, type(exc).__name__)

            raise ModelRequestFailedError(
                "模型请求发生不可重试错误："
                f"{type(exc).__name__}"
            ) from exc

        # ====================================================
        # 暂时性网络错误：最多 retry 一次
        # ====================================================

        except RETRYABLE_MODEL_ERRORS as exc:

            record_attempt(started, type(exc).__name__)

            can_retry_network = (
                budget.network_retry_count
                < budget.max_network_retries
            )

            has_total_budget = (
                budget.request_count
                < budget.max_requests
            )

            if (
                not can_retry_network
                or not has_total_budget
            ):
                raise ModelRequestFailedError(
                    "模型请求失败，"
                    "网络重试额度或"
                    "总请求额度已耗尽"
                ) from exc

            budget.network_retry_count += 1

            continue

        # ====================================================
        # structured output 在 invoke 阶段就失败
        # 也属于“输出错误”
        # ====================================================

        except ModelOutputValidationError as exc:

            record_attempt(started, type(exc).__name__)

            can_repair = (
                budget.output_repair_count
                < budget.max_output_repairs
            )

            has_total_budget = (
                budget.request_count
                < budget.max_requests
            )

            if (
                not can_repair
                or not has_total_budget
            ):
                raise

            budget.output_repair_count += 1

            repair_context = RepairContext(
                previous_output=None,
                error_message=str(exc),
            )

            continue

        except Exception as exc:
            record_attempt(started, type(exc).__name__)
            raise

        # ====================================================
        # HTTP / structured parsing 成功
        # 现在做业务校验
        # ====================================================

        try:
            result = validate_fn(
                raw_output
            )
            record_attempt(started)
            return result

        except ModelOutputValidationError as exc:

            record_attempt(started, type(exc).__name__)

            can_repair = (
                budget.output_repair_count
                < budget.max_output_repairs
            )

            has_total_budget = (
                budget.request_count
                < budget.max_requests
            )

            if (
                not can_repair
                or not has_total_budget
            ):
                raise

            budget.output_repair_count += 1

            repair_context = RepairContext(
                previous_output=raw_output,
                error_message=str(exc),
            )

            continue

        except Exception as exc:
            record_attempt(started, type(exc).__name__)
            raise


def get_llm(*, timeout=45):
    config = {
        name: os.getenv(name, "").strip()
        for name in ("LLM_MODEL", "LLM_API_KEY", "LLM_BASE_URL")
    }
    missing = [name for name, value in config.items() if not value]
    if missing:
        raise ValueError(
            f"缺少模型配置：{', '.join(missing)}。请在 {ENV_PATH} 中填写对应的环境变量。"
        )

    from app.v3.model_content import content_model
    from deploy.provider import StrictProvider
    return content_model(StrictProvider(ChatOpenAI(
        model=config["LLM_MODEL"],
        api_key=config["LLM_API_KEY"],
        base_url=config["LLM_BASE_URL"],
        temperature=0,
        timeout=timeout,
        max_retries=0,
    )))


def get_planning_llm():
    """A full multi-session route needs longer than a single tutor response."""
    return get_llm(timeout=120)


# Grading several text answers against rubrics took 63–78 s per request with a
# thinking model, so the 45 s default timed out on both attempts.
TASK_TIMEOUTS = {"grade": 180, "quiz": 120, "diagnosis": 120}


def get_task_llm(kind):
    """Per learning task kind (tutor, quiz, grade, diagnosis) request timeout."""
    return get_llm(timeout=TASK_TIMEOUTS.get(kind, 45))
