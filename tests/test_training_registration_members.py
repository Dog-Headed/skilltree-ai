"""4A: personal registration, unit member selection, backend QA admins."""
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from deploy import training_demo as demo
from deploy import training_admins
from tests.test_training_demo import login, visit
from tests.test_v3_notes_outline import OutlineFake as GuidedFake


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(demo, 'TRAINING_WORK', tmp_path)
    gateway = demo.create_app(root=tmp_path / 'instance', llm=GuidedFake())
    with TestClient(gateway, base_url='http://127.0.0.1:18780') as client:
        yield client, gateway


def register(client, email, password='personal-password', headers=None):
    payload = {
        'account': email, 'password': password, 'confirm_password': password, 'remember': True,
        'role': 'admin', 'unit_id': 'forged-unit',  # must be ignored
    }
    request_headers = {'X-SkillTree-Login': '1'}
    if headers:
        request_headers.update(headers)
    client.cookies.clear() if not headers else None
    return client.post('/auth/register', headers=request_headers, json=payload)


def test_guest_register_keeps_course_and_becomes_personal(runtime):
    client, gateway = runtime
    guest, account = visit(client)
    created = client.post('/projects', headers=guest, json={
        'request_id': str(uuid4()), 'intent': {'goal': '学习泡茶入门'}})
    assert created.status_code == 201, created.text
    pid = created.json()['project_id']
    email = 'learner.keep@example.test'
    response = client.post('/auth/register', headers={**guest, 'X-SkillTree-Login': '1'}, json={
        'account': email, 'password': 'personal-password', 'confirm_password': 'personal-password',
        'remember': True, 'role': 'admin'})
    assert response.status_code == 201, response.text
    headers = {'Cookie': response.headers['set-cookie'].split(';')[0],
               'X-CSRF-Token': response.json()['csrf_token']}
    session = client.get('/session', headers=headers).json()
    assert session['guest'] is False and session['logout'] is True
    assert session['login'] == email
    assert session['training']['role'] == 'personal'
    assert session['training']['unit_id'] is None
    assert session['account'] == account  # canonical guest account retained
    assert client.get('/projects/' + pid, headers=headers).status_code == 200
    assert client.get('/training/home', headers=headers).status_code == 200
    assert client.get('/training/tasks', headers=headers).status_code == 403
    assert client.get('/training/admin', headers=headers).status_code == 403
    assert gateway.training.store.member(account) is None


def test_fresh_personal_register_and_admin_add_member(runtime):
    client, gateway = runtime
    email = 'fresh.person@example.test'
    response = register(client, email)
    assert response.status_code == 201, response.text
    personal = {'Cookie': response.headers['set-cookie'].split(';')[0],
                'X-CSRF-Token': response.json()['csrf_token']}
    assert client.get('/session', headers=personal).json()['training']['role'] == 'personal'
    created = client.post('/projects', headers=personal, json={
        'request_id': str(uuid4()), 'intent': {'goal': '自学资料管理'}})
    assert created.status_code == 201
    pid = created.json()['project_id']

    admin = login(client, 0)
    # Employee cannot use member APIs.
    employee = login(client, 1)
    assert client.get('/training/api/admin/members/lookup?q=' + email, headers=employee).status_code == 403
    assert client.post('/training/api/admin/members', headers=employee,
                       json={'login': email}).status_code == 403

    found = client.get('/training/api/admin/members/lookup?q=' + email.upper(), headers=admin)
    assert found.status_code == 200, found.text
    assert found.json()['login'] == email and found.json()['in_this_unit'] is False

    added = client.post('/training/api/admin/members', headers=admin, json={
        'login': email, 'role': 'admin', 'unit_id': 'other', 'display_name': '新人甲'})
    assert added.status_code == 201, added.text
    body = added.json()
    assert body['role'] == 'employee' and body['created'] is True
    assert body['display_name'] == '新人甲'

    again = client.post('/training/api/admin/members', headers=admin, json={'login': email})
    assert again.status_code == 200 and again.json()['created'] is False

    # Personal project stays private from admin.
    assert client.get('/projects/' + pid, headers=admin).status_code == 404

    # Re-login as the added member: now employee with unit tasks API.
    client.cookies.clear()
    signed = client.post('/auth/login', headers={'X-SkillTree-Login': '1'},
                         json={'account': email, 'password': 'personal-password'})
    assert signed.status_code == 200
    member = {'Cookie': signed.headers['set-cookie'].split(';')[0],
              'X-CSRF-Token': signed.json()['csrf_token']}
    session = client.get('/session', headers=member).json()
    assert session['training']['role'] == 'employee'
    assert session['training']['unit_id'] == demo.UNIT_ID
    assert session['training']['unit_name'] == '中国电信延安分公司'
    assert client.get('/training/api/my-tasks', headers=member).status_code == 200
    assert client.get('/projects/' + pid, headers=member).status_code == 200


