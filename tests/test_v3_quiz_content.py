from copy import deepcopy
import json

import pytest
from pydantic import ValidationError

from app.services.llm import ModelCallBudget, ModelOutputValidationError
from app.v3 import assessment
from app.v3.contracts import SkillNode, EvaluationPolicy, AssessmentQuiz
from app.v3.quiz_content import build_content_contract
from tests.test_v3_evaluators import FakeModel, setup


def content_example(contract):
    result={}
    for slot in contract.slots:
        q={'prompt':'根据资料回答独立任务 '+slot.key,'source_refs':['b'+str(i) for i in range(1,len(slot.citations)+1)]}
        if slot.question_type in {'single_choice','multiple_choice'}:
            q.update(options=['变量保存值','变量不保存值'],max_score=10.0)
            q['correct_option' if slot.question_type=='single_choice' else 'correct_options']=1 if slot.question_type=='single_choice' else [1]
        elif slot.question_type=='numeric_scalar':q.update(numeric_rules={'expected':2.0},max_score=10.0)
        else:q.update(reference_answer='Yesterday I walked home.',rubric={
            'r'+str(i):{'description':'解释目标中的检查点 '+str(i),'max_score':5.0} for i in range(1,len(slot.criterion_ids)+1)})
        result[slot.key]=q
    return result


def call_content(model,quiz,node,policy,contexts,**kwargs):
    return assessment.generate_quiz(project_id=quiz.project_id,node=node,assessment_id=quiz.assessment_id,
        snapshot=quiz.snapshot,policy=policy,contexts=contexts,llm=model,generation_mode='content-v1',**kwargs)


def test_model_schema_contains_no_state_identity_or_cross_type_fields():
    quiz,_,node,policy,contexts=setup(('single_choice','numeric_scalar','text'))
    contract=build_content_contract(node,policy,contexts);schema=contract.schema.model_json_schema()
    keys=set()
    def collect(value):
        if isinstance(value,dict):
            keys.update(value.get('properties',{}))
            for item in value.values():collect(item)
        elif isinstance(value,list):
            for item in value:collect(item)
    collect(schema)
    assert not keys & {'project_id','node_id','assessment_id','previous_assessment_id','snapshot',
        'question_id','objective_ids','criterion_id','evaluator_id','evaluator_version','source_id','source_version','chunk_id','question_type','answer_key',
        'allowed_units','abs_tolerance','rel_tolerance'}
    model=FakeModel(content_example(contract));result=call_content(model,quiz,node,policy,contexts)
    assert (result.project_id,result.node_id,result.assessment_id,result.snapshot)==(quiz.project_id,quiz.node_id,quiz.assessment_id,quiz.snapshot)
    assert result.questions[0].answer_key=='option_1'
    assert result.questions[1].answer_key is None and not result.questions[1].rubric
    assert [c.criterion_id for c in result.questions[2].rubric]==['r1','r2']
    assert result.questions[2].max_score==10.0
    assert assessment.validate_quiz(result,node=node,policy=policy,contexts=contexts).model_dump()==result.model_dump()


@pytest.mark.parametrize('kind',['single_choice','multiple_choice','numeric_scalar','text'])
def test_each_type_uses_only_its_own_content_template(kind):
    quiz,_,node,policy,contexts=setup((kind,));contract=build_content_contract(node,policy,contexts)
    assert contract.slots[0].question_type==kind
    fields=set(contract.schema.model_fields['q1'].annotation.model_fields)
    expected={'single_choice':{'options','correct_option','max_score'},'multiple_choice':{'options','correct_options','max_score'},
        'numeric_scalar':{'numeric_rules','max_score'},'text':{'reference_answer','rubric'}}[kind]
    assert fields=={'prompt','source_refs'}|expected
    assert call_content(FakeModel(content_example(contract)),quiz,node,policy,contexts).questions[0].question_type==kind


