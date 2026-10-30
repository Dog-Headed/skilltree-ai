"""Small durable FIFO for two AI workflows, with one active job per identity.

Running jobs are NEVER automatically replayed after a process interruption.
Persisted queued inputs may start after restart; interrupted inputs require the
existing read-first workflow recovery. No worker holds a SQLite transaction while
calling the application or a model.
"""
import asyncio
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import sqlite3
import time
from uuid import uuid4


class AdmissionError(Exception):
    def __init__(self, code, message, status=429):
        self.code, self.message, self.status = code, message, status


def reserve_quota(conn, account):
    day = datetime.now(timezone(timedelta(hours=8))).date().isoformat()
    conn.execute('CREATE TABLE IF NOT EXISTS usage(day TEXT,account TEXT,used INTEGER NOT NULL,PRIMARY KEY(day,account))')
    total = conn.execute('SELECT COALESCE(SUM(used),0) FROM usage WHERE day=?', (day,)).fetchone()[0]
    row = conn.execute('SELECT used FROM usage WHERE day=? AND account=?', (day, account)).fetchone()
    if total >= int(os.getenv('SKILLTREE_DAILY_WRITES', '3000')) or (row and row[0] >= int(os.getenv('SKILLTREE_ACCOUNT_DAILY_WRITES', '300'))):
        raise AdmissionError('daily_limit', '今日体验操作额度已用完，请联系管理员。')
    conn.execute('INSERT INTO usage VALUES (?,?,1) ON CONFLICT(day,account) DO UPDATE SET used=used+1', (day, account))


