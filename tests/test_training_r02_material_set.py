"""R02: preview and publish share the materials the draft actually cites."""
import base64
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from app.v3.contracts import LearningPlan
from app.v3.learning_repository import LearningRepository
from app.v3.materials import MaterialService
from deploy import training_demo as demo
from tests.test_training_demo import login
from tests.test_training_employee_start import StartFlowFake
from tests.training_publish_support import choice_objective, learning_profile, policy_for


A_TEXT = "# 甲制度\n甲资料只此一句：新员工须在入职后五个工作日内完成基础制度学习。\n"
B_TEXT = "# 乙制度\n乙资料只此一句：供应商须在签约后十个工作日内交付并保留验收单。\n"
C_TEXT = "# 丙制度\n丙资料只此一句：修订后的基础制度改为入职后三个工作日内完成。\n"


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(demo, 'TRAINING_WORK', tmp_path)
    gateway = demo.create_app(root=tmp_path / 'instance', llm=StartFlowFake())
    with TestClient(gateway, base_url='http://127.0.0.1:18780') as client:
        yield client, gateway


def _upload(client, admin, filename, title, text):
    response = client.post('/training/api/admin/materials', headers=admin, json={
        'request_id': str(uuid4()),
        'filename': filename,
        'title': title,
        'data_base64': base64.b64encode(text.encode()).decode(),
    })
    assert response.status_code in {200, 201}, response.text
    body = response.json()
    assert body['status'] == 'ready', body
    return body['id']


