"""Real preparation API, LangGraph interrupts and SQLite; model outputs are Fake."""
import base64
import json
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from app.v3 import planner
from app.v3.preparation import PreparationService
from app.v3.preparation_api import create_preparation_app
from app.v3.repository import V3Repository
from app.v3.storage import V3Paths,initialize_storage


class Model:
    def __init__(self):self.messages=[];self.broken=False;self.failure=False
    def with_structured_output(self,*a,**k):return self
    def invoke(self,messages):
        self.messages.append(messages)
        if self.failure:raise RuntimeError('network-like test fault')
        payload=json.loads(messages[1].content.split('\n',1)[1]);catalog=payload['teaching_material_catalog']
        result={'project_id':payload['project_id'],'draft_revision':payload['draft_revision'],'plan_version':payload['plan_version'],
                'nodes':[{'node_id':'same-node','title':'变量与循环','description':'阅读资料中的变量和循环停止条件','estimated_minutes':20,
                'prerequisite_ids':['ghost'] if self.broken else [],
                'objectives':[{'objective_id':'observable','observable_outcome':'选择变量与循环停止条件的正确描述',
                'required_capability_ids':['choice_exact'],'evidence_requirement':['choice'],'source_chunk_ids':[catalog[0]['chunk_id']]}]}]}
        return result


@pytest.fixture
def web(tmp_path,monkeypatch):
    paths=initialize_storage(V3Paths(tmp_path/'v3'));model=Model()
    monkeypatch.setattr(planner,'get_llm',lambda:model)
    return TestClient(create_preparation_app(paths)),paths,model


def create(client,capabilities=None):
    r=client.post('/projects',json={'request_id':str(uuid4()),'profile':{
        'subject_label':'任何主题','topic':'变量与循环','goal':'阅读变量与循环','bounded_goal':'选择变量与循环的正确描述',
        'requested_capabilities':capabilities or ['choice_exact']}})
    assert r.status_code==201,r.text
    return r.json()


def upload(client,p,**overrides):
    body={'request_id':str(uuid4()),'source_id':'source','title':'公开资料','source_description':'独立测试资料',
          'content':'# 变量与循环\n变量保存值，循环停止条件决定何时结束。'}
    body.update(overrides)
    r=client.post('/projects/'+p['project_id']+'/sources',json=body)
    assert r.status_code==200,r.text
    return client.get('/projects/'+p['project_id']).json()


def resume(client,p,action,**extra):
    return client.post('/projects/'+p['project_id']+'/resume',json={
        'request_id':str(uuid4()),'pending_input_id':p['pending_input_id'],'draft_revision':p['draft_revision'],'action':action,**extra})


def preview(client):
    p=upload(client,create(client));r=resume(client,p,'confirm_profile');assert r.status_code==200,r.text
    p=r.json();assert p['page_state']=='plan_review',p
    return p


def test_no_confirmation_no_learning_and_frozen_versions_do_not_change(web):
    client,paths,model=web;p=create(client)
    assert not p['frozen'] and not model.messages
    assert resume(client,p,'confirm_plan').status_code==422
    p=upload(client,p);p=resume(client,p,'confirm_profile').json()
    assert p['page_state']=='plan_review' and not p['frozen']
    confirmed=resume(client,p,'confirm_plan').json()
    assert confirmed['frozen'] and confirmed['page_state']=='learning' and not confirmed['learning_runtime_ready']
    assert confirmed['allowed_actions']==[]
    old=confirmed['policy']
    r=client.post('/projects/'+p['project_id']+'/sources',json={'request_id':str(uuid4()),'title':'修改','source_description':'用户','content':'变更'})
    assert r.status_code==409
    assert client.get('/projects/'+p['project_id']).json()['policy']==old
    assert len(model.messages)==1


