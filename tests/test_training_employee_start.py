"""Day 3 employee start: independent project from published course, no Planner rewrite."""
import base64
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from deploy import training_demo as demo
from tests.test_training_demo import login, finish_request, GuestFlowFake
from tests.day11_support import learning_event, private_quiz, answers_for_quiz
from tests.training_publish_support import chain_nodes, confirm_draft, publish_payload
from app.v3.learning_repository import LearningRepository
import json


class StartFlowFake(GuestFlowFake):
    """GuestFlowFake plus choice QuizContent fields used by published short courses."""
    def _invoke(self, schema, messages):
        if schema != 'QuizContent':
            return super()._invoke(schema, messages)
        self.calls.append({'schema': schema})
        payload = json.loads(messages[1].content.split('\n', 1)[1])
        out = {}
        for key, slot in payload['slots'].items():
            fields = set(slot.get('output_fields') or [])
            if 'options' in fields or slot.get('question_type') in {'single_choice', 'multiple_choice'}:
                out[key] = {
                    'prompt': 'Fake流程验收：依据资料选择关于规则的正确说法 ' + key,
                    'source_refs': list(slot['source_blocks']),
                    'options': [
                        next(iter(slot['source_blocks'].values()))[:80],
                        '资料中未出现的无关说法',
                    ],
                    'correct_option': 1,
                    'max_score': 1.0,
                }
            else:
                out[key] = {
                    'prompt': 'Fake流程验收：解释资料中的规则 ' + key,
                    'source_refs': list(slot['source_blocks']),
                    'reference_answer': 'Fake参考说明 ' + next(iter(slot['source_blocks'].values()))[:150],
                    'rubric': {name: {'description': 'Fake检查资料说明', 'max_score': 1.0}
                               for name in slot.get('rubric_slots') or {'r1': None}},
                }
        return out


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(demo, 'TRAINING_WORK', tmp_path)
    model = StartFlowFake()
    gateway = demo.create_app(root=tmp_path / 'instance', llm=model)
    with TestClient(gateway, base_url='http://127.0.0.1:18780') as client:
        yield client, gateway, model


def publish_and_assign(client, gateway, admin, accounts, *, course_id='basic-policy', title='基础制度短课'):
    raw = '# 制度\n新员工须在入职后 5 个工作日内完成基础制度学习。\n适用范围：全体新员工。\n'.encode()
    material = client.post('/training/api/admin/materials', headers=admin, json={
        'request_id': str(uuid4()), 'filename': 'policy.md', 'title': '基础制度',
        'data_base64': base64.b64encode(raw).decode()}).json()
    assert material['status'] == 'ready'
    draft = confirm_draft(
        client, gateway, admin, material['id'], title, chain_nodes(), ['choice_exact'])
    published = client.post('/training/api/admin/courses/publish', headers=admin, json=publish_payload(
        draft, title=title, course_id=course_id, required_nodes=['n1', 'n2', 'n3']))
    assert published.status_code == 201, published.text
    course = published.json()
    task = client.post('/training/api/admin/tasks/assign', headers=admin, json={
        'request_id': str(uuid4()), 'course_version_id': course['id'],
        'title': '本周制度学习', 'due_at': '2026-12-31T18:00:00+08:00',
        'accounts': accounts,
    }).json()
    return material, course, task


