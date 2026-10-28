"""Content contracts must preserve full scope, durable budgets and public V3 data."""
from copy import deepcopy
import json

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.services.llm import ModelCallBudget, ModelOutputValidationError
from app.v3.onboarding import infer_scope, generate_notes, LearningPreparation, StudyNotes
from app.v3.preparation_content import notes_contract, assemble_notes, scope_payload
from app.v3.learning_api import create_learning_app
from app.v3.repository import V3Repository
from app.v3.storage import V3Paths, initialize_storage
from app.v3.runtime_storage import initialize_learning_storage
from tests.test_goal_first import GuidedFake, create, act, upload


def scope_result(**extra):
    return dict(subject_label='SQL', topic='SQL基础', bounded_goal='查询和筛选的文字学习',
        scope_in=['查询列', '筛选行'], scope_out=['数据库执行'],
        evaluation_capabilities=['text_rubric'], basis='general_knowledge', explanation='只验证文字推理。', **extra)


def notes_payload():
    from app.v3.contracts import LearningProfile
    profile=LearningProfile(subject_label='SQL', topic='SQL基础', goal='查询和筛选的文字学习',
        bounded_goal='查询和筛选的文字学习', scope_in=['查询列', '筛选行'], scope_out=['数据库执行'])
    return {'profile':profile.model_dump()}


def section():
    return {'core':'这是明确标记的合成资料。SELECT选择返回列，WHERE筛选满足条件的数据行。',
            'example':'SELECT name FROM demo WHERE age > 18 返回符合条件的姓名。',
            'misconception':'选择列不会自动筛选数据行，两个操作不能混淆。',
            'practice':'依据规则解释一个SELECT和WHERE例子各自的作用。'}


class Queue:
    def __init__(self,*results):self.results=list(results);self.messages=[]
    def with_structured_output(self,schema,**kwargs):self.schema=schema;return self
    def invoke(self,messages):
        self.messages.append(messages)
        return self.results.pop(0)


@pytest.mark.parametrize('supplied',[False,True])
def test_scope_checks_real_material_and_omits_unused_identity_metadata(supplied):
    catalog=[{'project_id':'private-id','content_hash':'private-hash','title':'合成资料','content':'完整正文'}] if supplied else []
    payload={'intent':{'goal':'SQL入门'},'user_material_catalog':catalog,'adjustment':'保留全部范围'}
    scope=scope_result();scope['basis']='provided_material' if supplied else 'general_knowledge'
    model=Queue(scope);result=infer_scope(model,ModelCallBudget(),payload,generation_mode='content-v1')
    assert isinstance(result,LearningPreparation)
    assert result.basis==('provided_material' if supplied else 'general_knowledge')
    assert result.scope_in==['查询列','筛选行']
    assert 'private-id' not in model.messages[0][1].content
    if supplied:assert '完整正文' in model.messages[0][1].content


@pytest.mark.parametrize('readiness',['requires_material','unsupported'])
def test_readiness_stop_is_never_replaced_by_general_knowledge(readiness):
    result=scope_result();result['basis']=readiness
    assert infer_scope(Queue(result),ModelCallBudget(),{'intent':{},'user_material_catalog':[]},
                       generation_mode='content-v1').basis==readiness


def test_invalid_scope_fields_and_duplicate_capabilities_consume_one_repair():
    invalid=scope_result();invalid['evaluation_capabilities']=['text_rubric','text_rubric']
    budget=ModelCallBudget();model=Queue(invalid,scope_result())
    infer_scope(model,budget,{'intent':{},'user_material_catalog':[]},generation_mode='content-v1')
    assert (budget.request_count,budget.output_repair_count)==(2,1)
    assert '评价能力不能重复' in model.messages[1][-1].content


