from copy import deepcopy
import json
from pathlib import Path

import pytest

import day13_evaluate as runner
from app.services.llm import ModelCallBudget, ModelOutputValidationError
from app.v3.assessment import validate_quiz
from app.v3.quality_review import review_assessment


def prepared(subject='python',index=1):
    case=runner.read_json(runner.ROOT/f'evals/v3/{subject}/cases/{subject}_debug_{index:02}.json')
    standard=runner.read_json(runner.ROOT/'evals/v3/day13/development_standards.json')['cases'][case['case_id']]
    return case,standard,runner.adapt_case(case,subject=subject,project_id='evaluation_project',standards=standard)


def test_revalidation_preserves_independent_origin_and_rejects_changed_references(tmp_path):
    selected = runner.select_cases('holdout', runner.SUBJECTS, runner.ROOT/'evals/v3/day13/final_suite')
    standard = runner.ROOT/'evals/v3/day13/final_standards.json'
    original = {'metadata': {'split': 'holdout', 'mode': 'real', 'validation_role': 'unseen_final_holdout',
        'input_cases': {p.relative_to(runner.ROOT).as_posix(): runner.digest(p) for p in selected},
        'standards_sha256': runner.digest(standard)},
        'by_subject': {s: {'automated_gates_passed': True,
            'semantic_citation_review': 'approved_independent_review'} for s in runner.SUBJECTS}}
    report = tmp_path/'original.json'
    report.write_text(json.dumps(original), encoding='utf8')
    provenance = runner.revalidation_provenance(report, selected, standard)
    assert not provenance['first_unseen_execution']
    assert provenance['previous_report_sha256'] == runner.digest(report)
    original['metadata']['standards_sha256'] = 'changed'
    report.write_text(json.dumps(original), encoding='utf8')
    with pytest.raises(ValueError, match='same approved independent cases'):
        runner.revalidation_provenance(report, selected, standard)
    original['metadata']['standards_sha256'] = runner.digest(standard)
    original['metadata']['validation_role'] = 'exposed_validation'
    report.write_text(json.dumps(original), encoding='utf8')
    with pytest.raises(ValueError, match='same approved independent cases'):
        runner.revalidation_provenance(report, selected, standard)


def test_all_development_cases_translate_to_available_versions_without_touching_frozen_bytes():
    for subject in runner.SUBJECTS:
        for index in range(1,9):
            case,standard,adapted=prepared(subject,index)
            assert {q.evaluator_version for q in adapted['quiz'].questions}=={'1.0.0'}
            validate_quiz(adapted['quiz'],node=adapted['node'],policy=adapted['policy'],contexts=adapted['contexts'])
            runner.assert_no_labels({'quiz':adapted['quiz'].model_dump(),'contexts':adapted['contexts']})
            assert case['human_expectation']['review_status']=='pending_user_review'
            assert standard['review_status']=='approved_by_user'


@pytest.mark.parametrize('label',sorted(runner.BLOCKED_MODEL_FIELDS))
def test_gold_label_rejected_at_any_nested_boundary(label):
    with pytest.raises(ValueError,match='Expected label'):
        runner.assert_no_labels({'outer':[{'nested':{label:'not for the model'}}]})


class ReviewFake:
    def __init__(self,answers):self.answers=list(answers);self.calls=0;self.prompts=[]
    def with_structured_output(self,*args,**kwargs):return self
    def invoke(self,messages):
        self.calls+=1;self.prompts.append(messages)
        return self.answers.pop(0)


def verdict(adapted,*,quote=None):
    block=next(iter(adapted['contexts'].values()))['blocks'][0]
    return {'project_id':adapted['quiz'].project_id,'assessment_id':adapted['quiz'].assessment_id,
        'verdict':'invalid_item','reason':'题面未限定输出依据，需重新出题。','findings':[{
            'question_id':'q1','source_chunk_id':block['citation']['chunk_id'],
            'source_quote':quote or block['content'][:25],'reason':'需要完整题面。'}]}


def test_quality_review_repairs_fabricated_source_quote_once_and_uses_no_gold_labels():
    case,standard,adapted=prepared(index=6)
    model=ReviewFake([verdict(adapted,quote='This is not a source quote.'),verdict(adapted)])
    budget=ModelCallBudget()
    result=review_assessment(quiz=adapted['quiz'],node=adapted['node'],policy=adapted['policy'],
        contexts=adapted['contexts'],answers=case['student_answers'],llm=model,budget=budget)
    assert result.verdict=='invalid_item' and model.calls==2
    assert (budget.request_count,budget.output_repair_count)==(2,1)
    assert 'human_expectation' not in str(model.prompts)


def test_continuous_forged_review_stops_without_creating_an_accepted_result():
    case,standard,adapted=prepared(index=5)
    model=ReviewFake([verdict(adapted,quote='fabricated')]*2)
    with pytest.raises(ModelOutputValidationError):
        review_assessment(quiz=adapted['quiz'],node=adapted['node'],policy=adapted['policy'],
            contexts=adapted['contexts'],answers=case['student_answers'],llm=model)
    assert model.calls==2


def test_quality_review_runtime_capability_comes_from_code_not_historical_material():
    case,_,adapted=prepared(index=6)
    model=ReviewFake([verdict(adapted)])
    review_assessment(quiz=adapted['quiz'],node=adapted['node'],policy=adapted['policy'],
        contexts=adapted['contexts'],answers=case['student_answers'],llm=model)
    payload=json.loads(model.prompts[0][1].content)
    assert payload['trusted_runtime_evaluators']==[
        {'evaluator_id':'text_rubric','evaluator_version':'1.0.0','available':True}]
    # Preserve the frozen material, while keeping runtime facts out of its control.
    assert '尚未实装' in json.dumps(payload['bound_material'],ensure_ascii=False)


