"""Replay missing required choice coverage; retain DAG, semantics and budgets."""
from copy import deepcopy
import json

import pytest

from app.services.llm import ModelCallBudget, ModelOutputValidationError
from app.v3.planning_contract import assessment_contract, required_capability_coverage
from app.v3.preparation_feedback import guarded_plan, RepeatedPlanFailure, safe_summary
from app.v3.repository import V3Repository
from tests.test_planner_task_contract import proposal, generate, feedback, Wire
from tests.test_goal_first import guided, create, act, GuidedFake

CAPS = ('choice_exact', 'text_rubric')


def text_only():
    return proposal(('text_rubric',), '解释C循环的停止条件')


def complete():
    data = text_only()
    choice = deepcopy(proposal()['nodes'][0])
    choice['title'] = '辨析C编译命令'
    choice['prerequisite_ids'] = []
    data['nodes'].append(choice)
    join = deepcopy(choice)
    join['title'] = '综合C循环判断'
    join['prerequisite_ids'] = ['n1', 'n2']
    data['nodes'].append(join)
    return data


def test_first_missing_choice_is_reported_in_model_slots_and_repaired_once():
    wire = Wire(lambda p,s: text_only() if len(wire.calls)==1 else complete())
    budget = ModelCallBudget()
    result = generate(wire, CAPS, budget)
    diagnostic = json.loads(feedback(wire)['validation_error'].split('：', 1)[1])
    issue = diagnostic['planning_errors'][0]
    assert issue['type'] == 'missing_required_plan_capability'
    assert issue['required'] == list(CAPS) and issue['actual_required'] == ['text_rubric']
    assert issue['missing'] == ['choice_exact']
    assert 'nodes.*.objectives.*.required_capability_ids' == issue['field']
    assert (budget.request_count, budget.output_repair_count, budget.network_retry_count) == (2,1,0)
    assert result.nodes[2].prerequisite_ids == ['n1','n2']
    assert result.nodes[0].objectives[0].observable_outcome == text_only()['nodes'][0]['objectives'][0]['observable_outcome']
    assert all(o.source_chunk_ids == ['chunk_1'] for n in result.nodes for o in n.objectives)
    assert wire.calls[0][1]['assessment_contract']['required_plan_evaluation_capabilities'] == list(CAPS)
    assert not required_capability_coverage([n.model_dump() for n in result.nodes], CAPS)['missing']


def test_optional_choice_does_not_cover_required_and_terminal_summary_is_safe():
    bad = complete()
    for node in bad['nodes'][1:]:
        node['objectives'][0]['required'] = False
    wire = Wire(bad)
    budget = ModelCallBudget()
    with pytest.raises(ModelOutputValidationError) as caught:
        generate(wire, CAPS, budget)
    assert (budget.request_count, budget.output_repair_count) == (2,1)
    summary = safe_summary(caught.value, 'plan', 12)
    assert summary['missing'] == ['choice_exact']
    assert summary['actual_required'] == ['text_rubric']
    assert 'observable_outcome' not in json.dumps(summary) and 'C循环' not in json.dumps(summary)


def test_adding_choice_tag_without_choice_task_is_rejected():
    tagged = text_only()
    tagged['nodes'][0]['objectives'][0]['required_capability_ids'] = list(CAPS)
    wire = Wire(tagged)
    with pytest.raises(ModelOutputValidationError):
        generate(wire, CAPS)
    assert 'choice_task_required' in feedback(wire)['validation_error']


def test_no_per_node_all_capabilities_requirement_or_profile_mutation():
    data = complete(); original = deepcopy(data)
    result = generate(Wire(data), CAPS)
    assert data == original and len(result.nodes) == 3
    assert result.nodes[0].objectives[0].required_capability_ids == ['text_rubric']
    assert result.nodes[1].objectives[0].required_capability_ids == ['choice_exact']
    assert assessment_contract(CAPS)['required_plan_evaluation_capabilities'] == list(CAPS)


def test_identical_terminal_failures_stop_before_new_paid_task_and_version_unlocks(guided, monkeypatch):
    client, paths, model = guided
    # Retain real Graph/repository, replacing only the model's scope selection.
    original = model._invoke
    def invoke(schema, messages):
        result = original(schema, messages)
        if schema == 'LearningPreparation':
            result['evaluation_capabilities'] = list(CAPS)
        return result
    monkeypatch.setattr(model, '_invoke', invoke)
    view,_ = create(client)
    for _ in range(2):
        view = act(client, view, 'confirm_profile')
        assert view['page_state'] == 'profile_review' and not view['plan']
        assert '选择题' in view['preparation_notice']
    before = deepcopy(model.call_counts)
    with V3Repository(paths) as repo:
        consumed = repo.conn.execute('SELECT SUM(requests) FROM model_tasks').fetchone()[0]
        rows = repo.conn.execute('SELECT summary_json FROM preparation_diagnostics').fetchall()
        assert len(rows) == 2 and all(json.loads(r[0])['missing'] == ['choice_exact'] for r in rows)
    view = act(client, view, 'confirm_profile')
    assert '停止重复调用' in view['preparation_notice'] and model.call_counts == before
    assert 'update_profile' in view['allowed_actions'] and 'import_material' in view['allowed_actions']
    with V3Repository(paths) as repo:
        assert repo.conn.execute('SELECT SUM(requests) FROM model_tasks').fetchone()[0] == consumed
    from app.v3 import planner
    monkeypatch.setattr(planner, 'PLANNER_PROMPT_VERSION', planner.PLANNER_PROMPT_VERSION+'-new')
    view = act(client, view, 'confirm_profile')
    assert model.call_counts['LearningPlan'] == before['LearningPlan']+2
    assert model.call_counts['LearningPreparation'] == before['LearningPreparation'] == 1
    assert model.call_counts['StudyNotes'] == before['StudyNotes'] == 1


def test_unsafe_exception_strings_are_never_saved_in_safe_summary():
    error = ModelOutputValidationError('PRIVATE_ANSWER API_KEY user private source')
    assert safe_summary(error, 'plan', 1) == {'stage':'plan','code':'model_output_invalid','elapsed_ms':1}


def test_retry_guard_allows_changed_input_or_model_and_success_breaks_failure_run(guided):
    client,paths,_ = guided
    view,_ = create(client); pid=view['project_id']
    class Model:
        model_name='model-a'
    from app.v3.planning_contract import PlanningTaskError, coverage_issue
    cause=PlanningTaskError([coverage_issue(text_only()['nodes'], CAPS)])
    def fail():
        raise ModelOutputValidationError('wrapped') from cause
    def run(key, inputs=None, version='v1'):
        return guarded_plan(paths,pid,key,inputs or {'profile':'same'},version,Model(),fail)
    for key in ('a','b'):
        with pytest.raises(ModelOutputValidationError):run(key)
    with pytest.raises(RepeatedPlanFailure):run('c')
    with pytest.raises(ModelOutputValidationError):run('d', {'profile':'changed'})
    Model.model_name='model-b'
    with pytest.raises(ModelOutputValidationError):run('e')
    assert guarded_plan(paths,pid,'ok',{'profile':'same'},'v1',Model(),lambda:'ok')=='ok'
    with pytest.raises(ModelOutputValidationError) as caught:run('after-success')
    assert not isinstance(caught.value, RepeatedPlanFailure)
