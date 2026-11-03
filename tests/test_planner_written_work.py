"""Submitted work, ephemeral repair context and safe final diagnostics."""
from copy import deepcopy
import json

import pytest

from app.services.llm import ModelCallBudget, ModelOutputValidationError, compact_parse_error
from app.v3.model_content import ContentModel
from app.v3.planning_contract import validate_objective_tasks, PlanningTaskError
from app.v3.preparation_feedback import safe_summary, guarded_plan
from app.v3.model_tasks import run_model_task
from app.v3.repository import V3Repository
from app.v3.contracts import LearningPlan
from tests import test_v3_planner as case
from tests.test_planner_task_contract import proposal, Wire, feedback
from tests.test_goal_first import guided, create

REAL_PRACTICE='编写一个提示词，要求 Claude 用表格形式输出两种编程语言的优缺点，并指定表格列名。'
SOURCE='Claude提示词可包含背景、任务和输出格式。表格应指定列名和长度。邮件应包含主题和三条要点。摘要须包含结论和依据。安装登录步骤只能用文字解释，不能验证真实操作。A prompt specifies table columns and length requirements. An email includes a subject and three points.'


def generate(wire, budget=None):
    profile=case.profile(requested_capabilities=['text_rubric'])
    policy=case.policy(evaluators=[{'evaluator_id':'text_rubric','evaluator_version':'1.0.0'}],allowed_question_types=['text'])
    return case.generate(ContentModel(wire),selected_profile=profile,selected_policy=policy,
                         selected_catalog=case.catalog(SOURCE),budget=budget)


def data(text):
    return proposal(('text_rubric',),text,quote=SOURCE[:120])


@pytest.mark.parametrize('text',[
    REAL_PRACTICE,REAL_PRACTICE.replace('编写','写出'),
    '撰写一条包含背景、任务和输出格式的提示词',
    '拟定一条提示词，要求包含背景和输出格式',
    '起草一封邮件，指定主题并包含三条要点',
    '撰写一份摘要，要求包含结论及依据',
    'Draft an email with a subject and three points',
    'Write a prompt with table columns and length requirements',
    '为“写一封请假邮件”和“总结一段新闻”分别设计提示词，并说明期望输出。',
    '规划一个三步任务（如总结、提问、改写），写出每步的提示词，并说明如何利用上下文连接各步骤。',
    '说明如何利用上下文连接各步骤，并写出每步的提示词。',
])
def test_specific_submitted_works_are_accepted_without_rewriting_or_claude_special_case(text):
    value=data(text);before=deepcopy(value);wire=Wire(value)
    plan=generate(wire)
    assert plan.nodes[0].objectives[0].observable_outcome==text
    assert value==before and len(wire.calls)==1


@pytest.mark.parametrize('text',[
    '完成Claude的安装并成功登录账号','安装Claude并登录账号',
    '编写包含背景的Claude提示词并实际安装Claude',
    '解释Claude安装步骤并实际登录账号',
    '写出提示词并实际登录Claude账号',
])
def test_vague_goals_and_external_completion_cannot_pass_by_adding_a_verb(text):
    wire=Wire(data(text));budget=ModelCallBudget()
    with pytest.raises(ModelOutputValidationError):generate(wire,budget)
    assert (budget.request_count,budget.output_repair_count)==(2,1)


def test_failure_target_reaches_single_repair_as_bounded_untrusted_data_not_exception_text(caplog):
    bad=data('熟练掌握Claude输出格式 PRIVATE_REPAIR_TARGET')
    bad['nodes'][0]['objectives'][0]['assessment_tasks'][0]['requirements']=['按要求完成']
    wire=Wire(lambda p,s:bad if len(wire.calls)==1 else data(REAL_PRACTICE))
    budget=ModelCallBudget()
    with caplog.at_level('INFO',logger='skilltree'):
        plan=generate(wire,budget)
    details=feedback(wire)
    target=details['rejected_candidate_data']['targets'][0]
    assert details['previous_output'] is None
    assert target['field']=='nodes.0.objectives.0.assessment_tasks.0.requirements'
    assert target['learning_target']==bad['nodes'][0]['objectives'][0]['learning_target']
    assert target['assessment_task']['task_form']=='text'
    assert 'untrusted' in details['rejected_candidate_data']['authority']
    assert 'PRIVATE_REPAIR_TARGET' not in details['validation_error']
    assert 'PRIVATE_REPAIR_TARGET' not in caplog.text
    assert 'model_attempt' in caplog.text
    assert (budget.request_count,budget.output_repair_count)==(2,1)
    assert plan.nodes[0].objectives[0].observable_outcome==REAL_PRACTICE


