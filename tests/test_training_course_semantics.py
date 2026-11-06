"""R01–R05: claim authorization, publish checks, and preserved course semantics."""
import base64
import json
import sqlite3
import threading
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from app.v3.contracts import EvaluationPolicy
from app.v3.learning_repository import LearningRepository
from deploy import training_demo as demo
from deploy import training_learner
from deploy.training_store import TrainingStore
from tests.day11_support import answers_for_quiz, learning_event, private_quiz
from tests.test_training_demo import finish_request, login
from tests.test_training_employee_start import StartFlowFake, publish_and_assign
from tests.training_publish_support import (
    choice_objective, confirm_draft, confirm_draft_with_policy, policy_for, publish_payload,
)


MATERIAL = 'material_' + ('a' * 32)
ANCHOR = f'ref_{MATERIAL}_1_1_' + ('ab' * 6)


def _objective(objective_id='obj_n1'):
    return {
        'objective_id': objective_id,
        'observable_outcome': '从给定选项中判断时限要求',
        'required_capability_ids': ['choice_exact'],
        'evidence_requirement': ['choice'],
        'required': True,
        'source_chunk_ids': [ANCHOR],
        'assessment_tasks': [{
            'task_form': 'choice',
            'submission': '选项作答',
            'requirements': ['判断时限'],
            'criteria': ['与资料一致'],
        }],
    }


def _node(node_id='n1', prerequisites=None, objective_id='obj_n1'):
    return {
        'node_id': node_id,
        'title': '时限要求',
        'description': '学习时限要求并做出选择。',
        'prerequisite_ids': prerequisites or [],
        'objectives': [_objective(objective_id)],
    }


def _tree(nodes=None):
    return {
        'plan_version': 1,
        'nodes': nodes or [_node()],
        'source_index': [{
            'anchor': ANCHOR,
            'material_version_id': MATERIAL,
            'content_hash': 'ab' * 32,
            'line_start': 1,
            'line_end': 1,
        }],
    }


def _policy(objective_ids, threshold=1.0):
    return EvaluationPolicy.model_validate({
        'policy_id': 'policy_unit_course',
        'policy_version': '1.0.0',
        'allowed_question_types': ['single_choice', 'multiple_choice'],
        'evaluators': [{'evaluator_id': 'choice_exact', 'evaluator_version': '1.0.0'}],
        'objective_rules': [{
            'objective_id': objective_id,
            'required': True,
            'evidence_kinds': ['choice'],
            'min_items': 1,
            'min_evidence': 1,
            'pass_threshold': threshold,
        } for objective_id in objective_ids],
        'total_pass_threshold': threshold,
        'critical_severities': ['critical'],
    }).model_dump(mode='json')


def _pass_rule(objective_ids, threshold=1.0, rule='all_required_nodes'):
    return {'rule': rule, 'policy': _policy(objective_ids, threshold)}


@pytest.fixture
def store(tmp_path):
    database = TrainingStore(tmp_path / 'training.sqlite')
    with database.connect() as conn:
        conn.execute('INSERT INTO training_units VALUES (?,?)', ('u', '单位'))
        conn.execute(
            'INSERT INTO training_members VALUES (?,?,?,?)',
            ('u', 'admin@example.test', '管理员', 'admin'))
        conn.execute(
            '''INSERT INTO training_material_versions
               (id,unit_id,owner_account,visibility,version,title,original_path,parsed_path,locations_json)
               VALUES (?,?,?,?,1,?,?,?,?)''',
            (MATERIAL, 'u', 'admin@example.test', 'unit', '资料', '/tmp/original', '/tmp/parsed', '[]'))
    return database


def _counts(database):
    with database.connect() as conn:
        courses = conn.execute('SELECT COUNT(*) FROM training_course_versions').fetchone()[0]
        requests = conn.execute('SELECT COUNT(*) FROM training_publish_requests').fetchone()[0]
    return courses, requests


def _publish(database, **overrides):
    payload = {
        'request_id': str(uuid4()),
        'course_id': 'policy-a',
        'title': '时限课',
        'tree': _tree(),
        'required_nodes': ['n1'],
        'pass_rule': _pass_rule(['obj_n1']),
        'material_version_ids': [MATERIAL],
    }
    payload.update(overrides)
    return database.publish_course('u', **payload)


