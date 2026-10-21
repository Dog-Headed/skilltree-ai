import json
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

import pytest

from app.v3.learning import LearningService
from app.v3.learning_repository import LearningRepository
from app.v3.repository import BudgetExhaustedError, ConflictError
from tests.day11_support import build_frozen_project, FakeLearningModel, learning_event, answers_for_quiz


def die(case,hook,event,tmp_path):
    target=tmp_path/'command.json';target.write_text(json.dumps(event),encoding='utf-8')
    run=subprocess.run([sys.executable,'-m','tests.day11_process_worker',str(case['paths'].root),case['project_id'],hook,str(target)],
                       cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True,timeout=45)
    assert run.returncode==71,run.stdout+run.stderr


def raw_quiz(case,view):
    with LearningRepository(case['paths']) as repo:return json.loads(repo.get_assessment(case['project_id'],view['assessment_id'])['quiz_json'])


@pytest.mark.parametrize('hook',['before_initialize','tutor_http','quiz_http','quiz_saved','evaluation_saved','completion_saved','finish'])
def test_real_process_death_recovers_same_identity_and_saved_facts(tmp_path,hook):
    case=build_frozen_project(tmp_path/'data');pid=case['project_id']
    service=LearningService(case['paths'],llm=case['model'])
    if hook in ('before_initialize','tutor_http'): event={'request_id':str(uuid4()),'action':'begin_learning'}
    else:
        view=service.start(pid,str(uuid4()))
        if hook in ('evaluation_saved','completion_saved'):
            view=service.resume(pid,learning_event(view,'start_quiz'))
            event=learning_event(view,'submit_answer',answers=answers_for_quiz(raw_quiz(case,view)))
        else:event=learning_event(view,'start_quiz')
    die(case,hook,event,tmp_path)
    model=FakeLearningModel();restarted=LearningService(case['paths'],llm=model)
    before=restarted.read(pid)
    assert before['page_state']=='error' and before['recovery_required']
    with LearningRepository(case['paths']) as repo:
        op_before=repo.get_project(pid)['operation_id']
        assessments_before=[dict(r) for r in repo.conn.execute('SELECT * FROM assessments WHERE project_id=?',(pid,))]
        charged=repo.conn.execute('SELECT SUM(requests) FROM model_tasks WHERE project_id=?',(pid,)).fetchone()[0]
    assert charged>=1 if hook!='before_initialize' else charged is None
    request=str(uuid4())
    after=restarted.retry(pid,retry_token=before['retry_token'],request_id=request)
    assert after['page_state'] in ('learning','quiz'),after
    assert after['project_id']==after['thread_id']==pid and not after['recovery_required']
    with LearningRepository(case['paths']) as repo:
        assert repo.get_project(pid)['operation_id']==op_before
        for old in assessments_before:
            row=repo.get_assessment(pid,old['id'])
            for field in ('snapshot_json','quiz_json','answers_json','evaluation_json','diagnosis_json'):
                if old[field] is not None:assert row[field]==old[field]
        if hook in ('evaluation_saved','completion_saved'):
            assert repo.rounds(pid,'node_1')['effective_rounds']==1
            assert repo.completed(pid)==['node_1']
        if hook=='completion_saved':assert repo.conn.execute('SELECT COUNT(*) FROM learning_transitions WHERE project_id=?',(pid,)).fetchone()[0]==1
    if hook in ('quiz_saved','finish'):assert model.call_counts['AssessmentQuiz']==0
    if hook in ('evaluation_saved','completion_saved'):assert model.call_counts['TextBatchScore']==0
    if hook=='completion_saved':assert model.call_counts['DiagnosisDecision']==0
    calls=len(model.calls)
    assert restarted.retry(pid,retry_token=before['retry_token'],request_id=request)==after
    assert len(model.calls)==calls


def test_reopening_unanswered_quiz_reuses_frozen_identity_without_model(tmp_path):
    c=build_frozen_project(tmp_path);s=LearningService(c['paths'],llm=c['model'])
    v=s.start(c['project_id'],str(uuid4()));v=s.resume(v['project_id'],learning_event(v,'start_quiz'))
    aid=v['assessment_id'];calls=c['model'].call_counts['AssessmentQuiz']
    v=s.resume(v['project_id'],learning_event(v,'return_to_teaching'))
    v=s.resume(v['project_id'],learning_event(v,'start_quiz'))
    assert v['page_state']=='quiz' and v['assessment_id']==aid
    assert c['model'].call_counts['AssessmentQuiz']==calls


