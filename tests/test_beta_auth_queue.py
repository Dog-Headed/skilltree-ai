"""Real cookie gateway/SQLite; deliberately fake slow work, no provider calls."""
import json
import sqlite3
import threading
import time
from uuid import uuid4

import bcrypt
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.v3.storage import V3Paths
from deploy.asgi import EvaluationGateway
from deploy.auth import AuthStore, password_hash
from deploy.jobs import JobStore, WorkerLease


@pytest.fixture(scope='module')
def encoded():
    return password_hash('test-password-2026')


@pytest.fixture
def beta(tmp_path, encoded):
    auth = AuthStore(tmp_path/'auth.sqlite')
    with auth.connect() as conn:
        conn.executemany('INSERT INTO auth_accounts VALUES (?,?,?,0)',
                         [(f'preview{i}@example.test', f'preview{i}@example.test', encoded) for i in range(1, 6)])
    app = FastAPI()
    lock, release, started = threading.Lock(), threading.Event(), threading.Event()
    metrics = {'active': 0, 'peak': 0, 'calls': []}
    @app.get('/')
    def root():
        return {'page': 'home'}
    @app.get('/capabilities')
    def read():
        return []
    @app.post('/projects', status_code=201)
    def create(body: dict):
        return {'project_id': 'v3_' + body['request_id'].replace('-', ''), 'page_state': 'profile_review'}
    @app.post('/projects/{pid}/begin')
    def slow(pid: str, body: dict):
        with lock:
            metrics['active'] += 1
            metrics['peak'] = max(metrics['peak'], metrics['active'])
            metrics['calls'].append(pid)
            if metrics['active'] == 2:
                started.set()
        try:
            assert release.wait(15), 'Test did not release fake work'
            return {'project_id': pid, 'page_state': 'teaching', 'marker': body.get('marker')}
        finally:
            with lock:
                metrics['active'] -= 1
    gateway = EvaluationGateway(app, V3Paths(tmp_path/'business'), tmp_path/'quota.sqlite',
                  auth_store=auth, queued=True, origin='https://testserver')
    for i in range(1, 6):
        gateway.ownership.claim(f'project{i}', f'preview{i}@example.test')
    with TestClient(gateway, base_url='https://testserver') as client:
        try:
            yield client, gateway, auth, metrics, release, started
        finally:
            release.set()


def signin(client, number=1):
    client.cookies.clear()
    response = client.post('/auth/login', json={'account': f'PREVIEW{number}@EXAMPLE.TEST', 'password': 'test-password-2026', 'remember': True}, headers={'X-SkillTree-Login': '1'})
    assert response.status_code == 200, response.text
    assert '__Host-skilltree_session=' in response.headers['set-cookie']
    assert all(flag in response.headers['set-cookie'] for flag in ('Secure', 'HttpOnly', 'SameSite=Lax', 'Max-Age=2592000'))
    return {'Cookie': response.headers['set-cookie'].split(';', 1)[0], 'X-CSRF-Token': response.json()['csrf_token']}


def wait_job(client, headers, job_id):
    until = time.monotonic()+12
    while time.monotonic() < until:
        job = client.get('/jobs/'+job_id, headers=headers).json()['job']
        if job['state'] not in ('queued', 'running'):
            return job
        time.sleep(.03)
    pytest.fail('Job did not finish')


def test_authentication_csrf_logout_and_opaque_sessions(beta):
    client, gateway, auth, *_ = beta
    assert client.get('/session', headers={'X-Evaluation-User': 'preview1@example.test'}).status_code == 401
    assert client.get('/', follow_redirects=False).status_code == 303
    assert client.post('/auth/login', json={}).status_code == 403
    headers = signin(client)
    assert client.get('/session', headers=headers).json()['account'] == 'preview1@example.test'
    with auth.connect() as conn:
        stored = conn.execute('SELECT token_hash FROM auth_sessions').fetchone()[0]
        assert stored != headers['Cookie'].split('=', 1)[1] and len(stored) == 64
    assert client.post('/projects', headers={'Cookie': headers['Cookie']}, json={'request_id': str(uuid4())}).status_code == 403
    assert client.post('/projects', headers={**headers, 'Origin': 'https://other.invalid'}, json={'request_id': str(uuid4())}).status_code == 403
    assert client.post('/auth/logout', headers=headers, json={}).status_code == 200
    assert client.get('/session', headers=headers).status_code == 401


