"""Normal confirmation, private purpose isolation and input replay boundaries."""
import json
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.v3.context import ContextBuilder
from app.v3.preparation import PreparationService
from app.v3.preparation_api import create_preparation_app
from app.v3.repository import V3Repository
from app.v3.storage import V3Paths
from tests.test_v3_preparation import web, create, upload, resume


def private_preview(web):
    client, paths, model = web
    p = upload(client, create(client))
    p = upload(client, p, source_id='private-answer-only', title='HIDDEN-PRIVATE-TITLE',
               content='# 评价参考\nHIDDEN-PRIVATE-BODY：变量保存值，循环停止条件决定何时结束。',
               visibility='assessment_private')
    p = resume(client, p, 'confirm_profile').json()
    assert p['page_state'] == 'plan_review'
    assert len(p['private_references']) == 1
    return client, paths, model, p


def event(p, choices):
    return {'request_id': str(uuid4()), 'pending_input_id': p['pending_input_id'],
            'draft_revision': p['draft_revision'], 'action': 'confirm_plan', 'private_references': choices}


def decision(p, action='bind', nodes=None):
    return {'reference_id': p['private_references'][0]['reference_id'], 'action': action,
            'node_ids': (['same-node'] if nodes is None else nodes) if action == 'bind' else []}


def test_normal_graph_freezes_private_choices_and_replays_without_side_effects(web):
    client, paths, model, p = private_preview(web)
    text = json.dumps(p)
    assert all(secret not in text for secret in ('HIDDEN-PRIVATE', 'private-answer-only'))
    calls = len(model.messages)
    body = event(p, [decision(p)])
    response = client.post('/projects/' + p['project_id'] + '/resume', json=body)
    assert response.status_code == 200, response.text
    frozen = response.json()
    assert frozen['frozen'] and frozen['private_references'] == []
    assert all(secret not in response.text for secret in ('HIDDEN-PRIVATE', 'private-answer-only'))
    with V3Repository(paths) as repo:
        snapshot = repo.get_project(p['project_id'])['frozen_snapshot']
        assert 'private-answer-only' in {d['source_id'] for d in snapshot['source_manifest']}
        builder = ContextBuilder(repo)
        assert 'HIDDEN-PRIVATE-BODY' in builder.for_assessment(p['project_id'], 'same-node', 'observable').payload
        assert 'HIDDEN-PRIVATE-BODY' in builder.for_grading(p['project_id'], 'same-node', 'observable').payload
        assert 'HIDDEN-PRIVATE' not in builder.for_teaching(p['project_id'], 'same-node', 'observable').payload
        links = repo.conn.execute('SELECT COUNT(*) FROM node_material_links').fetchone()[0]
    repeated = client.post('/projects/' + p['project_id'] + '/resume', json=body)
    assert repeated.status_code == 200 and len(model.messages) == calls
    with V3Repository(paths) as repo:
        assert repo.conn.execute('SELECT COUNT(*) FROM node_material_links').fetchone()[0] == links
    with PreparationService(paths)._graph() as graph:
        state = graph.get_state(PreparationService._config(p['project_id']))
        assert not state.next and not state.interrupts
    changed = {**body, 'private_references': [decision(p, 'exclude')]}
    assert client.post('/projects/' + p['project_id'] + '/resume', json=changed).status_code == 409


def test_private_reference_must_be_bound_or_explicitly_excluded_before_journal(web):
    client, paths, _, p = private_preview(web)
    response = resume(client, p, 'confirm_plan')
    assert response.status_code == 409
    with V3Repository(paths) as repo:
        assert not repo.get_project(p['project_id'])['frozen_snapshot']
        assert not repo.conn.execute('SELECT 1 FROM preparation_execution').fetchone()
    response = client.post('/projects/' + p['project_id'] + '/resume', json=event(p, [decision(p, 'exclude')]))
    assert response.status_code == 200
    with V3Repository(paths) as repo:
        assert {r['source_id'] for r in repo.get_project(p['project_id'])['frozen_snapshot']['source_manifest']} == {'source'}