@pytest.mark.parametrize('defect',['root_identity','question_identity','cross_type','choice_index','citation','missing_slot','unknown_slot','rubric_identity','unit','tolerance'])
def test_invalid_content_is_not_coerced_and_shares_one_repair(defect):
    quiz,_,node,policy,contexts=setup(('single_choice','numeric_scalar','text'))
    contract=build_content_contract(node,policy,contexts);good=content_example(contract);bad=deepcopy(good)
    if defect=='root_identity':bad['assessment_id']='foreign_assessment'
    elif defect=='question_identity':bad['q1']['question_id']='forged'
    elif defect=='cross_type':bad['q1']['numeric_rules']={'expected':4.0}
    elif defect=='choice_index':bad['q1']['correct_option']=3
    elif defect=='citation':bad['q1']['source_refs']=['b99']
    elif defect=='missing_slot':bad.pop('q2')
    elif defect=='unknown_slot':bad['q4']=deepcopy(bad['q1'])
    elif defect=='rubric_identity':bad['q3']['rubric']['r1']['criterion_id']='forged'
    elif defect=='unit':bad['q2']['numeric_rules'].update(unit='元',allowed_units=['元'])
    else:bad['q2']['numeric_rules']['abs_tolerance']=0.1
    model=FakeModel(bad,good);budget=ModelCallBudget()
    result=call_content(model,quiz,node,policy,contexts,budget=budget)
    assert result.assessment_id==quiz.assessment_id and (budget.request_count,budget.output_repair_count)==(2,1)
    assert len(model.calls)==2 and '完整修复' in model.calls[1][-1].content


@pytest.mark.parametrize('unit',[None,'','cm','%'])
def test_numeric_configuration_is_owned_by_program_and_uses_frozen_tolerance(unit):
    from app.v3.evaluators import evaluate_numeric_scalar,UNIT_RULES
    from app.v3.config import SERVER_LIMITS
    quiz,_,node,policy,contexts=setup(('numeric_scalar',))
    limits=(SERVER_LIMITS.max_numeric_absolute_tolerance,SERVER_LIMITS.max_numeric_relative_tolerance)
    policy=EvaluationPolicy.model_validate({**policy.model_dump(),'numeric_abs_tolerance':limits[0],'numeric_rel_tolerance':limits[1]})
    contract=build_content_contract(node,policy,contexts);good=content_example(contract)
    good['q1']['numeric_rules']['unit']=unit
    question=call_content(FakeModel(good),quiz,node,policy,contexts).questions[0]
    rules=question.numeric_rules
    assert (rules.abs_tolerance,rules.rel_tolerance)==limits
    if unit is None:assert rules.allowed_units==[]
    else:
        assert unit in rules.allowed_units
        assert all(UNIT_RULES[name][0]==UNIT_RULES[unit][0] for name in rules.allowed_units)
    answer='0.02m' if unit=='cm' else '2'+(unit or '')
    evaluated=evaluate_numeric_scalar(question,answer)
    assert evaluated.grading_status=='graded' and evaluated.result.score==question.max_score


def test_frozen_single_criterion_is_a_single_content_slot_without_renaming():
    quiz,_,node,policy,contexts=setup(('text',))
    node=SkillNode.model_validate({**node.model_dump(),'objectives':[
        {**node.objectives[0].model_dump(),'criterion_ids':['c1']}]})
    contract=build_content_contract(node,policy,contexts)
    good=content_example(contract)
    assert set(good['q1']['rubric'])=={'r1'}
    result=call_content(FakeModel(good),quiz,node,policy,contexts)
    assert [r.criterion_id for r in result.questions[0].rubric]==['c1']
    assert result.questions[0].rubric[0].max_score==result.questions[0].max_score
    again=call_content(FakeModel(good),quiz,node,policy,contexts)
    assert [q.question_id for q in result.questions]==[q.question_id for q in again.questions]