def test_scope_without_uploads_keeps_the_same_contract_and_prompt_in_both_modes():
    payload={'intent':{'goal':'SQL入门'},'adjustment':'','user_material_catalog':[],
             'prompt_version':'test','available_evaluators':['choice_exact','numeric_scalar','text_rubric']}
    old,new=Queue(scope_result()),Queue(scope_result())
    infer_scope(old,ModelCallBudget(),payload)
    infer_scope(new,ModelCallBudget(),payload,generation_mode='content-v1')
    assert old.schema is new.schema is LearningPreparation
    assert [m.content for m in old.messages[0]]==[m.content for m in new.messages[0]]


@pytest.mark.parametrize('mutation',['missing','extra','whitespace','overflow'])
def test_notes_fail_closed_without_dropping_or_truncating_a_branch(mutation):
    payload=notes_payload();valid={'sections':[list(section().values()) for _ in (1,2)]};bad=deepcopy(valid)
    if mutation=='missing':bad['sections'].pop()
    elif mutation=='extra':bad['sections'].append(list(section().values()))
    elif mutation=='whitespace':bad['sections'][0][0]=' '*30
    else:
        payload['profile']['scope_in']=['分支'+str(i) for i in range(1,13)]
        bad={'sections':[['正文'*min(350,len(v)*6) for v in section().values()] for _ in range(1,13)]}
    budget=ModelCallBudget()
    with pytest.raises(ModelOutputValidationError):
        generate_notes(Queue(bad,bad),budget,payload,generation_mode='content-v1')
    assert (budget.request_count,budget.output_repair_count)==(2,1)


def test_program_assembles_all_headings_and_original_notes_contract():
    payload=notes_payload();schema,_=notes_contract(payload)
    result=assemble_notes(schema.model_validate({'sections':[list(section().values()) for _ in (1,2)]}),payload)
    assert isinstance(result,StudyNotes)
    assert result.content.count('## ')==2 and '## 查询列' in result.content and '## 筛选行' in result.content
    assert result.content.count('常见误解：')==2 and result.content.count('练习方向：')==2


def test_positional_notes_reject_wrong_part_count_and_non_text_values():
    payload=notes_payload();schema,_=notes_contract(payload)
    for parts in ([section()['core']]*3,[section()['core']]*5,[20,*list(section().values())[1:]]):
        with pytest.raises(ValidationError):schema.model_validate({'sections':[parts,list(section().values())]})


def test_duplicate_notes_field_reports_a_safe_field_path_for_repair():
    from langchain_core.messages import AIMessage
    from langchain_core.exceptions import OutputParserException
    from types import SimpleNamespace
    from app.services.llm import compact_parse_error
    from deploy.provider import StructuredReply
    class Raw:
        def invoke(self,messages):
            return {'parsed':object(),'raw':AIMessage(content='{"sections":[],"sections":[]}'),'parsing_error':None}
    with pytest.raises(OutputParserException) as caught:StructuredReply(Raw(),'StudyNotesContent').invoke([])
    diagnostic=compact_parse_error(caught.value)
    assert 'duplicate_field' in diagnostic and 'sections' in diagnostic


class GuidedContentFake(GuidedFake):
    def _invoke(self,schema,messages):
        if schema not in {'LearningPreparation','StudyNotesContent'}:return super()._invoke(schema,messages)
        self.calls.append({'schema':schema});self.inputs.append({'schema':schema,'messages':[m.content for m in messages]})
        data=json.loads(messages[1].content)
        if schema=='LearningPreparation':
            result=scope_result();result['basis']='provided_material' if data['user_material_catalog'] else 'general_knowledge'
            return result
        return {'sections':[list(section().values()) for _ in data['sections']]}