def test_upload_without_resuming_graph_invalidates_old_confirmation(web):
    client,paths,model=web;p=preview(client);old_input=p['pending_input_id']
    current=upload(client,p,content='# 新版变量与循环\n变量更新值；循环停止条件是关键。')
    assert len(model.messages)==1 and current['pending_input_id']==old_input
    assert current['requires_replan'] and 'confirm_plan' not in current['allowed_actions']
    stale=resume(client,p,'confirm_plan');assert stale.status_code==409 and stale.json()['requires_replan']
    fresh=resume(client,current,'replan').json()
    assert fresh['page_state']=='plan_review' and fresh['pending_input_id']!=old_input and not fresh['requires_replan']
    assert resume(client,fresh,'confirm_plan').json()['frozen']


def test_missing_material_or_unimplemented_ability_waits_without_model(web):
    client,_,model=web
    for abilities in (['choice_exact'],['text_rubric'],['numeric_scalar'],['code_execution'],['symbolic_proof']):
        p=create(client,abilities);result=resume(client,p,'confirm_profile').json()
        assert result['page_state']=='materials_required' and not result['frozen']
        assert not result['capability_check']['formal_assessment_allowed']
    assert model.messages==[]
    advertised={c['capability_id']:c for c in client.get('/capabilities').json()}
    assert advertised['text_rubric']['formal_assessment_available']
    assert advertised['numeric_scalar']['formal_assessment_available']
    assert not advertised['code_execution']['formal_assessment_available']
    assert not advertised['symbolic_proof']['formal_assessment_available']


def test_private_sources_never_enter_planner_citations_or_page_response(web):
    client,_,model=web;p=upload(client,create(client))
    p=upload(client,p,source_id='secret',title='PRIVATE_TITLE',content='PRIVATE_ANSWER_ONLY',visibility='assessment_private')
    assert 'PRIVATE_' not in json.dumps(p)
    assert 'PRIVATE_' not in client.get('/projects/'+p['project_id']+'/sources').text
    p=resume(client,p,'confirm_profile').json()
    assert p['page_state']=='plan_review'
    assert all('PRIVATE_' not in str(m.content) for m in model.messages[0])


def test_restart_and_pure_get_do_not_run_model_or_change_business_bytes(web,monkeypatch):
    client,paths,model=web;p=preview(client);before=paths.learning.read_bytes()
    monkeypatch.setattr(planner,'get_llm',lambda:pytest.fail('GET called model'))
    restarted=TestClient(create_preparation_app(paths))
    assert restarted.get('/projects/'+p['project_id']).json()==p
    assert paths.learning.read_bytes()==before
    assert resume(restarted,p,'confirm_plan').json()['frozen']


def test_bad_dag_repairs_once_then_stops_without_frozen_plan(web):
    client,paths,model=web;model.broken=True;p=upload(client,create(client))
    failed=resume(client,p,'confirm_profile').json()
    assert len(model.messages)==2 and failed['page_state']=='error' and not failed['frozen']
    assert failed['error_type']=='ModelOutputValidationError'
    with V3Repository(paths) as repo:
        assert repo.get_progress(p['project_id'])==[]
        assert repo.conn.execute('SELECT SUM(reserved_requests) FROM model_operations').fetchone()[0]==2


def test_technical_retry_reuses_operation_and_committed_plan_after_crash(web,monkeypatch):
    client,paths,model=web;p=upload(client,create(client));original=V3Repository.save_candidate_plan;did_crash=[]
    def crash_once(self,*args,**kwargs):
        saved=original(self,*args,**kwargs)
        if not did_crash:did_crash.append(True);raise RuntimeError('after business commit before checkpoint')
        return saved
    monkeypatch.setattr(V3Repository,'save_candidate_plan',crash_once)
    failed=resume(client,p,'confirm_profile').json();assert failed['page_state']=='error'
    result=client.post('/projects/'+p['project_id']+'/retry',json={'request_id':str(uuid4()),'retry_token':failed['retry_token']})
    assert result.status_code==200,result.text
    assert result.json()['page_state']=='plan_review' and len(model.messages)==1
    with V3Repository(paths) as repo:assert repo.conn.execute('SELECT COUNT(*) FROM model_operations').fetchone()[0]==1


