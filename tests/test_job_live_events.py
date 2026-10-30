"""Real HTTP SSE, cookie ownership and durable queue; explicitly fake work."""
import json
import socket
import threading
import time
from uuid import uuid4
import httpx
from fastapi import FastAPI
import pytest
import uvicorn
from app.services.live_progress import phase_for_task, tutor_preview, validated_tutor
from app.v3.storage import V3Paths
from deploy.asgi import EvaluationGateway
from deploy.auth import AuthStore, password_hash
from deploy.jobs import JobStore


@pytest.fixture(scope='module')
def encoded():return password_hash('stream-test-password')


@pytest.fixture
def live(tmp_path,encoded):
    sock=socket.socket();sock.bind(('127.0.0.1',0))
    origin='http://127.0.0.1:'+str(sock.getsockname()[1])
    auth=AuthStore(tmp_path/'auth.sqlite')
    with auth.connect() as db:
        db.executemany('INSERT INTO auth_accounts VALUES (?,?,?,0)',[(f'stream{i}@example.test',f'stream{i}@example.test',encoded) for i in (1,2)])
    app=FastAPI();release=threading.Event();calls=[]
    @app.post('/projects/{pid}/begin')
    def work(pid:str,body:dict):
        calls.append(pid);phase_for_task('notes:test')
        phase_for_task('tutor:test')
        with tutor_preview(True,lambda text:False):validated_tutor('公开讲解 '+pid)
        assert release.wait(12)
        return {'project_id':pid,'page_state':'learning','tutor':{'text':'公开讲解 '+pid}}
    gateway=EvaluationGateway(app,V3Paths(tmp_path/'business'),tmp_path/'quota.sqlite',auth_store=auth,
                              queued=True,origin=origin,cookie_secure=False)
    for i in (1,2):gateway.ownership.claim(f'project{i}',f'stream{i}@example.test')
    server=uvicorn.Server(uvicorn.Config(gateway,log_level='error'))
    thread=threading.Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True);thread.start()
    until=time.monotonic()+10
    while not server.started and time.monotonic()<until:time.sleep(.02)
    assert server.started
    clients=[]
    def client(number):
        c=httpx.Client(base_url=origin,timeout=6,trust_env=False);clients.append(c)
        r=c.post('/auth/login',headers={'Origin':origin,'X-SkillTree-Login':'1'},json={'account':f'stream{number}@example.test','password':'stream-test-password'})
        assert r.status_code==200
        c.headers.update({'Origin':origin,'X-CSRF-Token':r.json()['csrf_token']})
        return c
    try:yield gateway,release,calls,client
    finally:
        release.set()
        for c in clients:c.close()
        server.should_exit=True;thread.join(10);sock.close()
        assert not thread.is_alive()


def submit(c):
    r=c.post('/projects/project1/begin',json={'request_id':str(uuid4())});assert r.status_code==202
    return r.json()['job']['id']


def text_frame(response):
    assert response.status_code==200
    for line in response.iter_lines():
        if line.startswith('data: '):
            value=json.loads(line[6:])
            if value.get('text'):return value
    pytest.fail('No live public text')


def test_real_sse_reconnect_does_not_repeat_work_or_charge_quota(live):
    gateway,release,calls,client=live;c=client(1);other=client(2);job=submit(c)
    with c.stream('GET','/jobs/'+job+'/events') as response:
        first=text_frame(response)
        assert response.headers['x-accel-buffering']=='no' and 'no-store' in response.headers['cache-control']
        assert c.get('/jobs/'+job).json()['job']['state']=='running'
        assert first['text']=='公开讲解 project1'
        assert other.get('/jobs/'+job+'/events').status_code==404
        assert c.get('/jobs/'+job+'/events',headers={'Origin':'https://foreign.test'}).status_code==403
    with c.stream('GET','/jobs/'+job+'/events') as response:assert text_frame(response)['text']==first['text']
    assert calls==['project1']
    with gateway.jobs.connect() as db:assert db.execute('SELECT sum(used) FROM usage').fetchone()[0]==1
    release.set();until=time.monotonic()+5
    while c.get('/jobs/'+job).json()['job']['state']=='running' and time.monotonic()<until:time.sleep(.02)
    assert gateway.jobs.public_progress(job,'stream1@example.test') is None
    assert c.get('/jobs/'+job).json()['job']['result']['tutor']['text']==first['text']
    assert calls==['project1']


def test_logout_closes_subscription_without_cancelling_the_job(live):
    gateway,release,calls,client=live;c=client(1);job=submit(c)
    with c.stream('GET','/jobs/'+job+'/events') as response:
        lines=response.iter_lines()
        for line in lines:
            if line.startswith('data: ') and json.loads(line[6:]).get('text'):break
        assert c.post('/auth/logout',json={}).status_code==200
        assert any(line=='event: closed' for line in lines)
    assert gateway.jobs.public(job,'stream1@example.test')['state']=='running'
    assert c.get('/jobs/'+job+'/events').status_code==401
    assert calls==['project1'];release.set()


def test_subscription_cap_and_account_isolation(live):
    gateway,release,calls,client=live;c=client(1);job=submit(c)
    with c.stream('GET','/jobs/'+job+'/events') as first,c.stream('GET','/jobs/'+job+'/events') as second:
        assert first.status_code==second.status_code==200
        assert c.get('/jobs/'+job+'/events').status_code==429
        assert gateway.jobs.public_progress(job,'stream2@example.test') is None
    release.set()


def test_interrupted_worker_removes_provisional_text_and_does_not_replay(tmp_path):
    store=JobStore(tmp_path/'queue.sqlite')
    job=store.admit('owner','p','POST','/projects/p/begin',{'request_id':'test'})
    store.claim();store.publish_progress(job,'owner',{'stage':'teaching','text':'provisional','generation':1})
    assert store.public_progress(job,'owner')['text']=='provisional'
    store.recover()
    assert store.public(job,'owner')['state']=='interrupted' and store.public_progress(job,'owner') is None
    assert store.claim() is None