def test_publish_rejects_each_invalid_course_without_a_leftover_row(store):
    published = _publish(store)
    assert published['created'] is True
    assert published['pass_rule']['policy']['total_pass_threshold'] == 1.0
    assert published['pass_rule']['policy']['objective_rules'][0]['pass_threshold'] == 1.0
    assert _counts(store) == (1, 1)
    before = _counts(store)
    with pytest.raises(ValueError, match='invalid_course_id'):
        _publish(store, course_id='发布为新课程')
    assert _counts(store) == before

    nodes = [
        _node('n1', [], 'obj_n1'),
        _node('n2', ['n1'], 'obj_n2'),
    ]
    nodes[1]['prerequisite_ids'] = ['n1']
    cycle = [_node('n1', ['n2'], 'obj_n1'), _node('n2', ['n1'], 'obj_n2')]
    cases = {
        'invalid_course_empty': {'tree': {'nodes': []}, 'required_nodes': ['does_not_exist'],
                                 'pass_rule': {'rule': 'unsupported_rule'}},
        'invalid_course_dangling_required': {'required_nodes': ['does_not_exist']},
        'invalid_course_unknown_rule': {'pass_rule': {'rule': 'unsupported_rule'}},
        'invalid_course_cycle': {
            'tree': _tree(cycle),
            'required_nodes': ['n1', 'n2'],
            'pass_rule': _pass_rule(['obj_n1', 'obj_n2']),
        },
        'invalid_course_dangling_dependency': {
            'tree': _tree([_node('n1', ['missing'], 'obj_n1')]),
        },
        'invalid_course_duplicate': {
            'tree': _tree([_node('n1', [], 'obj_n1'), _node('n1', [], 'obj_n1b')]),
            'required_nodes': ['n1'],
            'pass_rule': _pass_rule(['obj_n1', 'obj_n1b']),
        },
        'invalid_course_source': {
            'tree': _tree([_node() | {'objectives': [{**_objective(), 'source_chunk_ids': ['ref_missing']}]}]),
        },
        'invalid_course_policy': {'pass_rule': _pass_rule(['obj_n1'], threshold=0.5)},
    }
    for code, overrides in cases.items():
        before = _counts(store)
        with pytest.raises(ValueError, match=code):
            _publish(store, course_id='policy-a', **overrides)
        assert _counts(store) == before, code


def test_start_request_migration_preserves_existing_rows(tmp_path):
    database = tmp_path / 'legacy.sqlite'
    conn = sqlite3.connect(database)
    conn.execute('''CREATE TABLE training_start_requests(
        unit_id TEXT NOT NULL, request_id TEXT NOT NULL, employee_task_id TEXT NOT NULL,
        project_id TEXT NOT NULL, PRIMARY KEY(unit_id, request_id))''')
    conn.execute("INSERT INTO training_start_requests VALUES ('u','legacy-key','et_old','v3_kept')")
    conn.commit()
    conn.close()
    store = TrainingStore(database)
    row = store.start_request_row('u', 'legacy-key')
    assert row['project_id'] == 'v3_kept'
    assert row['operation'] == 'start'
    assert row['employee_task_id'] == 'et_old'
    with store.connect() as conn:
        conn.execute('INSERT INTO training_units VALUES (?,?)', ('u', '单位'))
        conn.execute(
            'INSERT INTO training_members VALUES (?,?,?,?)',
            ('u', 'a@example.test', '甲', 'employee'))
        conn.execute(
            '''INSERT INTO training_course_versions
               (id,unit_id,course_id,version,title,tree_json,required_nodes_json,pass_rule_json)
               VALUES (?,?,?,?,?,?,?,?)''',
            ('cv_old', 'u', 'old', 1, '旧课', '{}', '["n1"]', '{"rule":"all_required_nodes"}'))
        conn.execute(
            'INSERT INTO training_tasks(id,unit_id,course_version_id,title,created_by) VALUES (?,?,?,?,?)',
            ('task_old', 'u', 'cv_old', '旧任务', 'a@example.test'))
        conn.execute(
            'INSERT INTO training_employee_tasks(id,unit_id,task_id,account) VALUES (?,?,?,?)',
            ('et_old', 'u', 'task_old', 'a@example.test'))
        store._ensure_start_request_binding(conn)
    rebound = store.start_request_row('u', 'legacy-key')
    assert rebound['project_id'] == 'v3_kept'
    assert rebound['account'] == 'a@example.test'
    assert rebound['operation'] == 'start'


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(demo, 'TRAINING_WORK', tmp_path)
    gateway = demo.create_app(root=tmp_path / 'instance', llm=StartFlowFake())
    with TestClient(gateway, base_url='http://127.0.0.1:18780') as client:
        yield client, gateway


