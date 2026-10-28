"""Keep the single notes contract and complete scope across concise generation."""
from copy import deepcopy
import json
import logging

from fastapi.testclient import TestClient
import pytest

from app.services.llm import ModelCallBudget,ModelOutputValidationError
from app.v3.onboarding import StudyNotes,generate_notes,infer_scope
from app.v3.notes_outline import outline_request,validate_outline
from app.v3.learning_api import create_learning_app
from app.v3.repository import V3Repository
from app.v3.storage import V3Paths,initialize_storage
from app.v3.runtime_storage import initialize_learning_storage
from tests.test_v3_preparation_content import notes_payload,Queue,scope_result,section
from tests.test_goal_first import GuidedFake,create,act


def outline(headings):
    return '\n\n'.join(h+'\n'+section()['core']+'\n例子：'+section()['example']+
        '\n误解：'+section()['misconception']+'\n练习：'+section()['practice'] for h in headings)


def test_outline_uses_original_single_field_and_all_confirmed_branches():
    payload=notes_payload();data,headings=outline_request(payload)
    expected=outline(data['section_headings']);model=Queue({'content':expected})
    notes=generate_notes(model,ModelCallBudget(),payload,generation_mode='notes-outline-v1')
    assert model.schema is StudyNotes and notes.content==expected
    assert set(notes.model_dump())=={'content'}
    assert data['section_headings']==['## 查询列','## 筛选行']
    assert 100<=data['recommended_total_characters']<=3200


@pytest.mark.parametrize('kind',['missing','swapped','empty'])
def test_missing_or_empty_branches_are_repaired_once_then_rejected(kind):
    payload=notes_payload();data,_=outline_request(payload);heads=data['section_headings']
    bad=outline(heads[:1]) if kind=='missing' else outline(list(reversed(heads))) if kind=='swapped' else heads[0]+'\n只列目录\n'+outline(heads[1:])
    budget=ModelCallBudget()
    with pytest.raises(ModelOutputValidationError):
        generate_notes(Queue({'content':bad},{'content':bad}),budget,payload,generation_mode='notes-outline-v1')
    assert (budget.request_count,budget.output_repair_count)==(2,1)


def test_coverage_error_is_returned_and_valid_repair_preserves_body():
    payload=notes_payload();data,_=outline_request(payload);valid=outline(data['section_headings'])
    model=Queue({'content':outline(data['section_headings'][:1])},{'content':valid});budget=ModelCallBudget()
    assert generate_notes(model,budget,payload,generation_mode='notes-outline-v1').content==valid
    assert '筛选行' in model.messages[1][-1].content
    assert (budget.request_count,budget.output_repair_count)==(2,1)


def test_markdown_examples_do_not_count_as_extra_real_sections():
    content='## 查询列\n'+section()['core']+'\n```markdown\n## 示例里的标题\n```\n'+section()['example']
    content+='\n## 筛选行\n'+section()['core']+section()['example']
    validate_outline(StudyNotes(content=content),['查询列','筛选行'])


def test_long_scope_labels_keep_the_existing_contract_instead_of_a_smaller_limit():
    payload=notes_payload();payload['profile']['scope_in']=['学习范围'+('甲'*2500)]
    data,heads=outline_request(payload)
    assert data['section_headings']==['## '+heads[0]]
    assert data['recommended_total_characters']<=6000


def test_repeated_confirmed_labels_are_preserved_by_position_without_merging():
    payload=notes_payload();payload['profile']['scope_in']=['查询列','查询列']
    data,heads=outline_request(payload)
    validate_outline(StudyNotes(content=outline(data['section_headings'])),heads)
    assert len(heads)==2


def test_notes_only_mode_keeps_scope_request_identical():
    payload={'intent':{},'user_material_catalog':[],'adjustment':'','prompt_version':'test'}
    old,new=Queue(scope_result()),Queue(scope_result())
    infer_scope(old,ModelCallBudget(),payload)
    infer_scope(new,ModelCallBudget(),payload,generation_mode='notes-outline-v1')
    assert [m.content for m in old.messages[0]]==[m.content for m in new.messages[0]]


class OutlineFake(GuidedFake):
    def _invoke(self,schema,messages):
        if schema!='StudyNotes':return super()._invoke(schema,messages)
        self.calls.append({'schema':schema});data=json.loads(messages[1].content)
        return {'content':outline(data['section_headings'])}


def test_real_api_replan_reuses_saved_outline_and_logs_each_stage(tmp_path,caplog):
    paths=initialize_learning_storage(initialize_storage(V3Paths(tmp_path/'runtime')))
    model=OutlineFake();client=TestClient(create_learning_app(paths,llm=model,preparation_generation_mode='notes-outline-v1'))
    caplog.set_level(logging.INFO,logger='skilltree')
    p,_=create(client,'从零学习SQL查询与筛选');p=act(client,p,'confirm_profile')
    assert p['page_state']=='plan_review'
    assert model.call_counts=={'LearningPreparation':1,'StudyNotes':1,'LearningPlan':1}
    scope=next(i for i in model.inputs if i['schema']=='LearningPreparation')
    assert 'generation_contract' not in json.loads(scope['messages'][1])
    source=deepcopy(p['sources']);before=len(model.calls)
    assert client.get('/projects/'+p['project_id']).json()==p and len(model.calls)==before
    p=act(client,p,'replan');assert p['page_state']=='plan_review' and p['sources']==source
    assert model.call_counts=={'LearningPreparation':1,'StudyNotes':1,'LearningPlan':2}
    records=[json.loads(r.message) for r in caplog.records if r.name=='skilltree']
    stages=[r for r in records if r['event']=='preparation_stage_finished']
    assert {'scope','notes','guided_plan'}<={r['node'] for r in stages}
    assert all(r['elapsed_ms']>=0 for r in stages)
    assert any(r['event']=='preparation_reused' and r['outcome']=='cache_hit' for r in records)
    with V3Repository(paths) as repo:
        saved=json.loads(repo.conn.execute("SELECT result_json FROM model_tasks WHERE task_key LIKE 'notes:%'").fetchone()[0])
        assert set(saved)=={'content'} and len(repo.list_sources(p['project_id']))==1
