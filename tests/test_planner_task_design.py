"""Open wording, actual answer interfaces and unchanged hard integrity guards."""
from copy import deepcopy
import json
import pytest

from app.services.llm import ModelCallBudget, ModelOutputValidationError
from app.v3.contracts import LearningPlan
from app.v3.model_content import ContentModel
from app.v3.planner import validate_learnability
from app.v3.preparation import instantiate_policy
from app.v3.quiz_content import build_content_contract,content_payload
from app.v3.task_design import TASK_CAPABILITIES
from tests import test_v3_planner as case
from tests.test_planner_task_contract import proposal,feedback,Wire

SOURCE='新文化运动提倡民主与科学，白话文有助于知识传播。三大战役之后发生渡江战役，随后举行开国大典。科学救国主张以科学知识和教育推动社会进步。'

def course(target='讲清新文化运动中科学观念的含义',forms=('text',),submission='白话文演讲稿',requirement='以新文化运动为背景，围绕科学救国，约200字'):
    value=proposal(tuple(TASK_CAPABILITIES[f] for f in forms),target)
    for task in value['nodes'][0]['objectives'][0]['assessment_tasks']:
        task.update(submission=submission,requirements=[requirement],criteria=['历史背景准确、核心概念正确、解释清楚'])
    return value

def generate(wire,forms=('text',),budget=None):
    caps=[TASK_CAPABILITIES[f] for f in forms]
    p=case.profile(requested_capabilities=caps)
    policy=case.policy(evaluators=[{'evaluator_id':c,'evaluator_version':'1.0.0'} for c in caps],
        allowed_question_types=[{'text':'text','choice':'single_choice','numeric':'numeric_scalar'}[f] for f in forms])
    return case.generate(ContentModel(wire),selected_profile=p,selected_catalog=case.catalog(SOURCE),selected_policy=policy,budget=budget)

@pytest.mark.parametrize('verb',['拟定','撰写','写出','起草','讲述','叙述','描述','present','narrate','draft'])
@pytest.mark.parametrize('artifact',['白话文演讲稿','讲解提纲','史评','展览解说词'])
def test_synonymous_goals_and_open_artifact_names_share_the_same_evidence_interface(verb,artifact):
    target=f'{verb}新文化运动中科学救国观念的含义'
    wire=Wire(course(target,submission=artifact))
    result=generate(wire);goal=result.nodes[0].objectives[0]
    assert goal.observable_outcome==target and goal.assessment_tasks[0].submission==artifact
    assert goal.required_capability_ids==['text_rubric'] and goal.evidence_requirement==['text_excerpt']
    assert len(wire.calls)==1

@pytest.mark.parametrize('verb',['排列','排序','arrange','order'])
def test_ordering_can_use_existing_choice_and_explanation_without_matching_a_verb(verb):
    wire=Wire(course(f'{verb}三大战役、渡江战役、开国大典，并说明依据',('choice','text'),
                     requirement='三件事件的先后顺序与历史事实相符'))
    plan=generate(wire,('choice','text'));node=plan.nodes[0]
    profile=case.profile(requested_capabilities=['choice_exact','text_rubric'])
    template=case.policy(evaluators=[{'evaluator_id':c,'evaluator_version':'1.0.0'} for c in profile.requested_capabilities],allowed_question_types=['single_choice','text'])
    policy=instantiate_policy(template,plan)
    bound={node.objectives[0].objective_id:{'blocks':[{'content':SOURCE,'citation':{'source_id':'source_1','source_version':1,'chunk_id':'chunk_1'}}]}}
    contract=build_content_contract(node,policy,bound);payload=content_payload(contract,node,policy,bound,[])
    assert {s.question_type for s in contract.slots}=={'single_choice','text'}
    for slot in payload['slots'].values():
        tasks=slot['goals'][0]['assessment_tasks']
        assert len(tasks)==1 and tasks[0]['task_form']==('text' if slot['question_type']=='text' else 'choice')
        assert tasks[0]['criteria'] and tasks[0]['collection_instruction']

