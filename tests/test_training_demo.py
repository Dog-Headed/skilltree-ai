"""Real auth/store/queue boundary with explicitly Fake planning content."""
import json
import sqlite3
import time
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from deploy import training_demo as demo
from tests.test_v3_notes_outline import OutlineFake as GuidedFake


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(demo, 'TRAINING_WORK', tmp_path)
    model = GuidedFake()
    gateway = demo.create_app(root=tmp_path/'instance', llm=model)
    with TestClient(gateway, base_url='http://127.0.0.1:18780') as client:
        yield client, gateway, model


def login(client, index=0):
    client.cookies.clear()  # Independent browser identities; switching revokes the previous cookie.
    result = client.post('/auth/login', json={'account': demo.ACCOUNTS[index][0], 'password': demo.DEMO_PASSWORD},
        headers={'X-SkillTree-Login': '1'})
    assert result.status_code == 200, result.text
    return {'Cookie': result.headers['set-cookie'].split(';')[0], 'X-CSRF-Token': result.json()['csrf_token']}


def test_all_roles_server_auth_and_no_parameter_escalation(runtime):
    client, gateway, model = runtime
    assert client.get('/', follow_redirects=False).status_code == 303
    assert client.get('/training/home', follow_redirects=False).headers['location'] == '/login'
    assert client.get('/session', headers={'X-Evaluation-User': demo.ACCOUNTS[0][0]}).status_code == 401
    assert client.post('/auth/register', json={}).status_code == 403
    for i in range(4):
        headers = login(client, i)
        session = client.get('/session', headers=headers).json()
        assert session['training']['role'] == ('admin' if i == 0 else 'employee')
        landing = client.get('/', headers=headers, follow_redirects=False)
        assert landing.headers['location'] == ('/training/admin' if i == 0 else '/training/home')
        if i:
            forged = {**headers, 'X-Evaluation-User': demo.ACCOUNTS[0][0], 'X-Role': 'admin'}
            assert client.get('/training/admin?role=admin', headers=forged).status_code == 403
            assert client.get('/training/api/admin/overview?account=admin@example.test', headers=forged).status_code == 403
            assert client.post('/training/api/admin/publish', json={'role': 'admin'}, headers=forged).status_code == 403
        assert client.get('/learn', headers=headers).status_code == 200
    headers = login(client)
    value = client.get('/training/api/admin/overview', headers=headers).json()
    assert len(value['members']) == 4 and value['tasks'] == value['courses'] == []
    assert client.post('/training/api/admin/publish', headers=headers, json={}).status_code == 405
    assert client.post('/training/api/admin/publish', json={}).status_code == 403  # no CSRF
    assert model.calls == []


def test_free_learning_isolation_and_durable_reinitialization(runtime):
    client, gateway, model = runtime
    a = login(client, 1)
    payload = {'request_id': str(uuid4()), 'intent': {'goal': '理解工作交接记录', 'prior_knowledge': '零基础'}}
    created = client.post('/projects', json=payload, headers=a)
    assert created.status_code == 201, created.text
    project = created.json()
    assert project['page_state'] == 'profile_review'
    b = login(client, 2)
    assert client.get('/projects', headers=b).json() == []
    assert client.get('/projects/'+project['project_id'], headers=b).status_code == 404
    assert client.post('/projects', json=payload, headers=b).status_code == 404
    admin = login(client)
    assert client.get('/projects/'+project['project_id'], headers=admin).status_code == 404
    response = client.post('/projects/'+project['project_id']+'/resume', headers=a, json={
        'request_id': str(uuid4()), 'action': 'confirm_profile', 'pending_input_id': project['pending_input_id'],
        'draft_revision': project['draft_revision']})
    assert response.status_code == 202
    job_id = response.json()['job']['id']
    deadline = time.monotonic()+30
    while time.monotonic() < deadline:
        job = client.get('/jobs/'+job_id, headers=a).json()['job']
        if job['state'] not in {'queued', 'running'}:
            break
        time.sleep(.05)
    assert job['state'] == 'completed', job
    assert job['result']['page_state'] == 'plan_review'
    assert client.get('/jobs/'+job_id, headers=b).status_code == 404
    assert client.get('/training/api/my-tasks?account=employee.a@example.test', headers=b).json()['tasks'] == []
    with gateway.auth.connect() as conn:
        hashes_before = list(map(tuple, conn.execute('SELECT login,password_hash FROM auth_accounts ORDER BY login')))
    demo.seed(gateway.auth, gateway.training.store, 'a-different-secret-ignored')
    with gateway.auth.connect() as conn:
        assert list(map(tuple, conn.execute('SELECT login,password_hash FROM auth_accounts ORDER BY login'))) == hashes_before
    fresh = demo.create_app(root=gateway.paths.root.parent, llm=GuidedFake())
    # Simulate reconstruction of application stores, without starting a second queue worker.
    with TestClient(fresh.application) as direct:
        assert direct.get('/projects/'+project['project_id']).json()['page_state'] == 'plan_review'
    assert fresh.auth.session(a['Cookie'].split('=',1)[1]) == demo.ACCOUNTS[1][0]
    assert fresh.ownership.owned(demo.ACCOUNTS[1][0]) == {project['project_id']}