def test_cannot_add_guest_or_cross_unit_or_forge_admin(runtime):
    client, gateway = runtime
    guest, guest_account = visit(client)
    admin = login(client, 0)
    assert client.get('/training/api/admin/members/lookup?q=' + guest_account, headers=admin).status_code == 404
    assert client.post('/training/api/admin/members', headers=admin,
                       json={'account': guest_account}).status_code == 404

    # Move employee.c into another unit to exercise the cross-unit refusal.
    other_unit = 'other-demo-unit'
    with gateway.training.store.connect() as conn:
        conn.execute('INSERT INTO training_units VALUES (?,?)', (other_unit, '另一虚构单位'))
        conn.execute('DELETE FROM training_members WHERE account=?', (demo.ACCOUNTS[3][0],))
        conn.execute('INSERT INTO training_members VALUES (?,?,?,?)',
                     (other_unit, demo.ACCOUNTS[3][0], '丙外挂', 'employee'))
    blocked = client.post('/training/api/admin/members', headers=admin,
                          json={'login': demo.ACCOUNTS[3][0]})
    assert blocked.status_code == 409 and blocked.json()['error']['code'] == 'other_unit'


def test_remove_employee_keeps_personal_account(runtime):
    client, gateway = runtime
    email = 'temp.member@example.test'
    assert register(client, email).status_code == 201
    admin = login(client, 0)
    added = client.post('/training/api/admin/members', headers=admin, json={'login': email})
    assert added.status_code == 201
    account = added.json()['account']
    removed = client.post('/training/api/admin/members/remove', headers=admin, json={'account': account})
    assert removed.status_code == 200 and removed.json()['removed'] is True
    assert gateway.training.store.member(account) is None
    # Account can still log in as personal.
    client.cookies.clear()
    signed = client.post('/auth/login', headers={'X-SkillTree-Login': '1'},
                         json={'account': email, 'password': 'personal-password'})
    assert signed.status_code == 200
    headers = {'Cookie': signed.headers['set-cookie'].split(';')[0]}
    assert client.get('/session', headers=headers).json()['training']['role'] == 'personal'
    # Cannot remove admin via this API.
    assert client.post('/training/api/admin/members/remove', headers=admin,
                       json={'account': demo.ACCOUNTS[0][0]}).status_code == 409


def test_backend_qa_admins_script(tmp_path, monkeypatch):
    monkeypatch.setattr(demo, 'TRAINING_WORK', tmp_path)
    gateway = demo.create_app(root=tmp_path / 'qa-instance', llm=GuidedFake())
    private = tmp_path / 'private' / 'qa.json'
    # Invoke grant helpers directly against this instance DBs.
    results = []
    records = []
    for i, login in enumerate(training_admins.QA_LOGINS, start=1):
        results.append(training_admins.grant_admin(
            gateway.auth, gateway.training.store, login,
            unit_id=demo.UNIT_ID, unit_name='青禾研习社（虚构演示单位）',
            display_name=f'QA管理员{i}', password=None, private_records=records))
    assert all(r['created_account'] and r['membership'] == 'joined_as_admin' for r in results)
    training_admins.write_private(private, records, {'unit_id': demo.UNIT_ID})
    assert private.is_file() and private.stat().st_mode & 0o777 == 0o600
    payload = private.read_text(encoding='utf-8')
    assert 'admin.qa1@example.test' in payload and 'password' in payload
    # Idempotent re-run does not reset passwords / recreate.
    again = []
    for i, login in enumerate(training_admins.QA_LOGINS, start=1):
        again.append(training_admins.grant_admin(
            gateway.auth, gateway.training.store, login,
            unit_id=demo.UNIT_ID, unit_name='青禾研习社（虚构演示单位）',
            display_name=f'QA管理员{i}', password='SHOULD-NOT-APPLY-123', private_records=[]))
    assert all(r['created_account'] is False and r['membership'] == 'already_admin' for r in again)
    # Login + admin overview works with generated password.
    password = records[0]['password']
    with TestClient(gateway, base_url='http://127.0.0.1:18780') as client:
        signed = client.post('/auth/login', headers={'X-SkillTree-Login': '1'},
                             json={'account': training_admins.QA_LOGINS[0], 'password': password})
        assert signed.status_code == 200, signed.text
        headers = {'Cookie': signed.headers['set-cookie'].split(';')[0]}
        session = client.get('/session', headers=headers).json()
        assert session['training']['role'] == 'admin'
        overview = client.get('/training/api/admin/overview', headers=headers)
        assert overview.status_code == 200
        assert any(m['account'] == session['account'] for m in overview.json()['members'])


def test_login_page_exposes_registration_controls(runtime):
    client, _ = runtime
    page = client.get('/login').text
    assert 'id="auth-mode"' in page and 'confirm-password' in page
    assert 'guest-entry' in page
