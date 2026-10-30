import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import sqlite3
import threading
import time
from types import SimpleNamespace
from uuid import uuid4

from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from deploy.asgi import EvaluationGateway
from deploy.auth import AuthStore
from deploy.jobs import AdmissionError, JobStore
from deploy.model_settings import (AccountModel, ModelSettings, ModelScopedApplication,
                                   ProviderConfig, _current_model)


@pytest.fixture
def settings(tmp_path):
    key_file = tmp_path/'master.key'; key_file.write_bytes(Fernet.generate_key())
    configs = {p: ProviderConfig(p, p, 'https://example.invalid', 'PLATFORM_'+p) for p in ('deepseek', 'intern')}
    return ModelSettings(tmp_path/'quota.sqlite', key_file, configs)


def choose(settings, account, provider='intern', **kw):
    return settings.update(account, {'provider': provider, 'key_source': 'platform', **kw})


def test_default_choice_and_per_account_independence(settings):
    assert settings.public('a')['provider'] == 'deepseek'
    choose(settings, 'a')
    assert settings.public('a')['provider'] == 'intern'
    assert settings.public('b')['provider'] == 'deepseek'
    assert settings.resolve('a')[2].api_key == 'PLATFORM_intern'


def test_encrypted_key_is_not_public_and_binds_to_identity(settings):
    secret = 'PRIVATE_KEY_abcdefghijklmnopqrstuvwxyz'
    result = choose(settings, 'a', key_source='personal', api_key=secret)
    assert secret not in json.dumps(result) and 'PLATFORM_' not in json.dumps(result)
    assert settings.resolve('a')[2].api_key == secret
    with settings.connect() as conn:
        encrypted = conn.execute('SELECT ciphertext FROM account_model_secrets WHERE account=?', ('a',)).fetchone()[0]
        assert secret not in encrypted and secret.encode() not in settings.database.read_bytes()
        conn.execute('INSERT INTO account_model_settings VALUES (?,?,?,?)', ('b','intern','personal',time.time()))
        conn.execute('INSERT INTO account_model_secrets VALUES (?,?,?)', ('b','intern',encrypted))
    with pytest.raises(AdmissionError) as error: settings.resolve('b')
    assert error.value.code == 'model_unavailable'  # Never fall back to platform credentials.


def test_keep_separate_provider_keys_replace_and_delete(settings):
    choose(settings, 'a', 'deepseek', key_source='personal', api_key='FIRST_DEEPSEEK_KEY_123456789')
    choose(settings, 'a', 'intern', key_source='personal', api_key='FIRST_INTERN_KEY_123456789')
    choose(settings, 'a', 'deepseek', key_source='personal')
    assert settings.resolve('a')[2].api_key == 'FIRST_DEEPSEEK_KEY_123456789'
    choose(settings, 'a', 'deepseek', key_source='personal', api_key='REPLACED_DEEPSEEK_KEY_123456789')
    assert settings.resolve('a')[2].api_key == 'REPLACED_DEEPSEEK_KEY_123456789'
    result = choose(settings, 'a', 'deepseek', remove_key=True)
    assert not result['providers'][0]['has_personal_key'] and result['providers'][1]['has_personal_key']
    assert settings.resolve('a')[2].api_key == 'PLATFORM_deepseek'


@pytest.mark.parametrize('payload', [[], {'provider': 'other', 'key_source': 'platform'},
    {'provider':'intern','key_source':'platform','account':'victim'},
    {'provider':'intern','key_source':'platform','base_url':'http://127.0.0.1'},
    {'provider':'intern','key_source':'personal','api_key':'x'},
    {'provider':'intern','key_source':'personal','api_key':'abc\n'+('a'*20)},
    {'provider':'intern','key_source':'platform','remove_key':'yes'},
    {'provider': [], 'key_source':'platform'}])
def test_rejects_unknown_fields_providers_and_bad_keys(settings, payload):
    with pytest.raises(AdmissionError): settings.update('a', payload)
    assert settings.public('a')['provider'] == 'deepseek'


def test_failed_updates_do_not_destroy_saved_key(settings):
    choose(settings, 'a', key_source='personal', api_key='PRESERVED_KEY_123456789')
    with pytest.raises(AdmissionError): choose(settings, 'a', key_source='personal', remove_key=True)
    assert settings.resolve('a')[2].api_key == 'PRESERVED_KEY_123456789'


def test_model_change_rejected_for_queued_or_running_and_survives_restart(settings):
    jobs = JobStore(settings.database)
    job_id = jobs.admit('a', 'p', 'POST', '/projects/p/begin', {'request_id':'r'})
    for _ in range(2):
        with pytest.raises(AdmissionError) as error: choose(settings, 'a')
        assert error.value.status == 409
        jobs.claim()
    jobs.finish(job_id, 200, b'{}'); choose(settings, 'a')
    again = ModelSettings(settings.database, settings.database.parent/'master.key', settings.configs)
    assert again.resolve('a')[0] == 'intern'


def test_settings_rate_limit_without_spending_course_quota(settings):
    for _ in range(10): choose(settings, 'a')
    with pytest.raises(AdmissionError) as error: choose(settings, 'a')
    assert error.value.code == 'rate_limited'
    with settings.connect() as conn:
        assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name='usage'").fetchone()


