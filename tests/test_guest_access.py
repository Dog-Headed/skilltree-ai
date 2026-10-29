"""Visitors learn without signing up; registering or signing in keeps their courses."""
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from app.v3.learning_api import create_learning_app
from app.v3.runtime_storage import initialize_learning_storage
from app.v3.storage import V3Paths, initialize_storage
from deploy.asgi import EvaluationGateway
from deploy.auth import AuthStore
from tests.day11_support import FakeLearningModel


@pytest.fixture
def site(tmp_path, monkeypatch):
    monkeypatch.delenv('SKILLTREE_REGISTRATION_LIMIT', raising=False)
    paths = initialize_learning_storage(initialize_storage(V3Paths(tmp_path/'learning')))
    auth = AuthStore(tmp_path/'auth.sqlite')
    gateway = EvaluationGateway(create_learning_app(paths, llm=FakeLearningModel()), paths, tmp_path/'quota.sqlite',
                                auth_store=auth, queued=True, origin='https://testserver')
    with TestClient(gateway, base_url='https://testserver') as client:
        yield client, gateway, auth


def visit(client):
    """Open the garden as a new visitor; returns write headers for that guest."""
    client.cookies.clear()
    home = client.get('/', follow_redirects=False)
    assert home.status_code == 200 and '<script src="/assets/v3.js" defer>' in home.text
    cookie = home.headers['set-cookie']
    assert all(flag in cookie for flag in ('HttpOnly', 'Secure', 'SameSite=Lax', 'Max-Age=31536000'))
    headers = {'Cookie': cookie.split(';')[0]}
    session = client.get('/session', headers=headers).json()
    assert session['guest'] is True and session['logout'] is False and session['account'].startswith('guest_')
    return {**headers, 'X-CSRF-Token': session['csrf_token']}, session['account']


def plant(client, headers):
    response = client.post('/projects', headers=headers, json={'request_id': str(uuid4()), 'intent': {'goal': '比较整数大小'}})
    assert response.status_code == 201, response.text
    return response.json()['project_id']


def credentials(email, **extra):
    return {'account': email, 'password': 'registration-password', 'confirm_password': 'registration-password', 'remember': True, **extra}


def test_visitor_learns_then_registration_keeps_the_same_courses(site):
    client, gateway, auth = site
    headers, guest = visit(client)
    project = plant(client, headers)
    # Reopening the page keeps the same guest instead of creating another.
    assert 'set-cookie' not in client.get('/', headers=headers).headers
    assert client.get('/session', headers=headers).json()['account'] == guest
    client.cookies.clear()
    response = client.post('/auth/register', headers={**headers, 'X-SkillTree-Login': '1'}, json=credentials('Learner@Example.test'))
    assert response.status_code == 201, response.text
    assert response.json()['account'] == guest
    member = {'Cookie': response.headers['set-cookie'].split(';')[0], 'X-CSRF-Token': response.json()['csrf_token']}
    session = client.get('/session', headers=member).json()
    assert session == {**session, 'account': guest, 'login': 'learner@example.test', 'guest': False, 'logout': True}
    assert [p['project_id'] for p in client.get('/projects', headers=member).json()] == [project]
    # The guest token is revoked; the new password signs in to the same account.
    assert client.get('/session', headers={'Cookie': headers['Cookie']}).status_code == 401
    assert auth.login('learner@example.test', 'registration-password', 'ip')['account'] == guest
    assert auth.login(guest, '!', 'ip')['status'] == 401


def test_signing_in_from_a_guest_session_brings_its_courses(site):
    client, gateway, auth = site
    client.cookies.clear()
    owner = client.post('/auth/register', headers={'X-SkillTree-Login': '1'}, json=credentials('owner@example.test'))
    owner_headers = {'Cookie': owner.headers['set-cookie'].split(';')[0], 'X-CSRF-Token': owner.json()['csrf_token']}
    kept = plant(client, owner_headers)
    headers, guest = visit(client)
    new = plant(client, headers)
    client.cookies.clear()
    response = client.post('/auth/login', headers={**headers, 'X-SkillTree-Login': '1'},
                           json={'account': 'owner@example.test', 'password': 'registration-password', 'remember': True})
    assert response.status_code == 200, response.text
    member = {'Cookie': response.headers['set-cookie'].split(';')[0]}
    assert sorted(p['project_id'] for p in client.get('/projects', headers=member).json()) == sorted([kept, new])
    assert gateway.ownership.owned(guest) == set()


def test_registration_is_open_without_a_configured_limit(site):
    client, gateway, auth = site
    for i in range(12):
        assert auth.register(f'open{i}@example.test', 'valid-password', f'ip{i}')['status'] == 201


def test_guest_creation_is_limited_per_address(site):
    client, gateway, auth = site
    assert all(auth.create_guest('10.0.0.1') for _ in range(60))
    assert auth.create_guest('10.0.0.1') is None
    assert auth.create_guest('10.0.0.2')
    # Over the limit, a visitor is sent to the sign-in page instead of getting a guest.
    client.cookies.clear()
    gateway.auth.create_guest = lambda ip: None
    response = client.get('/', follow_redirects=False)
    assert response.status_code == 303 and response.headers['location'].startswith('/login')


def test_guest_access_can_be_turned_off(site):
    client, gateway, auth = site
    gateway.guest_access = False
    client.cookies.clear()
    response = client.get('/', follow_redirects=False)
    assert response.status_code == 303 and response.headers['location'].startswith('/login')


def test_refused_adoption_preserves_guest_session_and_course(site, monkeypatch):
    client, gateway, auth = site
    auth.create_account('existing@example.test', 'registration-password')
    headers, guest = visit(client)
    project = plant(client, headers)
    monkeypatch.setattr(gateway.ownership, 'adopt', lambda source, target: False)
    response = client.post('/auth/login', headers={**headers, 'X-SkillTree-Login': '1'},
                           json={'account': 'existing@example.test', 'password': 'registration-password'})
    assert response.status_code == 409 and 'set-cookie' not in response.headers
    assert client.get('/session', headers=headers).json()['account'] == guest
    assert gateway.ownership.owned(guest) == {project}
    with auth.connect() as conn:
        assert conn.execute('SELECT COUNT(*) FROM auth_sessions WHERE account=?', ('existing@example.test',)).fetchone()[0] == 0


def test_guest_registration_cannot_fall_back_to_another_account_after_upgrade(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    auth = AuthStore(tmp_path/'auth.sqlite')
    guest = auth.create_guest('ip')
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda i: auth.register(f'parallel{i}@example.test', 'registration-password', f'ip{i}', guest=guest['account']), range(2)))
    assert sorted(r['status'] for r in results) == [201, 409]
    assert next(r for r in results if r['status'] == 201)['account'] == guest['account']
    assert next(r for r in results if r['status'] == 409)['code'] == 'guest_session_changed'
    with auth.connect() as conn:
        assert conn.execute('SELECT COUNT(*) FROM auth_accounts').fetchone()[0] == 1
