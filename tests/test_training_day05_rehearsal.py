"""Day 5 isolated offline rehearsal for the training demo loop."""
import base64
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from deploy import training_demo as demo
from tests.test_training_demo import login, finish_request, visit
from tests.test_training_employee_start import StartFlowFake
from tests.training_publish_support import chain_nodes, confirm_draft, publish_payload
from tests.day11_support import learning_event, private_quiz, answers_for_quiz


SAMPLES = Path(__file__).resolve().parents[1] / 'docs' / 'training-demo' / 'samples'


@pytest.fixture
def rehearsal(tmp_path, monkeypatch):
    monkeypatch.setattr(demo, 'TRAINING_WORK', tmp_path)
    root = tmp_path / 'rehearsal-day05'
    model = StartFlowFake()
    gateway = demo.create_app(root=root, llm=model, port=18781)
    with TestClient(gateway, base_url='http://127.0.0.1:18781') as client:
        yield client, gateway, model, root


def _pass_current_node(client, headers, gateway, pid, view):
    view = finish_request(client, headers, '/projects/' + pid + '/resume', learning_event(view, 'start_quiz'))
    assert view['page_state'] == 'quiz', view
    quiz = private_quiz(gateway.paths, pid, view['assessment_id'])
    return finish_request(client, headers, '/projects/' + pid + '/resume',
                          learning_event(view, 'submit_answer', answers=answers_for_quiz(quiz)))


def _wrong_answers(quiz):
    answers = answers_for_quiz(quiz)
    for qid, answer in list(answers.items()):
        question = next(q for q in quiz['questions'] if q['question_id'] == qid)
        if question['question_type'] not in {'single_choice', 'multiple_choice'}:
            continue
        options = [o['option_id'] for o in question['options']]
        key = answer if isinstance(answer, str) else answer[0]
        answers[qid] = next(o for o in options if o != key)
    return answers


def test_day05_isolated_rehearsal_loop(rehearsal):
    client, gateway, model, root = rehearsal
    admin = login(client, 0)
    a, b, c = demo.ACCOUNTS[1][0], demo.ACCOUNTS[2][0], demo.ACCOUNTS[3][0]

    # Guest entry on isolated instance.
    guest_headers, guest_account = visit(client)
    assert guest_account
    assert client.get('/training/home', headers=guest_headers).status_code == 200

    # Upload all four office formats.
    material_ids = []
    for sample in sorted(SAMPLES.iterdir()):
        response = client.post('/training/api/admin/materials', headers=admin, json={
            'request_id': str(uuid4()), 'filename': sample.name, 'title': sample.stem,
            'data_base64': base64.b64encode(sample.read_bytes()).decode()})
        assert response.status_code in {200, 201}, response.text
        body = response.json()
        assert body['status'] == 'ready', body
        material_ids.append(body['id'])
        detail = client.get('/training/api/admin/materials/' + body['id'], headers=admin).json()
        assert detail['parsed']['content']
    assert len(material_ids) == 4

    bad = client.post('/training/api/admin/materials', headers=admin, json={
        'request_id': str(uuid4()), 'filename': 'broken.exe', 'title': '坏文件',
        'data_base64': base64.b64encode(b'MZ-not-office').decode()})
    assert bad.status_code in {400, 422} or bad.json().get('status') == 'failed'

    # Publish the confirmed draft of the uploaded DOCX, not a hand-filled placeholder tree.
    docx_id = next(i for i, p in zip(material_ids, sorted(SAMPLES.iterdir())) if p.suffix == '.docx')
    draft = confirm_draft(client, gateway, admin, docx_id, 'Day5 制度短课', chain_nodes(), ['choice_exact'])
    published = client.post('/training/api/admin/courses/publish', headers=admin, json=publish_payload(
        draft, title='Day5 制度短课', course_id='day5-policy', required_nodes=['n1', 'n2', 'n3']))
    assert published.status_code == 201, published.text
    course = published.json()
    assert course['course_id'] == 'day5-policy' and course['material_version_ids'] == [docx_id]
    assign_req = str(uuid4())
    task = client.post('/training/api/admin/tasks/assign', headers=admin, json={
        'request_id': assign_req, 'course_version_id': course['id'],
        'title': 'Day5 演练任务', 'accounts': [a, b],
    }).json()
    replay = client.post('/training/api/admin/tasks/assign', headers=admin, json={
        'request_id': assign_req, 'course_version_id': course['id'],
        'title': 'Day5 演练任务', 'accounts': [a, b],
    }).json()
    assert replay['id'] == task['id'] and replay['created'] is False

    detail = client.get('/training/api/admin/tasks/' + task['id'], headers=admin).json()
    by_account = {row['account']: row for row in detail['assignees']}
    et_a, et_b = by_account[a]['id'], by_account[b]['id']
    headers_a, headers_b, headers_c = login(client, 1), login(client, 2), login(client, 3)
    assert client.get('/training/api/my-tasks', headers=headers_c).json()['tasks'] == []

    start_a = client.post('/training/api/my-tasks/' + et_a + '/start', headers=headers_a,
                          json={'request_id': str(uuid4())}).json()
    start_b = client.post('/training/api/my-tasks/' + et_b + '/start', headers=headers_b,
                          json={'request_id': str(uuid4())}).json()
    pid_a, pid_b = start_a['project_id'], start_b['project_id']
    assert pid_a != pid_b

    # 甲：干净完成全部必学节点。
    view = finish_request(client, headers_a, '/projects/' + pid_a + '/begin', {'request_id': str(uuid4())})
    for _ in range(3):
        assert view['page_state'] == 'learning', view
        view = _pass_current_node(client, headers_a, gateway, pid_a, view)
    assert len(view.get('completed_node_ids') or []) == 3, view

    # 乙：答错进入补弱/诊断分支，保持进行中。
    view_b = finish_request(client, headers_b, '/projects/' + pid_b + '/begin', {'request_id': str(uuid4())})
    view_b = finish_request(client, headers_b, '/projects/' + pid_b + '/resume', learning_event(view_b, 'start_quiz'))
    quiz_b = private_quiz(gateway.paths, pid_b, view_b['assessment_id'])
    failed = finish_request(client, headers_b, '/projects/' + pid_b + '/resume',
                            learning_event(view_b, 'submit_answer', answers=_wrong_answers(quiz_b)))
    assert failed.get('guard', {}).get('passed') is False
    assert failed.get('mode') == 'remediate' or failed['page_state'] in {'learning', 'remediation', 'review'}
    assert not failed.get('completed_node_ids')

    # 丙与游客：自主学习，不计入单位任务。
    assert client.post('/projects', headers=headers_c, json={
        'request_id': str(uuid4()), 'intent': {'goal': '自由了解办公礼仪', 'prior_knowledge': '零基础'},
    }).status_code == 201
    assert client.post('/projects', headers=guest_headers, json={
        'request_id': str(uuid4()), 'intent': {'goal': '游客自学入门', 'prior_knowledge': '零基础'},
    }).status_code == 201

    board = client.get('/training/api/admin/tasks/' + task['id'] + '/board', headers=admin).json()
    assert board['counts']['assigned'] == 2 and board['counts']['started'] == 2
    assert board['counts']['completed'] == 1
    by = {row['account']: row for row in board['employees']}
    assert by[a]['completed'] is True and by[a]['progress']['required_passed'] == 3
    assert by[b]['completed'] is False and by[b]['status'] == 'in_progress'

