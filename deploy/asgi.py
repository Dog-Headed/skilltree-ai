"""Bounded evaluation gateway around the unchanged V3 application."""
import asyncio
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import sqlite3
import hmac
from http.cookies import SimpleCookie
from urllib.parse import quote
from uuid import UUID

from app.v3.learning_api import create_learning_app
from app.v3.storage import V3Paths
from .ownership import Ownership
from .provider import StrictProvider, create_runtime_model
from .auth import GUEST_SECONDS, AuthStore, csrf_token
from .jobs import AdmissionError, JobStore, JobRunner


class EvaluationGateway:
    def __init__(self, application, paths, quota_path, *, auth_store=None, queued=False,
                 origin='https://skilltree.goutouren.work', cookie_secure=True, queue_capacity=10, cookie_name=None,
                 guest_access=True):
        self.application = application
        self.paths = paths
        self.quota_path = Path(quota_path).resolve()
        self.ownership = Ownership(self.quota_path)
        self.active_writes = 0
        self.auth = auth_store
        self.origin = origin.rstrip('/')
        self.cookie_secure = cookie_secure
        self.cookie_name = cookie_name or ('__Host-skilltree_session' if cookie_secure else 'skilltree_session')
        self.auth_slots = asyncio.Semaphore(2)
        # A first visit to the garden gets a guest identity instead of a sign-in wall.
        self.guest_access = guest_access
        self.jobs = JobStore(self.quota_path, capacity=queue_capacity) if queued else None
        self.runner = JobRunner(self.jobs, application, self.origin) if queued else None

    async def reply(self, send, status, value, extra_headers=()):
        body = json.dumps(value, ensure_ascii=False).encode()
        await send({'type': 'http.response.start', 'status': status, 'headers': [
            (b'content-type', b'application/json; charset=utf-8'),
            (b'cache-control', b'no-store'), (b'x-content-type-options', b'nosniff'), *extra_headers]})
        await send({'type': 'http.response.body', 'body': body})

    def reserve(self, user):
        day = datetime.now(timezone(timedelta(hours=8))).date().isoformat()
        self.quota_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.quota_path, timeout=5) as conn:
            conn.execute('CREATE TABLE IF NOT EXISTS usage (day TEXT, account TEXT, used INTEGER NOT NULL, PRIMARY KEY(day,account))')
            conn.execute('BEGIN IMMEDIATE')
            total = conn.execute('SELECT COALESCE(SUM(used),0) FROM usage WHERE day=?', (day,)).fetchone()[0]
            row = conn.execute('SELECT used FROM usage WHERE day=? AND account=?', (day, user)).fetchone()
            if total >= int(os.environ.get('SKILLTREE_DAILY_WRITES', '3000')) or (row and row[0] >= int(os.environ.get('SKILLTREE_ACCOUNT_DAILY_WRITES', '300'))):
                return False
            conn.execute('INSERT INTO usage VALUES (?,?,1) ON CONFLICT(day,account) DO UPDATE SET used=used+1', (day, user))
        return True

    async def body(self, receive, maximum=262144):
        body = b''
        while True:
            message = await receive()
            if message['type'] == 'http.disconnect':
                raise AdmissionError('disconnected', '连接已断开，请先刷新状态。', 400)
            body += message.get('body', b'')
            if len(body) > maximum:
                raise AdmissionError('request_too_large', '请求超过大小限制。', 413)
            if not message.get('more_body'):
                return body

    def cookie(self, token='', remember=False, max_age=2592000):
        value = f'{self.cookie_name}={token}; Path=/; HttpOnly; SameSite=Lax'
        if self.cookie_secure:
            value += '; Secure'
        if remember or not token:
            value += '; Max-Age=' + (str(max_age) if token else '0')
        return value.encode()

    async def authenticated(self, scope, receive, send):
        path, method, headers = scope['path'], scope['method'], dict(scope['headers'])
        try:
            cookies = SimpleCookie(); cookies.load(headers.get(b'cookie', b'').decode('latin1'))
            token = cookies[self.cookie_name].value if self.cookie_name in cookies else ''
        except Exception:
            token = ''
        account = await asyncio.to_thread(self.auth.session, token)
        if method in ('POST', 'PATCH', 'DELETE'):
            origin = headers.get(b'origin', b'').decode('latin1')
            cross_site = headers.get(b'sec-fetch-site') == b'cross-site'
            if cross_site or (origin and origin.rstrip('/') != self.origin):
                await self.reply(send, 403, {'error': {'code': 'invalid_origin', 'message': '请从当前网站提交。'}})
                return None, token
        if path in {'/auth/login', '/auth/register'} and method == 'POST':
            if headers.get(b'x-skilltree-login') != b'1' or headers.get(b'content-type', b'').split(b';')[0].strip() != b'application/json':
                await self.reply(send, 403, {'error': {'code': 'invalid_origin', 'message': '请使用登录页面。'}})
                return None, token
            try:
                value = json.loads(await self.body(receive, 4096))
                if not isinstance(value, dict) or not isinstance(value.get('remember', False), bool):
                    raise ValueError()
                registering = path == '/auth/register'
                if registering and value.get('password') != value.get('confirm_password'):
                    raise ValueError()
                guest = account if account and await asyncio.to_thread(self.auth.is_guest, account) else None
                if guest and not registering and self.jobs and await asyncio.to_thread(self.jobs.active, guest):
                    await self.reply(send, 409, {'error': {'code': 'account_busy', 'message': '你有一个学习任务还在处理，等它完成后再登录。'}})
                    return None, token
                ip = str((scope.get('client') or ('unknown',))[0])
                async with self.auth_slots:
                    if registering:
                        result = await asyncio.to_thread(self.auth.register, value.get('account'), value.get('password'), ip, value.get('remember', False), guest)
                    else:
                        result = await asyncio.to_thread(self.auth.login, value.get('account'), value.get('password'), ip, value.get('remember', False))
                if result['status'] in (200, 201):
                    # Signing in from a guest session brings the guest's courses along.
                    if guest and result['account'] != guest:
                        adopted = await asyncio.to_thread(self.ownership.adopt, guest, result['account'])
                        if not adopted:
                            await asyncio.to_thread(self.auth.logout, result['token'])
                            await self.reply(send, 409, {'error': {'code': 'account_busy', 'message': '学习任务还在处理，原课程和访客登录已保留，请完成后再登录。'}})
                            return None, token
                    if token:
                        await asyncio.to_thread(self.auth.logout, token)
                    await self.reply(send, result['status'], {'account': result['account'], 'csrf_token': csrf_token(result['token'])},
                                     [(b'set-cookie', self.cookie(result['token'], value.get('remember', False)))])
                else:
                    status = result['status']; retry = result.get('retry_after', 0)
                    code = result.get('code', 'rate_limited' if status == 429 else 'invalid_credentials')
                    message = {'rate_limited': '尝试过于频繁，请稍后再试。', 'email_taken': '该邮箱已注册，请直接登录。',
                               'registration_closed': '本轮公测注册名额已满，请稍后再来。',
                               'guest_session_changed': '当前访客状态已变化，请刷新页面后重新登录。',
                               'invalid_input': '请填写有效邮箱和至少 10 位密码。'}.get(code, '邮箱或密码不正确。')
                    await self.reply(send, status, {'error': {'code': code,
                                      'message': message, 'retry_after': retry}},
                                     [(b'retry-after', str(retry).encode())] if retry else [])
            except (ValueError, TypeError, AdmissionError):
                await self.reply(send, 422, {'error': {'code': 'invalid_input', 'message': '请检查登录信息。'}})
            return None, token
        if not account and self.guest_access and method == 'GET' and path == '/':
            guest = await asyncio.to_thread(self.auth.create_guest, str((scope.get('client') or ('unknown',))[0]))
            if guest:
                scope['skilltree_set_cookie'] = self.cookie(guest['token'], True, GUEST_SECONDS)
                return guest['account'], guest['token']
        if not account:
            if method in ('GET', 'HEAD') and (path == '/' or path == '/login' or path.startswith('/assets/') or path == '/healthz'):
                if path == '/':
                    await self.reply(send, 303, {}, [(b'location', ('/login?next=' + quote('/', safe='')).encode())])
                else:
                    return '', token
            else:
                await self.reply(send, 401, {'error': {'code': 'invalid_account', 'message': '请先登录。'}})
            return None, token
        if method in ('POST', 'PATCH', 'DELETE'):
            actual = headers.get(b'x-csrf-token', b'')
            if not hmac.compare_digest(actual, csrf_token(token).encode()):
                await self.reply(send, 403, {'error': {'code': 'csrf_failed', 'message': '登录状态已更新，请刷新页面后再操作。'}})
                return None, token
            if path == '/auth/logout' and method == 'POST':
                await asyncio.to_thread(self.auth.logout, token)
                await self.reply(send, 200, {'signed_out': True}, [(b'set-cookie', self.cookie())])
                return None, token
            if headers.get(b'content-type', b'').split(b';')[0].strip() != b'application/json':
                await self.reply(send, 415, {'error': {'code': 'json_required', 'message': '请使用当前页面提交。'}})
                return None, token
        return account, token

    async def queued_write(self, scope, receive, send, user, project):
        try:
            raw = await self.body(receive)
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ValueError()
            path, method = scope['path'], scope['method']
            slow = method == 'POST' and project and (path.endswith(('/begin', '/retry')) or
                   (path.endswith('/resume') and payload.get('action') not in {'rest', 'update_profile', 'adjust_scope', 'confirm_plan', 'choose_exploration'}))
            if self.runner.stopping:
                raise AdmissionError('restarting', '服务正在更新，请稍后重试；本次未扣额度。', 503)
            if slow:
                job_id = await asyncio.to_thread(self.jobs.admit, user, project, method, path, payload)
                job = await asyncio.to_thread(self.jobs.public, job_id, user)
                return await self.reply(send, 202, {'job': job}, [(b'location', ('/jobs/' + job_id).encode())])
            if self.active_writes >= 8:
                raise AdmissionError('busy', '操作较多，请稍后重试。')
            self.active_writes += 1
            try:
                pid = None
                if path == '/projects' and method == 'POST':
                    try:
                        pid = 'v3_' + UUID(payload['request_id']).hex
                    except (ValueError, TypeError, KeyError, AttributeError):
                        raise AdmissionError('invalid_input', '请求身份无效。', 422) from None
                await asyncio.to_thread(self.jobs.reserve_fast, user, project, pid)
                delivered = False
                async def replay():
                    nonlocal delivered
                    if not delivered:
                        delivered = True
                        return {'type': 'http.request', 'body': raw, 'more_body': False}
                    return await receive()
                return await self.application(scope, replay, send)
            finally:
                self.active_writes -= 1
        except AdmissionError as exc:
            return await self.reply(send, exc.status, {'error': {'code': exc.code, 'message': exc.message}})
        except (ValueError, TypeError):
            return await self.reply(send, 422, {'error': {'code': 'invalid_input', 'message': '请检查请求内容。'}})

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'lifespan' and self.runner:
            async def lifecycle():
                message = await receive()
                if message['type'] == 'lifespan.startup':
                    await self.runner.start()
                elif message['type'] == 'lifespan.shutdown':
                    await self.runner.stop()
                return message
            return await self.application(scope, lifecycle, send)
        if scope['type'] != 'http':
            return await self.application(scope, receive, send)
        path, method = scope['path'], scope['method']
        headers = dict(scope['headers'])
        # Nginx replaces this header after successful HTTP authentication. Both
        # application ports bind only to loopback; they are never public.
        user = headers.get(b'x-evaluation-user', b'local').decode('ascii', errors='ignore')
        token = ''
        if self.auth:
            user, token = await self.authenticated(scope, receive, send)
            if user is None:
                return
            if scope.get('skilltree_set_cookie'):
                original_send, cookie = send, scope['skilltree_set_cookie']
                async def send(message):
                    if message['type'] == 'http.response.start':
                        message = {**message, 'headers': [*message.get('headers', []), (b'set-cookie', cookie)]}
                    await original_send(message)
        if not self.auth and not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', user):
            return await self.reply(send, 401, {'error': {'code': 'invalid_account', 'message': '请重新登录。'}})
        if path == '/session' and method == 'GET':
            guest = bool(self.auth and await asyncio.to_thread(self.auth.is_guest, user))
            return await self.reply(send, 200, {'account': user, **({'login': await asyncio.to_thread(self.auth.login_name, user), 'csrf_token': csrf_token(token), 'guest': guest, 'logout': not guest} if self.auth else {})})
        if self.jobs and path.startswith('/jobs') and method == 'GET':
            job = await asyncio.to_thread(self.jobs.active, user) if path == '/jobs/active' else await asyncio.to_thread(self.jobs.public, path.removeprefix('/jobs/'), user)
            if job is None and path != '/jobs/active':
                return await self.reply(send, 404, {'error': {'code': 'not_found', 'message': '任务不存在。'}})
            return await self.reply(send, 200, {'job': job})
        if path == '/healthz' and method == 'GET':
            try:
                with sqlite3.connect(self.paths.learning.as_uri() + '?mode=ro', uri=True) as conn:
                    conn.execute('SELECT 1 FROM runtime_metadata LIMIT 1').fetchone()
                if not self.paths.checkpoints.is_file() or not (self.paths.root / 'learning-checkpoints.sqlite').is_file():
                    raise RuntimeError('missing checkpoint store')
                return await self.reply(send, 200, {'status': 'ok', 'version': os.environ.get('SKILLTREE_COMMIT', 'unknown')})
            except Exception:
                return await self.reply(send, 503, {'status': 'unhealthy'})
        allowed = path in {'/', '/login', '/capabilities'} or path.startswith('/assets/') or path == '/projects' or path.startswith('/projects/') or path == '/material-packs' or path.startswith('/material-packs/')
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
            scope.setdefault('state', {})['allowed_project_ids'] = owned
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
            if self.jobs:
                return await self.queued_write(scope, receive, send, user, match[1] if match else None)
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
    # LearningService expects an actual model instance; its own provider method
    # already supplies lazy access to durable model tasks.
    return EvaluationGateway(create_learning_app(paths, llm=create_runtime_model(),
        quiz_generation_mode=os.getenv('SKILLTREE_QUIZ_GENERATION', 'legacy'),
        preparation_generation_mode=os.getenv('SKILLTREE_PREPARATION_GENERATION', 'legacy')), paths,
        os.environ.get('SKILLTREE_QUOTA_DB', 'data/deployment-quota.sqlite'),
        auth_store=AuthStore(os.getenv('SKILLTREE_AUTH_DB', 'data/auth.sqlite')), queued=True,
        origin=os.getenv('SKILLTREE_PUBLIC_ORIGIN', 'https://skilltree.goutouren.work'))