def test_repair_fragment_is_bounded_and_does_not_disclose_whole_plan():
    value=data('PRIVATE_REPAIR_TARGET '*100)
    base=value['nodes'][0]['objectives'][0]
    base['observable_outcome']=base.pop('learning_target')
    base['required_capability_ids']=['text_rubric']
    base['assessment_tasks'][0]['requirements']=['按要求完成']
    for _ in range(4):value['nodes'][0]['objectives'].append(deepcopy(base))
    # Test diagnostic construction directly, not schema length rejection.
    for o in value['nodes'][0]['objectives']:o['evidence_requirement']=['text_excerpt']
    with pytest.raises(PlanningTaskError) as caught:
        validate_objective_tasks(value['nodes'],['text_rubric'])
    error=caught.value
    assert len(error.rejected_targets)<=3
    assert len(json.dumps(error.rejected_targets,ensure_ascii=False))<=1200
    assert 'PRIVATE_REPAIR_TARGET' not in str(error)
    assert 'PRIVATE_REPAIR_TARGET' not in compact_parse_error(error)
    assert 'PRIVATE_REPAIR_TARGET' not in json.dumps(safe_summary(error,'plan',1))


def test_final_failure_code_is_separate_from_first_error_and_no_fragment_is_persisted(guided):
    client,paths,_=guided;view,_=create(client);pid=view['project_id']
    first=data('熟练掌握Claude PRIVATE_REPAIR_TARGET')
    first['nodes'][0]['objectives'][0]['assessment_tasks'][0]['requirements']=['按要求完成']
    final=data('完成Claude的安装并成功登录账号')
    wire=Wire(lambda p,s:first if len(wire.calls)==1 else final)
    with V3Repository(paths) as db:op=db.create_operation(pid,'dd18a3b1-c770-4c9f-a362-f910785e7caf',kind='confirm_profile')['operation_id']
    # Use the actual tracked adapter so repair reservations/first errors persist.
    def callback(tracked,budget):
        profile=case.profile(requested_capabilities=['text_rubric'])
        policy=case.policy(evaluators=[{'evaluator_id':'text_rubric','evaluator_version':'1.0.0'}],allowed_question_types=['text'])
        return case.generate(tracked,selected_profile=profile,selected_catalog=case.catalog(SOURCE),selected_policy=policy,budget=budget)
    with pytest.raises(ModelOutputValidationError):
        guarded_plan(paths,pid,'guided_plan:test',{'fixed':'input'},'written-work-test',ContentModel(wire),
            lambda:run_model_task(paths,pid,op,'guided_plan:test',{'fixed':'input'},LearningPlan,callback,llm=ContentModel(wire)))
    with V3Repository(paths) as db:
        task=dict(db.conn.execute('SELECT * FROM model_tasks WHERE project_id=?',(pid,)).fetchone())
        summary=json.loads(db.conn.execute('SELECT summary_json FROM preparation_diagnostics WHERE project_id=?',(pid,)).fetchone()[0])
    assert task['requests']==2 and task['output_repairs']==1 and task['status']=='invalid'
    assert 'assessment_task_incomplete' in task['repair_json']
    assert summary['code']=='unsupported_assessment_claim' and summary['category']=='content'
    assert summary['field']=='nodes.0.objectives.0.assessment_tasks.0.requirements'
    assert 'PRIVATE_REPAIR_TARGET' not in task['repair_json']
    assert 'Claude' not in json.dumps(summary)


def test_final_safe_summary_filters_uncontrolled_types_paths_and_messages():
    error=PlanningTaskError([
        {'loc':('PRIVATE_KEY',),'type':'observable_task_required','msg':'PRIVATE_DATA'},
        {'loc':('nodes',0,'objectives',0,'observable_outcome'),'type':'PRIVATE_ERROR','msg':'PRIVATE_DATA'},
        {'loc':('nodes',0,'objectives',0,'observable_outcome'),'type':'choice_task_required','msg':'PRIVATE_DATA'},
    ])
    summary=safe_summary(error,'plan',1)
    assert summary['code']=='choice_task_required' and len(summary['errors'])==1
    assert 'PRIVATE_' not in json.dumps(summary)


def test_long_candidate_compaction_preserves_failed_target_and_trusted_input():
    from app.services.llm import RepairContext
    from app.v3.planner import build_planner_messages,PlannerMaterial
    fragment={'authority':'untrusted rejected candidate data','targets':[{
        'field':'nodes.0.objectives.0.observable_outcome','observable_outcome':'PRIVATE_REPAIR_TARGET',
        'capabilities':['text_rubric'],'node_title':'有限目标'}]}
    previous=case.plan();previous['nodes'][0]['description']='very long rejected output '*3000
    catalog=[PlannerMaterial.model_validate(c) for c in case.catalog(SOURCE)]
    messages=build_planner_messages(profile=case.profile(),project_id='project_1',draft_revision=3,
        material_catalog=catalog,policy=case.policy(),
        repair_context=RepairContext(previous_output=previous,error_message='observable_task_required',
                                     rejected_candidate_data=fragment))
    payload=json.loads(messages[-1].content.split('\n')[1])
    assert payload['rejected_candidate_data']==fragment and 'previous_output_omitted' in payload
    assert SOURCE in messages[1].content and sum(len(m.content) for m in messages)<=24000
