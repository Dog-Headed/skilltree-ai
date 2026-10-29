"""Registration and alias changes on the real auth store and V3 gateway."""
from concurrent.futures import ThreadPoolExecutor
import sqlite3
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from app.v3.learning_api import create_learning_app
from app.v3.runtime_storage import initialize_learning_storage
from app.v3.storage import V3Paths, initialize_storage
from deploy.asgi import EvaluationGateway
from deploy.auth import AuthStore, password_hash
from tests.day11_support import FakeLearningModel


@pytest.fixture
def registration(tmp_path, monkeypatch):
    monkeypatch.setenv('SKILLTREE_REGISTRATION_LIMIT', '10')
    paths = initialize_learning_storage(initialize_storage(V3Paths(tmp_path/'learning')))
    auth = AuthStore(tmp_path/'auth.sqlite')
    gateway = EvaluationGateway(create_learning_app(paths, llm=FakeLearningModel()), paths, tmp_path/'quota.sqlite',
                                auth_store=auth, queued=True, origin='https://testserver')
    with TestClient(gateway, base_url='https://testserver') as client:
        yield client, gateway, auth


def signup(client, email, password='registration-password'):
    client.cookies.clear()
    response = client.post('/auth/register', headers={'X-SkillTree-Login': '1'}, json={
        'account': email, 'password': password, 'confirm_password': password, 'remember': True})
    return response


def test_five_registered_users_own_only_their_projects(registration):
    client, gateway, auth = registration
    identities, projects = [], []
    for i in range(5):
        email = f'new{i}@example.test'
        response = signup(client, email.upper())
        assert response.status_code == 201, response.text
        assert response.json()['account'] == email
        assert all(flag in response.headers['set-cookie'] for flag in ('Secure', 'HttpOnly', 'SameSite=Lax'))
        headers = {'Cookie': response.headers['set-cookie'].split(';')[0], 'X-CSRF-Token': response.json()['csrf_token']}
        assert client.get('/session', headers=headers).json()['login'] == email
        assert client.get('/projects', headers=headers).json() == []
        response = client.post('/projects', headers=headers, json={'request_id': str(uuid4()), 'intent': {'goal': '比较整数大小'}})
        assert response.status_code == 201, response.text
        projects.append(response.json()['project_id']); identities.append(headers)
    for i, headers in enumerate(identities):
        assert [p['project_id'] for p in client.get('/projects', headers=headers).json()] == [projects[i]]
        for j in range(5):
            assert client.get('/projects/'+projects[j], headers=headers).status_code == (200 if i == j else 404)
    with auth.connect() as conn:
        assert conn.execute('SELECT COUNT(*) FROM auth_registrations').fetchone()[0] == 5
        assert all(r[0].startswith('pbkdf2_sha256$600000$') for r in conn.execute('SELECT password_hash FROM auth_accounts'))


def test_registration_validation_duplicate_and_csrf(registration):
    client, gateway, auth = registration
    assert client.post('/auth/register', json={}).status_code == 403
    response = client.post('/auth/register', headers={'X-SkillTree-Login': '1', 'Origin': 'https://attacker.invalid'}, json={})
    assert response.status_code == 403
    for email, password in [('legacy', 'valid-password'), ('a@example.test', 'short')]:
        assert signup(client, email, password).status_code == 422
    assert client.post('/auth/register', headers={'X-SkillTree-Login': '1'}, json={
        'account': 'a@example.test', 'password': 'valid-password', 'confirm_password': 'different'}).status_code == 422
    first = signup(client, 'owner@example.test')
    assert first.status_code == 201
    assert signup(client, 'OWNER@EXAMPLE.TEST', 'different-password').status_code == 409
    assert auth.login('owner@example.test', 'registration-password', '127.0.0.1')['status'] == 200
    assert auth.login('owner@example.test', 'different-password', '127.0.0.1')['status'] == 401


def test_registration_capacity_atomic_under_parallel_hashing(tmp_path, monkeypatch):
    monkeypatch.setenv('SKILLTREE_REGISTRATION_LIMIT', '2')
    auth = AuthStore(tmp_path/'auth.sqlite')
    with ThreadPoolExecutor(max_workers=5) as executor:
        results = list(executor.map(lambda i: auth.register(f'race{i}@example.test', 'valid-password', f'ip{i}'), range(5)))
    assert sorted(r['status'] for r in results) == [201, 201, 403, 403, 403]
    with auth.connect() as conn:
        assert conn.execute('SELECT COUNT(*) FROM auth_accounts').fetchone()[0] == 2
        assert conn.execute('SELECT COUNT(*) FROM auth_registrations').fetchone()[0] == 2
        conn.execute('UPDATE auth_accounts SET disabled=1 WHERE account=(SELECT account FROM auth_registrations LIMIT 1)')
    assert auth.register('replacement@example.test','valid-password','new-ip')['status'] == 201


def test_registration_duplicate_race_and_ip_limit(tmp_path, monkeypatch):
    monkeypatch.setenv('SKILLTREE_REGISTRATION_LIMIT', '10')
    auth = AuthStore(tmp_path/'auth.sqlite')
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda i: auth.register('same@example.test', 'valid-password', 'shared'), range(2)))
    assert sorted(r['status'] for r in results) == [201, 409]
    for _ in range(8):
        assert auth.register('same@example.test', 'valid-password', 'shared')['status'] == 409
    limited = auth.register('next@example.test', 'valid-password', 'shared')
    assert limited['status'] == 429 and 0 < limited['retry_after'] <= 3601


def test_binding_email_preserves_password_owner_and_existing_session(tmp_path):
    auth = AuthStore(tmp_path/'auth.sqlite')
    encoded = password_hash('old-password')
    with auth.connect() as conn:
        conn.execute('INSERT INTO auth_accounts VALUES (?,?,?,0)', ('legacy', 'legacy', encoded))
    before = auth.login('legacy', 'old-password', 'ip')
    assert auth.bind_email('legacy', 'PERSON@EXAMPLE.TEST') == 'person@example.test'
    assert auth.session(before['token']) == 'legacy'
    assert auth.login('person@example.test', 'old-password', 'ip')['account'] == 'legacy'
    assert auth.login('legacy', 'old-password', 'ip')['status'] == 401
    with auth.connect() as conn:
        assert tuple(conn.execute('SELECT account,password_hash FROM auth_accounts').fetchone()) == ('legacy', encoded)
    auth.create_account('other@example.test', 'other-password')
    with pytest.raises(ValueError):
        auth.bind_email('legacy', 'other@example.test')
    auth.bind_email('other@example.test', 'new@example.test')
    assert auth.register('other@example.test', 'new-password', 'ip')['status'] == 409


def test_local_ports_use_distinct_cookies(registration):
    client, gateway, auth = registration
    preview = EvaluationGateway(gateway.application, gateway.paths, gateway.quota_path,
             auth_store=auth, cookie_secure=False, cookie_name='skilltree_preview_session')
    local = EvaluationGateway(gateway.application, gateway.paths, gateway.quota_path,
             auth_store=auth, cookie_secure=False, cookie_name='skilltree_local_session')
    response = signup(client, 'person@example.test')
    token = response.headers['set-cookie'].split('=', 1)[1].split(';')[0]
    with TestClient(local) as local_client:
        assert local_client.get('/session', headers={'Cookie': 'skilltree_preview_session='+token}).status_code == 401
        assert local_client.get('/session', headers={'Cookie': 'skilltree_local_session='+token}).status_code == 200
    assert preview.cookie_name != local.cookie_name
