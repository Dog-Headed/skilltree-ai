"""Bounded evaluation gateway around the unchanged V3 application."""
import asyncio
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import sqlite3
from uuid import UUID

from app.v3.learning_api import create_learning_app
from app.v3.storage import V3Paths
from .ownership import Ownership


class EvaluationGateway:
    def __init__(self, application, paths, quota_path):
        self.application = application
        self.paths = paths
        self.quota_path = Path(quota_path).resolve()
        self.ownership = Ownership(self.quota_path)
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
        headers = dict(scope['headers'])
        # Nginx replaces this header after successful HTTP authentication. Both
        # application ports bind only to loopback; they are never public.
        user = headers.get(b'x-evaluation-user', b'local').decode('ascii', errors='ignore')
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', user):
            return await self.reply(send, 401, {'error': {'code': 'invalid_account', 'message': '请重新登录。'}})
        if path == '/session' and method == 'GET':
            return await self.reply(send, 200, {'account': user})
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
        length = headers.get(b'content-length', b'0')
        if not length.isdigit() or int(length) > 262144:
            return await self.reply(send, 413, {'error': {'code': 'request_too_large', 'message': '请求超过大小限制。'}})
        match = re.match(r'^/projects/([^/]+)(?:/|$)', path)
        if match and match[1] not in await asyncio.to_thread(self.ownership.owned, user):
            return await self.reply(send, 404, {'error': {'code': 'not_found', 'message': '项目或记录不存在。'}})
        if path == '/projects' and method == 'GET':
            owned = await asyncio.to_thread(self.ownership.owned, user)
            if not owned:
                return await self.reply(send, 200, [])
            chunks = []
            status = 500
            async def capture(message):
                nonlocal status
                if message['type'] == 'http.response.start':
                    status = message['status']
                elif message['type'] == 'http.response.body':
                    chunks.append(message.get('body', b''))
            await self.application(scope, receive, capture)
            value = json.loads(b''.join(chunks))
            if status == 200:
                value = [p for p in value if p.get('project_id') in owned]
            return await self.reply(send, status, value)
        if method in {'POST', 'PATCH'}:
            if self.active_writes >= 2:
                return await self.reply(send, 429, {'error': {'code': 'busy', 'message': '服务正在处理其他学习操作，请稍后重试。'}})
            self.active_writes += 1
            try:
                if not await asyncio.to_thread(self.reserve, user):
                    return await self.reply(send, 429, {'error': {'code': 'daily_limit', 'message': '今日体验操作额度已用完，请联系演示负责人。'}})
                if path == '/projects' and method == 'POST':
                    body = b''
                    while True:
                        message = await receive()
                        if message['type'] == 'http.disconnect':
                            return
                        body += message.get('body', b'')
                        if len(body) > 262144:
                            return await self.reply(send, 413, {'error': {'code': 'request_too_large', 'message': '请求超过大小限制。'}})
                        if not message.get('more_body'):
                            break
                    try:
                        project_id = 'v3_' + UUID(json.loads(body)['request_id']).hex
                    except (ValueError, TypeError, KeyError, AttributeError):
                        project_id = None
                    if project_id and not await asyncio.to_thread(self.ownership.claim, project_id, user):
                        return await self.reply(send, 404, {'error': {'code': 'not_found', 'message': '项目或记录不存在。'}})
                    original_receive = receive
                    delivered = False
                    async def replay():
                        nonlocal delivered
                        if not delivered:
                            delivered = True
                            return {'type': 'http.request', 'body': body, 'more_body': False}
                        return await original_receive()
                    receive = replay
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
        thinking = os.environ.get('SKILLTREE_THINKING_MODE', 'auto').lower()
        if thinking not in {'auto', 'true', 'false'}:
            raise ValueError('Thinking mode must be auto, true, or false')
        extra_body = None if thinking == 'auto' else {'thinking_mode': thinking == 'true'}
        # Construct the SDK client with the timeout. Changing a Pydantic field
        # on an already-built model leaves its underlying HTTP client unchanged.
        return ChatOpenAI(model=model.model_name, api_key=model.openai_api_key,
                          base_url=model.openai_api_base, temperature=model.temperature,
                          timeout=seconds, max_retries=0, extra_body=extra_body)
    # LearningService expects an actual model instance; its own provider method
    # already supplies lazy access to durable model tasks.
    return EvaluationGateway(create_learning_app(paths, llm=production_model()), paths, os.environ.get('SKILLTREE_QUOTA_DB', 'data/deployment-quota.sqlite'))
