"""Day 3 foundation: publish course versions and assign tasks (no learner start yet)."""
import base64
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from deploy import training_demo as demo
from tests.test_training_demo import login
from tests.test_v3_notes_outline import OutlineFake as GuidedFake
from tests.training_publish_support import chain_nodes, confirm_draft, publish_payload


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(demo, 'TRAINING_WORK', tmp_path)
    gateway = demo.create_app(root=tmp_path / 'instance', llm=GuidedFake())
    with TestClient(gateway, base_url='http://127.0.0.1:18780') as client:
        yield client, gateway


def upload_unit_material(client, headers, name='policy.md'):
    raw = '# 制度\n新员工须在入职后 5 个工作日内完成基础制度学习。\n'.encode()
    response = client.post('/training/api/admin/materials', headers=headers, json={
        'request_id': str(uuid4()), 'filename': name, 'title': '基础制度',
        'data_base64': base64.b64encode(raw).decode()})
    assert response.status_code in {200, 201}, response.text
    body = response.json()
    assert body['status'] == 'ready'
    return body['id']


def test_publish_assign_idempotent_and_visibility(runtime):
    client, gateway = runtime
    admin = login(client, 0)
    overview = client.get('/training/api/admin/overview', headers=admin).json()
    assert overview['publishing_available'] is True
    material_id = upload_unit_material(client, admin)
    draft = confirm_draft(
        client, gateway, admin, material_id, '基础制度短课', chain_nodes(), ['choice_exact'])
    request = str(uuid4())
    body = publish_payload(
        draft, title='基础制度短课', course_id='basic-policy', request_id=request,
        required_nodes=['n1', 'n2', 'n3'])
    published = client.post('/training/api/admin/courses/publish', headers=admin, json=body)
    assert published.status_code == 201, published.text
    course = published.json()
    assert course['created'] is True and course['version'] == 1
    assert course['material_version_ids'] == [material_id]
    assert course['tree']['published_from']['project_id'] == draft['project_id']
    assert course['tree']['published_from']['draft_revision'] == draft['draft_revision']
    again = client.post('/training/api/admin/courses/publish', headers=admin, json=body)
    assert again.status_code == 200 and again.json()['id'] == course['id']
    assert again.json()['created'] is False

    # Employees cannot publish.
    employee = login(client, 1)
    assert client.post('/training/api/admin/courses/publish', headers=employee, json={
        'request_id': str(uuid4()), 'course_id': 'x', 'title': 'x',
        'draft_project_id': draft['project_id'], 'draft_revision': draft['draft_revision'],
        'required_nodes': ['n1'], 'material_version_ids': [material_id],
    }).status_code == 403

    assign_req = str(uuid4())
    a, b, c = demo.ACCOUNTS[1][0], demo.ACCOUNTS[2][0], demo.ACCOUNTS[3][0]
    assigned = client.post('/training/api/admin/tasks/assign', headers=admin, json={
        'request_id': assign_req, 'course_version_id': course['id'],
        'title': '本周制度学习', 'due_at': '2026-12-31T18:00:00+08:00',
        'accounts': [a, b],
    })
    assert assigned.status_code == 201, assigned.text
    task = assigned.json()
    assert {row['account'] for row in task['assignees']} == {a, b}
    replay = client.post('/training/api/admin/tasks/assign', headers=admin, json={
        'request_id': assign_req, 'course_version_id': course['id'],
        'title': '本周制度学习', 'accounts': [a, b],
    })
    assert replay.status_code == 200 and replay.json()['id'] == task['id']

    # Visibility: A and B see the task; C does not.
    for index, expect in ((1, 1), (2, 1), (3, 0)):
        headers = login(client, index)
        mine = client.get('/training/api/my-tasks', headers=headers)
        assert mine.status_code == 200
        assert len(mine.json()['tasks']) == expect

    detail = client.get('/training/api/admin/tasks/' + task['id'], headers=admin)
    assert detail.status_code == 200 and len(detail.json()['assignees']) == 2
    assert client.get('/training/api/admin/tasks/' + task['id'], headers=login(client, 1)).status_code == 403