def test_explicit_budget_continuation_is_idempotent_and_keeps_assessment(tmp_path):
    c=build_frozen_project(tmp_path);pid=c['project_id'];model=c['model']
    s=LearningService(c['paths'],llm=model);v=s.start(pid,str(uuid4()))
    def exhaust(messages):
        with LearningRepository(c['paths']) as repo:
            with repo.transaction():
                op=repo.get_project(pid)['operation_id']
                repo.conn.execute("UPDATE model_operations SET reserved_requests=12,status='budget_exhausted' WHERE operation_id=?",(op,))
        raise BudgetExhaustedError('Simulated earlier requests in the same operation')
    model.faults['AssessmentQuiz'].append(exhaust)
    v=s.resume(pid,learning_event(v,'start_quiz'))
    assert v['page_state']=='budget_exhausted' and v['operation_budget']=={'used':12,'limit':12}
    aid=v['assessment_id'];token=v['retry_token'];rid=str(uuid4())
    v=s.retry(pid,retry_token=token,request_id=rid,continue_budget=True)
    assert v['page_state']=='quiz' and v['assessment_id']==aid
    assert v['operation_budget']=={'used':13,'limit':24}
    count=len(model.calls)
    assert s.retry(pid,retry_token=token,request_id=rid,continue_budget=True)==v
    assert len(model.calls)==count
    with LearningRepository(c['paths']) as repo:
        task=repo.conn.execute("SELECT requests FROM model_tasks WHERE project_id=? AND task_key=?",(pid,'quiz:'+aid)).fetchone()
        assert task[0]==2
        assert repo.conn.execute('SELECT COUNT(*) FROM model_operations WHERE project_id=? AND parent_operation_id IS NOT NULL',(pid,)).fetchone()[0]==1


def test_bad_grade_never_writes_evaluation_diagnosis_round_or_completion(tmp_path):
    c=build_frozen_project(tmp_path);pid=c['project_id'];s=LearningService(c['paths'],llm=c['model'])
    v=s.start(pid,str(uuid4()));v=s.resume(pid,learning_event(v,'start_quiz'))
    c['model'].faults['TextBatchScore'].extend([{},{}])
    v=s.resume(pid,learning_event(v,'submit_answer',answers=answers_for_quiz(raw_quiz(c,v))))
    assert v['page_state']=='error' and not v['completed_node_ids'] and v['rounds']['effective_rounds']==0
    with LearningRepository(c['paths']) as repo:
        row=repo.get_assessment(pid,v['assessment_id'])
        assert row['evaluation_json'] is None and row['diagnosis_json'] is None
    calls=len(c['model'].calls)
    assert 'retry' not in v['allowed_actions']
    with pytest.raises(ConflictError,match='No retryable unfinished task'):
        s.retry(pid,retry_token=v['retry_token'],request_id=str(uuid4()))
    assert s.read(pid)==v and len(c['model'].calls)==calls
    with LearningRepository(c['paths']) as repo:
        assert repo.conn.execute('SELECT COUNT(*) FROM learning_retries WHERE project_id=?',(pid,)).fetchone()[0]==0
        row=repo.get_assessment(pid,v['assessment_id'])
        assert row['evaluation_json'] is None and row['diagnosis_json'] is None
    # There is an explicit exit from an exhausted logical task without rewriting the answer.
    v=s.resume(pid,learning_event(v,'return_to_teaching'))
    assert v['page_state']=='learning'


def test_diagnosis_technical_failure_does_not_count_student_round(tmp_path):
    c=build_frozen_project(tmp_path);pid=c['project_id'];s=LearningService(c['paths'],llm=c['model'])
    v=s.start(pid,str(uuid4()));v=s.resume(pid,learning_event(v,'start_quiz'))
    c['model'].faults['DiagnosisDecision'].extend([{},{}])
    v=s.resume(pid,learning_event(v,'submit_answer',answers=answers_for_quiz(raw_quiz(c,v))))
    assert v['page_state']=='error' and v['rounds']['effective_rounds']==0 and not v['completed_node_ids']
    with LearningRepository(c['paths']) as repo:
        row=repo.get_assessment(pid,v['assessment_id'])
        assert row['evaluation_json'] and not row['diagnosis_json']
