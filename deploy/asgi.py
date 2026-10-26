"""Bounded evaluation gateway around the unchanged V3 application."""
import asyncio
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import sqlite3

from app.v3.learning_api import create_learning_app
from app.v3.storage import V3Paths


class EvaluationGateway:
    def __init__(self, application, paths, quota_path):
        self.application = application
        self.paths = paths
        self.quota_path = Path(quota_path)
        self.active_writes = 0

    async def reply(self, send, status, value):
        body = json.dumps(value, ensure_ascii=False).encode()
        await send({'type': 'http.response.start', 'status': status, 'headers': [
            (b'content-type', b'application/json; charset=utf-8'),
            (b'cache-control', b'no-store'), (b'x-content-type-options', b'nosniff')]})
        await send({'type': 'http.response.body', 'body': body})

    def reserve(self, user):
        day = datetime.now(timezone(timedelta(hours=8))).date().isoformat()
        self.quota_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.quota_path, timeout=5) as conn:
            conn.execute('CREATE TABLE IF NOT EXISTS usage (day TEXT, account TEXT, used INTEGER NOT NULL, PRIMARY KEY(day,account))')
            conn.execute('BEGIN IMMEDIATE')
            total = conn.execute('SELECT COALESCE(SUM(used),0) FROM usage WHERE day=?', (day,)).fetchone()[0]
            row = conn.execute('SELECT used FROM usage WHERE day=? AND account=?', (day, user)).fetchone()
            if total >= int(os.environ.get('SKILLTREE_DAILY_WRITES', '120')) or (row and row[0] >= int(os.environ.get('SKILLTREE_ACCOUNT_DAILY_WRITES', '40'))):
                return False
            conn.execute('INSERT INTO usage VALUES (?,?,1) ON CONFLICT(day,account) DO UPDATE SET used=used+1', (day, user))
        return True

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.application(scope, receive, send)
        path, method = scope['path'], scope['method']
        if path == '/healthz' and method == 'GET':
            try:
                with sqlite3.connect(self.paths.learning.as_uri() + '?mode=ro', uri=True) as conn:
                    conn.execute('SELECT 1 FROM runtime_metadata LIMIT 1').fetchone()
                if not self.paths.checkpoints.is_file() or not (self.paths.root / 'learning-checkpoints.sqlite').is_file():
                    raise RuntimeError('missing checkpoint store')
                return await self.reply(send, 200, {'status': 'ok', 'version': os.environ.get('SKILLTREE_COMMIT', 'unknown')})
            except Exception:
                return await self.reply(send, 503, {'status': 'unhealthy'})
        allowed = path == '/' or path == '/capabilities' or path.startswith('/assets/') or path == '/projects' or path.startswith('/projects/') or path == '/material-packs' or path.startswith('/material-packs/')
        if not allowed or method not in {'GET', 'HEAD', 'POST', 'PATCH'}:
            return await self.reply(send, 403, {'error': {'code': 'evaluation_restricted', 'message': '评审环境不开放此操作。'}})
        headers = dict(scope['headers'])
        length = headers.get(b'content-length', b'0')
        if not length.isdigit() or int(length) > 262144:
            return await self.reply(send, 413, {'error': {'code': 'request_too_large', 'message': '请求超过大小限制。'}})
        if method in {'POST', 'PATCH'}:
            user = headers.get(b'x-evaluation-user', b'local').decode('ascii', errors='ignore')
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', user):
                user = 'local'
            if self.active_writes >= 2:
                return await self.reply(send, 429, {'error': {'code': 'busy', 'message': '服务正在处理其他学习操作，请稍后重试。'}})
            self.active_writes += 1
            try:
                if not await asyncio.to_thread(self.reserve, user):
                    return await self.reply(send, 429, {'error': {'code': 'daily_limit', 'message': '今日体验操作额度已用完，请联系演示负责人。'}})
                return await self.application(scope, receive, send)
            finally:
                self.active_writes -= 1
        return await self.application(scope, receive, send)


def create_app():
    paths = V3Paths(Path(os.environ.get('SKILLTREE_DATA_ROOT', 'data/v3')))
    # Intern-S2 may reason for up to 120 seconds before returning non-streaming
    # JSON. Configure transport here; retain business budgets and deep thinking.
    def production_model():
        from langchain_openai import ChatOpenAI
        from app.services.llm import get_llm
        model = get_llm()
        seconds = float(os.environ.get('SKILLTREE_MODEL_TIMEOUT', '150'))
        if not 45 <= seconds <= 180:
            raise ValueError('Deployment model timeout must be 45..180 seconds')
        # Construct the SDK client with the timeout. Changing a Pydantic field
        # on an already-built model leaves its underlying HTTP client unchanged.
        return ChatOpenAI(model=model.model_name, api_key=model.openai_api_key,
                          base_url=model.openai_api_base, temperature=model.temperature,
                          timeout=seconds, max_retries=0)
    return EvaluationGateway(create_learning_app(paths, llm=production_model), paths, os.environ.get('SKILLTREE_QUOTA_DB', 'data/deployment-quota.sqlite'))
