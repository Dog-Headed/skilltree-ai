"""Goal-first UI backend: real SQLite/Graph, explicitly Fake model content."""
from copy import deepcopy
import json
from uuid import uuid4
from pathlib import Path
import subprocess
import sys

from fastapi.testclient import TestClient
import httpx
from openai import APITimeoutError
import pytest

from app.v3.learning_api import create_learning_app
from app.v3.materials import MaterialService
from app.v3.onboarding import LearningIntent, metadata
from app.v3.repository import V3Repository
from app.v3.storage import V3Paths, initialize_storage
from app.v3.runtime_storage import initialize_learning_storage
from tests.day11_support import FakeLearningModel


class GuidedFake(FakeLearningModel):
    def __init__(self,**kwargs):
        super().__init__(**kwargs);self.inputs=[]

    def _invoke(self,schema,messages):
        self.inputs.append({'schema':schema,'messages':[m.content for m in messages]})
        result=super()._invoke(schema,messages)
        if schema=='LearningPreparation' and isinstance(result,dict) and 'evaluation_capabilities' in result:
            result['evaluation_capabilities']=['text_rubric']
        return result

    def _plan(self,data):
        chunk=data['teaching_material_catalog'][0]
        return {'project_id':data['project_id'],'draft_revision':data['draft_revision'],'plan_version':data['plan_version'],
            'nodes':[{'node_id':'first','title':'解释本课规则','description':'Fake流程目标，非内容质量结论',
            'estimated_minutes':15,'prerequisite_ids':[],
            'objectives':[{'objective_id':'explain','observable_outcome':'依据资料说明：'+chunk['content'][:150],
            'required_capability_ids':['text_rubric'],'evidence_requirement':['text_excerpt'],
            'source_chunk_ids':[chunk['chunk_id']],'criterion_ids':['criterion_explain']}]}]}


@pytest.fixture
def guided(tmp_path):
    paths=initialize_learning_storage(initialize_storage(V3Paths(tmp_path/'runtime')))
    model=GuidedFake()
    return TestClient(create_learning_app(paths,llm=model)),paths,model


def create(client,goal='从零学习英语基础',request_id=None):
    payload={'request_id':request_id or str(uuid4()),'intent':{'goal':goal,'prior_knowledge':'零基础'}}
    r=client.post('/projects',json=payload);assert r.status_code==201,r.text
    return r.json(),payload


def act(client,p,action,request_id=None,**extra):
    r=client.post('/projects/'+p['project_id']+'/resume',json={'request_id':request_id or str(uuid4()),
        'pending_input_id':p['pending_input_id'],'draft_revision':p['draft_revision'],'action':action,**extra})
    assert r.status_code==200,r.text
    return r.json()


def upload(client,p,content='# 规则\n请按照资料逐条解释，不补充不存在的规定。',**extra):
    r=client.post('/projects/'+p['project_id']+'/sources',json={'request_id':str(uuid4()),'title':'本课资料',
        'source_description':'明确标记的合成验收资料','content':content,**extra})
    assert r.status_code==200,r.text
    return client.get('/projects/'+p['project_id']).json()


def test_goal_only_create_and_get_are_read_only_and_creation_is_idempotent(guided):
    client,paths,model=guided;p,payload=create(client)
    assert p['guided'] and p['profile']['bounded_goal'] is None and p['allowed_actions']
    assert client.post('/projects',json=payload).json()==p
    assert client.get('/projects/'+p['project_id']).json()==p and model.calls==[]
    payload['intent']['goal']='改变目标'
    assert client.post('/projects',json=payload).status_code==409
    with V3Repository(paths) as repo:
        assert len(repo.list_projects())==1
        assert repo.conn.execute('SELECT count(*) FROM guided_projects').fetchone()[0]==1
        assert not repo.list_sources(p['project_id'],include_private=True)


