"""Day 4 admin dashboard from real learning facts."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from deploy import training_demo as demo
from deploy import training_learner
from tests.test_training_demo import login, finish_request
from tests.test_training_employee_start import StartFlowFake, publish_and_assign
from tests.day11_support import learning_event, private_quiz, answers_for_quiz


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(demo, 'TRAINING_WORK', tmp_path)
    model = StartFlowFake()
    gateway = demo.create_app(root=tmp_path / 'instance', llm=model)
    with TestClient(gateway, base_url='http://127.0.0.1:18780') as client:
        yield client, gateway, model


def test_dashboard_progress_overdue_and_isolation(runtime):
    client, gateway, model = runtime
    admin = login(client, 0)
    a, b, c = demo.ACCOUNTS[1][0], demo.ACCOUNTS[2][0], demo.ACCOUNTS[3][0]
    _, course, task = publish_and_assign(client, gateway, admin, [a, b])
    # Force an overdue deadline via a fresh assign with past due.
    past = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    overdue_task = client.post('/training/api/admin/tasks/assign', headers=admin, json={
        'request_id': str(uuid4()), 'course_version_id': course['id'],
        'title': '逾期制度复习', 'due_at': past, 'accounts': [a, b],
    }).json()
    assert overdue_task['created'] is True

    empty = client.get('/training/api/admin/dashboard', headers=admin)
    assert empty.status_code == 200
    assert empty.json()['dashboard_available'] is True
    assert len(empty.json()['tasks']) >= 2

    # Start both on the overdue task; A completes first node.
    detail = client.get('/training/api/admin/tasks/' + overdue_task['id'], headers=admin).json()
    by_account = {row['account']: row for row in detail['assignees']}
    et_a, et_b = by_account[a]['id'], by_account[b]['id']
    headers_a = login(client, 1)
    headers_b = login(client, 2)
    pid_a = client.post('/training/api/my-tasks/' + et_a + '/start', headers=headers_a,
                        json={'request_id': str(uuid4())}).json()['project_id']
    client.post('/training/api/my-tasks/' + et_b + '/start', headers=headers_b,
                json={'request_id': str(uuid4())})
    view = finish_request(client, headers_a, '/projects/' + pid_a + '/begin', {'request_id': str(uuid4())})
    view = finish_request(client, headers_a, '/projects/' + pid_a + '/resume', learning_event(view, 'start_quiz'))
    quiz = private_quiz(gateway.paths, pid_a, view['assessment_id'])
    view = finish_request(client, headers_a, '/projects/' + pid_a + '/resume',
                          learning_event(view, 'submit_answer', answers=answers_for_quiz(quiz)))
    assert view['guard']['passed']

    board = client.get('/training/api/admin/tasks/' + overdue_task['id'] + '/board', headers=admin)
    assert board.status_code == 200, board.text
    body = board.json()
    assert body['counts']['assigned'] == 2
    assert body['counts']['started'] == 2
    assert body['counts']['completed'] == 0  # course has 3 required nodes
    assert body['overdue'] is True
    by = {row['account']: row for row in body['employees']}
    assert by[a]['progress']['required_passed'] == 1
    assert by[a]['progress']['required_total'] == 3
    assert by[a]['status'] == 'in_progress'
    assert by[a]['overdue'] is True
    assert by[b]['progress']['required_passed'] == 0
    assert by[b]['status'] == 'in_progress'

    # Employees cannot read admin board.
    assert client.get('/training/api/admin/dashboard', headers=headers_a).status_code == 403
    assert client.get('/training/api/admin/tasks/' + overdue_task['id'] + '/board',
                      headers=headers_a).status_code == 403
    # Unassigned employee C still denied.
    assert client.get('/training/api/admin/tasks/' + overdue_task['id'] + '/board',
                      headers=login(client, 3)).status_code == 403

    # Personal courses do not appear in unit dashboard counts.
    overview = client.get('/training/api/admin/dashboard', headers=admin).json()
    target = next(t for t in overview['tasks'] if t['id'] == overdue_task['id'])
    assert target['counts']['started'] == 2


def test_overdue_timezone_helper():
    due = '2026-01-01T12:00:00+08:00'
    before = datetime(2026, 1, 1, 3, 0, tzinfo=timezone.utc)  # 11:00 +08
    after = datetime(2026, 1, 1, 5, 0, tzinfo=timezone.utc)   # 13:00 +08
    assert training_learner.overdue_flag(due, now=before)['overdue'] is False
    assert training_learner.overdue_flag(due, now=after)['overdue'] is True
    naive = training_learner.overdue_flag('2026-01-01T12:00:00', now=after)
    assert naive['due_timezone'] is not None
