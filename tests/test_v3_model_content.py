"""Exercise the production wire adapter through unchanged V3 validators."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.exceptions import OutputParserException
import pytest

from app.services.llm import ModelCallBudget, ModelOutputValidationError
from app.v3.model_content import ContentModel, bind, content_model
from app.v3.evaluators import TextBatchScore, evaluate_text_rubric
from app.v3.diagnosis import diagnose, DiagnosisDecision
from app.v3.tutor import generate_tutor_reply, TutorReply
from app.v3.contracts import LearningPlan
from tests.test_v3_evaluators import setup
from tests.test_v3_guard import make_case
from tests import test_v3_planner as planner_case
from tests import test_v3_tutor as tutor_case


class Wire:
    def __init__(self, output):
        self.output = output
        self.calls = []

    def with_structured_output(self, schema, **kwargs):
        parent = self
        class Bound:
            def invoke(self, messages, *args, **kw):
                payload = json.loads(messages[-1].content)
                parent.calls.append((schema, payload, messages))
                return deepcopy(parent.output(payload, schema) if callable(parent.output) else parent.output)
        return Bound()

    def bind_tools(self, *args, **kwargs):
        class Tools:
            def invoke(self, messages):
                return AIMessage(content='', tool_calls=[])
        return Tools()


def grade_content(payload, schema=None):
    return {'grading_status': 'graded', 'questions': {
        question['question_id']: {'criteria': {
            ref: {'score': criterion['max_score'], 'anchors': [{'quote': payload['answers'][question['question_id']]}]}
            for ref, criterion in question['rubric'].items()}, 'feedback': '符合冻结标准。'}
        for question in payload['questions']}}


def grade(model, *, quiz=None, answers=None, budget=None):
    sample, defaults, *_ = setup(('text',))
    return evaluate_text_rubric(quiz=quiz or sample, answers=defaults if answers is None else answers,
                               llm=ContentModel(model), budget=budget)


def test_grade_binds_all_identity_versions_maxima_and_offsets_without_model_echo():
    quiz, answers, *_ = setup(('text',))
    quiz = quiz.model_copy(update={'project_id': 'v3_' + 'a' * 32, 'assessment_id': 'assessment_' + 'b' * 32})
    model = Wire(grade_content)
    result = grade(model, quiz=quiz, answers=answers)
    assert result.grading_status == 'graded'
    assert result.results[0].max_score == quiz.questions[0].max_score
    assert result.results[0].question_id == quiz.questions[0].question_id
    assert result.evidence[0].quote == answers[quiz.questions[0].question_id]
    schema, payload, messages = model.calls[0]
    rendered = json.dumps(payload)
    assert quiz.project_id not in rendered and quiz.assessment_id not in rendered
    assert 'snapshot' not in rendered and 'content_hash' not in rendered
    assert schema.__name__ == 'TextGradeContent'
    assert set(schema.model_fields) == {'grading_status', 'uncertainty_reasons', 'questions'}
    assert 'start' not in schema.model_json_schema()['$defs']['QuoteContent']['properties']
    assert len(model.calls) == 1


@pytest.mark.parametrize('mutation', ['foreign_identity', 'snapshot', 'max_score', 'unknown_question',
                                     'missing_question', 'missing_criterion', 'forged_quote', 'forged_offset', 'over_score'])
def test_grade_rejects_injected_authority_or_incomplete_evidence_with_same_single_repair(mutation):
    def output(payload, schema):
        value = grade_content(payload)
        item = value['questions']['q1']; criterion = item['criteria']['r1']
        if mutation == 'foreign_identity': value['assessment_id'] = 'foreign'
        if mutation == 'snapshot': value['snapshot'] = {}
        if mutation == 'max_score': item['max_score'] = 999
        if mutation == 'unknown_question': value['questions']['q999'] = item
        if mutation == 'missing_question': value['questions'] = {}
        if mutation == 'missing_criterion': item['criteria'] = {}
        if mutation == 'forged_quote': criterion['anchors'] = [{'quote': 'not present in this answer'}]
        if mutation == 'forged_offset': criterion['anchors'][0]['start'] = 500
        if mutation == 'over_score': criterion['score'] = 100000
        return value
    model = Wire(output); budget = ModelCallBudget()
    with pytest.raises(ModelOutputValidationError): grade(model, budget=budget)
    assert budget.request_count == 2 and budget.output_repair_count == 1
    assert len(model.calls) == 2


def test_grade_one_repair_can_correct_a_content_error_without_new_identity_fields():
    model = Wire(lambda p, s: {'grading_status': 'graded', 'questions': {}} if not model.calls[:-1] else grade_content(p))
    budget = ModelCallBudget(); result = grade(model, budget=budget)
    assert result.grading_status == 'graded' and budget.request_count == 2 and budget.output_repair_count == 1
    assert 'supplemental_data' in model.calls[1][1]


def test_quote_offsets_are_computed_exactly_for_unicode_and_repeated_occurrences():
    quiz, answers, *_ = setup(('text',)); answers = {quiz.questions[0].question_id: '相同😀相同😀'}
    def output(payload, schema):
        result = grade_content(payload)
        result['questions']['q1']['criteria']['r1']['anchors'] = [{'quote': '相同😀', 'occurrence': 2}]
        return result
    result = grade(Wire(output), quiz=quiz, answers=answers)
    assert (result.evidence[0].start, result.evidence[0].end, result.evidence[0].quote) == (3, 6, '相同😀')


def test_learner_prose_that_mentions_an_id_is_never_rewritten():
    quiz, answers, *_ = setup(('text',)); text = '我的原文含有assessment_' + 'b' * 32
    quiz = quiz.model_copy(update={'assessment_id': 'assessment_' + 'b' * 32})
    answers = {quiz.questions[0].question_id: text}; model = Wire(grade_content)
    result = grade(model, quiz=quiz, answers=answers)
    assert model.calls[0][1]['answers']['q1'] == text and result.evidence[0].quote == text


def test_same_bound_schema_keeps_concurrent_request_identities_separate():
    quiz, answers, *_ = setup(('text',)); model = ContentModel(Wire(grade_content))
    bound = model.with_structured_output(TextBatchScore, method='json_mode')
    def call(index):
        payload = {'project_id': 'project_' + str(index), 'node_id': quiz.node_id,
            'assessment_id': 'assessment_' + str(index), 'snapshot': quiz.snapshot.model_dump(),
            'questions': [q.model_dump() for q in quiz.questions], 'answers': answers}
        return bound.invoke([HumanMessage(content=json.dumps(payload))])
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(call, (1, 2)))
    assert [(r.project_id, r.assessment_id) for r in results] == [('project_1', 'assessment_1'), ('project_2', 'assessment_2')]


def test_diagnosis_maps_only_authorized_short_evidence_and_binds_snapshot():
    case = make_case(prerequisites=[])
    model = Wire(lambda p, s: {'action': 'remediate', 'reason': '当前证据提示仍需练习。',
                               'evidence_refs': [p['allowed_evidence_refs'][0]], 'review_node_ref': None})
    result = diagnose(quiz=case['quiz'], evaluation=case['evaluation'], node=case['node'], policy=case['policy'],
        completed_node_ids=[], history=[], llm=ContentModel(model))
    assert result.project_id == case['quiz']['project_id'] and result.snapshot == DiagnosisDecision.model_validate(case['diagnosis']).snapshot
    assert result.evidence_ids == [case['evaluation']['evidence'][0]['evidence_id']]
    assert set(model.calls[0][0].model_fields) == {'action', 'reason', 'evidence_refs', 'review_node_ref'}


@pytest.mark.parametrize('field,value', [('evidence_refs', ['e999']), ('review_node_ref', 'n999'), ('assessment_id', 'other')])
def test_diagnosis_cannot_reference_foreign_evidence_or_change_owner(field, value):
    case = make_case(prerequisites=[])
    def output(p, s):
        result = {'action': 'remediate', 'reason': '需要复习。', 'evidence_refs': [p['allowed_evidence_refs'][0]]}
        result[field] = value; return result
    budget = ModelCallBudget()
    with pytest.raises(ModelOutputValidationError):
        diagnose(quiz=case['quiz'], evaluation=case['evaluation'], node=case['node'], policy=case['policy'],
            completed_node_ids=[], history=[], llm=ContentModel(Wire(output)), budget=budget)
    assert budget.request_count == 2 and budget.output_repair_count == 1


def test_tutor_uses_bound_source_refs_and_cannot_set_exploration_or_versions():
    model = Wire({'text': '变量保存值；赋值后读取更新后的内容。', 'citation_refs': ['b1']})
    result = generate_tutor_reply(profile=tutor_case.profile(), node=tutor_case.node(), mode='normal',
        contexts=[tutor_case.context_dict()], history=[], llm=ContentModel(model))
    assert result.citations[0].chunk_id == 'chunk-1' and not result.exploration
    assert set(model.calls[0][0].model_fields) == {'text', 'citation_refs'}
    assert model.calls[0][1]['teaching_contexts'][0]['blocks'][0]['citation']['chunk_id'] == 'b1'


@pytest.mark.parametrize('extra', [{'exploration': True}, {'citations': []}, {'citation_refs': ['b999']}])
def test_tutor_cannot_forge_modes_or_sources(extra):
    model = Wire({'text': '说明变量。', 'citation_refs': ['b1'], **extra}); budget = ModelCallBudget()
    with pytest.raises(ModelOutputValidationError):
        generate_tutor_reply(profile=tutor_case.profile(), node=tutor_case.node(), mode='normal',
            contexts=[tutor_case.context_dict()], history=[], llm=ContentModel(model), budget=budget)
    assert budget.request_count == 2 and budget.output_repair_count == 1


def test_plan_binds_versions_and_preserves_original_dag_and_source_validation():
    value = planner_case.plan()
    model = Wire({'nodes': value['nodes']})
    result = planner_case.generate(ContentModel(model))
    assert result.project_id == value['project_id'] and result.plan_version == LearningPlan.model_validate(value).plan_version
    assert set(model.calls[0][0].model_fields) == {'nodes'}
    assert 'project_id' not in model.calls[0][1]
    assert model.calls[0][1]['profile']['goal'] == planner_case.profile().goal


def test_content_model_is_idempotent_and_unknown_already_content_schemas_pass_through():
    model = ContentModel(Wire({})); assert content_model(model) is model
    from app.v3.onboarding import LearningPreparation
    bound = model.with_structured_output(LearningPreparation, method='json_mode')
    assert bound is not None


def test_legacy_quiz_entry_also_uses_content_slots_and_program_owned_snapshot():
    from app.v3.assessment import generate_quiz
    from app.v3.quiz_content import build_content_contract
    from tests.test_v3_quiz_content import content_example
    quiz, _, node, policy, contexts = setup(('single_choice', 'numeric_scalar', 'text'))
    contract = build_content_contract(node, policy, contexts)
    example = content_example(contract)
    for item in example.values():
        if 'numeric_rules' in item: item['numeric_rules']['unit_index'] = 0
    model = Wire(example)
    result = generate_quiz(project_id=quiz.project_id, node=node, assessment_id=quiz.assessment_id,
        snapshot=quiz.snapshot, policy=policy, contexts=contexts, llm=ContentModel(model))
    assert result.snapshot == quiz.snapshot and result.assessment_id == quiz.assessment_id
    assert [q.question_type for q in result.questions] == ['single_choice', 'numeric_scalar', 'text']
    assert 'snapshot' not in json.dumps(model.calls[0][1]) and model.calls[0][0].__name__ == 'QuizContentWire'


def test_quality_review_binds_identity_and_checks_actual_source_quotes():
    from app.v3.quality_review import review_assessment
    quiz, answers, node, policy, contexts = setup(('text',))
    model = Wire({'verdict': 'accepted', 'reason': '材料支持题目。', 'findings': []})
    result = review_assessment(quiz=quiz, node=node, policy=policy, contexts=contexts,
                              answers=answers, llm=ContentModel(model))
    assert result.project_id == quiz.project_id and result.assessment_id == quiz.assessment_id
    assert set(model.calls[0][0].model_fields) == {'verdict', 'reason', 'findings'}
    invalid = Wire({'verdict': 'invalid_item', 'reason': '声称存在资料问题。', 'findings': [{
        'question_ref': 'q1', 'source_ref': 'b1', 'source_quote': 'fabricated absent source excerpt', 'reason': '材料不符。'}]})
    with pytest.raises(ModelOutputValidationError):
        review_assessment(quiz=quiz, node=node, policy=policy, contexts=contexts,
                          answers=answers, llm=ContentModel(invalid))
    assert len(invalid.calls) == 2


@pytest.mark.parametrize('unit', [None, '', 'cm', '%', '秒'])
def test_numeric_unit_closed_choice_roundtrips_without_changing_calculation_or_saved_contract(unit):
    from app.v3.assessment import generate_quiz
    from app.v3.quiz_content import build_content_contract
    from tests.test_v3_quiz_content import content_example
    quiz, _, node, policy, contexts = setup(('numeric_scalar',))
    contract = build_content_contract(node, policy, contexts)
    def output(payload, schema):
        value = content_example(contract)
        index = next(int(k) for k, v in payload['unit_choices'].items() if v == unit)
        value['q1']['numeric_rules'] = {'expected': 2.0, 'unit_index': index}
        return value
    wire = Wire(output)
    result = generate_quiz(project_id=quiz.project_id, node=node, assessment_id=quiz.assessment_id,
        snapshot=quiz.snapshot, policy=policy, contexts=contexts, llm=ContentModel(wire), generation_mode='content-v1')
    assert result.questions[0].numeric_rules.expected == 2.0
    assert result.questions[0].numeric_rules.unit == unit
    assert 'unit_index' not in result.model_dump_json()
    numeric_schema = wire.calls[0][0].model_fields['q1'].annotation.model_fields['numeric_rules'].annotation
    assert set(numeric_schema.model_fields) == {'expected', 'unit_index'}
    assert len(wire.calls) == 1


@pytest.mark.parametrize('bad', [-1, 500, '元', '0', None])
def test_numeric_unit_selector_cannot_inject_unregistered_units(bad):
    from app.v3.assessment import generate_quiz
    from app.v3.quiz_content import build_content_contract
    from tests.test_v3_quiz_content import content_example
    quiz, _, node, policy, contexts = setup(('numeric_scalar',))
    value = content_example(build_content_contract(node, policy, contexts))
    value['q1']['numeric_rules']['unit_index'] = bad
    budget = ModelCallBudget()
    with pytest.raises(ModelOutputValidationError):
        generate_quiz(project_id=quiz.project_id, node=node, assessment_id=quiz.assessment_id,
            snapshot=quiz.snapshot, policy=policy, contexts=contexts, llm=ContentModel(Wire(value)),
            generation_mode='content-v1', budget=budget)
    assert budget.request_count == 2 and budget.output_repair_count == 1
