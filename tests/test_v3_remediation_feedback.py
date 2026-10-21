from copy import deepcopy
from hashlib import sha256
import json
from uuid import uuid4

import pytest

from app.v3.learning import LearningService
from app.v3.learning_repository import LearningRepository
from app.v3.repository import ConflictError,encode
from tests.day11_support import (FakeLearningModel,build_frozen_project,learning_event,private_quiz,answers_for_quiz,_payload)


class CaptureModel(FakeLearningModel):
    def __init__(self,**kwargs):
        super().__init__(**kwargs);self.tutor_inputs=[];self.fail_remediation=False
    def _invoke(self,schema,messages):
        if schema=='TutorReply':
            value=_payload(messages);self.tutor_inputs.append(deepcopy(value))
            if self.fail_remediation and value['mode']=='remediate':
                self.fail_remediation=False
                raise RuntimeError('Tutor interrupted after the feedback input was prepared')
        result=super()._invoke(schema,messages)
        if schema=='TextBatchScore' and result.get('questions'):
            result['questions'][0]['feedback']='本轮公开反馈：请重新解释实际作答中的混淆。'
        if schema=='DiagnosisDecision':result['reason']='本轮诊断原因：需要针对当前错误解释进行补弱。'
        return result


def start_case(tmp_path,**kwargs):
    model=CaptureModel(grade_ratio=0.2)
    case=build_frozen_project(tmp_path,model=model,**kwargs)
    service=LearningService(case['paths'],llm=model)
    view=service.start(case['project_id'],str(uuid4()))
    return case,model,service,view


def answer_wrong(case,service,view,text):
    view=service.resume(view['project_id'],learning_event(view,'start_quiz'))
    quiz=private_quiz(case['paths'],view['project_id'],view['assessment_id'])
    answers=answers_for_quiz(quiz)
    for question in quiz['questions']:
        if question['question_type']=='text':answers[question['question_id']]=text
    return service.resume(view['project_id'],learning_event(view,'submit_answer',answers=answers))


def test_two_errors_in_same_node_get_distinct_current_answer_objective_and_reason(tmp_path):
    case,model,service,view=start_case(tmp_path,node_count=1)
    assert model.tutor_inputs[-1]['remediation_feedback'] is None
    for text in ['错误A：赋值就是比较 UNIQUE_ASSIGNMENT','错误B：列表元素永远是下标 UNIQUE_INDEX']:
        view=answer_wrong(case,service,view,text)
        assert view['page_state']=='learning' and view['mode']=='remediate',view
        data=model.tutor_inputs[-1];feedback=data['remediation_feedback']
        assert feedback['assessment_id']==view['assessment_id'] and feedback['project_id']==view['project_id']
        assert feedback['questions'][0]['student_answer_excerpt']==text
        assert feedback['questions'][0]['feedback'].startswith('本轮公开反馈')
        assert feedback['diagnosis_reason'].startswith('本轮诊断原因')
        assert feedback['failed_objectives'][0]['score_ratio']==0.2
    assert 'UNIQUE_ASSIGNMENT' not in json.dumps(model.tutor_inputs[-1]['remediation_feedback'],ensure_ascii=False)


def test_restart_uses_same_frozen_feedback_and_includes_it_in_task_fingerprint(tmp_path):
    case,model,service,view=start_case(tmp_path,node_count=1)
    captured={};run=service._task
    def task(pid,key,data,*args,**kwargs):
        if key.startswith('tutor:') and data.get('remediation_feedback'):captured.update(deepcopy(data))
        return run(pid,key,data,*args,**kwargs)
    service._task=task;model.fail_remediation=True
    failed=answer_wrong(case,service,view,'持久化错答 UNIQUE_RESTART_ERROR')
    assert failed['page_state']=='error'
    with LearningRepository(case['paths']) as repo:
        session=repo.session(view['project_id'])
        row=repo.conn.execute('SELECT * FROM model_tasks WHERE project_id=? AND task_key=?',
                             (view['project_id'],'tutor:'+session['tutor_request_id'])).fetchone()
        fingerprint=row['input_hash'];assert row['requests']==1
    assert fingerprint==sha256(encode(captured).encode()).hexdigest()
    without={k:v for k,v in captured.items() if k!='remediation_feedback'}
    assert fingerprint!=sha256(encode(without).encode()).hexdigest()
    replacement=CaptureModel();restarted=LearningService(case['paths'],llm=replacement)
    fixed=restarted.retry(view['project_id'],retry_token=failed['retry_token'],request_id=str(uuid4()))
    assert fixed['page_state']=='learning'
    assert replacement.tutor_inputs[-1]['remediation_feedback']==model.tutor_inputs[-1]['remediation_feedback']
    assert replacement.call_counts['TextBatchScore']==replacement.call_counts['DiagnosisDecision']==0