def _fork_material():
    return (
        '# 时限\n新员工须在入职后五个工作日内完成基础制度学习。\n\n'
        '# 范围\n适用范围覆盖全体新员工，不包含临时访客。\n'
    ).encode()


def _fork_nodes():
    return [
        {
            'node_id': 'n_pre', 'title': '阅读原文',
            'description': '先阅读时限原文，再进入后继节点。',
            'prerequisite_ids': [],
            'objectives': [choice_objective('obj_pre', '$0', '从给定选项中判断新员工完成基础制度学习的时限')],
        },
        {
            'node_id': 'n1', 'title': '时限要求',
            'description': '在读过原文后判断时限。',
            'prerequisite_ids': ['n_pre'],
            'objectives': [choice_objective('obj_n1', '$0', '从给定选项中判断入职后五个工作日的时限要求')],
        },
        {
            'node_id': 'n2', 'title': '适用范围',
            'description': '用文字说明适用范围。',
            'prerequisite_ids': [],
            'objectives': [{
                'objective_id': 'obj_n2',
                'observable_outcome': '根据资料说明适用范围并写明不包含临时访客',
                'required_capability_ids': ['text_rubric'],
                'evidence_requirement': ['text_excerpt'],
                'required': True,
                'source_chunk_ids': ['$1'],
                'criterion_ids': ['crit_scope'],
                'assessment_tasks': [{
                    'task_form': 'text',
                    'submission': '文字说明',
                    'requirements': ['说明适用范围是否包含临时访客'],
                    'criteria': ['必须写明不包含临时访客'],
                }],
            }],
        },
        {
            'node_id': 'n3', 'title': '时限应用',
            'description': '只依赖时限分支，不依赖适用范围。',
            'prerequisite_ids': ['n1'],
            'objectives': [choice_objective('obj_n3', '$0', '从给定选项中判断时限要求如何应用到新员工')],
        },
    ]


def _upload(client, admin, raw, name='fork.md'):
    response = client.post('/training/api/admin/materials', headers=admin, json={
        'request_id': str(uuid4()), 'filename': name, 'title': '分叉制度',
        'data_base64': base64.b64encode(raw).decode()})
    assert response.status_code in {200, 201}, response.text
    body = response.json()
    assert body['status'] == 'ready', body
    return body['id']


