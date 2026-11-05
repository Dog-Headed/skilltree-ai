"""Real auth/store/queue boundary with explicitly Fake planning content."""
import json
import base64
import sqlite3
import time
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from deploy import training_demo as demo
from tests.test_v3_notes_outline import OutlineFake as GuidedFake
from tests.day11_support import learning_event, private_quiz, answers_for_quiz


class GuestFlowFake(GuidedFake):
    """Fake content for the production content-v1 path; no permission overrides."""
    def _invoke(self, schema, messages):
        if schema != 'QuizContent':
            return super()._invoke(schema, messages)
        self.calls.append({'schema': schema})
        payload = json.loads(messages[1].content.split('\n', 1)[1])
        return {key: {
            'prompt': 'Fake流程验收：解释资料中的规则 ' + key,
            'source_refs': list(slot['source_blocks']),
            'reference_answer': 'Fake参考说明 ' + next(iter(slot['source_blocks'].values()))[:150],
            'rubric': {name: {'description': 'Fake检查资料说明', 'max_score': 1.0}
                       for name in slot['rubric_slots']}
        } for key, slot in payload['slots'].items()}


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(demo, 'TRAINING_WORK', tmp_path)
    model = GuestFlowFake()
    gateway = demo.create_app(root=tmp_path/'instance', llm=model)
    with TestClient(gateway, base_url='http://127.0.0.1:18780') as client:
        yield client, gateway, model


def login(client, index=0):
    client.cookies.clear()  # Independent browser identities; switching revokes the previous cookie.
    result = client.post('/auth/login', json={'account': demo.ACCOUNTS[index][0], 'password': demo.DEMO_PASSWORD},
        headers={'X-SkillTree-Login': '1'})
    assert result.status_code == 200, result.text
    return {'Cookie': result.headers['set-cookie'].split(';')[0], 'X-CSRF-Token': result.json()['csrf_token']}


GARDEN_ENTRY = '/learn#/garden'


def assert_garden(response):
    """Original v3 garden shell, not the training card hub."""
    assert response.status_code == 200, response.text
    page = response.text
    assert 'SkillTree · 生长图谱' in page
    assert '让好奇慢慢生长' in page
    assert '＋ 种一棵树' in page
    assert '我的树' in page
    assert '正在打开你的学习空间' not in page
    assert 'training.js' not in page


def visit(client):
    client.cookies.clear()
    response = client.get('/', follow_redirects=False)
    assert response.status_code == 303 and response.headers['location'] == GARDEN_ENTRY
    cookie = response.headers['set-cookie']
    assert 'HttpOnly' in cookie and 'Max-Age=31536000' in cookie
    session = client.get('/session').json()
    assert session['guest'] and not session['logout']
    assert session['training']['role'] == 'guest' and session['training']['unit_id'] is None
    headers = {'Cookie': cookie.split(';')[0], 'X-CSRF-Token': session['csrf_token']}
    assert_garden(client.get('/learn', headers=headers))
    return headers, session['account']


def finish_request(client, headers, path, payload):
    response = client.post(path, headers=headers, json=payload)
    assert response.status_code in {200, 202}, response.text
    if response.status_code == 200:
        return response.json()
    job_id = response.json()['job']['id']
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        job = client.get('/jobs/' + job_id, headers=headers).json()['job']
        if job['state'] not in {'queued', 'running'}:
            break
        time.sleep(.05)
    assert job['state'] == 'completed', job
    return job['result']


def test_guest_isolation_unit_denial_and_login_keeps_personal_course(runtime):
    client, gateway, model = runtime
    assert 'id="guest-entry"' in client.get('/login').text
    guest, account = visit(client)
    assert client.get('/training/home', headers=guest).status_code == 200
    assert client.get('/training/materials', headers=guest).status_code == 200
    assert client.get('/learn', headers=guest).status_code == 200
    forged = {**guest, 'X-Role': 'admin', 'X-Evaluation-User': demo.ACCOUNTS[0][0]}
    for path in ('/training/admin', '/training/api/admin/overview', '/training/tasks', '/training/api/my-tasks'):
        assert client.get(path + '?role=admin', headers=forged).status_code == 403
    payload = {'request_id': str(uuid4()), 'intent': {'goal': '比较整数大小'}}
    assert client.post('/projects', json=payload, headers={'Cookie': guest['Cookie']}).status_code == 403
    created = client.post('/projects', json=payload, headers=guest)
    assert created.status_code == 201, created.text
    pid = created.json()['project_id']
    assert 'set-cookie' not in client.get('/', headers=guest).headers
    other, other_account = visit(client)
    assert account != other_account
    for headers in (other, login(client, 1), login(client, 0)):
        assert client.get('/projects/' + pid, headers=headers).status_code == 404
    assert gateway.training.store.member(account) is None
    assert len(gateway.training.store.overview(demo.UNIT_ID)['members']) == 4
    # Login from the guest cookie must adopt, not discard, the personal course.
    response = client.post('/auth/login', headers={**guest, 'X-SkillTree-Login': '1'},
        json={'account': demo.ACCOUNTS[1][0], 'password': demo.DEMO_PASSWORD})
    assert response.status_code == 200, response.text
    member = {'Cookie': response.headers['set-cookie'].split(';')[0]}
    assert client.get('/session', headers=member).json()['training']['role'] == 'employee'
    assert client.get('/projects/' + pid, headers=member).status_code == 200
    assert gateway.ownership.owned(account) == set()
    assert client.get('/session', headers=guest).status_code == 401
    assert model.calls == []