def test_no_upload_scope_notes_plan_freeze_learning_and_quiz(guided):
    client,paths,model=guided;p,_=create(client)
    p=act(client,p,'confirm_profile');assert p['page_state']=='plan_review',p
    assert p['learning_basis']=='ai_generated' and p['profile']['bounded_goal'] and not p['profile']['prior_knowledge']['assessed_evidence']
    assert model.call_counts=={'LearningPreparation':1,'StudyNotes':1,'LearningPlan':1}
    assert len(p['sources'])==1 and 'AI生成' in p['sources'][0]['trust_note']
    p=act(client,p,'confirm_plan',private_references=[])
    p=client.post('/projects/'+p['project_id']+'/begin',json={'request_id':str(uuid4())}).json()
    assert p['page_state']=='learning' and p['tutor']['citations']
    p=act(client,p,'start_quiz');assert p['quiz']['questions']
    assert p['learning_basis']=='ai_generated'
    with V3Repository(paths) as repo:
        assert repo.get_project(p['project_id'])['frozen_snapshot']['source_manifest']
        assert all(r[0]<=3 for r in repo.conn.execute('SELECT requests FROM model_tasks'))


def test_uploaded_material_is_authority_and_private_never_enters_scope_or_tutor(guided):
    client,paths,model=guided;p,_=create(client,'学习本公司的培训制度')
    p=upload(client,p,'# 培训制度\n本演示单位每周五安排一小时培训，缺席应提前申请，不编造罚款。')
    p=upload(client,p,'# 私有\nPRIVATE_ONLY_REFERENCE_MARKER 答案仅供评分。',visibility='assessment_private',title='独立私有评价参考')
    p=act(client,p,'confirm_profile');assert p['page_state']=='plan_review'
    assert p['learning_basis']=='provided_material' and model.call_counts['StudyNotes']==0
    scope=next(x for x in model.inputs if x['schema']=='LearningPreparation')
    assert '每周五' in str(scope) and 'PRIVATE_ONLY_REFERENCE_MARKER' not in str(scope)
    p=act(client,p,'confirm_plan',private_references=[{'reference_id':x['reference_id'],'action':'exclude','node_ids':[]} for x in p['private_references']])
    p=client.post('/projects/'+p['project_id']+'/begin',json={'request_id':str(uuid4())}).json()
    assert 'PRIVATE_ONLY_REFERENCE_MARKER' not in str(next(x for x in model.inputs if x['schema']=='TutorReply'))


def test_internal_policy_without_document_waits_zero_requests_then_upload_replans(guided):
    client,paths,model=guided;p,_=create(client,'学习本公司的请假制度')
    p=act(client,p,'confirm_profile')
    assert p['page_state']=='materials_required' and p['learning_basis']=='requires_material' and model.calls==[]
    assert '不会由AI编造' in p['preparation_notice'] and 'replan' in p['allowed_actions']
    p=upload(client,p,'# 请假制度\n合成案例：请假提前一天提交申请，交直属负责人审核。')
    p=act(client,p,'replan')
    assert p['page_state']=='plan_review' and p['learning_basis']=='provided_material' and model.call_counts['StudyNotes']==0


def test_generated_identity_cannot_be_written_from_upload_api(guided):
    client,_,_=guided;p,_=create(client)
    r=client.post('/projects/'+p['project_id']+'/sources',json={'request_id':str(uuid4()),'source_id':'ai_notes_forged',
        'title':'冒充','source_description':'不可冒充生成来源','content':'fake'})
    assert r.status_code==422


def test_duplicate_prepare_reuses_all_model_results_and_budget(guided):
    client,paths,model=guided;p,_=create(client);request=str(uuid4());old=deepcopy(p)
    p=act(client,p,'confirm_profile',request_id=request)
    assert act(client,old,'confirm_profile',request_id=request)==p
    assert len(model.calls)==3
    with V3Repository(paths) as repo:
        assert repo.conn.execute('SELECT sum(reserved_requests) FROM model_operations').fetchone()[0]==3
        assert len(repo.list_sources(p['project_id']))==1