@pytest.mark.parametrize('mutation',[
    lambda g:g.update(assessment_tasks=[]),
    lambda g:g['assessment_tasks'][0].update(task_form='oral_performance'),
    lambda g:g['assessment_tasks'][0].update(requirements=[]),
    lambda g:g['assessment_tasks'][0].update(criteria=['  ']),
    lambda g:g['assessment_tasks'][0].update(approved=True),
    lambda g:g.update(required_capability_ids=['text_rubric']),
    lambda g:g.update(source_chunk_ids=['s999']),
])
def test_task_labels_or_self_approval_do_not_replace_the_required_contract(mutation):
    value=course();mutation(value['nodes'][0]['objectives'][0]);budget=ModelCallBudget()
    with pytest.raises(ModelOutputValidationError):generate(Wire(value),budget=budget)
    assert (budget.request_count,budget.output_repair_count)==(2,1)

@pytest.mark.parametrize('field',['submission','requirements','criteria'])
def test_known_actual_execution_claims_are_repaired_in_content_even_with_text_label(field):
    bad=course();task=bad['nodes'][0]['objectives'][0]['assessment_tasks'][0]
    task[field]='完成软件安装并成功登录账号' if field=='submission' else ['完成软件安装并成功登录账号']
    wire=Wire(lambda p,s:bad if len(wire.calls)==1 else course());budget=ModelCallBudget()
    assert generate(wire,budget=budget)
    assert 'unsupported_assessment_claim' in feedback(wire)['validation_error']
    assert (budget.request_count,budget.output_repair_count)==(2,1)

def test_missing_task_content_is_repaired_with_its_actual_slot_and_bounded_fragment():
    bad=course();bad['nodes'][0]['objectives'][0]['assessment_tasks'][0]['requirements']=['按要求完成']
    wire=Wire(lambda p,s:bad if len(wire.calls)==1 else course());budget=ModelCallBudget()
    generate(wire,budget=budget);repair=feedback(wire)
    assert '任务内容需要修复' in repair['validation_error']
    target=repair['rejected_candidate_data']['targets'][0]
    assert target['field'].endswith('.assessment_tasks.0.requirements')
    assert target['assessment_task']['requirements']==['按要求完成']

def test_model_cannot_recopy_or_fabricate_program_owned_source_text():
    bad=course();bad['nodes'][0]['objectives'][0]['assessment_tasks'][0]['support_quote']='不存在于资料的历史原文'
    wire=Wire(lambda p,s:bad if len(wire.calls)==1 else course())
    generate(wire)
    assert 'extra_forbidden' in feedback(wire)['validation_error']

@pytest.mark.parametrize('artifact',['安装指南','登录流程说明','部署检查清单'])
def test_artifact_names_are_not_interpreted_as_verified_execution_claims(artifact):
    assert generate(Wire(course(submission=artifact)))

def test_lexical_mismatch_is_a_warning_and_not_semantic_proof_or_a_hard_veto(caplog):
    value=course('Present the intellectual movement in accessible language')
    with caplog.at_level('INFO',logger='skilltree'):plan=generate(Wire(value))
    assert plan and 'planner_source_relevance_warning' in caplog.text
    assert value['nodes'][0]['objectives'][0]['learning_target'] not in caplog.text

def test_legacy_frozen_objectives_roundtrip_without_new_keys_or_migration():
    old=case.plan();first=LearningPlan.model_validate(old).model_dump()
    assert 'assessment_tasks' not in first['nodes'][0]['objectives'][0]
    assert LearningPlan.model_validate(first).model_dump()==first

def test_final_guard_rechecks_mutated_tasks_instead_of_trusting_the_schema_tag():
    plan=generate(Wire(course()));goal=plan.nodes[0].objectives[0]
    goal.assessment_tasks[0]=goal.assessment_tasks[0].model_copy(update={'task_form':'choice'})
    profile=case.profile(requested_capabilities=['text_rubric'])
    policy=case.policy(evaluators=[{'evaluator_id':'text_rubric','evaluator_version':'1.0.0'}],allowed_question_types=['text'])
    with pytest.raises(ValueError):validate_learnability(plan,profile,case.catalog(SOURCE),policy)

def test_existing_legacy_quote_still_requires_an_actual_selected_source_extract():
    plan=generate(Wire(course()));goal=plan.nodes[0].objectives[0]
    goal.assessment_tasks[0]=goal.assessment_tasks[0].model_copy(update={'support_quote':'不是该资料中的原文'})
    profile=case.profile(requested_capabilities=['text_rubric'])
    policy=case.policy(evaluators=[{'evaluator_id':'text_rubric','evaluator_version':'1.0.0'}],allowed_question_types=['text'])
    with pytest.raises(ValueError,match='assessment_source_quote_missing'):
        validate_learnability(plan,profile,case.catalog(SOURCE),policy)