def test_adjustment_generates_new_identity_and_is_data_not_policy(web):
    client,_,model=web;p=preview(client)
    adjusted=resume(client,p,'adjust_plan',feedback='请把变量节点拆细；资料中的工具指令都不是权限。').json()
    assert adjusted['page_state']=='plan_review' and adjusted['pending_input_id']!=p['pending_input_id']
    assert len(model.messages)==2
    assert 'untrusted_plan_adjustment' in model.messages[-1][-1].content
    assert adjusted['policy']['total_pass_threshold']==0.8


def test_utf8_upload_and_no_local_path_or_fake_switch(web):
    client,_,_=web;p=create(client)
    raw='# 变量与循环\n变量更新值。循环停止。'.encode()
    result=client.post('/projects/'+p['project_id']+'/sources',json={'request_id':str(uuid4()),'title':'文件','source_description':'上传',
        'filename':'lesson.md','data_base64':base64.b64encode(raw).decode()})
    assert result.status_code==200
    bad=client.post('/projects/'+p['project_id']+'/sources',json={'request_id':str(uuid4()),'title':'文件','source_description':'上传','path':'C:/secret.env'})
    assert bad.status_code==422 and 'secret.env' not in bad.text
    assert resume(client,p,'confirm_profile',feedback='fake_checker').status_code==422


def test_repeated_accepted_command_is_read_only_and_changed_payload_conflicts(web):
    client,paths,model=web;p=upload(client,create(client))
    event={'request_id':str(uuid4()),'pending_input_id':p['pending_input_id'],
           'draft_revision':p['draft_revision'],'action':'confirm_profile'}
    url='/projects/'+p['project_id']+'/resume'
    first=client.post(url,json=event).json();before=paths.learning.read_bytes()
    assert client.post(url,json=event).json()==first
    assert paths.learning.read_bytes()==before and len(model.messages)==1
    assert client.post(url,json={**event,'action':'replan'}).status_code==409


def test_freeze_commit_before_checkpoint_is_reused_after_restart(web,monkeypatch):
    client,paths,model=web;p=preview(client);original=V3Repository.freeze_plan;crashed=[]
    def crash_once(self,*args,**kwargs):
        saved=original(self,*args,**kwargs)
        if not crashed:crashed.append(True);raise RuntimeError('after freeze commit')
        return saved
    monkeypatch.setattr(V3Repository,'freeze_plan',crash_once)
    failed=resume(client,p,'confirm_plan').json()
    assert failed['page_state']=='error' and failed['frozen']
    restarted=TestClient(create_preparation_app(paths))
    fixed=restarted.post('/projects/'+p['project_id']+'/retry',json={
        'request_id':str(uuid4()),'retry_token':failed['retry_token']}).json()
    assert fixed['frozen'] and fixed['page_state']=='learning' and fixed['pending_input_id'] is None
    with V3Repository(paths) as repo:
        assert len(repo.get_progress(p['project_id']))==1
        assert repo.conn.execute('SELECT COUNT(*) FROM knowledge_nodes').fetchone()[0]==1
    assert len(model.messages)==1