def test_employee_start_idempotent_independent_and_learnable(runtime):
    client, gateway, model = runtime
    admin = login(client, 0)
    a, b, c = demo.ACCOUNTS[1][0], demo.ACCOUNTS[2][0], demo.ACCOUNTS[3][0]
    material, course, task = publish_and_assign(client, gateway, admin, [a, b])

    # Resolve employee_task ids from assignee rows.
    detail = client.get('/training/api/admin/tasks/' + task['id'], headers=admin).json()
    by_account = {row['account']: row for row in detail['assignees']}
    et_a, et_b = by_account[a]['id'], by_account[b]['id']

    headers_a = login(client, 1)
    request = str(uuid4())
    started = client.post('/training/api/my-tasks/' + et_a + '/start', headers=headers_a,
                          json={'request_id': request})
    assert started.status_code == 201, started.text
    body = started.json()
    assert body['created'] is True and body['project_id'].startswith('v3_')
    pid_a = body['project_id']
    assert body['node_bindings'] == {'n1': 'n1', 'n2': 'n2', 'n3': 'n3'}

    # Idempotent request_id and already-started.
    again = client.post('/training/api/my-tasks/' + et_a + '/start', headers=headers_a,
                        json={'request_id': request})
    assert again.status_code == 200 and again.json()['project_id'] == pid_a and again.json()['created'] is False
    other = client.post('/training/api/my-tasks/' + et_a + '/start', headers=headers_a,
                        json={'request_id': str(uuid4())})
    assert other.status_code == 200 and other.json()['project_id'] == pid_a

    # B gets an independent project; chunks are not shared by id.
    headers_b = login(client, 2)
    started_b = client.post('/training/api/my-tasks/' + et_b + '/start', headers=headers_b,
                            json={'request_id': str(uuid4())})
    assert started_b.status_code == 201, started_b.text
    pid_b = started_b.json()['project_id']
    assert pid_b != pid_a

    with LearningRepository(gateway.paths) as repo:
        chunks_a = [r['chunk_id'] for r in repo.conn.execute(
            'SELECT chunk_id FROM source_chunks WHERE project_id=?', (pid_a,))]
        chunks_b = [r['chunk_id'] for r in repo.conn.execute(
            'SELECT chunk_id FROM source_chunks WHERE project_id=?', (pid_b,))]
        assert chunks_a and chunks_b and set(chunks_a).isdisjoint(set(chunks_b))
        plan_a = repo.get_project(pid_a)['candidate_plan']
        assert plan_a['project_id'] == pid_a
        assert [n['node_id'] for n in plan_a['nodes']] == ['n1', 'n2', 'n3']
        assert plan_a['nodes'][0]['title'] == '时限要求'
        # Frozen; no Planner calls for start.
        assert repo.get_project(pid_a)['frozen_snapshot']
    assert not any(call.get('schema') == 'LearningPlan' for call in getattr(model, 'calls', []))

    # Ownership isolation.
    assert pid_a in gateway.ownership.owned(a)
    assert pid_a not in gateway.ownership.owned(b)
    assert client.get('/projects/' + pid_a, headers=headers_b).status_code == 404
    assert client.get('/projects/' + pid_a, headers=headers_a).status_code == 200

    # C cannot start A's task.
    headers_c = login(client, 3)
    assert client.post('/training/api/my-tasks/' + et_a + '/start', headers=headers_c,
                       json={'request_id': str(uuid4())}).status_code == 404

    # Real teach + quiz on first node for A (Fake content path).
    view = client.get('/projects/' + pid_a, headers=headers_a).json()
    view = finish_request(client, headers_a, '/projects/' + pid_a + '/begin', {'request_id': str(uuid4())})
    assert view['page_state'] == 'learning', view
    view = finish_request(client, headers_a, '/projects/' + pid_a + '/resume', learning_event(view, 'start_quiz'))
    assert view['page_state'] == 'quiz', view
    quiz = private_quiz(gateway.paths, pid_a, view['assessment_id'])
    view = finish_request(client, headers_a, '/projects/' + pid_a + '/resume',
                          learning_event(view, 'submit_answer', answers=answers_for_quiz(quiz)))
    assert view['guard']['passed'], view
    assert 'n1' in view['completed_node_ids']

    # B unchanged.
    view_b = client.get('/projects/' + pid_b, headers=headers_b).json()
    assert view_b.get('completed_node_ids', []) == []

    mine = client.get('/training/api/my-tasks', headers=headers_a).json()
    assert mine['learning_available'] is True
    row = next(t for t in mine['tasks'] if t['id'] == et_a)
    assert row['progress']['required_passed'] >= 1
    assert row['progress']['required_total'] == 3
    assert row['status'] == 'in_progress'
