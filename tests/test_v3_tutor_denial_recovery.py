"""Replay the reported negated claim and deny exhausted-task retry loops."""
from copy import deepcopy
import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.services.llm import ModelCallBudget
from app.v3.learning_api import create_learning_app
from app.v3.learning_repository import LearningRepository
from app.v3.tutor import has_completion_claim
from tests.test_v3_tutor import FakeModel,generate,profile,reply
from tests.day11_support import (FakeLearningModel,build_exploration_project,build_frozen_project,
                                learning_event,private_quiz,answers_for_quiz)


@pytest.mark.parametrize('text',[
    '你提到“都懂了”，这只是一次自我报告，我不会据此认为你已经通过或完成了任何测评；下面仍是探索讲解。',
    '我不能宣称你已经通过。',
    '这不意味着你已经掌握本单元。',
    '不是你已经通过了测评，而是一次不计分讨论。',
    '我不会说“你已经通过”。',
    'I cannot conclude that you have passed the assessment.',
    "This does not mean you have passed the assessment.",
    "I can't say you have already passed the assessment.",
])
def test_explicit_denial_is_accepted_without_wasting_output_repair(text):
    model=FakeModel(reply(text=text,citations=[],exploration=True));budget=ModelCallBudget()
    result=generate(model,profile=profile(learning_mode='exploration'),mode='exploration',contexts=[],budget=budget)
    assert text in result.text and result.exploration
    assert (budget.request_count,budget.output_repair_count)==(1,0)
    assert len(model.messages)==1 and not has_completion_claim(text)


@pytest.mark.parametrize('text',[
    '你已经通过了测评。',
    '我不会说你已经通过，但本节点已经完成。',
    '我不能说你已经掌握，不过系统已经为你解锁后续节点。',
    '不能提前通过。你已经通过了测评。',
    '我不是不认为你已经通过了测评。',
    '我不能不认为你已经通过了测评。',
    '我并非不能说你已经通过了测评。',
    'I cannot claim you have passed, but you have mastered this unit.',
    'You have passed the assessment; I cannot save this result.',
])
def test_denial_elsewhere_contrast_and_double_negation_cannot_authorize_completion(text):
    model=FakeModel(reply(text=text,citations=[],exploration=True),reply(citations=[],exploration=True))
    budget=ModelCallBudget()
    result=generate(model,profile=profile(learning_mode='exploration'),mode='exploration',contexts=[],budget=budget)
    assert text not in result.text and has_completion_claim(text)
    assert (budget.request_count,budget.output_repair_count)==(2,1)


def client_for(case,tmp_path):
    return TestClient(create_learning_app(case['paths'],llm=case['model'],
        legacy_business_path=tmp_path/'no-legacy.sqlite',legacy_checkpoint_path=tmp_path/'no-cp.sqlite'))


def snapshot(case):
    return {path:path.read_bytes() for path in (case['paths'].learning,case['paths'].checkpoints,
                                               case['paths'].root/'learning-checkpoints.sqlite')}


@pytest.mark.parametrize('failure',['invalid','network'])
def test_exhausted_tutor_has_useful_recovery_but_retry_cannot_write_or_call_again(tmp_path,failure):
    case=build_exploration_project(tmp_path/'v3',direct_profile=True);model=case['model'];client=client_for(case,tmp_path)
    pid=case['project_id'];url=f'/projects/{pid}'
    view=client.post(url+'/begin',json={'request_id':str(uuid4())}).json()
    bad=reply(text='你已经通过了测评。',citations=[],exploration=True)
    model.faults['TutorReply'].extend([bad,bad] if failure=='invalid' else [TimeoutError('offline'),TimeoutError('offline')])
    failed=client.post(url+'/resume',json=learning_event(view,'ask',question='我都懂了')).json()
    assert failed['page_state']=='error' and failed['error_code']=='model_task_exhausted'
    assert failed['failed_task_kind']=='tutor' and 'retry' not in failed['allowed_actions']
    assert set(failed['allowed_actions'])=={'return_to_teaching','rest'}
    assert failed['operation_budget']['used']==2 and not failed['completed_node_ids']
    before=snapshot(case);calls=deepcopy(model.calls)
    restarted=client_for(case,tmp_path)
    for _ in range(3):
        assert restarted.get(url).json()==failed
        assert restarted.post(url+'/retry',json={'request_id':str(uuid4()),'retry_token':failed['retry_token']}).status_code==409
    assert snapshot(case)==before and model.calls==calls
    with LearningRepository(case['paths']) as repo:
        old=dict(repo.conn.execute("SELECT * FROM model_tasks WHERE project_id=? AND status='invalid'",(pid,)).fetchone())
    recovered=restarted.post(url+'/resume',json=learning_event(failed,'return_to_teaching')).json()
    assert recovered['page_state']=='exploring' and recovered['error_code'] is None
    assert recovered['project_id']==pid and not recovered['completed_node_ids'] and recovered['assessment_id'] is None
    with LearningRepository(case['paths']) as repo:
        assert dict(repo.conn.execute('SELECT * FROM model_tasks WHERE project_id=? AND task_key=?',(pid,old['task_key'])).fetchone())==old
        assert repo.conn.execute('SELECT COUNT(*) FROM assessments WHERE project_id=?',(pid,)).fetchone()[0]==0
    assert len(model.calls)==len(calls)+1


def test_transient_technical_failure_keeps_same_task_retry_available(tmp_path):
    model=FakeLearningModel(faults={'TutorReply':[RuntimeError('temporary technical fault')]})
    case=build_exploration_project(tmp_path/'v3',model=model,direct_profile=True);client=client_for(case,tmp_path);pid=case['project_id']
    failed=client.post(f'/projects/{pid}/begin',json={'request_id':str(uuid4())}).json()
    assert failed['error_code'] is None and 'retry' in failed['allowed_actions']
    result=client.post(f'/projects/{pid}/retry',json={'request_id':str(uuid4()),'retry_token':failed['retry_token']}).json()
    assert result['page_state']=='exploring'
    with LearningRepository(case['paths']) as repo:
        tasks=repo.conn.execute('SELECT requests FROM model_tasks WHERE project_id=?',(pid,)).fetchall()
        assert len(tasks)==1 and tasks[0][0]==2


def test_invalid_grade_does_not_gain_more_budget_or_count_a_failed_student_round(tmp_path):
    case=build_frozen_project(tmp_path/'v3',node_count=1);model=case['model'];client=client_for(case,tmp_path);pid=case['project_id']
    view=client.post(f'/projects/{pid}/begin',json={'request_id':str(uuid4())}).json()
    view=client.post(f'/projects/{pid}/resume',json=learning_event(view,'start_quiz')).json()
    model.faults['TextBatchScore'].extend([{},{}])
    quiz=private_quiz(case['paths'],pid,view['assessment_id'])
    failed=client.post(f'/projects/{pid}/resume',json=learning_event(view,'submit_answer',answers=answers_for_quiz(quiz))).json()
    assert failed['error_code']=='model_task_exhausted' and failed['failed_task_kind']=='grade'
    assert 'retry' not in failed['allowed_actions'] and 'replace_assessment' in failed['allowed_actions']
    assert failed['rounds']['effective_rounds']==0 and failed['completed_node_ids']==[]
    with LearningRepository(case['paths']) as repo:
        row=repo.get_assessment(pid,failed['assessment_id'])
        assert row['evaluation_json'] is None and row['diagnosis_json'] is None
