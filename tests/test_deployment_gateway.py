from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.v3.storage import V3Paths
from deploy.asgi import EvaluationGateway


def gateway(tmp_path):
    application = FastAPI()

    @application.post('/projects')
    def create():
        return {'created': True}

    return TestClient(EvaluationGateway(application, V3Paths(tmp_path / 'runtime'), tmp_path / 'quota.sqlite'))


def test_persistent_global_and_per_account_quotas(tmp_path, monkeypatch):
    monkeypatch.setenv('SKILLTREE_DAILY_WRITES', '3')
    monkeypatch.setenv('SKILLTREE_ACCOUNT_DAILY_WRITES', '2')
    client = gateway(tmp_path)
    assert client.post('/projects', headers={'X-Evaluation-User': 'judge1'}).status_code == 200
    assert client.post('/projects', headers={'X-Evaluation-User': 'judge1'}).status_code == 200
    # New gateway/process shares the durable counter.
    client = gateway(tmp_path)
    assert client.post('/projects', headers={'X-Evaluation-User': 'judge1'}).status_code == 429
    assert client.post('/projects', headers={'X-Evaluation-User': 'judge2'}).status_code == 200
    assert client.post('/projects', headers={'X-Evaluation-User': 'judge3'}).status_code == 429


def test_restricted_routes_and_production_deletion_are_blocked(tmp_path):
    client = gateway(tmp_path)
    for path in ['/.env', '/docs', '/openapi.json', '/legacy/projects', '/data/v3/learning.sqlite']:
        assert client.get(path).status_code == 403
    assert client.delete('/projects/example').status_code == 403


def test_health_fails_for_missing_database_and_does_not_create_it(tmp_path):
    client = gateway(tmp_path)
    assert client.get('/healthz').status_code == 503
    assert not (tmp_path / 'runtime' / 'learning.sqlite').exists()


def test_large_request_is_rejected_before_quota_or_business_write(tmp_path):
    client = gateway(tmp_path)
    assert client.post('/projects', content='x' * 262145).status_code == 413
    assert not (tmp_path / 'quota.sqlite').exists()


def test_model_timeout_reaches_underlying_transport(monkeypatch):
    from langchain_openai import ChatOpenAI
    from deploy import asgi
    import app.services.llm

    monkeypatch.setattr(app.services.llm, 'get_llm', lambda: ChatOpenAI(
        model='unit-test-model', api_key='unit-test-placeholder',
        base_url='http://127.0.0.1:1/v1', timeout=45, max_retries=0))
    monkeypatch.setattr(asgi, 'create_learning_app', lambda paths, llm: llm)
    model = asgi.create_app().application
    assert hasattr(model, 'invoke') and hasattr(model, 'with_structured_output')
    assert model.root_client.timeout == 150
    assert model.root_client.max_retries == 0
