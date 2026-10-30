"""Replay the real C failure without weakening evidence or execution limits."""
from copy import deepcopy
import json

import pytest

from app.services.llm import ModelCallBudget, ModelOutputValidationError
from app.services.llm import compact_parse_error
from app.v3.model_content import ContentModel
from app.v3.planning_contract import assessment_contract, EVIDENCE_BY_CAPABILITY
from app.v3.onboarding import infer_scope
from app.v3.notes_outline import outline_request
from tests import test_v3_planner as case
from tests.test_v3_model_content import Wire
from tests.test_v3_preparation_content import Queue, scope_result, notes_payload


MATERIAL = 'C代码使用变量和循环。gcc命令编译C程序。printf打印Hello World。循环条件控制执行次数，示例循环执行3次。'


@pytest.mark.parametrize('token', [r'\0', r'\d', r'\('])
def test_json_escape_feedback_locates_token_without_exposing_completion(token):
    raw = '{"private":"DO_NOT_LEAK","outcome":"' + token + '"}'
    with pytest.raises(json.JSONDecodeError) as caught:
        json.loads(raw)
    detail = json.loads(compact_parse_error(caught.value))
    assert detail['invalid_escape'] == token
    assert r'"\\0"' in detail['instruction']
    assert 'DO_NOT_LEAK' not in json.dumps(detail) and 'private' not in json.dumps(detail)
    # Diagnostics never make an invalid model completion acceptable.
    with pytest.raises(json.JSONDecodeError):
        json.loads(raw)


def proposal(caps=('choice_exact',), outcome='从给定选项中选出C程序的正确编译顺序'):
    nodes = deepcopy(case.plan()['nodes'])
    goal = nodes[0]['objectives'][0]
    goal.update(required_capability_ids=list(caps), observable_outcome=outcome, source_chunk_ids=['s1'])
    goal.pop('evidence_requirement')
    for node in nodes:
        node.pop('node_id')
        for item in node['objectives']: item.pop('objective_id')
    return {'nodes': nodes}


def generate(wire, caps=('choice_exact',), budget=None):
    policy = case.policy(evaluators=[{'evaluator_id': cap, 'evaluator_version': '1.0.0'} for cap in caps],
        allowed_question_types=[{'choice_exact':'single_choice','numeric_scalar':'numeric_scalar','text_rubric':'text'}[cap] for cap in caps])
    return case.generate(ContentModel(wire), selected_profile=case.profile(requested_capabilities=list(caps)),
        selected_catalog=case.catalog(MATERIAL), selected_policy=policy, budget=budget)


def feedback(wire):
    return wire.calls[1][1]['supplemental_data'][0]


@pytest.mark.parametrize('outcome', [
    '在命令行执行gcc -o hello hello.c && ./hello并观察到Hello World输出',
    '在终端执行gcc -o hello hello.c && ./hello并输出Hello World',
    '完成在终端执行gcc -o hello hello.c并运行程序的任务',
    '在终端执行gcc编译C程序，再解释输出',
])
def test_real_execution_goal_gets_precise_slot_feedback_and_one_successful_repair(outcome):
    bad, good = proposal(outcome=outcome), proposal()
    wire = Wire(lambda p,s: bad if len(wire.calls)==1 else good)
    budget = ModelCallBudget()
    result = generate(wire, budget=budget)
    error = feedback(wire)['validation_error']
    assert 'nodes.0.objectives.0.observable_outcome' in error
    assert 'unverifiable_external_operation' in error and '当前不能验证' in error
    assert '只有笼统' not in error and feedback(wire)['previous_output'] is None
    assert (budget.request_count, budget.output_repair_count) == (2, 1)
    assert result.nodes[0].objectives[0].observable_outcome == good['nodes'][0]['objectives'][0]['observable_outcome']
    assert result.nodes[0].objectives[0].evidence_requirement == ['choice']
    assert result.nodes[0].objectives[0].source_chunk_ids == ['chunk_1']


def test_all_invalid_objectives_are_reported_together_before_fixed_metadata_is_bound():
    bad = proposal(outcome='熟练掌握C编译过程')
    second = deepcopy(bad['nodes'][0]['objectives'][0])
    second['observable_outcome']='深入理解C循环规则'
    bad['nodes'][0]['objectives'].append(second)
    wire = Wire(lambda p,s: bad if len(wire.calls)==1 else proposal())
    generate(wire)
    error = feedback(wire)['validation_error']
    assert all(f'nodes.0.objectives.{i}.observable_outcome' in error for i in (0,1))
    assert 'observable_task_required' in error


@pytest.mark.parametrize('caps', [
    ('choice_exact',), ('numeric_scalar',), ('text_rubric',),
    ('choice_exact','text_rubric'), ('numeric_scalar','text_rubric'),
    ('choice_exact','numeric_scalar','text_rubric'),
])
def test_program_derives_evidence_exactly_from_registered_selected_evaluators(caps):
    wire=Wire(proposal(caps, '给定C循环代码，计算执行次数并解释或选出正确结果'))
    result=generate(wire,caps)
    assert set(result.nodes[0].objectives[0].evidence_requirement)=={EVIDENCE_BY_CAPABILITY[c] for c in caps}
    schema=wire.calls[0][0].model_json_schema()
    assert 'evidence_requirement' not in json.dumps(schema)
    assert set(wire.calls[0][1]['assessment_contract']['task_forms'])==set(caps)
    assert len(wire.calls)==1


