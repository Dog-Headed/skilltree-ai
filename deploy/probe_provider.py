"""Tiny JSON-mode compatibility probe; never logs keys or request headers."""
import json
import time

from langchain_core.messages import HumanMessage
from pydantic import BaseModel

from app.services.llm import get_llm


class Probe(BaseModel):
    ok: bool


if __name__ == '__main__':
    for mode in ('default', 'no_thinking'):
        model = get_llm()
        if mode == 'no_thinking':
            model = model.model_copy(update={'extra_body': {'thinking_mode': False}})
        start = time.monotonic()
        try:
            result = model.with_structured_output(Probe, method='json_mode').invoke([HumanMessage(content='Return only JSON: {"ok":true}')])
            print(json.dumps({'mode': mode, 'elapsed_seconds': round(time.monotonic()-start, 2), 'valid': result.ok}), flush=True)
        except Exception as exc:
            print(json.dumps({'mode': mode, 'elapsed_seconds': round(time.monotonic()-start, 2), 'error_type': type(exc).__name__, 'cause_type': type(exc.__cause__).__name__, 'status_code': getattr(exc, 'status_code', None)}), flush=True)
