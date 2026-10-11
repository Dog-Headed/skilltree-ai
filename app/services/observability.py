"""只记录白名单运行字段；不记录 Prompt、答案、异常正文或模型配置。"""

import json
import logging
from contextvars import ContextVar
from functools import wraps
from time import perf_counter


logger = logging.getLogger("skilltree")
_context = ContextVar("skilltree_log_context", default={})
_FIELDS = {
    "project_id", "node_id", "assessment_id", "node", "logical_call_id",
    "operation", "request_count", "network_retry_count", "output_repair_count",
    "elapsed_ms", "tool", "error_type", "outcome", "attempt",
}


def log_event(event, *, state=None, **fields):
    context = dict(_context.get())
    if state is not None:
        context.update({
            "project_id": state.get("project_id"),
            "node_id": state.get("current_node_id"),
            "assessment_id": state.get("assessment_id"),
        })
    context.update(fields)
    record = {key: context.get(key) for key in _FIELDS}
    logger.info(json.dumps({"event": event, **record}, ensure_ascii=False))


def observed_node(function):
    @wraps(function)
    def wrapped(state, *args, **kwargs):
        token = _context.set({
            "project_id": state.get("project_id"),
            "node_id": state.get("current_node_id"),
            "assessment_id": state.get("assessment_id"),
            "node": function.__name__,
        })
        started = perf_counter()
        error_type = None
        try:
            return function(state, *args, **kwargs)
        except Exception as exc:
            error_type = type(exc).__name__
            raise
        finally:
            log_event("node_finished", elapsed_ms=round((perf_counter() - started) * 1000, 3),
                      error_type=error_type)
            _context.reset(token)
    return wrapped


def configure_logging(path):
    """演示入口保存 JSONL；库代码不修改全局 logging 配置。"""
    from pathlib import Path
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not any(isinstance(h, logging.FileHandler) and h.baseFilename == str(path)
               for h in logger.handlers):
        handler = logging.FileHandler(path, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