def test_optional_mode_freezes_real_notes_and_replan_reuses_preparation_without_extra_calls(tmp_path):
    paths=initialize_learning_storage(initialize_storage(V3Paths(tmp_path/'runtime')))
    model=GuidedContentFake();client=TestClient(create_learning_app(paths,llm=model,preparation_generation_mode='content-v1'))
    p,_=create(client,'从零学习SQL查询和筛选');original=deepcopy(p)
    p=act(client,p,'confirm_profile');assert p['page_state']=='plan_review'
    assert p['profile']['scope_in']==['查询列','筛选行'] and p['learning_basis']=='ai_generated'
    assert model.call_counts=={'LearningPreparation':1,'StudyNotesContent':1,'LearningPlan':1}
    before=len(model.calls);assert client.get('/projects/'+p['project_id']).json()==p and len(model.calls)==before
    p=act(client,p,'replan');assert p['page_state']=='plan_review'
    assert model.call_counts=={'LearningPreparation':1,'StudyNotesContent':1,'LearningPlan':2}
    p=act(client,p,'confirm_plan',private_references=[]);assert p['frozen']
    with V3Repository(paths) as repo:
        assert len(repo.list_sources(p['project_id']))==1
        assert all(row[0]<=3 for row in repo.conn.execute('SELECT requests FROM model_tasks'))
        saved=repo.conn.execute("SELECT result_json FROM model_tasks WHERE task_key LIKE 'notes:%'").fetchone()[0]
        assert set(json.loads(saved))=={'content'}  # Persist original public contract.


def test_supplied_material_skips_notes_and_private_reference_stays_out(tmp_path):
    paths=initialize_learning_storage(initialize_storage(V3Paths(tmp_path/'runtime')))
    model=GuidedContentFake();client=TestClient(create_learning_app(paths,llm=model,preparation_generation_mode='content-v1'))
    p,_=create(client,'SQL入门');p=upload(client,p,section()['core'])
    p=upload(client,p,'PRIVATE_REFERENCE_NEVER_IN_SCOPE',visibility='assessment_private',title='私有参考')
    p=act(client,p,'confirm_profile');assert p['page_state']=='plan_review'
    assert p['learning_basis']=='provided_material' and model.call_counts['StudyNotesContent']==0
    scope=next(i for i in model.inputs if i['schema']=='LearningPreparation')
    assert section()['core'] in str(scope) and 'PRIVATE_REFERENCE_NEVER_IN_SCOPE' not in str(scope)


def test_internal_document_gate_remains_zero_calls_in_optional_mode(tmp_path):
    paths=initialize_learning_storage(initialize_storage(V3Paths(tmp_path/'runtime')))
    model=GuidedContentFake();client=TestClient(create_learning_app(paths,llm=model,preparation_generation_mode='content-v1'))
    p,_=create(client,'学习本公司请假制度');p=act(client,p,'confirm_profile')
    assert p['page_state']=='materials_required' and not model.calls


def test_notes_saved_before_interruption_are_reused_with_same_durable_budget(tmp_path,monkeypatch):
    from app.v3.materials import MaterialService
    paths=initialize_learning_storage(initialize_storage(V3Paths(tmp_path/'runtime')))
    model=GuidedContentFake();client=TestClient(create_learning_app(paths,llm=model,preparation_generation_mode='content-v1'))
    original=MaterialService.import_text;interrupted=False
    def crash(self,*args,**kwargs):
        nonlocal interrupted
        saved=original(self,*args,**kwargs)
        if kwargs.get('source_id','').startswith('ai_notes_') and not interrupted:
            interrupted=True;raise RuntimeError('synthetic interruption after notes commit')
        return saved
    monkeypatch.setattr(MaterialService,'import_text',crash)
    p,_=create(client,'SQL入门');p=act(client,p,'confirm_profile')
    assert p['page_state']=='error' and model.call_counts=={'LearningPreparation':1,'StudyNotesContent':1}
    before=len(model.calls)
    assert client.get('/projects/'+p['project_id']).json()==p and len(model.calls)==before
    from uuid import uuid4
    p=client.post('/projects/'+p['project_id']+'/retry',json={'request_id':str(uuid4()),'retry_token':p['retry_token']}).json()
    assert p['page_state']=='plan_review'
    assert model.call_counts=={'LearningPreparation':1,'StudyNotesContent':1,'LearningPlan':1}
    with V3Repository(paths) as repo:
        assert len(repo.list_sources(p['project_id']))==1
        assert repo.conn.execute('SELECT sum(requests) FROM model_tasks').fetchone()[0]==3