def test_day05_restart_keeps_progress(tmp_path, monkeypatch):
    """Second process on the same isolated root must keep Day5 progress."""
    monkeypatch.setattr(demo, 'TRAINING_WORK', tmp_path)
    root = tmp_path / 'rehearsal-day05-restart'
    model = StartFlowFake()
    gateway = demo.create_app(root=root, llm=model, port=18782)
    with TestClient(gateway, base_url='http://127.0.0.1:18782') as client:
        admin = login(client, 0)
        a, b = demo.ACCOUNTS[1][0], demo.ACCOUNTS[2][0]
        sample = next(p for p in sorted(SAMPLES.iterdir()) if p.suffix == '.docx')
        mid = client.post('/training/api/admin/materials', headers=admin, json={
            'request_id': str(uuid4()), 'filename': sample.name, 'title': sample.stem,
            'data_base64': base64.b64encode(sample.read_bytes()).decode()}).json()['id']
        draft = confirm_draft(client, gateway, admin, mid, '重启课', chain_nodes(), ['choice_exact'])
        published = client.post('/training/api/admin/courses/publish', headers=admin, json=publish_payload(
            draft, title='重启课', course_id='day5-restart', required_nodes=['n1', 'n2', 'n3']))
        assert published.status_code == 201, published.text
        course = published.json()
        task = client.post('/training/api/admin/tasks/assign', headers=admin, json={
            'request_id': str(uuid4()), 'course_version_id': course['id'],
            'title': '重启任务', 'accounts': [a, b]}).json()
        detail = client.get('/training/api/admin/tasks/' + task['id'], headers=admin).json()
        by_account = {row['account']: row for row in detail['assignees']}
        headers_a, headers_b = login(client, 1), login(client, 2)
        pid_a = client.post('/training/api/my-tasks/' + by_account[a]['id'] + '/start',
                            headers=headers_a, json={'request_id': str(uuid4())}).json()['project_id']
        pid_b = client.post('/training/api/my-tasks/' + by_account[b]['id'] + '/start',
                            headers=headers_b, json={'request_id': str(uuid4())}).json()['project_id']
        view = finish_request(client, headers_a, '/projects/' + pid_a + '/begin', {'request_id': str(uuid4())})
        for _ in range(3):
            view = _pass_current_node(client, headers_a, gateway, pid_a, view)
        assert len(view.get('completed_node_ids') or []) == 3
        view_b = finish_request(client, headers_b, '/projects/' + pid_b + '/begin', {'request_id': str(uuid4())})
        assert view_b['page_state'] == 'learning'
        task_id = task['id']
    fresh = demo.create_app(root=root, llm=StartFlowFake(), port=18782)
    with TestClient(fresh, base_url='http://127.0.0.1:18782') as client2:
        admin2 = login(client2, 0)
        board2 = client2.get('/training/api/admin/tasks/' + task_id + '/board', headers=admin2).json()
        assert board2['counts']['completed'] == 1 and board2['counts']['started'] == 2
        headers_b2 = login(client2, 2)
        restarted = client2.get('/projects/' + pid_b, headers=headers_b2).json()
        assert restarted['page_state'] == 'learning'
        assert restarted.get('completed_node_ids', []) == []