def _attach(client, admin, material_id, project_id):
    response = client.post(
        '/training/api/admin/materials/' + material_id + '/attach',
        headers=admin,
        json={'project_id': project_id, 'request_id': str(uuid4())},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _project(client, admin, title):
    created = client.post('/projects', headers=admin, json={
        'request_id': str(uuid4()),
        'profile': learning_profile(title, ['choice_exact']),
    })
    assert created.status_code in {200, 201}, created.text
    return created.json()['project_id']


def _save_plan(gateway, project_id, markers):
    """Confirm a plan that cites one chunk for each content marker."""
    with LearningRepository(gateway.paths) as repo:
        project = repo.get_project(project_id)
        catalog = MaterialService(repo).catalog(project_id)
        chosen = []
        for marker in markers:
            chosen.append(next(chunk for chunk in catalog if marker in chunk['content']))
        nodes = []
        for index, chunk in enumerate(chosen, start=1):
            nodes.append({
                'node_id': f'n{index}',
                'title': f'要点{index}',
                'description': f'根据已引用资料判断要点{index}。',
                'prerequisite_ids': [],
                'objectives': [choice_objective(
                    f'obj_n{index}', chunk['chunk_id'], f'从给定选项中判断要点{index}')],
            })
        objectives = [objective for node in nodes for objective in node['objectives']]
        plan = LearningPlan.model_validate({
            'project_id': project_id,
            'draft_revision': project['draft_revision'],
            'plan_version': 1,
            'nodes': nodes,
        })
        policy = policy_for(objectives, ['choice_exact'])
        repo.save_candidate_plan(
            project_id, plan, expected_revision=project['draft_revision'], policy=policy)
        saved = repo.get_project(project_id)
    return saved['draft_revision'], sorted({chunk['source_id'] for chunk in chosen})


def _listed(client, admin, project_id):
    body = client.get('/training/api/admin/course-drafts', headers=admin)
    assert body.status_code == 200, body.text
    return next(item for item in body.json()['drafts'] if item['project_id'] == project_id)


def _frontend_publish(draft, title):
    """The fields training.js sends: the preview's referenced id list, unchanged."""
    return {
        'request_id': str(uuid4()),
        'draft_project_id': draft['project_id'],
        'draft_revision': draft['draft_revision'],
        'title': title,
        'required_nodes': [node['node_id'] for node in draft['nodes']],
        'material_version_ids': list(draft['material_version_ids']),
    }


def _claim(client, gateway, admin, course, marker_present, marker_absent):
    account = demo.ACCOUNTS[1][0]
    task = client.post('/training/api/admin/tasks/assign', headers=admin, json={
        'request_id': str(uuid4()),
        'course_version_id': course['id'],
        'title': '引用资料任务',
        'accounts': [account],
    })
    assert task.status_code == 201, task.text
    employee_task = next(row['id'] for row in client.get(
        '/training/api/admin/tasks/' + task.json()['id'], headers=admin).json()['assignees']
        if row['account'] == account)
    started = client.post(
        '/training/api/my-tasks/' + employee_task + '/start',
        headers=login(client, 1),
        json={'request_id': str(uuid4())},
    )
    assert started.status_code == 201, started.text
    project_id = started.json()['project_id']
    with LearningRepository(gateway.paths) as repo:
        documents = repo.list_sources(project_id, include_private=True)
        text = '\n'.join(document['content'] for document in documents)
        source_ids = {document['source_id'] for document in documents}
    assert source_ids == set(course['material_version_ids'])
    assert marker_present in text
    assert marker_absent not in text
    return project_id


def test_preview_publish_and_claim_use_only_the_referenced_material(runtime):
    client, gateway = runtime
    admin = login(client, 0)
    material_a = _upload(client, admin, 'a.md', '甲制度', A_TEXT)
    material_b = _upload(client, admin, 'b.md', '乙制度', B_TEXT)
    project_id = _project(client, admin, '只引用甲')
    _attach(client, admin, material_a, project_id)
    _attach(client, admin, material_b, project_id)
    _save_plan(gateway, project_id, ['甲资料只此一句'])

    draft = _listed(client, admin, project_id)
    assert draft['publishable'] is True
    assert draft['material_version_ids'] == [material_a]
    assert draft['unreferenced_material_version_ids'] == [material_b]
    cited = [row for row in draft['materials'] if row['referenced']]
    extra = [row for row in draft['materials'] if not row['referenced']]
    assert [row['material_version_id'] for row in cited] == [material_a]
    assert cited[0]['title'] == '甲制度'
    assert [row['material_version_id'] for row in extra] == [material_b]

    before = client.get('/training/api/admin/overview', headers=admin).json()['courses']
    mismatched = client.post('/training/api/admin/courses/publish', headers=admin, json={
        **_frontend_publish(draft, '只引用甲'),
        'material_version_ids': sorted([material_a, material_b]),
    })
    assert mismatched.status_code == 422
    assert mismatched.json()['error']['code'] == 'material_mismatch'
    assert client.get('/training/api/admin/overview', headers=admin).json()['courses'] == before

    published = client.post(
        '/training/api/admin/courses/publish', headers=admin,
        json=_frontend_publish(draft, '只引用甲'))
    assert published.status_code == 201, published.text
    course = published.json()
    assert course['material_version_ids'] == [material_a]
    assert {item['material_version_id'] for item in course['tree']['source_index']} == {material_a}
    _claim(client, gateway, admin, course, '甲资料只此一句', '乙资料只此一句')


def test_both_attached_materials_are_referenced_and_claimed(runtime):
    client, gateway = runtime
    admin = login(client, 0)
    material_a = _upload(client, admin, 'a.md', '甲制度', A_TEXT)
    material_b = _upload(client, admin, 'b.md', '乙制度', B_TEXT)
    project_id = _project(client, admin, '两份都引用')
    _attach(client, admin, material_a, project_id)
    _attach(client, admin, material_b, project_id)
    _save_plan(gateway, project_id, ['甲资料只此一句', '乙资料只此一句'])

    draft = _listed(client, admin, project_id)
    assert draft['publishable'] is True
    assert draft['material_version_ids'] == sorted([material_a, material_b])
    assert draft['unreferenced_material_version_ids'] == []
    published = client.post(
        '/training/api/admin/courses/publish', headers=admin,
        json=_frontend_publish(draft, '两份都引用'))
    assert published.status_code == 201, published.text
    course = published.json()
    assert course['material_version_ids'] == sorted([material_a, material_b])
    account = demo.ACCOUNTS[1][0]
    task = client.post('/training/api/admin/tasks/assign', headers=admin, json={
        'request_id': str(uuid4()),
        'course_version_id': course['id'],
        'title': '两份资料任务',
        'accounts': [account],
    })
    assert task.status_code == 201, task.text
    employee_task = task.json()['assignees'][0]['id']
    started = client.post(
        '/training/api/my-tasks/' + employee_task + '/start',
        headers=login(client, 1),
        json={'request_id': str(uuid4())},
    )
    assert started.status_code == 201, started.text
    with LearningRepository(gateway.paths) as repo:
        documents = repo.list_sources(started.json()['project_id'], include_private=True)
    text = '\n'.join(document['content'] for document in documents)
    assert {document['source_id'] for document in documents} == {material_a, material_b}
    assert '甲资料只此一句' in text and '乙资料只此一句' in text


def test_material_change_after_confirmation_requires_replan(runtime):
    client, gateway = runtime
    admin = login(client, 0)
    material_a = _upload(client, admin, 'a.md', '甲制度', A_TEXT)
    project_id = _project(client, admin, '待修订')
    _attach(client, admin, material_a, project_id)
    saved_revision, _cited = _save_plan(gateway, project_id, ['甲资料只此一句'])
    ready = _listed(client, admin, project_id)
    assert ready['publishable'] is True
    assert ready['draft_revision'] == saved_revision

    material_c = _upload(client, admin, 'c.md', '丙制度', C_TEXT)
    attached = _attach(client, admin, material_c, project_id)
    assert attached['draft_revision'] != saved_revision
    stale = _listed(client, admin, project_id)
    assert stale['publishable'] is False
    assert '重新生成' in (stale['reason'] or '')
    before = client.get('/training/api/admin/overview', headers=admin).json()['courses']
    refused = client.post('/training/api/admin/courses/publish', headers=admin, json={
        **_frontend_publish(stale, '待修订'),
        'draft_revision': saved_revision,
    })
    assert refused.status_code == 409
    assert refused.json()['error']['code'] == 'draft_stale'
    assert client.get('/training/api/admin/overview', headers=admin).json()['courses'] == before

    _save_plan(gateway, project_id, ['丙资料只此一句'])
    refreshed = _listed(client, admin, project_id)
    assert refreshed['publishable'] is True
    assert refreshed['material_version_ids'] == [material_c]
    assert material_a in refreshed['unreferenced_material_version_ids']
    published = client.post(
        '/training/api/admin/courses/publish', headers=admin,
        json=_frontend_publish(refreshed, '修订后只引用丙'))
    assert published.status_code == 201, published.text
    course = published.json()
    assert course['material_version_ids'] == [material_c]
    _claim(client, gateway, admin, course, '丙资料只此一句', '甲资料只此一句')


def test_publish_page_submits_referenced_ids_and_shows_unreferenced_materials():
    source = Path('app/static/training.js').read_text(encoding='utf-8')
    submit = source.split("form.addEventListener('submit'", 1)[1].split('for(const draft of drafts', 1)[0]
    assert 'material_version_ids:draft.material_version_ids' in submit
    assert 'unreferenced_material_version_ids' not in submit
    assert 'materials.filter' not in submit
    assert '不会进入本次发布' in source
    assert '本次发布引用' in source
