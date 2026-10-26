from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from app.v3.learning_api import create_learning_app
from app.v3.storage import V3Paths, initialize_storage
from app.v3.runtime_storage import initialize_learning_storage
from deploy.asgi import EvaluationGateway
from tests.day11_support import FakeLearningModel


@pytest.fixture
def secured(tmp_path):
    paths = initialize_learning_storage(initialize_storage(V3Paths(tmp_path / 'business')))
    model = FakeLearningModel()
    application = create_learning_app(paths, llm=model)
    gateway = EvaluationGateway(application, paths, tmp_path / 'access.sqlite')
    return TestClient(gateway), gateway, application, paths, model


def account(name):
    return {'X-Evaluation-User': name}


def create(client, user, request_id=None):
    payload = {'request_id': request_id or str(uuid4()), 'intent': {'goal': '学习整数比较'}}
    response = client.post('/projects', headers=account(user), json=payload)
    assert response.status_code == 201, response.text
    return response.json()['project_id'], payload


def test_each_account_lists_only_its_own_real_projects(secured):
    client, gateway, application, paths, model = secured
    first, _ = create(client, 'judge01')
    second, _ = create(client, 'judge03')
    assert [p['project_id'] for p in client.get('/projects', headers=account('judge01')).json()] == [first]
    assert [p['project_id'] for p in client.get('/projects', headers=account('judge03')).json()] == [second]
    assert client.get('/projects', headers=account('goutouren')).json() == []
    assert model.calls == []


def test_all_foreign_project_reads_and_writes_are_denied(secured):
    client, gateway, application, paths, model = secured
    project, _ = create(client, 'judge03')
    urls = [f'/projects/{project}', f'/projects/{project}/sources',
            f'/projects/{project}/sources/example/versions/1']
    for url in urls:
        response = client.get(url, headers=account('judge01'))
        assert response.status_code == 404
        assert project not in response.text
    for suffix in ('begin', 'resume', 'retry', 'sources'):
        assert client.post(f'/projects/{project}/{suffix}', headers=account('judge01'), json={}).status_code == 404
    assert client.patch(f'/projects/{project}', headers=account('judge01'), json={'display_name': 'stolen'}).status_code == 404
    assert client.get(f'/projects/{project}', headers=account('judge03')).status_code == 200
    assert model.calls == []


def test_request_replay_cannot_steal_another_accounts_project(secured):
    client, gateway, application, paths, model = secured
    project, payload = create(client, 'judge03')
    assert client.post('/projects', headers=account('judge01'), json=payload).status_code == 404
    assert client.post('/projects', headers=account('judge03'), json=payload).json()['project_id'] == project


def test_ownership_survives_new_gateway_and_old_unassigned_data_is_hidden(secured, tmp_path):
    client, gateway, application, paths, model = secured
    project, _ = create(client, 'judge01')
    unassigned, _ = create(TestClient(application), 'ignored')
    restarted = TestClient(EvaluationGateway(application, paths, gateway.quota_path))
    visible = restarted.get('/projects', headers=account('judge01')).json()
    assert [p['project_id'] for p in visible] == [project]
    assert restarted.get(f'/projects/{unassigned}', headers=account('judge01')).status_code == 404
    assert gateway.ownership.claim(unassigned, 'judge03')
    assert not gateway.ownership.claim(unassigned, 'judge01')
    assert restarted.get(f'/projects/{unassigned}', headers=account('judge03')).status_code == 200


def test_session_identity_and_malformed_creation_are_safe(secured):
    client, gateway, application, paths, model = secured
    assert client.get('/session', headers=account('judge03')).json() == {'account': 'judge03'}
    assert TestClient(application).get('/session').json() == {'account': None}
    assert client.get('/session', headers=account('invalid name')).status_code == 401
    assert client.post('/projects', headers=account('judge01'), json={'request_id': 123}).status_code == 422