def test_five_identities_two_running_three_queued_and_fast_writes(beta):
    client, gateway, auth, metrics, release, started = beta
    identities = [signin(client, i) for i in range(1, 6)]
    submissions = []
    for i, headers in enumerate(identities, 1):
        payload = {'request_id': str(uuid4()), 'marker': i}
        response = client.post(f'/projects/project{i}/begin', headers=headers, json=payload)
        assert response.status_code == 202, response.text
        submissions.append((response.json()['job']['id'], payload))
    assert started.wait(3)
    with gateway.jobs.connect() as conn:
        states = dict(conn.execute('SELECT state,COUNT(*) FROM deployment_jobs GROUP BY state'))
        used = conn.execute('SELECT SUM(used) FROM usage').fetchone()[0]
    assert states == {'running': 2, 'queued': 3}
    assert metrics['peak'] == 2 and used == 5
    # A retransmission gets the original durable job, without another quota debit.
    same = client.post('/projects/project1/begin', headers=identities[0], json=submissions[0][1])
    assert same.json()['job']['id'] == submissions[0][0]
    altered = {**submissions[0][1], 'marker': 'changed'}
    assert client.post('/projects/project1/begin', headers=identities[0], json=altered).status_code == 409
    assert client.post('/projects/project1/begin', headers=identities[0], json={'request_id': str(uuid4())}).status_code == 409
    assert client.get('/jobs/'+submissions[0][0], headers=identities[1]).status_code == 404
    assert client.post('/projects/project1/begin', headers=identities[1], json={'request_id': str(uuid4())}).status_code == 404
    assert client.get('/capabilities', headers=identities[4]).status_code == 200
    fast = client.post('/projects', headers=identities[4], json={'request_id': str(uuid4())})
    assert fast.status_code == 201 and fast.json()['page_state'] == 'profile_review'
    release.set()
    for i, ((job_id, _), headers) in enumerate(zip(submissions, identities), 1):
        result = wait_job(client, headers, job_id)
        assert result['state'] == 'completed'
        assert result['result']['page_state'] == 'teaching' and result['result']['marker'] == i
    assert metrics['peak'] == 2 and len(metrics['calls']) == 5


def test_restart_never_replays_running_work_and_preserves_waiting(tmp_path):
    store = JobStore(tmp_path/'queue.sqlite')
    first = store.admit('a', 'p1', 'POST', '/projects/p1/begin', {'request_id': '1'})
    second = store.admit('b', 'p2', 'POST', '/projects/p2/begin', {'request_id': '2'})
    assert store.claim()['id'] == first
    store.recover()
    assert store.public(first, 'a')['state'] == 'interrupted'
    assert store.public(second, 'b')['state'] == 'queued'
    assert store.claim()['id'] == second
    assert store.public(first, 'b') is None


def test_worker_owner_is_exclusive(tmp_path):
    first, second = WorkerLease(tmp_path/'queue.lock'), WorkerLease(tmp_path/'queue.lock')
    first.acquire()
    try:
        with pytest.raises(RuntimeError):
            second.acquire()
    finally:
        first.release()
    second.acquire(); second.release()


def test_full_queue_no_quota_charge_and_fast_project_conflict(tmp_path):
    store = JobStore(tmp_path/'queue.sqlite', capacity=2)
    for i in range(2):
        store.admit(str(i), str(i), 'POST', f'/projects/{i}/begin', {'request_id': str(i)})
    from deploy.jobs import AdmissionError
    with pytest.raises(AdmissionError, match='') as failure:
        store.admit('third', 'p3', 'POST', '/projects/p3/begin', {'request_id': '3'})
    assert failure.value.code == 'queue_full'
    with pytest.raises(AdmissionError) as failure:
        store.reserve_fast('0', '0')
    assert failure.value.code == 'account_busy'
    with store.connect() as conn:
        assert conn.execute('SELECT SUM(used) FROM usage').fetchone()[0] == 2


def test_legacy_password_import_preserves_canonical_owner(tmp_path):
    auth = AuthStore(tmp_path/'auth.sqlite')
    file = tmp_path/'private.htpasswd'
    file.write_text('goutouren:' + bcrypt.hashpw(b'old-password', bcrypt.gensalt(rounds=4)).decode() + '\n')
    assert auth.import_htpasswd(file) == 1
    assert auth.import_htpasswd(file) == 1
    result = auth.login('GOUTOUREN', 'old-password', '127.0.0.1')
    assert result['status'] == 200 and result['account'] == 'goutouren'
    assert auth.session(result['token']) == 'goutouren'
    assert auth.login('goutouren', 'bad-password', '127.0.0.1')['status'] == 401


def test_brute_force_expiry_and_no_self_registration(beta):
    client, gateway, auth, *_ = beta
    for _ in range(8):
        assert client.post('/auth/login', headers={'X-SkillTree-Login': '1'}, json={'account': 'nobody@example.test', 'password': 'bad'}).status_code == 401
    denied = client.post('/auth/login', headers={'X-SkillTree-Login': '1'}, json={'account': 'nobody@example.test', 'password': 'bad'})
    assert denied.status_code == 429 and int(denied.headers['retry-after']) > 0
    headers = signin(client, 2)
    assert client.post('/auth/register', headers=headers, json={}).status_code == 403
    with auth.connect() as conn:
        conn.execute('UPDATE auth_sessions SET expires=0')
    assert client.get('/session', headers=headers).status_code == 401