@pytest.mark.parametrize('outcome', [
    '从选项中选出在终端执行gcc的正确命令',
    '解释在终端执行gcc命令时各个参数的作用',
    '给定在终端执行gcc得到的错误信息，解释失败原因',
    '给定在终端执行gcc的错误信息，预测C代码需要修正的部分',
    '编写包含printf的C代码',
    '补全C循环代码',
])
def test_valid_text_about_commands_or_text_code_artifacts_are_not_banned(outcome):
    result=generate(Wire(proposal(('text_rubric',),outcome)),('text_rubric',))
    assert result.nodes[0].objectives[0].observable_outcome==outcome


def test_writing_code_does_not_grant_permission_to_certify_external_execution():
    value=proposal(('text_rubric',),'编写C代码并在终端运行程序')
    wire=Wire(value);budget=ModelCallBudget()
    with pytest.raises(ModelOutputValidationError):generate(wire,('text_rubric',),budget)
    assert (budget.request_count,budget.output_repair_count)==(2,1)
    assert 'unverifiable_external_operation' in feedback(wire)['validation_error']


def test_late_budget_repair_projects_previous_output_back_to_the_same_model_contract():
    bad=proposal();bad['nodes'][0]['estimated_minutes']=121
    wire=Wire(lambda p,s:bad if len(wire.calls)==1 else proposal())
    generate(wire)
    previous=feedback(wire)['previous_output']
    assert previous['nodes'][0]['estimated_minutes']==121
    goal=previous['nodes'][0]['objectives'][0]
    assert 'evidence_requirement' not in goal and goal['source_chunk_ids']==['s1']
    assert not {'project_id','draft_revision','plan_version'} & previous.keys()
    assert 'node_id' not in previous['nodes'][0] and 'objective_id' not in goal


@pytest.mark.parametrize('outcome', ['手算C循环的执行次数','推演C表达式的数值结果','预测C循环执行次数','求出C变量最终值'])
def test_numeric_code_reasoning_is_observable_without_certifying_execution(outcome):
    assert generate(Wire(proposal(('numeric_scalar',),outcome)),('numeric_scalar',)).nodes[0].objectives[0].observable_outcome==outcome


@pytest.mark.parametrize('field', ['node_id','objective_id'])
def test_model_cannot_select_program_owned_graph_identities(field):
    value=proposal()
    target=value['nodes'][0] if field=='node_id' else value['nodes'][0]['objectives'][0]
    target[field]='chosen_by_model'
    with pytest.raises(ModelOutputValidationError):generate(Wire(value))


def branching_proposal():
    value=proposal()
    first=value['nodes'][0]
    value['nodes']=[deepcopy(first) for _ in range(3)]
    for index,node in enumerate(value['nodes']):
        node['estimated_minutes']=20
        node['prerequisite_ids']=[] if index==0 else ['n1']
    return value


def test_program_owned_ids_preserve_model_selected_branching_dependencies():
    result=generate(Wire(branching_proposal()))
    assert [n.node_id for n in result.nodes]==['n1','n2','n3']
    assert [n.objectives[0].objective_id for n in result.nodes]==['o1','o2','o3']
    assert [n.prerequisite_ids for n in result.nodes]==[[],['n1'],['n1']]


@pytest.mark.parametrize('prerequisites', [['n1'],['n9']])
def test_program_id_binding_does_not_hide_self_dependencies_or_unknown_nodes(prerequisites):
    value=proposal();value['nodes'][0]['prerequisite_ids']=prerequisites
    with pytest.raises(ModelOutputValidationError):generate(Wire(value))


def test_program_id_binding_does_not_remove_cycles():
    value=branching_proposal()
    value['nodes'][1]['prerequisite_ids']=['n3'];value['nodes'][2]['prerequisite_ids']=['n2']
    with pytest.raises(ModelOutputValidationError):generate(Wire(value))


@pytest.mark.parametrize('mutation', ['forced_evidence','unrequested_capability'])
def test_model_cannot_override_program_evidence_or_request_new_tools(mutation):
    value=proposal();goal=value['nodes'][0]['objectives'][0]
    if mutation=='forced_evidence':goal['evidence_requirement']=['text_excerpt']
    else:goal['required_capability_ids']=['code_execution']
    wire=Wire(value);budget=ModelCallBudget()
    with pytest.raises(ModelOutputValidationError):generate(wire,budget=budget)
    assert (budget.request_count,budget.output_repair_count)==(2,1)


def test_scope_and_notes_receive_the_same_trusted_assessment_boundary_without_changing_scope():
    original={'intent':{},'user_material_catalog':[],'available_evaluators':['text_rubric']}
    value=scope_result();value['evaluation_capabilities']=['text_rubric'];wire=Queue(value)
    before=deepcopy(original)
    infer_scope(wire,ModelCallBudget(),original,generation_mode='content-v1')
    payload=json.loads(wire.messages[0][1].content)
    assert payload['assessment_contract']==assessment_contract(['text_rubric'])
    assert original==before
    notes=notes_payload();notes['profile']['requested_capabilities']=['text_rubric']
    data,headings=outline_request(notes)
    assert data['assessment_contract']==payload['assessment_contract'] and len(headings)==2


def test_scope_cannot_choose_an_evaluator_outside_this_request():
    bad=scope_result();good=deepcopy(bad)
    bad['evaluation_capabilities']=['numeric_scalar'];good['evaluation_capabilities']=['text_rubric']
    wire=Queue(bad,good);budget=ModelCallBudget()
    result=infer_scope(wire,budget,{'intent':{},'user_material_catalog':[],'available_evaluators':['text_rubric']},generation_mode='content-v1')
    assert result.evaluation_capabilities==['text_rubric'] and budget.output_repair_count==1
    assert 'evaluation_capabilities' in wire.messages[1][-1].content