def test_notes_commit_then_failure_retries_cached_scope_and_notes(guided,monkeypatch):
    client,paths,model=guided;p,_=create(client);original=MaterialService.import_text;failed=False
    def crash(self,*args,**kwargs):
        nonlocal failed
        result=original(self,*args,**kwargs)
        if kwargs.get('source_id','').startswith('ai_notes_') and not failed:
            failed=True;raise RuntimeError('fault after notes commit')
        return result
    monkeypatch.setattr(MaterialService,'import_text',crash)
    p=act(client,p,'confirm_profile');assert p['page_state']=='error' and len(model.calls)==2
    p=client.post('/projects/'+p['project_id']+'/retry',json={'request_id':str(uuid4()),'retry_token':p['retry_token']}).json()
    assert p['page_state']=='plan_review',p
    assert model.call_counts=={'LearningPreparation':1,'StudyNotes':1,'LearningPlan':1}
    with V3Repository(paths) as repo:assert len(repo.list_sources(p['project_id']))==1


def test_candidate_commit_then_failure_reuses_plan_and_input_identity(guided,monkeypatch):
    client,paths,model=guided;p,_=create(client);original=V3Repository.save_candidate_plan;failed=False
    def crash(self,*args,**kwargs):
        nonlocal failed
        result=original(self,*args,**kwargs)
        if not failed:failed=True;raise RuntimeError('fault after candidate commit')
        return result
    monkeypatch.setattr(V3Repository,'save_candidate_plan',crash)
    p=act(client,p,'confirm_profile');assert p['page_state']=='error'
    with V3Repository(paths) as repo:identity=repo.get_project(p['project_id'])['candidate_input_id']
    p=client.post('/projects/'+p['project_id']+'/retry',json={'request_id':str(uuid4()),'retry_token':p['retry_token']}).json()
    assert p['page_state']=='plan_review' and p['pending_input_id']==identity and len(model.calls)==3


def test_scope_network_retry_is_persisted(guided):
    client,paths,model=guided;model.faults['LearningPreparation'].append(APITimeoutError(request=httpx.Request('POST','https://example.invalid/fake')))
    p,_=create(client);p=act(client,p,'confirm_profile');assert p['page_state']=='plan_review'
    with V3Repository(paths) as repo:
        row=repo.conn.execute("SELECT requests,network_retries,output_repairs FROM model_tasks WHERE task_key LIKE 'scope:%'").fetchone()
        assert tuple(row)==(2,1,0)


def test_invalid_scope_can_repair_and_following_tasks_share_operation(guided):
    client,paths,model=guided;model.faults['LearningPreparation'].append({})
    p,_=create(client);p=act(client,p,'confirm_profile');assert p['page_state']=='plan_review'
    with V3Repository(paths) as repo:
        assert repo.conn.execute('SELECT sum(reserved_requests) FROM model_operations').fetchone()[0]==4
        assert tuple(repo.conn.execute("SELECT requests,output_repairs FROM model_tasks WHERE task_key LIKE 'scope:%'").fetchone())==(2,1)


def test_exhausted_operation_requires_explicit_idempotent_continuation(guided,monkeypatch):
    client,paths,model=guided;p,_=create(client);original=V3Repository.create_operation;first=True
    def full(self,*args,**kwargs):
        nonlocal first
        op=original(self,*args,**kwargs)
        if first:
            first=False
            with self.transaction():self.conn.execute('UPDATE model_operations SET reserved_requests=12 WHERE operation_id=?',(op['operation_id'],))
        return op
    monkeypatch.setattr(V3Repository,'create_operation',full)
    p=act(client,p,'confirm_profile');assert p['page_state']=='budget_exhausted' and not model.calls
    request={'request_id':str(uuid4()),'retry_token':p['retry_token'],'action':'continue_with_new_budget'}
    p=client.post('/projects/'+p['project_id']+'/retry',json=request).json()
    assert p['page_state']=='plan_review',p
    assert client.post('/projects/'+p['project_id']+'/retry',json=request).json()==p
    assert len(model.calls)==3
    with V3Repository(paths) as repo:
        assert repo.conn.execute('SELECT count(*),sum(reserved_requests) FROM model_operations').fetchone()[:]==(2,15)