def test_real_learning_graph_correct_and_remediation_through_cookie_queue(tmp_path, encoded):
    from app.v3.learning_api import create_learning_app
    from tests.day11_support import build_frozen_project, learning_event, answers_for_quiz, private_quiz
    frozen = build_frozen_project(tmp_path/'learning', subject='mathematics', node_count=2)
    auth = AuthStore(tmp_path/'auth.sqlite')
    with auth.connect() as conn:
        conn.execute('INSERT INTO auth_accounts VALUES (?,?,?,0)', ('preview1@example.test', 'preview1@example.test', encoded))
    gateway = EvaluationGateway(create_learning_app(frozen['paths'], llm=frozen['model']), frozen['paths'], tmp_path/'quota.sqlite',
                auth_store=auth, queued=True, origin='https://testserver')
    pid = frozen['project_id']
    gateway.ownership.claim(pid, 'preview1@example.test')
    with TestClient(gateway, base_url='https://testserver') as client:
        headers = signin(client)
        def perform(suffix, body):
            response = client.post(f'/projects/{pid}/{suffix}', headers=headers, json=body)
            assert response.status_code == 202, response.text
            completed = wait_job(client, headers, response.json()['job']['id'])
            assert completed['status_code'] == 200, completed
            return completed['result']
        view = perform('begin', {'request_id': str(uuid4())})
        assert view['page_state'] == 'learning'
        first_node = view['current_node_id']
        view = perform('resume', learning_event(view, 'start_quiz'))
        assert view['page_state'] == 'quiz'
        quiz = private_quiz(frozen['paths'], pid, view['assessment_id'])
        frozen['model'].grade_ratio = 0
        wrong = {key: '999' for key in answers_for_quiz(quiz)}
        view = perform('resume', learning_event(view, 'submit_answer', answers=wrong))
        assert view['current_node_id'] == first_node
        assert not view['feedback']['guard']['passed']
        assert view['mode'] == 'remediate' and not any(n['passed'] for n in view['nodes'])
        frozen['model'].grade_ratio = 1
        view = perform('resume', learning_event(view, 'start_quiz'))
        quiz = private_quiz(frozen['paths'], pid, view['assessment_id'])
        view = perform('resume', learning_event(view, 'submit_answer', answers=answers_for_quiz(quiz)))
        assert view['feedback']['guard']['passed'] and sum(n['passed'] for n in view['nodes']) == 1
        assert view['current_node_id'] != first_node
        view = perform('resume', learning_event(view, 'start_quiz'))
        quiz = private_quiz(frozen['paths'], pid, view['assessment_id'])
        view = perform('resume', learning_event(view, 'submit_answer', answers=answers_for_quiz(quiz)))
        assert view['page_state'] == 'completed' and all(n['passed'] for n in view['nodes'])


def test_email_cookie_accounts_isolate_real_courses_and_sources(tmp_path, encoded):
    from app.v3.learning_api import create_learning_app
    from app.v3.runtime_storage import initialize_learning_storage
    from app.v3.storage import initialize_storage
    from tests.day11_support import FakeLearningModel
    paths = initialize_learning_storage(initialize_storage(V3Paths(tmp_path/'learning')))
    auth = AuthStore(tmp_path/'auth.sqlite')
    with auth.connect() as conn:
        conn.executemany('INSERT INTO auth_accounts VALUES (?,?,?,0)', [(f'preview{i}@example.test', f'preview{i}@example.test', encoded) for i in (1,2)])
    gateway = EvaluationGateway(create_learning_app(paths,llm=FakeLearningModel()),paths,tmp_path/'quota.sqlite',
                               auth_store=auth,queued=True,origin='https://testserver')
    with TestClient(gateway,base_url='https://testserver') as client:
        first,second=signin(client,1),signin(client,2)
        courses=[]
        for headers in (first,second):
            response=client.post('/projects',headers=headers,json={'request_id':str(uuid4()),'intent':{'goal':'比较整数大小'}})
            assert response.status_code==201,response.text
            courses.append(response.json()['project_id'])
        assert [p['project_id'] for p in client.get('/projects',headers=first).json()]==[courses[0]]
        assert [p['project_id'] for p in client.get('/projects',headers=second).json()]==[courses[1]]
        for suffix in ('','/sources','/sources/secret/versions/1'):
            assert client.get('/projects/'+courses[0]+suffix,headers=second).status_code==404
        assert client.patch('/projects/'+courses[0],headers=second,json={'display_name':'other'}).status_code==404
        assert client.get('/projects/'+courses[0],headers=first).json()['profile']['goal']=='比较整数大小'