def test_two_parallel_jobs_keep_model_context_through_threadpool(settings):
    choose(settings, 'b')
    app = FastAPI(); model = AccountModel(); barrier = threading.Barrier(2)
    @app.post('/work')
    def work():
        barrier.wait(timeout=5)
        with ThreadPoolExecutor(1) as pool:
            from contextvars import copy_context
            nested = pool.submit(copy_context().run, model.invoke, []).result()
        return {'thread':model.invoke([]),'nested':nested}
    factory = lambda cfg: SimpleNamespace(invoke=lambda messages: cfg.model+':'+cfg.api_key)
    wrapped = ModelScopedApplication(app, settings, factory)
    async def run(account):
        import httpx
        async def scoped(scope, receive, send):
            scope['skilltree_account'] = account
            await wrapped(scope, receive, send)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=scoped),base_url='https://testserver') as client:
            return (await client.post('/work')).json()
    async def both():return await asyncio.gather(run('a'), run('b'))
    results = asyncio.run(both())
    assert results == [{'thread':'deepseek:PLATFORM_deepseek','nested':'deepseek:PLATFORM_deepseek'},
                       {'thread':'intern:PLATFORM_intern','nested':'intern:PLATFORM_intern'}]
    assert _current_model.get() is None
    with pytest.raises(RuntimeError): model.invoke([])


def test_gateway_csrf_ownership_busy_and_durable_queue_identity(settings, tmp_path):
    app = FastAPI(); proxy = AccountModel()
    @app.post('/projects/{pid}/begin')
    def begin(pid:str): return {'model':proxy.invoke([]), 'page_state':'learning'}
    auth = AuthStore(tmp_path/'auth.sqlite')
    auth.create_account('a@example.test', 'test-password-2026')
    auth.create_account('b@example.test', 'test-password-2026')
    wrapped = ModelScopedApplication(app, settings, lambda cfg: SimpleNamespace(invoke=lambda _:cfg.model))
    gateway = EvaluationGateway(wrapped, SimpleNamespace(), settings.database, auth_store=auth,
        queued=True, origin='https://testserver', model_settings=settings)
    gateway.ownership.claim('p1', 'a@example.test')
    with TestClient(gateway,base_url='https://testserver') as client:
        assert client.get('/model-settings').status_code == 401
        def login(account):
            response = client.post('/auth/login',headers={'X-SkillTree-Login':'1'},json={'account':account,'password':'test-password-2026'})
            assert response.status_code == 200
            return {'X-CSRF-Token':response.json()['csrf_token']}
        headers = login('a@example.test')
        assert client.post('/model-settings',json={'provider':'intern','key_source':'platform'}).status_code == 403
        assert client.post('/model-settings',headers={**headers,'Origin':'https://evil.test'},json={}).status_code == 403
        assert client.post('/model-settings',headers=headers,json={'provider':'intern','key_source':'platform'}).status_code == 200
        response = client.post('/projects/p1/begin',headers=headers,json={'request_id':str(uuid4())})
        assert response.status_code == 202
        job_id = response.json()['job']['id']
        until = time.monotonic()+8
        while time.monotonic()<until:
            job = client.get('/jobs/'+job_id).json()['job']
            if job['state'] not in ('queued','running'):break
            time.sleep(.03)
        assert job['state'] == 'completed' and job['result']['model'] == 'intern'
        with settings.connect() as conn:
            assert tuple(conn.execute('SELECT provider,key_source,model FROM account_model_runs WHERE job_id=?',(job_id,)).fetchone()) == ('intern','platform','intern')
        login('b@example.test')
        assert client.get('/model-settings').json()['provider'] == 'deepseek'
        assert client.get('/jobs/'+job_id).status_code == 404
        assert client.post('/projects/p1/begin',headers={'X-CSRF-Token':client.get('/session').json()['csrf_token']},json={'request_id':str(uuid4())}).status_code == 404


def test_context_is_cleared_after_application_failure(settings):
    async def fail(scope, receive, send):
        assert AccountModel().current() == 'test'
        raise ValueError('test failure')
    wrapped = ModelScopedApplication(fail, settings, lambda cfg:'test')
    with pytest.raises(ValueError): asyncio.run(wrapped({'type':'http','method':'POST','skilltree_account':'a'}, None, None))
    assert _current_model.get() is None


def test_production_factory_injects_context_proxy_and_default_deepseek(settings, monkeypatch):
    from deploy import asgi
    monkeypatch.setenv('SKILLTREE_MODEL_KEY_FILE', str(settings.database.parent/'master.key'))
    monkeypatch.setenv('SKILLTREE_QUOTA_DB', str(settings.database))
    monkeypatch.setenv('SKILLTREE_AUTH_DB', str(settings.database.parent/'factory-auth.sqlite'))
    monkeypatch.setattr(asgi,'create_learning_app',lambda paths,llm,**options:llm)
    gateway=asgi.create_app()
    assert gateway.model_settings.public('new-account')['provider']=='deepseek'
    assert isinstance(gateway.application,ModelScopedApplication)
    assert isinstance(gateway.application.application,AccountModel)