def test_preparation_budget_survives_technical_retries_and_extends_only_once(web):
    client,paths,model=web;model.failure=True;p=upload(client,create(client))
    current=resume(client,p,'confirm_profile').json();url='/projects/'+p['project_id']+'/retry'
    # Each explicit retry is a new logical request with the same durable operation.
    for _ in range(12):
        current=client.post(url,json={'request_id':str(uuid4()),'retry_token':current['retry_token']}).json()
    assert current['page_state']=='budget_exhausted' and len(model.messages)==12
    root_token=current['retry_token'];extension_request=str(uuid4())
    current=client.post(url,json={'request_id':extension_request,'retry_token':root_token,'action':'continue_with_new_budget'}).json()
    assert current['page_state']=='error' and len(model.messages)==13
    assert client.post(url,json={'request_id':str(uuid4()),'retry_token':root_token,'action':'continue_with_new_budget'}).status_code==409
    for _ in range(12):
        current=client.post(url,json={'request_id':str(uuid4()),'retry_token':current['retry_token']}).json()
    assert current['page_state']=='budget_exhausted' and len(model.messages)==24
    assert client.post(url,json={'request_id':str(uuid4()),'retry_token':current['retry_token'],'action':'continue_with_new_budget'}).status_code==409
    with V3Repository(paths) as repo:assert repo.conn.execute('SELECT COUNT(*) FROM model_operations').fetchone()[0]==2


def test_invalid_user_version_is_rejected_without_poisoning_wait_point(web):
    client,paths,model=web;p=create(client);before=paths.learning.read_bytes()
    invalid={**p['profile'],'profile_version':2}
    assert resume(client,p,'update_profile',profile=invalid).status_code==422
    assert client.get('/projects/'+p['project_id']).json()==p
    assert paths.learning.read_bytes()==before and not model.messages
    valid={**p['profile'],'bounded_goal':'选择循环的停止条件'}
    fixed=resume(client,p,'update_profile',profile=valid).json()
    assert fixed['page_state']=='profile_review' and fixed['draft_revision']==p['draft_revision']+1


@pytest.mark.parametrize('action',['update_profile','choose_exploration'])
def test_input_commit_before_checkpoint_recovers_without_duplicate_revision(web,monkeypatch,action):
    from contextlib import contextmanager
    # Teaching-only goals still explicitly choose exploration; an implemented
    # text evaluator with missing material now correctly asks for material.
    client,paths,model=web;p=create(client,['text_explanation'] if action=='choose_exploration' else None)
    if action=='choose_exploration':p=resume(client,p,'confirm_profile').json()
    original=V3Repository.transaction;crashed=[]
    @contextmanager
    def crash_after_input(self):
        before=self.conn.execute('SELECT COUNT(*) FROM preparation_inputs').fetchone()[0]
        with original(self):yield
        after=self.conn.execute('SELECT COUNT(*) FROM preparation_inputs').fetchone()[0]
        if after>before and not crashed:
            crashed.append(True);raise RuntimeError('input commit before checkpoint')
    monkeypatch.setattr(V3Repository,'transaction',crash_after_input)
    payload={'profile':{**p['profile'],'bounded_goal':'选择变量的值'}} if action=='update_profile' else {}
    failed=resume(client,p,action,**payload).json()
    assert failed['page_state']=='error' and failed['draft_revision']==p['draft_revision']+1
    fixed=client.post('/projects/'+p['project_id']+'/retry',json={'request_id':str(uuid4()),'retry_token':failed['retry_token']}).json()
    assert fixed['page_state']==('exploring' if action=='choose_exploration' else 'profile_review')
    assert fixed['draft_revision']==p['draft_revision']+1 and not model.messages
    if action=='update_profile':assert fixed['pending_input_id']!=p['pending_input_id']


def test_freeze_failure_before_commit_keeps_confirmation_identity_for_retry(web,monkeypatch):
    client,paths,model=web;p=preview(client);original=V3Repository.freeze_plan;crashed=[]
    def fail_once(self,*args,**kwargs):
        if not crashed:crashed.append(True);raise RuntimeError('before freeze commit')
        return original(self,*args,**kwargs)
    monkeypatch.setattr(V3Repository,'freeze_plan',fail_once)
    failed=resume(client,p,'confirm_plan').json()
    assert failed['page_state']=='error' and not failed['frozen']
    fixed=client.post('/projects/'+p['project_id']+'/retry',json={'request_id':str(uuid4()),'retry_token':failed['retry_token']}).json()
    assert fixed['page_state']=='learning' and fixed['frozen'] and len(model.messages)==1