@pytest.mark.parametrize('kind,expected', [('unknown_node', 422), ('foreign_reference', 409), ('duplicate', 422)])
def test_invalid_binding_is_rejected_without_freezing(web, kind, expected):
    client, paths, _, p = private_preview(web)
    choices = [decision(p)]
    if kind == 'unknown_node': choices[0]['node_ids'] = ['not-a-node']
    if kind == 'foreign_reference': choices[0]['reference_id'] = 'reference_' + uuid4().hex
    if kind == 'duplicate': choices.append(decision(p))
    response = client.post('/projects/' + p['project_id'] + '/resume', json=event(p, choices))
    assert response.status_code == expected
    with V3Repository(paths) as repo:
        assert not repo.get_project(p['project_id'])['frozen_snapshot']
        assert not repo.conn.execute('SELECT 1 FROM preparation_execution').fetchone()


def test_private_version_change_rejects_old_handle_even_with_current_input(web):
    client, paths, _, p = private_preview(web)
    old = decision(p)
    p = upload(client, p, source_id='private-answer-only', title='HIDDEN-PRIVATE-TITLE',
               content='# 新评价参考\nHIDDEN-PRIVATE-V2：变量保存新值。', visibility='assessment_private')
    p = resume(client, p, 'replan').json()
    assert p['private_references'][0]['reference_id'] != old['reference_id']
    response = client.post('/projects/' + p['project_id'] + '/resume', json=event(p, [old]))
    assert response.status_code == 409
    with V3Repository(paths) as repo:
        assert not repo.get_project(p['project_id'])['frozen_snapshot']


def test_same_source_identity_in_another_project_cannot_supply_a_reference(web):
    client, paths, _, first = private_preview(web)
    _, _, _, second = private_preview(web)
    assert first['project_id'] != second['project_id']
    assert first['private_references'] != second['private_references']
    response = client.post('/projects/' + second['project_id'] + '/resume',
                           json=event(second, [decision(first)]))
    assert response.status_code == 409
    with V3Repository(paths) as repo:
        assert not repo.get_project(second['project_id'])['frozen_snapshot']


def test_oversized_private_context_stays_editable_and_can_be_excluded(web):
    client, paths, model, p = private_preview(web)
    p = upload(client, p, source_id='private-answer-only', title='HIDDEN-PRIVATE-TITLE',
               content='# 大评价参考\n' + ('变量保存值。\n' * 4000), visibility='assessment_private')
    p = resume(client, p, 'replan').json()
    calls = len(model.messages)
    with V3Repository(paths) as repo:
        before = repo.conn.execute('SELECT COUNT(*) FROM model_operations').fetchone()[0]
    response = client.post('/projects/' + p['project_id'] + '/resume', json=event(p, [decision(p)]))
    assert response.status_code == 422 and response.json()['error']['code'] == 'context_limit'
    current = client.get('/projects/' + p['project_id']).json()
    assert current == p and {'confirm_plan', 'import_material', 'replan'} <= set(current['allowed_actions'])
    with V3Repository(paths) as repo:
        assert not repo.get_project(p['project_id'])['frozen_snapshot']
        assert not repo.conn.execute('SELECT 1 FROM preparation_execution').fetchone()
        assert not repo.conn.execute('SELECT 1 FROM node_material_links').fetchone()
        assert repo.conn.execute('SELECT COUNT(*) FROM model_operations').fetchone()[0] == before
    # No failed command has captured the input; a deliberate exclusion succeeds
    # immediately, without retry, new model calls, or a new project.
    response = client.post('/projects/' + p['project_id'] + '/resume', json=event(p, [decision(p, 'exclude')]))
    assert response.status_code == 200 and response.json()['frozen']
    assert len(model.messages) == calls