def test_placeholder_tree_is_rejected_and_draft_publication_ignores_it(runtime):
    client, gateway = runtime
    admin = login(client, 0)
    material_id = _upload(client, admin, _fork_material())
    before = client.get('/training/api/admin/overview', headers=admin).json()['courses']
    rejected = client.post('/training/api/admin/courses/publish', headers=admin, json={
        'request_id': str(uuid4()), 'course_id': 'unit-course', 'title': '占位课',
        'tree': {'plan_version': 1, 'nodes': []},
        'required_nodes': ['does_not_exist'],
        'pass_rule': {'rule': 'unsupported_rule'},
        'material_version_ids': [material_id],
    })
    assert rejected.status_code == 422
    assert rejected.json()['error']['code'] == 'draft_required'
    assert client.get('/training/api/admin/overview', headers=admin).json()['courses'] == before

    nodes = _fork_nodes()
    objectives = [objective for node in nodes for objective in node['objectives']]
    policy = policy_for(objectives, ['choice_exact', 'text_rubric'], threshold=1.0)
    draft = confirm_draft_with_policy(
        client, gateway, admin, material_id, '分叉制度短课', nodes,
        ['choice_exact', 'text_rubric'], policy)
    assert len(draft['material_version_ids']) == 1
    listed = client.get('/training/api/admin/course-drafts', headers=admin).json()
    found = next(item for item in listed['drafts'] if item['project_id'] == draft['project_id'])
    assert found['publishable'] is True
    assert found['draft_revision'] == draft['draft_revision']
    by_node = {item['node_id']: item['prerequisite_ids'] for item in found['nodes']}
    assert by_node['n3'] == ['n1']
    assert by_node['n1'] == ['n_pre']
    assert found['policy']['total_pass_threshold'] == 1.0

    published = client.post('/training/api/admin/courses/publish', headers=admin, json={
        **publish_payload(draft, title='分叉制度短课', required_nodes=['n1', 'n2', 'n3']),
        'tree': {'plan_version': 1, 'nodes': [{'node_id': 'n1', 'title': '手填占位', 'objectives': []}]},
        'pass_rule': {'rule': 'unsupported_rule'},
    })
    assert published.status_code == 201, published.text
    course = published.json()
    assert course['course_id'].startswith('course_')
    assert course['version'] == 1
    published_nodes = {node['node_id']: node for node in course['tree']['nodes']}
    assert published_nodes['n3']['prerequisite_ids'] == ['n1']
    assert published_nodes['n3']['title'] != '手填占位'
    assert course['pass_rule']['rule'] == 'all_required_nodes'
    assert course['pass_rule']['policy']['total_pass_threshold'] == 1.0
    assert {rule['objective_id']: rule['pass_threshold']
            for rule in course['pass_rule']['policy']['objective_rules']} == {
                'obj_pre': 1.0, 'obj_n1': 1.0, 'obj_n2': 1.0, 'obj_n3': 1.0}
    text = next(objective for node in course['tree']['nodes'] if node['node_id'] == 'n2'
                for objective in node['objectives'])
    assert text['criterion_ids'] == ['crit_scope']
    assert text['assessment_tasks'][0]['task_form'] == 'text'
    assert text['source_chunk_ids'] != ['$1']
    sources = {item['anchor']: item for item in course['tree']['source_index']}
    assert set(text['source_chunk_ids']) <= set(sources)
    choice = next(objective for node in course['tree']['nodes'] if node['node_id'] == 'n1'
                  for objective in node['objectives'])
    assert sources[text['source_chunk_ids'][0]]['content_hash'] != sources[choice['source_chunk_ids'][0]]['content_hash']

    other = client.post('/training/api/admin/courses/publish', headers=admin, json=publish_payload(
        draft, title='另一门范围课', required_nodes=['n1', 'n2', 'n3']))
    assert other.status_code == 201, other.text
    second = other.json()
    assert second['course_id'] != course['course_id'] and second['version'] == 1
    revised = client.post('/training/api/admin/courses/publish', headers=admin, json=publish_payload(
        draft, title='分叉制度短课', course_id=course['course_id'], required_nodes=['n1', 'n2', 'n3']))
    assert revised.status_code == 201, revised.text
    revision = revised.json()
    assert revision['course_id'] == course['course_id'] and revision['version'] == 2
    assert revision['id'] != course['id']
    task = client.post('/training/api/admin/tasks/assign', headers=admin, json={
        'request_id': str(uuid4()), 'course_version_id': course['id'],
        'title': '第一版任务', 'accounts': [demo.ACCOUNTS[1][0], demo.ACCOUNTS[2][0]],
    })
    assert task.status_code == 201, task.text
    assert task.json()['course_version_id'] == course['id']
    fresh = client.get('/training/api/admin/tasks/' + task.json()['id'], headers=admin).json()
    assert fresh['course_version_id'] == course['id']
    versions = {(item['course_id'], item['version'])
                for item in client.get('/training/api/admin/overview', headers=admin).json()['courses']}
    assert (course['course_id'], 1) in versions and (course['course_id'], 2) in versions
    assert (second['course_id'], 1) in versions and (second['course_id'], 2) not in versions


def _signature(plan):
    return [{
        'node_id': node['node_id'],
        'prerequisite_ids': list(node['prerequisite_ids']),
        'objectives': [{
            'objective_id': objective['objective_id'],
            'observable_outcome': objective['observable_outcome'],
            'required_capability_ids': list(objective['required_capability_ids']),
            'evidence_requirement': list(objective['evidence_requirement']),
            'criterion_ids': list(objective.get('criterion_ids') or []),
            'assessment_tasks': objective.get('assessment_tasks') or [],
            'sources': list(objective['source_chunk_ids']),
        } for objective in node['objectives']],
    } for node in plan['nodes']]


