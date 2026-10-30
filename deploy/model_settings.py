"""Account-scoped model choices. Credentials never enter course DTOs or jobs."""
from contextvars import ContextVar
from contextlib import contextmanager
from dataclasses import dataclass, field
from functools import lru_cache
import json
import os
from pathlib import Path
import re
import sqlite3
import time

from cryptography.fernet import Fernet, InvalidToken
from .jobs import AdmissionError


def ensure_local_key_file(path):
    """Initialize the workstation's encryption key once, with owner-only access."""
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return path
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(Fernet.generate_key())
        if os.name == 'nt':
            import csv
            import subprocess
            identity = subprocess.check_output(['whoami', '/user', '/fo', 'csv', '/nh'], text=True)
            sid = next(csv.reader(identity.splitlines()))[1]
            subprocess.run(['icacls', str(path), '/inheritance:r', '/grant:r', '*' + sid + ':F'],
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return path


@dataclass(frozen=True)
class ProviderConfig:
    label: str
    model: str
    base_url: str
    api_key: str = field(repr=False)
    thinking: str = 'auto'


def platform_configs():
    return {
        'deepseek': ProviderConfig('DeepSeek', os.getenv('SKILLTREE_DEEPSEEK_MODEL', 'deepseek-flash'),
            os.getenv('SKILLTREE_DEEPSEEK_BASE_URL', 'https://api.deepseek.com/v1'),
            os.getenv('SKILLTREE_DEEPSEEK_API_KEY', '')),
        'intern': ProviderConfig('书生 Intern-S2', os.getenv('LLM_MODEL', 'intern-s2'),
            os.getenv('LLM_BASE_URL', 'https://chat.intern-ai.org.cn/api/v1'),
            os.getenv('LLM_API_KEY', ''), os.getenv('SKILLTREE_THINKING_MODE', 'false')),
    }


class ModelSettings:
    def __init__(self, database, key_file, configs=None):
        self.database = Path(database).resolve()
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self.cipher = Fernet(Path(key_file).read_bytes().strip())
        self.configs = configs if configs is not None else platform_configs()
        if set(self.configs) != {'deepseek', 'intern'}:
            raise ValueError('Exactly two configured providers required')
        # Same database and transaction lock as queue admission: a model cannot
        # change between the busy check and an AI request being queued.
        with self.connect() as conn:
            conn.executescript('''
              CREATE TABLE IF NOT EXISTS account_model_settings(
                account TEXT PRIMARY KEY,provider TEXT NOT NULL,key_source TEXT NOT NULL,updated REAL NOT NULL);
              CREATE TABLE IF NOT EXISTS account_model_secrets(
                account TEXT NOT NULL,provider TEXT NOT NULL,ciphertext TEXT NOT NULL,
                PRIMARY KEY(account,provider));
              CREATE TABLE IF NOT EXISTS account_model_ticks(account TEXT NOT NULL,at REAL NOT NULL);
              CREATE TABLE IF NOT EXISTS account_model_runs(
                job_id TEXT PRIMARY KEY,account TEXT NOT NULL,provider TEXT NOT NULL,
                key_source TEXT NOT NULL,model TEXT NOT NULL,created REAL NOT NULL);
            ''')

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.database, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    @staticmethod
    def busy(conn, account):
        return bool(conn.execute("SELECT 1 FROM sqlite_master WHERE name='deployment_jobs'").fetchone()
            and conn.execute("SELECT 1 FROM deployment_jobs WHERE account=? AND state IN ('queued','running')", (account,)).fetchone())

    def public(self, account):
        with self.connect() as conn:
            row = conn.execute('SELECT provider,key_source,updated FROM account_model_settings WHERE account=?', (account,)).fetchone()
            saved = {r[0] for r in conn.execute('SELECT provider FROM account_model_secrets WHERE account=?', (account,))}
            return {'provider': row['provider'] if row else 'deepseek',
                'key_source': row['key_source'] if row else 'platform',
                'updated_at': row['updated'] if row else None, 'busy': self.busy(conn, account),
                'providers': [{'id': p, 'label': c.label, 'model': c.model,
                    'platform_available': bool(c.api_key), 'has_personal_key': p in saved}
                    for p, c in self.configs.items()]}

    def update(self, account, payload):
        allowed = {'provider', 'key_source', 'api_key', 'remove_key'}
        if not isinstance(payload, dict) or set(payload) - allowed:
            raise AdmissionError('invalid_input', '请检查模型设置。', 422)
        provider, source = payload.get('provider'), payload.get('key_source')
        if not isinstance(provider, str) or provider not in self.configs or source not in ('platform', 'personal'):
            raise AdmissionError('invalid_input', '请选择 DeepSeek 或书生，以及密钥来源。', 422)
        key, remove = payload.get('api_key', ''), payload.get('remove_key', False)
        if not isinstance(key, str) or type(remove) is not bool:
            raise AdmissionError('invalid_input', '请检查 API Key。', 422)
        key = key.strip()
        if key and (not re.fullmatch(r'[!-~]{16,512}', key) or remove):
            raise AdmissionError('invalid_input', 'API Key 格式不正确。', 422)
        with self.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            if self.busy(conn, account):
                raise AdmissionError('account_busy', '学习任务还在处理或排队，完成后才能切换模型。', 409)
            at = time.time()
            conn.execute('DELETE FROM account_model_ticks WHERE at<?', (at-60,))
            if conn.execute('SELECT COUNT(*) FROM account_model_ticks WHERE account=?', (account,)).fetchone()[0] >= 10:
                raise AdmissionError('rate_limited', '设置修改过于频繁，请稍后再试。')
            conn.execute('INSERT INTO account_model_ticks VALUES (?,?)', (account, at))
            if remove:
                conn.execute('DELETE FROM account_model_secrets WHERE account=? AND provider=?', (account, provider))
            if key:
                encoded = json.dumps({'account': account, 'provider': provider, 'key': key}).encode()
                encrypted = self.cipher.encrypt(encoded).decode()
                conn.execute('INSERT INTO account_model_secrets VALUES (?,?,?) ON CONFLICT(account,provider) DO UPDATE SET ciphertext=excluded.ciphertext', (account, provider, encrypted))
            saved = conn.execute('SELECT 1 FROM account_model_secrets WHERE account=? AND provider=?', (account, provider)).fetchone()
            if source == 'personal' and not saved:
                raise AdmissionError('key_required', '请先填写这个模型的 API Key，或选择使用平台额度。', 422)
            if source == 'platform' and not self.configs[provider].api_key:
                raise AdmissionError('model_unavailable', '这个模型的平台密钥暂未配置，请填写自己的 API Key。', 503)
            conn.execute('INSERT INTO account_model_settings VALUES (?,?,?,?) ON CONFLICT(account) DO UPDATE SET provider=excluded.provider,key_source=excluded.key_source,updated=excluded.updated', (account, provider, source, at))
        return self.public(account)

    def resolve(self, account):
        with self.connect() as conn:
            row = conn.execute('SELECT provider,key_source FROM account_model_settings WHERE account=?', (account,)).fetchone()
            provider, source = tuple(row) if row else ('deepseek', 'platform')
            cfg = self.configs[provider]
            key = cfg.api_key
            if source == 'personal':
                secret = conn.execute('SELECT ciphertext FROM account_model_secrets WHERE account=? AND provider=?', (account, provider)).fetchone()
                try:
                    value = json.loads(self.cipher.decrypt(secret[0].encode()))
                    if value['account'] != account or value['provider'] != provider:
                        raise ValueError()
                    key = value['key']
                except (InvalidToken, TypeError, ValueError, KeyError):
                    raise AdmissionError('model_unavailable', '个人密钥无法读取，请重新保存；不会改用平台额度。', 503) from None
            if not key:
                raise AdmissionError('model_unavailable', '当前模型暂不可用，请在模型设置中选择其他模型或填写 API Key。', 503)
            return provider, source, ProviderConfig(cfg.label, cfg.model, cfg.base_url, key, cfg.thinking)


_current_model = ContextVar('skilltree_account_model', default=None)


class AccountModel:
    """A real model proxy, resolved inside each HTTP/job context, never globally."""
    def current(self):
        model = _current_model.get()
        if model is None:
            raise RuntimeError('No authenticated model context')
        return model

    def invoke(self, *args, **kwargs):
        return self.current().invoke(*args, **kwargs)

    def with_structured_output(self, *args, **kwargs):
        return self.current().with_structured_output(*args, **kwargs)

    def bind_tools(self, *args, **kwargs):
        return self.current().bind_tools(*args, **kwargs)


def build_model(cfg):
    from langchain_openai import ChatOpenAI
    from .provider import create_runtime_model
    model = ChatOpenAI(model=cfg.model, api_key=cfg.api_key, base_url=cfg.base_url,
                      temperature=0, max_retries=0, timeout=150)
    return create_runtime_model(model=model, thinking=cfg.thinking,
        extra_body_override={'thinking': {'type': 'disabled'}} if cfg.model.startswith('deepseek-') else None)


class ModelScopedApplication:
    def __init__(self, application, settings, factory=build_model):
        self.application, self.settings, self.factory = application, settings, factory

    @lru_cache(maxsize=2)
    def platform_model(self, provider):
        return self.factory(self.settings.configs[provider])

    def model_for(self, account, job_id=None):
        provider, source, cfg = self.settings.resolve(account)
        model = self.platform_model(provider) if source == 'platform' else self.factory(cfg)
        if job_id:
            with self.settings.connect() as conn:
                conn.execute('INSERT OR IGNORE INTO account_model_runs VALUES (?,?,?,?,?,?)',
                    (job_id, account, provider, source, cfg.model, time.time()))
        return model

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope['method'] not in ('POST', 'PATCH'):
            return await self.application(scope, receive, send)
        import asyncio
        try:
            account = scope.get('skilltree_account')
            if not account:
                raise AdmissionError('invalid_account', '请刷新登录状态。', 401)
            model = await asyncio.to_thread(self.model_for, account, scope.get('skilltree_job_id'))
        except AdmissionError as exc:
            body = json.dumps({'error': {'code': exc.code, 'message': exc.message}}, ensure_ascii=False).encode()
            await send({'type': 'http.response.start', 'status': exc.status,
                        'headers': [(b'content-type', b'application/json'), (b'cache-control', b'no-store')]})
            return await send({'type': 'http.response.body', 'body': body})
        context = _current_model.set(model)
        try:
            return await self.application(scope, receive, send)
        finally:
            _current_model.reset(context)