def test_private_binding_freeze_commit_is_reused_after_checkpoint_failure(web, monkeypatch):
    client, paths, model, p = private_preview(web)
    original = V3Repository.freeze_plan
    attempts = []
    def crash_after_commit(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        attempts.append(True)
        raise RuntimeError('Simulated exit after private bindings commit')
    monkeypatch.setattr(V3Repository, 'freeze_plan', crash_after_commit)
    body = event(p, [decision(p)])
    failed = client.post('/projects/' + p['project_id'] + '/resume', json=body).json()
    assert failed['frozen'] and failed['page_state'] == 'error'
    calls = len(model.messages)
    with V3Repository(paths) as repo:
        snapshot = repo.get_project(p['project_id'])['frozen_snapshot']
        links = list(repo.conn.execute('SELECT * FROM node_material_links'))
    retry = {'request_id': str(uuid4()), 'retry_token': failed['retry_token']}
    result = client.post('/projects/' + p['project_id'] + '/retry', json=retry)
    assert result.status_code == 200 and result.json()['page_state'] == 'learning'
    assert len(attempts) == 1 and len(model.messages) == calls
    assert client.post('/projects/' + p['project_id'] + '/resume', json=body).status_code == 200
    assert client.post('/projects/' + p['project_id'] + '/retry', json=retry).json() == result.json()
    with V3Repository(paths) as repo:
        assert repo.get_project(p['project_id'])['frozen_snapshot'] == snapshot
        assert list(repo.conn.execute('SELECT * FROM node_material_links')) == links


@pytest.mark.parametrize('point', ['business_commit', 'checkpoint_commit'])
def test_private_bindings_survive_real_process_death(tmp_path, monkeypatch, point):
    directory = tmp_path / point
    worker = Path(__file__).parent / 'support' / 'day13_reference_recovery_worker.py'
    child = subprocess.run([sys.executable, '-X', 'utf8', str(worker), str(directory), point],
                           cwd=worker.parents[2], capture_output=True, timeout=50)
    assert child.returncode == 73, child.stderr.decode('utf8', errors='replace')
    saved = json.loads((directory / 'reference-command.json').read_text(encoding='utf8'))
    paths = V3Paths(directory)
    client = TestClient(create_preparation_app(paths))
    from app.v3 import planner
    monkeypatch.setattr(planner, 'get_llm', lambda: pytest.fail('Saved frozen plan called model'))
    pid = saved['view']['project_id']
    before = [f.read_bytes() for f in (paths.learning, paths.checkpoints)]
    view = client.get('/projects/' + pid).json()
    assert view['recovery_required'] and view['frozen']
    assert before == [f.read_bytes() for f in (paths.learning, paths.checkpoints)]
    with V3Repository(paths) as repo:
        snapshot = repo.get_project(pid)['frozen_snapshot']
        links = list(repo.conn.execute('SELECT * FROM node_material_links'))
        charged = repo.conn.execute('SELECT SUM(reserved_requests) FROM model_operations').fetchone()[0]
    retry = {'request_id': str(uuid4()), 'retry_token': view['retry_token']}
    response = client.post('/projects/' + pid + '/retry', json=retry)
    assert response.status_code == 200, response.text
    assert response.json()['page_state'] == 'learning' and not response.json()['recovery_required']
    assert client.post('/projects/' + pid + '/resume', json=saved['body']).status_code == 200
    assert client.post('/projects/' + pid + '/retry', json=retry).json() == response.json()
    with V3Repository(paths) as repo:
        assert repo.get_project(pid)['frozen_snapshot'] == snapshot
        assert list(repo.conn.execute('SELECT * FROM node_material_links')) == links
        assert repo.conn.execute('SELECT SUM(reserved_requests) FROM model_operations').fetchone()[0] == charged
        assert 'SECRET-BODY' in ContextBuilder(repo).for_grading(pid, 'same-node', 'observable').payload
        assert 'SECRET-BODY' not in ContextBuilder(repo).for_teaching(pid, 'same-node', 'observable').payload
    with PreparationService(paths)._graph() as graph:
        assert not graph.get_state(PreparationService._config(pid)).next


def test_pre_extension_accepted_confirmation_keeps_its_original_recovery_semantics(web):
    client, paths, model, p = private_preview(web)
    # This simulates the durable accepted-command format from before reference
    # choices existed, not a new submission bypassing today's public validator.
    old_event = event(p, [])
    old_event.pop('private_references')
    pid = p['project_id']
    service = PreparationService(paths)
    from app.v3.repository import encode
    with V3Repository(paths) as repo:
        op = repo.create_operation(pid, old_event['request_id'], kind='confirm_plan')
        service._mark(repo, pid, operation_id=op['operation_id'], retry_token=op['retry_token'])
        with repo.transaction():
            repo.conn.execute('INSERT INTO preparation_execution VALUES (?,?,NULL)', (pid, encode(old_event)))
    calls = len(model.messages)
    interrupted = client.get('/projects/' + pid).json()
    assert interrupted['recovery_required']
    response = client.post('/projects/' + pid + '/retry', json={
        'request_id': str(uuid4()), 'retry_token': interrupted['retry_token']})
    assert response.status_code == 200 and response.json()['frozen']
    assert not response.json()['recovery_required'] and len(model.messages) == calls
    with V3Repository(paths) as repo:
        assert {d['source_id'] for d in repo.get_project(pid)['frozen_snapshot']['source_manifest']} == {'source'}
        assert not repo.conn.execute('SELECT 1 FROM preparation_execution').fetchone()
        assert len(repo.list_sources(pid, include_private=True)) == 2