def test_two_employees_keep_published_semantics_and_distinct_chunk_identities(runtime):
    client, gateway = runtime
    admin = login(client, 0)
    material_id = _upload(client, admin, _fork_material())
    nodes = _fork_nodes()
    objectives = [objective for node in nodes for objective in node['objectives']]
    policy = policy_for(objectives, ['choice_exact', 'text_rubric'], threshold=1.0)
    draft = confirm_draft_with_policy(
        client, gateway, admin, material_id, '分叉制度短课', nodes,
        ['choice_exact', 'text_rubric'], policy)
    course = client.post('/training/api/admin/courses/publish', headers=admin, json=publish_payload(
        draft, title='分叉制度短课', course_id='fork-policy', required_nodes=['n1', 'n2', 'n3'])).json()
    task = client.post('/training/api/admin/tasks/assign', headers=admin, json={
        'request_id': str(uuid4()), 'course_version_id': course['id'], 'title': '分叉任务',
        'accounts': [demo.ACCOUNTS[1][0], demo.ACCOUNTS[2][0]],
    }).json()
    detail = client.get('/training/api/admin/tasks/' + task['id'], headers=admin).json()
    by_account = {row['account']: row for row in detail['assignees']}
    headers = [login(client, 1), login(client, 2)]
    projects = []
    plans = []
    for index, account in enumerate((demo.ACCOUNTS[1][0], demo.ACCOUNTS[2][0])):
        started = client.post(
            '/training/api/my-tasks/' + by_account[account]['id'] + '/start',
            headers=headers[index], json={'request_id': str(uuid4())})
        assert started.status_code == 201, started.text
        project_id = started.json()['project_id']
        projects.append(project_id)
        with LearningRepository(gateway.paths) as repo:
            stored = repo.get_project(project_id)
            plans.append(stored['candidate_plan'])
            frozen_policy = stored['policy']
            chunks = {row['chunk_id']: json.loads(row['chunk_json']) for row in repo.conn.execute(
                'SELECT chunk_id, chunk_json FROM source_chunks WHERE project_id=?', (project_id,))}
        assert frozen_policy['total_pass_threshold'] == 1.0
        assert {rule['objective_id']: rule['pass_threshold'] for rule in frozen_policy['objective_rules']} == {
            'obj_pre': 1.0, 'obj_n1': 1.0, 'obj_n2': 1.0, 'obj_n3': 1.0}
        signature = {node['node_id']: node for node in _signature(stored['candidate_plan'])}
        assert list(signature) == ['n_pre', 'n1', 'n2', 'n3']
        assert signature['n3']['prerequisite_ids'] == ['n1']
        assert signature['n1']['prerequisite_ids'] == ['n_pre']
        assert signature['n2']['prerequisite_ids'] == []
        assert signature['n2']['objectives'][0]['criterion_ids'] == ['crit_scope']
        assert signature['n2']['objectives'][0]['assessment_tasks'][0]['task_form'] == 'text'
        published = {node['node_id']: node for node in course['tree']['nodes']}
        index_by_anchor = {item['anchor']: item for item in course['tree']['source_index']}
        for node_id, published_node in published.items():
            for published_objective, employee_objective in zip(
                    published_node['objectives'], signature[node_id]['objectives']):
                assert employee_objective['objective_id'] == published_objective['objective_id']
                assert employee_objective['criterion_ids'] == published_objective.get('criterion_ids', [])
                hashes = []
                for anchor, chunk_id in zip(published_objective['source_chunk_ids'], employee_objective['sources']):
                    chunk = chunks[chunk_id]
                    assert chunk['content_hash'] == index_by_anchor[anchor]['content_hash']
                    assert chunk['line_start'] == index_by_anchor[anchor]['line_start']
                    hashes.append(chunk['content_hash'])
                assert hashes
        n1_hash = chunks[signature['n1']['objectives'][0]['sources'][0]]['content_hash']
        n2_hash = chunks[signature['n2']['objectives'][0]['sources'][0]]['content_hash']
        assert n1_hash != n2_hash
        assert '五个工作日' in chunks[signature['n1']['objectives'][0]['sources'][0]]['content']
        assert '临时访客' in chunks[signature['n2']['objectives'][0]['sources'][0]]['content']
        assert '临时访客' not in chunks[signature['n1']['objectives'][0]['sources'][0]]['content']
    assert projects[0] != projects[1]
    left = _signature(plans[0])
    right = _signature(plans[1])
    for node_a, node_b in zip(left, right):
        assert node_a['node_id'] == node_b['node_id']
        assert node_a['prerequisite_ids'] == node_b['prerequisite_ids']
        for obj_a, obj_b in zip(node_a['objectives'], node_b['objectives']):
            assert obj_a['sources'] != obj_b['sources']
            assert {key: value for key, value in obj_a.items() if key != 'sources'} == {
                key: value for key, value in obj_b.items() if key != 'sources'}