def test_return_to_normal_teaching_does_not_reuse_old_assessment_feedback(tmp_path):
    case,model,service,view=start_case(tmp_path,node_count=1)
    view=answer_wrong(case,service,view,'旧错误 SHOULD_NOT_REAPPEAR')
    view=service.resume(view['project_id'],learning_event(view,'start_quiz'))
    view=service.resume(view['project_id'],learning_event(view,'return_to_teaching'))
    assert view['page_state']=='learning' and view['mode']=='normal'
    assert model.tutor_inputs[-1]['remediation_feedback'] is None
    assert 'SHOULD_NOT_REAPPEAR' not in json.dumps(model.tutor_inputs[-1],ensure_ascii=False)


def test_prerequisite_review_receives_current_node_error_and_review_target(tmp_path):
    case,model,service,view=start_case(tmp_path,node_count=2)
    model.grade_ratio=1.0
    view=answer_wrong(case,service,view,'完整正确解释，Fake评分固定通过。')
    assert view['current_node_id']=='node_2'
    model.grade_ratio=0.2
    original=model._invoke
    def review(schema,messages):
        result=original(schema,messages)
        if schema=='DiagnosisDecision':result.update(action='revisit_prerequisite',review_node_id='node_1',reason='先修变量概念混淆，需要回顾。')
        return result
    model._invoke=review
    view=answer_wrong(case,service,view,'先修错误 UNIQUE_PREREQUISITE')
    assert view['page_state']=='learning' and view['mode']=='review',view
    data=model.tutor_inputs[-1]
    assert data['node']['node_id']=='node_1'
    assert data['remediation_feedback']['node_id']=='node_2'
    assert data['remediation_feedback']['review_node_id']=='node_1'
    assert 'UNIQUE_PREREQUISITE' in json.dumps(data['remediation_feedback'],ensure_ascii=False)


def tutor_reply(messages,text):
    data=_payload(messages)
    citations={tuple(c[k] for k in ('source_id','source_version','chunk_id')):c
        for context in data['teaching_contexts'] for c in context['public_citations']}
    return {'text':text,'exploration':False,'citations':[{k:v[k] for k in ('source_id','source_version','chunk_id')} for v in citations.values()]}


def test_private_standards_are_filtered_from_input_and_echo_is_repaired_before_publication(tmp_path):
    case,model,service,view=start_case(tmp_path,node_count=1)
    secret_answer='PRIVATE_ANSWER_SENTINEL_6017';secret_rubric='PRIVATE_RUBRIC_SENTINEL_3892'
    def quiz(messages):
        value=model._quiz(_payload(messages))
        value['questions'][0]['answer_key']=secret_answer
        value['questions'][0]['rubric'][0]['description']=secret_rubric
        return value
    model.faults['AssessmentQuiz'].append(quiz)
    original=model._invoke
    def leak(schema,messages):
        result=original(schema,messages)
        if schema=='TextBatchScore':result['questions'][0]['feedback']='参考答案：'+secret_answer
        if schema=='DiagnosisDecision':result['reason']='私有量规：'+secret_rubric
        return result
    model._invoke=leak
    model.faults['TutorReply'].extend([lambda msgs:tutor_reply(msgs,secret_answer),lambda msgs:tutor_reply(msgs,'请围绕你写出的错误解释重新比较概念。')])
    view=answer_wrong(case,service,view,'学生的独立错误 UNIQUE_STUDENT_ERROR')
    assert view['page_state']=='learning',view
    feedback=model.tutor_inputs[-1]['remediation_feedback']
    raw=json.dumps(feedback,ensure_ascii=False)
    assert 'UNIQUE_STUDENT_ERROR' in raw and secret_answer not in raw and secret_rubric not in raw
    for private in ('answer_key','rubric','criterion_results','grading_contexts','source_manifest'):
        assert '"'+private+'"' not in raw
    assert secret_answer not in json.dumps(view,ensure_ascii=False) and secret_rubric not in json.dumps(view,ensure_ascii=False)
    with LearningRepository(case['paths']) as repo:
        row=repo.conn.execute('SELECT requests,output_repairs FROM model_tasks WHERE project_id=? AND task_key LIKE ?',
            (view['project_id'],'tutor:after_%')).fetchone()
        assert tuple(row)==(2,1)