def test_shared_course_separate_employee_identity_and_foreign_keys(runtime):
    _, gateway, _ = runtime
    with gateway.training.store.connect() as conn:
        conn.execute('INSERT INTO training_course_versions(id,unit_id,course_id,version,title,tree_json,required_nodes_json,pass_rule_json) VALUES (?,?,?,?,?,?,?,?)',
            ('cv1', demo.UNIT_ID, 'course', 1, 'contract-only fixture', '{}', '["node1"]', '{"rule":"all_required_nodes"}'))
        conn.execute('INSERT INTO training_tasks(id,unit_id,course_version_id,title,created_by) VALUES (?,?,?,?,?)',
            ('t1', demo.UNIT_ID, 'cv1', 'test task', demo.ACCOUNTS[0][0]))
        for i in (1,2):
            conn.execute('INSERT INTO training_employee_tasks(id,unit_id,task_id,account,project_id) VALUES (?,?,?,?,?)',
                (f'e{i}', demo.UNIT_ID, 't1', demo.ACCOUNTS[i][0], f'p{i}'))
        assert conn.execute('SELECT COUNT(DISTINCT project_id) FROM training_employee_tasks WHERE task_id="t1"').fetchone()[0] == 2
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute('INSERT INTO training_employee_tasks(id,unit_id,task_id,account) VALUES (?,?,?,?)', ('duplicate', demo.UNIT_ID, 't1', demo.ACCOUNTS[1][0]))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute('UPDATE training_course_versions SET title="changed" WHERE id="cv1"')
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute('INSERT INTO training_employee_tasks(id,unit_id,task_id,account) VALUES (?,?,?,?)', ('foreign', 'other-unit', 't1', demo.ACCOUNTS[3][0]))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute('INSERT INTO training_node_bindings VALUES (?,?,?,?)', ('e1', 'p2', 'node1', 'n1'))
        conn.execute('INSERT INTO training_node_bindings VALUES (?,?,?,?)', ('e1', 'p1', 'node1', 'n1'))


def test_isolated_configuration_and_public_password_guard(tmp_path, monkeypatch):
    monkeypatch.setattr(demo, 'TRAINING_WORK', tmp_path/'training')
    with pytest.raises(ValueError):
        demo.create_app(root=tmp_path/'old-data', llm=GuidedFake())
    with pytest.raises(ValueError):
        demo.create_app(port=8765, llm=GuidedFake())
    other = tmp_path/'training'/'occupied'; other.mkdir(parents=True); (other/'old.txt').write_text('preserve')
    with pytest.raises(ValueError):
        demo.create_app(root=other, llm=GuidedFake())
    with pytest.raises(ValueError):
        demo.create_app(root=tmp_path/'training'/'public', llm=GuidedFake(), public_origin='https://testserver')