def test_claim_checks_permission_before_idempotency_and_keeps_one_project(runtime):
    client, gateway = runtime
    admin = login(client, 0)
    accounts = [demo.ACCOUNTS[1][0], demo.ACCOUNTS[2][0]]
    _, course, first = publish_and_assign(client, gateway, admin, accounts)
    second = client.post('/training/api/admin/tasks/assign', headers=admin, json={
        'request_id': str(uuid4()), 'course_version_id': course['id'],
        'title': '第二项任务', 'accounts': accounts,
    }).json()
    first_rows = {row['account']: row for row in client.get(
        '/training/api/admin/tasks/' + first['id'], headers=admin).json()['assignees']}
    second_rows = {row['account']: row for row in client.get(
        '/training/api/admin/tasks/' + second['id'], headers=admin).json()['assignees']}
    headers_a, headers_b = login(client, 1), login(client, 2)
    shared = str(uuid4())
    started = client.post(
        '/training/api/my-tasks/' + first_rows[accounts[0]]['id'] + '/start',
        headers=headers_a, json={'request_id': shared})
    assert started.status_code == 201, started.text
    project_id = started.json()['project_id']
    stolen = client.post(
        '/training/api/my-tasks/' + first_rows[accounts[1]]['id'] + '/start',
        headers=headers_b, json={'request_id': shared})
    assert stolen.status_code == 409
    assert stolen.json()['error']['code'] == 'request_target_mismatch'
    assert project_id not in stolen.text
    cross = client.post(
        '/training/api/my-tasks/' + first_rows[accounts[0]]['id'] + '/start',
        headers=headers_b, json={'request_id': shared})
    assert cross.status_code == 404
    assert project_id not in cross.text
    other_task = client.post(
        '/training/api/my-tasks/' + second_rows[accounts[0]]['id'] + '/start',
        headers=headers_a, json={'request_id': shared})
    assert other_task.status_code == 409
    assert project_id not in other_task.text
    untouched = client.get('/training/api/admin/tasks/' + second['id'], headers=admin).json()
    assert all(row['project_id'] is None for row in untouched['assignees'])

    view = finish_request(client, headers_a, '/projects/' + project_id + '/begin', {'request_id': str(uuid4())})
    view = finish_request(client, headers_a, '/projects/' + project_id + '/resume', learning_event(view, 'start_quiz'))
    quiz = private_quiz(gateway.paths, project_id, view['assessment_id'])
    view = finish_request(
        client, headers_a, '/projects/' + project_id + '/resume',
        learning_event(view, 'submit_answer', answers=answers_for_quiz(quiz)))
    assert view['guard']['passed'] and 'n1' in view['completed_node_ids']
    again = client.post(
        '/training/api/my-tasks/' + first_rows[accounts[0]]['id'] + '/start',
        headers=headers_a, json={'request_id': str(uuid4())})
    assert again.status_code == 200
    assert again.json()['project_id'] == project_id and again.json()['created'] is False
    resumed = client.get('/projects/' + project_id, headers=headers_a).json()
    assert 'n1' in resumed['completed_node_ids']
    with LearningRepository(gateway.paths) as repo:
        completed = repo.conn.execute(
            'SELECT completed_at FROM learning_progress WHERE project_id=? AND node_id=?',
            (project_id, 'n1')).fetchone()[0]
    assert completed

    # Historical course without a policy is not rewritten and is not deleted.
    with gateway.training.store.connect() as conn:
        before = conn.execute('SELECT COUNT(*) FROM training_course_versions').fetchone()[0]
        conn.execute(
            '''INSERT INTO training_course_versions
               (id,unit_id,course_id,version,title,tree_json,required_nodes_json,pass_rule_json)
               VALUES (?,?,?,?,?,?,?,?)''',
            ('cv_legacy', demo.UNIT_ID, 'legacy-course', 1, '旧占位课',
             json.dumps({'plan_version': 1, 'nodes': [
                 {'node_id': 'n1', 'title': '时限要求', 'objectives': []},
                 {'node_id': 'n3', 'title': '汇总', 'prerequisite_ids': ['n1'], 'objectives': []},
             ]}, ensure_ascii=False),
             json.dumps(['n1', 'n3']),
             json.dumps({'rule': 'all_required_nodes'})))
    legacy = client.post('/training/api/admin/tasks/assign', headers=admin, json={
        'request_id': str(uuid4()), 'course_version_id': 'cv_legacy', 'title': '旧任务',
        'accounts': [accounts[0]],
    })
    assert legacy.status_code == 201, legacy.text
    legacy_task = legacy.json()['assignees'][0]['id']
    refused = client.post(
        '/training/api/my-tasks/' + legacy_task + '/start', headers=headers_a,
        json={'request_id': str(uuid4())})
    assert refused.status_code == 409
    assert refused.json()['error']['code'] == 'course_needs_republish'
    with gateway.training.store.connect() as conn:
        assert conn.execute('SELECT COUNT(*) FROM training_course_versions').fetchone()[0] == before + 1
        stored = json.loads(conn.execute(
            'SELECT tree_json FROM training_course_versions WHERE id=?', ('cv_legacy',)).fetchone()[0])
    assert stored['nodes'][1]['prerequisite_ids'] == ['n1']
    assert stored['nodes'][0]['objectives'] == []
    assert client.get('/training/api/admin/tasks/' + legacy.json()['id'], headers=admin).json()['assignees'][0]['project_id'] is None