@pytest.mark.parametrize('basis',['requires_material','unsupported'])
def test_model_can_request_needed_document_or_stop_unsupported_scope(guided,basis):
    client,paths,model=guided
    model.faults['LearningPreparation'].append({'subject_label':'通用主题','topic':'有限范围','bounded_goal':'先明确必要依据',
        'scope_in':['文字解释'],'scope_out':['无法实际验证的实践'],'evaluation_capabilities':['text_rubric'],
        'basis':basis,'explanation':'需要指定资料或当前尚未实现的实际评价能力，不能假装已经验证。'})
    p,_=create(client);p=act(client,p,'confirm_profile')
    assert p['page_state']=='materials_required' and p['learning_basis']==basis
    assert len(model.calls)==1 and not p['plan']


@pytest.mark.parametrize('phase',['LearningPreparation','StudyNotes'])
def test_invalid_output_repairs_once_then_stops_without_plan(guided,phase):
    client,paths,model=guided;model.faults[phase].extend([{},{}]);p,_=create(client)
    p=act(client,p,'confirm_profile');assert p['page_state']=='profile_review'
    assert not p['plan'] and model.call_counts[phase]==2 and model.call_counts['LearningPlan']==0
    with V3Repository(paths) as repo:assert not repo.get_project(p['project_id'])['frozen_snapshot']
    assert 'confirm_profile' in p['allowed_actions'] and '已用请求不会清零' in p['preparation_notice']
    # This is a new explicit prepare command, never a third automatic repair.
    p=act(client,p,'confirm_profile');assert p['page_state']=='plan_review'
    with V3Repository(paths) as repo:
        assert repo.conn.execute("SELECT count(*) FROM model_tasks WHERE status='invalid'").fetchone()[0]==1


def test_upload_after_generated_preview_invalidates_confirmation_and_replans_on_user_sources(guided):
    client,paths,model=guided;p,_=create(client);p=act(client,p,'confirm_profile');old=deepcopy(p)
    p=upload(client,p,'# 新的学习依据\n这份上传资料限定当前学习内容。只按这份材料整理范围。')
    assert p['requires_replan'] and 'confirm_plan' not in p['allowed_actions']
    r=client.post('/projects/'+p['project_id']+'/resume',json={'request_id':str(uuid4()),'pending_input_id':old['pending_input_id'],
        'draft_revision':old['draft_revision'],'action':'confirm_plan','private_references':[]});assert r.status_code==409
    p=act(client,p,'replan');assert p['learning_basis']=='provided_material' and model.call_counts['StudyNotes']==1
    last=[x for x in model.inputs if x['schema']=='LearningPlan'][-1]
    assert '新的学习依据' in str(last) and 'Fake通用学习讲义' not in str(last)


def test_edit_goal_reprepares_ai_scope_without_changing_prior_evidence(guided):
    client,paths,model=guided
    initial,_=create(client,'学习英语句子');profile=initial['profile'];profile['goal']='学习英语问候表达'
    initial=act(client,initial,'update_profile',profile=profile)
    initial=act(client,initial,'confirm_profile')
    assert initial['profile']['bounded_goal']=='学习英语问候表达'
    assert initial['profile']['prior_knowledge']['assessed_evidence']==[]


@pytest.mark.parametrize('fault',['notes','plan'])
def test_hard_process_exit_reuses_durable_preparation_results(tmp_path,fault):
    worker=Path(__file__).parent/'support/goal_first_worker.py'
    command=[sys.executable,'-X','utf8',str(worker),'--root',str(tmp_path)]
    first=subprocess.run([*command,'--mode',fault],capture_output=True,text=True,encoding='utf-8',timeout=60)
    assert first.returncode==91,first.stdout+first.stderr
    resumed=subprocess.run([*command,'--mode','recover'],capture_output=True,text=True,encoding='utf-8',timeout=60)
    assert resumed.returncode==0,resumed.stdout+resumed.stderr
    assert json.loads((tmp_path/'result.json').read_text())['requests']==3
