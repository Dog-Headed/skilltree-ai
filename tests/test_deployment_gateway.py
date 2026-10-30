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


def test_model_timeout_reaches_underlying_transport(monkeypatch,tmp_path):
    monkeypatch.setenv('SKILLTREE_AUTH_DB',str(tmp_path/'auth.sqlite'))
    monkeypatch.setenv('SKILLTREE_QUOTA_DB',str(tmp_path/'quota.sqlite'))
    monkeypatch.setenv('SKILLTREE_THINKING_MODE','auto')
    monkeypatch.setenv('SKILLTREE_MODEL_TIMEOUT','150')
    from langchain_openai import ChatOpenAI
    from deploy import asgi
    from deploy.provider import create_runtime_model
    import app.services.llm

    monkeypatch.setattr(app.services.llm, 'get_llm', lambda: ChatOpenAI(
        model='unit-test-model', api_key='unit-test-placeholder',
        base_url='http://127.0.0.1:1/v1', timeout=45, max_retries=0))
    monkeypatch.setattr(asgi, 'create_learning_app', lambda paths, llm, **options: llm)
    model = create_runtime_model()
    assert hasattr(model, 'invoke') and hasattr(model, 'with_structured_output')
    assert model.root_client.timeout == 150
    assert model.root_client.max_retries == 0
    assert model.extra_body is None
    monkeypatch.setenv('SKILLTREE_THINKING_MODE', 'false')
    model = create_runtime_model()
    assert model.extra_body == {'thinking_mode': False}


def test_production_injection_uses_task_timeouts_and_keeps_strict_provider(monkeypatch,tmp_path):
    monkeypatch.setenv('SKILLTREE_AUTH_DB',str(tmp_path/'auth.sqlite'))
    monkeypatch.setenv('SKILLTREE_QUOTA_DB',str(tmp_path/'quota.sqlite'))
    from types import SimpleNamespace
    from langchain_openai import ChatOpenAI
    from deploy import asgi
    from deploy.provider import create_runtime_model
    from deploy.provider import StructuredReply
    from app.v3.contracts import AssessmentQuiz, LearningPlan
    from app.v3.evaluators import TextBatchScore
    from app.v3.diagnosis import DiagnosisDecision
    from app.v3.tutor import TutorReply
    from app.v3.onboarding import LearningPreparation, StudyNotes
    from app.v3.preparation_content import notes_contract
    from tests.test_v3_preparation_content import notes_payload
    StudyNotesContent=notes_contract(notes_payload())[0]
    from app.v3.model_content import _tutor
    TutorContent=_tutor({'teaching_contexts':[],'exploration':True}).schema
    import app.services.llm
    monkeypatch.setattr(app.services.llm, 'get_llm', lambda: ChatOpenAI(
        model='unit-test-model', api_key='unit-test-placeholder',
        base_url='http://127.0.0.1:1/v1', timeout=45, max_retries=0))
    monkeypatch.setattr(asgi, 'create_learning_app', lambda paths, llm, **options: llm)
    monkeypatch.setenv('SKILLTREE_THINKING_MODE', 'false')
    def bind(self, schema, **kwargs):
        assert kwargs == {'method': 'json_mode', 'include_raw': True}
        return SimpleNamespace(model=self)
    monkeypatch.setattr(ChatOpenAI, 'with_structured_output', bind)
    monkeypatch.setattr(ChatOpenAI, 'bind_tools', lambda self, *a, **kw: self)
    provider = create_runtime_model().model
    for schema, seconds in [(TextBatchScore,180),(AssessmentQuiz,120),(DiagnosisDecision,120),(TutorReply,45),(TutorContent,45),
                            (LearningPlan,120),(LearningPreparation,120),(StudyNotes,120),(StudyNotesContent,120)]:
        bound = provider.with_structured_output(schema, method='json_mode')
        assert isinstance(bound, StructuredReply) and bound.schema_name == schema.__name__
        assert bound.runnable.model.root_client.timeout == seconds
        assert bound.runnable.model.root_client.max_retries == 0
        assert bound.runnable.model.extra_body == {'thinking_mode': False}
        assert bound.runnable.model.streaming is (schema in {LearningPlan, LearningPreparation, StudyNotes,StudyNotesContent,TutorReply,TutorContent})
    assert provider.bind_tools([]).root_client.timeout == 120
    assert provider.bind_tools([]).streaming is False