def test_concurrent_claims_create_one_project_without_resetting_progress(runtime):
    client, gateway = runtime
    admin = login(client, 0)
    account = demo.ACCOUNTS[1][0]
    _, _, task = publish_and_assign(client, gateway, admin, [account, demo.ACCOUNTS[2][0]])
    employee_task_id = next(row['id'] for row in client.get(
        '/training/api/admin/tasks/' + task['id'], headers=admin).json()['assignees']
        if row['account'] == account)
    barrier = threading.Barrier(2)
    results, errors = [], []

    def claim(request_id):
        try:
            barrier.wait(timeout=5)
            results.append(training_learner.ensure_initialized(
                gateway.paths, gateway.training.materials.root, gateway.training.store,
                gateway.ownership, demo.UNIT_ID, account, employee_task_id, request_id=request_id))
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=claim, args=(str(uuid4()),)) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert errors == []
    assert len(results) == 2
    assert {item['project_id'] for item in results} == {results[0]['project_id']}
    assert sorted(item['created'] for item in results) == [False, True]
    project_id = results[0]['project_id']
    with LearningRepository(gateway.paths) as repo:
        rows = list(repo.conn.execute(
            'SELECT node_id, completed_at FROM learning_progress WHERE project_id=? ORDER BY node_id',
            (project_id,)))
    assert [row[0] for row in rows] == ['n1', 'n2', 'n3']
    assert all(row[1] is None for row in rows)
    replay = training_learner.ensure_initialized(
        gateway.paths, gateway.training.materials.root, gateway.training.store, gateway.ownership,
        demo.UNIT_ID, account, employee_task_id, request_id=str(uuid4()))
    assert replay['project_id'] == project_id and replay['created'] is False
    with LearningRepository(gateway.paths) as repo:
        again = list(repo.conn.execute(
            'SELECT completed_at FROM learning_progress WHERE project_id=?', (project_id,)))
    assert [row[0] for row in again] == [None, None, None]


def test_publish_page_uses_the_confirmed_draft_instead_of_placeholder_nodes():
    source = Path('app/static/training.js').read_text(encoding='utf-8')
    assert 'course_id:\'unit-course\'' not in source
    assert "n'+(i+1)" not in source
    assert '时限要求,适用范围,常见问题' not in source
    assert 'draft_project_id' in source and 'draft_revision' in source
    assert "freshCourse.value=''" in source
    assert '/training/api/admin/course-drafts' in source
    assert '用这份资料准备课程' in source