def test_candidate_audit_does_not_receive_the_fixture_answer_revealing_error_annotation():
    case,_,adapted=prepared(index=5)
    candidate=runner._candidate(case,adapted)
    assert '错误评分' not in candidate.question_results[0].feedback
    assert candidate.question_results[0].score==10
    runner.assert_no_labels(candidate.model_dump())


def test_student_omission_is_graded_and_error_candidate_is_a_separate_task():
    for subject in runner.SUBJECTS:
        _,omission,_=prepared(subject,4)
        _,audit,_=prepared(subject,5)
        assert omission['grading_status']=='graded' and not omission['passed']
        assert audit['task_type']=='candidate_score_audit'


def test_fake_or_failed_development_cannot_freeze_a_candidate(tmp_path):
    report=tmp_path/'report.json'
    runner.write_json(report,{'metadata':{'split':'debug','mode':'fake'},'by_subject':{}})
    with pytest.raises(ValueError,match='real development'):
        runner.freeze_candidate(report,tmp_path/'freeze.json')
    runner.write_json(report,{'metadata':{'split':'debug','mode':'real'},'by_subject':{
        'python':{'automated_gates_passed':True,'semantic_citation_review':'pending_independent_review'}}})
    with pytest.raises(ValueError,match='Independent semantic review'):
        runner.freeze_candidate(report,tmp_path/'freeze.json')


def test_correct_rejection_is_not_hidden_by_zero_false_advances():
    case,standard,_=prepared()
    result={'passed':False,'effective_action':'assessment_review','grading_status':'needs_review'}
    metrics=runner.metrics_for(case,standard,result)
    assert not metrics['false_advance'] and metrics['false_reject_complete_correct'] and metrics['unexpected_refusal']


def test_history_preserves_question_needed_to_interpret_a_short_answer():
    from app.v3.diagnosis import _historical_entries
    case,standard,adapted=prepared('mathematics',8)
    history=runner.adapt_history(case,adapted,standard)
    entries=_historical_entries(history,quiz=adapted['quiz'],node=adapted['node'])
    assert entries[0]['evidence'][0]['quote']==case['available_history'][0]['student_answer']
    assert case['available_history'][0]['question'] in entries[0]['question_results'][0]['feedback']
    assert 'human_expectation' not in json.dumps(entries)


def test_original_item_audit_binds_the_actual_validity_rule():
    for subject in runner.SUBJECTS:
        _,_,adapted=prepared(subject,6)
        blocks=next(iter(adapted['contexts'].values()))['blocks']
        assert any('quality' in b['content'].splitlines()[0] for b in blocks)


def test_history_requires_observed_scores_and_preserves_a_correct_control():
    case,standard,adapted=prepared('python',8)
    with pytest.raises(ValueError,match='explicit reviewed input'):
        runner.adapt_history(case,adapted,{'input_revision':{}})
    observation=standard['input_revision']['history'][case['available_history'][0]['assessment_id']]
    observation.update(score=10.0,feedback='预置的历史正确作答记录')
    rows=runner.adapt_history(case,adapted,standard)
    actual=rows[0]['evaluation']['question_results'][0]
    assert actual['score']==10 and '错答' not in actual['feedback']
    assert case['available_history'][0]['question'] in actual['feedback']


@pytest.mark.parametrize('score',[float('nan'),float('inf'),-1,11,True])
def test_history_does_not_accept_invalid_scores(score):
    case,standard,adapted=prepared('python',8)
    standard['input_revision']['history'][case['available_history'][0]['assessment_id']]['score']=score
    with pytest.raises(ValueError,match='Invalid historical score'):
        runner.adapt_history(case,adapted,standard)


def test_only_actual_attachment_content_crosses_model_boundary():
    case,standard,_=prepared()
    case['context_anomalies']=[{'attachment_id':'attached_1','visibility':'teaching','content':'range包含stop。',
        'type':'source_conflict','trust_note':'假材料','conflicts_with':{'section_id':'gold'}}]
    adapted=runner.adapt_case(case,subject='python',project_id='p',standards=standard)
    attachments=next(iter(adapted['contexts'].values()))['untrusted_supplement']
    assert attachments==[{'attachment_id':'attached_1','visibility':'teaching','content':'range包含stop。'}]


@pytest.mark.parametrize('revision',[
    {'unimplemented_field':{}}, {'questions':{'ghost':{}}},
    {'questions':{'q1':{'rubric':[]}}}, {'questions':{'q1':{'criterion_descriptions':{'ghost':'x'}}}},
    {'objectives':{'ghost':{}}}, {'objectives':{'o1':{'required':False}}},
])
def test_unsupported_revisions_are_not_silently_ignored(revision):
    case,standard,_=prepared()
    standard['input_revision']=revision
    with pytest.raises(ValueError):runner.adapt_case(case,subject='python',project_id='p',standards=standard)


def test_separate_case_suite_and_preflight_stop_before_models(tmp_path):
    root=runner.ROOT/'evals/v3/day13/nonexistent_independent_suite'
    assert runner.select_cases('holdout',runner.SUBJECTS,root)==[]
    with pytest.raises(ValueError,match='inside the repository'):
        runner.select_cases('holdout',runner.SUBJECTS,tmp_path)
    standards=runner.read_json(runner.ROOT/'evals/v3/day13/development_standards.json')
    selected=runner.select_cases('debug',runner.SUBJECTS)
    runner.preflight_cases(selected,standards,'debug')
    broken=deepcopy(standards)
    broken['cases']['python_debug_08']['input_revision'].pop('history')
    with pytest.raises(ValueError,match='explicit reviewed input'):
        runner.preflight_cases(selected,broken,'debug')