def test_coverage_packing_never_drops_required_objectives_or_minimum_counts():
    quiz,_,node,policy,contexts=setup(('text',)*5)
    node=SkillNode.model_validate({**node.model_dump(),'objectives':[
        {**o.model_dump(),'required_capability_ids':['choice_exact','numeric_scalar','text_rubric'],
         'evidence_requirement':['choice','numeric_result','text_excerpt']} for o in node.objectives]})
    raw=policy.model_dump();raw.update(allowed_question_types=['single_choice','numeric_scalar','text'],
        evaluators=[{'evaluator_id':k,'evaluator_version':'1.0.0'} for k in ('choice_exact','numeric_scalar','text_rubric')])
    for rule in raw['objective_rules']:rule.update(evidence_kinds=['choice','numeric_result','text_excerpt'],min_items=3)
    policy=EvaluationPolicy.model_validate(raw)
    quiz=AssessmentQuiz.model_validate({**quiz.model_dump(),'snapshot':{**quiz.snapshot.model_dump(),'evaluator_manifest':raw['evaluators']}})
    contract=build_content_contract(node,policy,contexts)
    assert len(contract.slots)==10
    result=call_content(FakeModel(content_example(contract)),quiz,node,policy,contexts)
    assert assessment.validate_quiz(result,node=node,policy=policy,contexts=contexts)
    for goal in node.objectives:
        questions=[q for q in result.questions if goal.objective_id in q.objective_ids]
        assert len(questions)>=3 and {q.question_type for q in questions}=={'single_choice','numeric_scalar','text'}


def test_continuously_invalid_content_stops_without_returning_a_quiz():
    quiz,_,node,policy,contexts=setup(('text',));contract=build_content_contract(node,policy,contexts)
    bad=content_example(contract);bad['project_id']='forged'
    model=FakeModel(bad,bad);budget=ModelCallBudget()
    with pytest.raises(ModelOutputValidationError):call_content(model,quiz,node,policy,contexts,budget=budget)
    assert (budget.request_count,budget.output_repair_count)==(2,1)


def test_content_prompt_omits_frozen_snapshot_and_uses_real_source_text():
    quiz,_,node,policy,contexts=setup(('text',))
    messages,_=assessment.quiz_generation_messages(project_id=quiz.project_id,node=node,assessment_id=quiz.assessment_id,
        snapshot=quiz.snapshot,policy=policy,contexts=contexts,generation_mode='content-v1')
    payload=json.loads(messages[1].content.split('\n',1)[1])
    assert 'snapshot' not in payload and 'project_id' not in payload
    assert payload['slots']['q1']['source_blocks']['b1']==contexts['objective_0']['blocks'][0]['content']
    assert set(payload['slots']['q1']['output_fields'])=={'prompt','source_refs','reference_answer','rubric'}
    assert '文字题顶层禁止max_score' in messages[0].content


def test_content_contract_persists_and_grades_through_the_real_learning_graph(tmp_path):
    from uuid import uuid4
    from app.v3.learning import LearningService
    from tests.day11_support import FakeLearningModel,build_frozen_project,learning_event,private_quiz,answers_for_quiz
    class ContentFake(FakeLearningModel):
        def _invoke(self,schema,messages):
            if schema!='QuizContent':return super()._invoke(schema,messages)
            self.calls.append({'schema':schema})
            payload=json.loads(messages[1].content.split('\n',1)[1]);result={}
            for key,slot in payload['slots'].items():
                q={'prompt':'明确标注Fake流程验收 '+key+' '+slot['goals'][0]['outcome'],
                   'source_refs':list(slot['source_blocks'])}
                if slot['question_type']=='single_choice':q.update(options=['符合资料的表述','相反表述'],correct_option=1,max_score=1.0)
                else:q.update(reference_answer='Fake说明 '+next(iter(slot['source_blocks'].values()))[:100],rubric={
                    name:{'description':'Fake检查目标','max_score':1.0} for name in slot['rubric_slots']})
                result[key]=q
            return result
    model=ContentFake();ready=build_frozen_project(tmp_path/'typed-flow',model=model)
    service=LearningService(ready['paths'],llm=model,quiz_generation_mode='content-v1');pid=ready['project_id']
    view=service.start(pid,str(uuid4()));first=view['current_node_id']
    view=service.resume(pid,learning_event(view,'start_quiz'))
    assert view['page_state']=='quiz'
    quiz=private_quiz(ready['paths'],pid,view['assessment_id'])
    assert all(q['question_id'].startswith('question_') for q in quiz['questions'])
    view=service.resume(pid,learning_event(view,'submit_answer',answers=answers_for_quiz(quiz)))
    assert view['page_state']=='learning' and view['guard']['passed'] and view['current_node_id']!=first
    assert view['completed_node_ids']==[first] and view['tutor']['text']
    count=len(model.calls);assert service.read(pid)['completed_node_ids']==[first] and len(model.calls)==count