@pytest.mark.parametrize('filename', [None, 'guest-material.md', 'guest-material.txt'])
def test_guest_complete_learning_with_or_without_uploaded_material(runtime, filename):
    client, gateway, model = runtime
    headers, account = visit(client)
    response = client.post('/projects', headers=headers, json={
        'request_id': str(uuid4()), 'intent': {'goal': '学习整数大小比较', 'prior_knowledge': '零基础'}})
    assert response.status_code == 201, response.text
    view = response.json()
    pid = view['project_id']
    if filename:
        response = client.post('/projects/' + pid + '/sources', headers=headers, json={
            'request_id': str(uuid4()), 'title': '游客自己的资料',
            'source_description': '明确标记的合成流程验收资料', 'filename': filename,
            'data_base64': base64.b64encode('# 整数比较\n数轴上右侧的整数比左侧的大。\n例如 3 大于 1。'.encode()).decode()})
        assert response.status_code == 200, response.text
        view = client.get('/projects/' + pid, headers=headers).json()
    view = finish_request(client, headers, '/projects/' + pid + '/resume', learning_event(view, 'confirm_profile'))
    assert view['page_state'] == 'plan_review', view
    assert view['learning_basis'] == ('provided_material' if filename else 'ai_generated')
    assert model.call_counts['StudyNotes'] == (0 if filename else 1)
    view = finish_request(client, headers, '/projects/' + pid + '/resume',
                          learning_event(view, 'confirm_plan', private_references=[]))
    view = finish_request(client, headers, '/projects/' + pid + '/begin', {'request_id': str(uuid4())})
    assert view['page_state'] == 'learning' and view['tutor']['citations']
    view = finish_request(client, headers, '/projects/' + pid + '/resume', learning_event(view, 'start_quiz'))
    assert view['page_state'] == 'quiz', view
    assert 'answer_key' not in json.dumps(view['quiz'])
    quiz = private_quiz(gateway.paths, pid, view['assessment_id'])
    view = finish_request(client, headers, '/projects/' + pid + '/resume',
                          learning_event(view, 'submit_answer', answers=answers_for_quiz(quiz)))
    assert view['page_state'] == 'completed' and view['guard']['passed'], view
    assert len(view['completed_node_ids']) == 1
    calls = len(model.calls)
    assert client.get('/projects/' + pid, headers=headers).json()['page_state'] == 'completed'
    fresh = demo.create_app(root=gateway.paths.root.parent, llm=GuestFlowFake())
    with TestClient(fresh.application) as direct:
        assert direct.get('/projects/' + pid).json()['page_state'] == 'completed'
    assert fresh.auth.session(headers['Cookie'].split('=', 1)[1]) == account
    assert fresh.ownership.owned(account) == {pid}
    assert len(model.calls) == calls


def test_all_roles_server_auth_and_no_parameter_escalation(runtime):
    client, gateway, model = runtime
    assert client.get('/training/home', follow_redirects=False).headers['location'] == '/'
    assert client.get('/session', headers={'X-Evaluation-User': demo.ACCOUNTS[0][0]}).status_code == 401
    landing = client.get('/', follow_redirects=False)
    assert landing.status_code == 303 and landing.headers['location'] == GARDEN_ENTRY
    assert 'HttpOnly' in landing.headers['set-cookie']
    assert_garden(client.get('/learn'))
    assert client.get('/session').json()['guest'] is True
    assert client.post('/auth/register', json={}).status_code == 403
    for i in range(4):
        headers = login(client, i)
        session = client.get('/session', headers=headers).json()
        assert session['training']['role'] == ('admin' if i == 0 else 'employee')
        landing = client.get('/', headers=headers, follow_redirects=False)
        assert landing.status_code == 303 and landing.headers['location'] == GARDEN_ENTRY
        assert_garden(client.get('/learn', headers=headers))
        if i:
            forged = {**headers, 'X-Evaluation-User': demo.ACCOUNTS[0][0], 'X-Role': 'admin'}
            assert client.get('/training/admin?role=admin', headers=forged).status_code == 403
            assert client.get('/training/api/admin/overview?account=admin@example.test', headers=forged).status_code == 403
            assert client.post('/training/api/admin/publish', json={'role': 'admin'}, headers=forged).status_code == 403
        assert client.get('/learn', headers=headers).status_code == 200
        if i == 0:
            assert client.get('/training/admin', headers=headers).status_code == 200
        else:
            assert client.get('/training/home', headers=headers).status_code == 200
    client.cookies.clear()
    registered = client.post('/auth/register', headers={'X-SkillTree-Login': '1'}, json={
        'account': 'personal.entry@example.test', 'password': 'personal-password',
        'confirm_password': 'personal-password', 'remember': True})
    assert registered.status_code == 201, registered.text
    personal = client.get('/', follow_redirects=False)
    assert personal.status_code == 303 and personal.headers['location'] == GARDEN_ENTRY
    assert client.get('/session').json()['training']['role'] == 'personal'
    assert_garden(client.get('/learn'))
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
