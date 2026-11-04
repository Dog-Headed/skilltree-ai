"""The production cookie gateway exposes scoped, confirmed and retryable deletion."""
from uuid import uuid4

from fastapi.testclient import TestClient
from app.v3.learning_api import create_learning_app
from app.v3.runtime_storage import initialize_learning_storage
from app.v3.storage import V3Paths,initialize_storage
from deploy.asgi import EvaluationGateway
from deploy.auth import AuthStore
from tests.test_beta_auth_queue import encoded,signin
from tests.test_goal_first import GuidedFake


def test_delete_through_real_cookie_gateway_is_owned_confirmed_and_not_ai_quota(tmp_path,encoded,monkeypatch):
    paths=initialize_learning_storage(initialize_storage(V3Paths(tmp_path/'learning')))
    auth=AuthStore(tmp_path/'auth.sqlite')
    with auth.connect() as c:
        c.executemany('INSERT INTO auth_accounts VALUES (?,?,?,0)',[
            (f'preview{i}@example.test',f'preview{i}@example.test',encoded) for i in (1,2)])
    model=GuidedFake()
    gateway=EvaluationGateway(create_learning_app(paths,llm=model),paths,tmp_path/'quota.sqlite',
        auth_store=auth,queued=True,origin='https://testserver')
    with TestClient(gateway,base_url='https://testserver') as client:
        one,two=signin(client,1),signin(client,2)
        def create(headers):
            response=client.post('/projects',headers=headers,json={'request_id':str(uuid4()),'intent':{'goal':'变量与循环'}})
            assert response.status_code==201
            return response.json()['project_id']
        own,other=create(one),create(two)
        body={'confirm_project_id':own};url='/projects/'+own
        monkeypatch.setenv('SKILLTREE_DAILY_WRITES','1')
        assert client.request('DELETE',url,headers=two,json=body).status_code==404
        assert client.request('DELETE',url,headers={'Cookie':one['Cookie']},json=body).status_code==403
        assert client.request('DELETE',url,headers=one,json={'confirm_project_id':other}).status_code==409
        # Active work cannot be deleted or replayed through the fast path.
        with gateway.jobs.connect() as c:
            c.execute("INSERT INTO deployment_jobs(id,account,project_id,method,path,request_key,body_hash,body,state,created) VALUES (?,?,?,?,?,?,?,?,?,?)",
                ('f'*32,'preview1@example.test',own,'POST',url+'/begin','busy','hash',b'{}','running',1.0))
        assert client.request('DELETE',url,headers=one,json=body).status_code==409
        with gateway.jobs.connect() as c:
            c.execute("UPDATE deployment_jobs SET state='interrupted' WHERE id=?",('f'*32,))
            used=c.execute('SELECT sum(used) FROM usage').fetchone()[0]
        assert client.request('DELETE',url,headers=one,json=body).status_code==200
        assert client.request('DELETE',url,headers=one,json=body).status_code==200
        assert client.get(url,headers=one).status_code==404
        assert client.get('/projects',headers=one).json()==[]
        assert client.get('/projects/'+other,headers=two).status_code==200
        assert not model.inputs
        with gateway.jobs.connect() as c:
            assert c.execute('SELECT sum(used) FROM usage').fetchone()[0]==used