class JobStore:
    def __init__(self, database, capacity=10):
        self.database = Path(database).resolve()
        self.capacity = capacity  # Includes the two running workflows.
        self.database.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript('''
              CREATE TABLE IF NOT EXISTS deployment_jobs(
                id TEXT PRIMARY KEY,account TEXT NOT NULL,project_id TEXT NOT NULL,
                method TEXT NOT NULL,path TEXT NOT NULL,request_key TEXT NOT NULL,
                body_hash TEXT NOT NULL,body BLOB NOT NULL,state TEXT NOT NULL,
                created REAL NOT NULL,started REAL,finished REAL,status_code INTEGER,result BLOB,
                UNIQUE(account,method,path,request_key));
              CREATE UNIQUE INDEX IF NOT EXISTS deployment_one_active_account
                ON deployment_jobs(account) WHERE state IN ('queued','running');
              CREATE INDEX IF NOT EXISTS deployment_queue ON deployment_jobs(state,created);
              CREATE TABLE IF NOT EXISTS deployment_write_ticks(account TEXT NOT NULL,at REAL NOT NULL);
              CREATE INDEX IF NOT EXISTS deployment_write_rate ON deployment_write_ticks(account,at);
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

    def admit(self, account, project, method, path, payload):
        key = payload.get('request_id')
        if not isinstance(key, str) or not 1 <= len(key) <= 128:
            raise AdmissionError('invalid_input', '请求身份无效，请刷新页面。', 422)
        body = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()
        fingerprint = sha256(body).hexdigest()
        with self.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            conn.execute("DELETE FROM deployment_jobs WHERE state NOT IN ('queued','running') AND finished<?", (time.time()-259200,))
            existing = conn.execute('SELECT * FROM deployment_jobs WHERE account=? AND method=? AND path=? AND request_key=?',
                                    (account, method, path, key)).fetchone()
            if existing:
                if existing['body_hash'] != fingerprint:
                    raise AdmissionError('state_conflict', '同一请求身份不能用于不同内容。', 409)
                return existing['id']
            if conn.execute("SELECT 1 FROM deployment_jobs WHERE account=? AND state IN ('queued','running')", (account,)).fetchone():
                raise AdmissionError('account_busy', '你已有一个任务正在处理或排队，请等待完成。', 409)
            count = conn.execute("SELECT COUNT(*) FROM deployment_jobs WHERE state IN ('queued','running')").fetchone()[0]
            if count >= self.capacity:
                raise AdmissionError('queue_full', '等待人数较多，请稍后再提交；本次未扣体验额度。')
            self._rate(conn, account)
            reserve_quota(conn, account)
            job_id = uuid4().hex
            conn.execute('INSERT INTO deployment_jobs(id,account,project_id,method,path,request_key,body_hash,body,state,created) VALUES (?,?,?,?,?,?,?,?,?,?)',
                         (job_id, account, project, method, path, key, fingerprint, body, 'queued', time.time()))
            return job_id

    def _rate(self, conn, account):
        at = time.time()
        conn.execute('DELETE FROM deployment_write_ticks WHERE at<?', (at-60,))
        count = conn.execute('SELECT COUNT(*) FROM deployment_write_ticks WHERE account=?', (account,)).fetchone()[0]
        if count >= 30:
            raise AdmissionError('rate_limited', '操作有点频繁，请稍后再试。')
        conn.execute('INSERT INTO deployment_write_ticks VALUES (?,?)', (account, at))

    def reserve_fast(self, account, project=None, creation_id=None):
        with self.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            if project and conn.execute("SELECT 1 FROM deployment_jobs WHERE project_id=? AND state IN ('queued','running')", (project,)).fetchone():
                raise AdmissionError('account_busy', '这棵树的任务还在处理或排队，请先等待结果。', 409)
            if creation_id:
                conn.execute('CREATE TABLE IF NOT EXISTS project_owners(project_id TEXT PRIMARY KEY,account TEXT NOT NULL,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)')
                owner = conn.execute('SELECT account FROM project_owners WHERE project_id=?', (creation_id,)).fetchone()
                if owner and owner['account'] != account:
                    raise AdmissionError('not_found', '项目或记录不存在。', 404)
            self._rate(conn, account)
            reserve_quota(conn, account)
            if creation_id:
                conn.execute('INSERT OR IGNORE INTO project_owners(project_id,account) VALUES (?,?)', (creation_id, account))

    def claim(self):
        with self.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            if conn.execute("SELECT COUNT(*) FROM deployment_jobs WHERE state='running'").fetchone()[0] >= 2:
                return None
            row = conn.execute("SELECT * FROM deployment_jobs WHERE state='queued' ORDER BY created,rowid LIMIT 1").fetchone()
            if row:
                conn.execute("UPDATE deployment_jobs SET state='running',started=? WHERE id=?", (time.time(), row['id']))
                return dict(row)
        return None

    def finish(self, job_id, status, body):
        with self.connect() as conn:
            conn.execute('UPDATE deployment_jobs SET state=?,finished=?,status_code=?,result=?,body=x\'\' WHERE id=? AND state=\'running\'',
                         ('completed' if status < 400 else 'failed', time.time(), status, body, job_id))

    def recover(self):
        # Called only by the exclusive worker owner, after the prior process exits.
        with self.connect() as conn:
            conn.execute("UPDATE deployment_jobs SET state='interrupted',finished=?,body=x'' WHERE state='running'", (time.time(),))
            conn.execute("DELETE FROM deployment_jobs WHERE state NOT IN ('queued','running') AND finished<?", (time.time()-259200,))

    def active(self, account):
        with self.connect() as conn:
            row = conn.execute("SELECT id FROM deployment_jobs WHERE account=? AND state IN ('queued','running')", (account,)).fetchone()
        return self.public(row['id'], account) if row else None

    def public(self, job_id, account):
        with self.connect() as conn:
            row = conn.execute('SELECT * FROM deployment_jobs WHERE id=? AND account=?', (job_id, account)).fetchone()
            if not row:
                return None
            position = 0
            if row['state'] == 'queued':
                position = conn.execute("SELECT COUNT(*) FROM deployment_jobs WHERE state='queued' AND rowid<=(SELECT rowid FROM deployment_jobs WHERE id=?)", (job_id,)).fetchone()[0]
            value = {'id': row['id'], 'state': row['state'], 'project_id': row['project_id'], 'position': position}
            if row['state'] in ('completed', 'failed'):
                value['status_code'] = row['status_code']
                value['result'] = json.loads(row['result'])
            return value


class WorkerLease:
    """Fail startup rather than silently multiply queue executors with workers."""
    def __init__(self, path):
        self.path, self.handle = path, None

    def acquire(self):
        handle = open(self.path, 'a+b')
        if handle.tell() == 0:
            handle.write(b'0'); handle.flush()
        handle.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            raise RuntimeError('Queue already has a worker owner; use one Uvicorn worker') from None
        self.handle = handle

    def release(self):
        if self.handle:
            self.handle.close(); self.handle = None


class JobRunner:
    def __init__(self, store, application, origin):
        self.store, self.application, self.origin = store, application, origin
        self.lease = WorkerLease(str(store.database) + '.worker.lock')
        self.tasks = []
        self.stopping = False

    async def start(self):
        if self.tasks:
            return
        self.lease.acquire()
        try:
            await asyncio.to_thread(self.store.recover)
            self.tasks = [asyncio.create_task(self.worker()) for _ in range(2)]
        except BaseException:
            self.lease.release()
            raise

    async def stop(self):
        self.stopping = True
        try:
            if self.tasks:
                done, pending = await asyncio.wait(self.tasks, timeout=150)
                for task in pending:
                    task.cancel()
                await asyncio.gather(*self.tasks, return_exceptions=True)
        finally:
            self.lease.release()
            self.tasks = []

    async def worker(self):
        while not self.stopping:
            try:
                job = await asyncio.to_thread(self.store.claim)
                if not job:
                    await asyncio.sleep(0.15)
                    continue
                await self.execute(job)
            except asyncio.CancelledError:
                raise
            except Exception:
                # Do not drop executor capacity on a transient SQLite conflict.
                import logging
                logging.getLogger(__name__).error('Queue executor error; saved task retained')
                await asyncio.sleep(1)

    async def execute(self, job):
        from urllib.parse import urlsplit
        parsed = urlsplit(self.origin)
        body_sent, finished = False, asyncio.Event()
        chunks, status = [], 500
        async def receive():
            nonlocal body_sent
            if not body_sent:
                body_sent = True
                return {'type': 'http.request', 'body': job['body'], 'more_body': False}
            await finished.wait()
            return {'type': 'http.disconnect'}
        async def send(message):
            nonlocal status
            if message['type'] == 'http.response.start':
                status = message['status']
            elif message['type'] == 'http.response.body':
                chunks.append(message.get('body', b''))
                if not message.get('more_body'):
                    finished.set()
        scope = {'type': 'http', 'asgi': {'version': '3.0', 'spec_version': '2.3'}, 'http_version': '1.1',
                 'method': job['method'], 'scheme': parsed.scheme, 'path': job['path'], 'raw_path': job['path'].encode(),
                 'root_path': '', 'query_string': b'', 'client': ('127.0.0.1', 0),
                 'skilltree_account': job['account'],
                 'skilltree_job_id': job['id'],
                 'server': (parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80)),
                 'headers': [(b'host', parsed.netloc.encode()), (b'content-type', b'application/json'),
                             (b'content-length', str(len(job['body'])).encode())]}
        try:
            await self.application(scope, receive, send)
            response = b''.join(chunks)
            json.loads(response)
        except asyncio.CancelledError:
            # Remains running in storage; next exclusive owner marks interrupted.
            raise
        except Exception:
            status, response = 500, b'{"error":{"code":"service_error","message":"Task response unavailable; refresh saved project state."}}'
        while True:
            try:
                await asyncio.to_thread(self.store.finish, job['id'], status, response)
                break
            except sqlite3.Error:
                # Retain this executor slot until the response is durable.
                await asyncio.sleep(1)
