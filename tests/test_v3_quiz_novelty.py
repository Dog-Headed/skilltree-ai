"""Retest novelty must be validated and repaired in the model's slot protocol."""
from copy import deepcopy
import json
import re

import pytest

from app.services.llm import ModelCallBudget, ModelOutputValidationError
from app.v3.assessment import generate_quiz
from app.v3.config import SERVER_LIMITS
from app.v3.model_content import ContentModel
from app.v3.quiz_content import build_content_contract
from tests.test_v3_evaluators import setup
from tests.test_v3_model_content import Wire
from tests.test_v3_quiz_content import content_example


MODES = ('legacy', 'content-v1')


def case(types=('single_choice', 'numeric_scalar', 'text')):
    quiz, _, node, policy, contexts = setup(types)
    content = content_example(build_content_contract(node, policy, contexts))
    for item in content.values():
        if 'numeric_rules' in item:
            item['numeric_rules']['unit_index'] = 0
    return quiz, node, policy, contexts, content


def generate(sample, wire, mode, history=(), budget=None):
    quiz, node, policy, contexts, _ = sample
    return generate_quiz(project_id=quiz.project_id, node=node,
        assessment_id=quiz.assessment_id, snapshot=quiz.snapshot,
        policy=policy, contexts=contexts, previous_question_prompts=history,
        generation_mode=mode, llm=ContentModel(wire), budget=budget)


def repair_payload(wire):
    supplemental = wire.calls[1][1]['supplemental_data']
    return next(item for item in supplemental if isinstance(item, dict) and 'error' in item)


@pytest.mark.parametrize('mode', MODES)
@pytest.mark.parametrize('normalized', [False, True])
def test_all_historical_repeats_are_reported_as_slot_paths_before_binding(mode, normalized):
    sample = case()
    bad = deepcopy(sample[-1])
    history = ['Explain STEP_A!', '计算金额：7×4。', '解释变量保存值。']
    prompts = [' explain step a ', '计 算 金 额 7 4', '解 释 变 量 保 存 值！'] if normalized else history
    for item, prompt in zip(bad.values(), prompts):
        item['prompt'] = prompt
    wire = Wire(bad)
    budget = ModelCallBudget()
    with pytest.raises(ModelOutputValidationError) as failure:
        generate(sample, wire, mode, history, budget)
    assert 'Content binding validation failed' in str(failure.value)
    repair = repair_payload(wire)
    assert all(f'q{i}.prompt' in repair['error'] for i in range(1, 4))
    assert 'previous_question_prompts' in repair['error']
    assert not re.search(r'\bquestion_[0-9a-f]{24,}\b', repair['error'])
    # No internal unit:null snapshot should be returned as model-facing content.
    assert repair['previous_output'] is None
    assert len(wire.calls) == budget.request_count == 2
    assert budget.output_repair_count == 1 and budget.network_retry_count == 0


@pytest.mark.parametrize('mode', MODES)
def test_one_repair_can_replace_repeated_tasks_without_changing_frozen_bindings(mode):
    sample = case()
    quiz, node, _, _, good = sample
    bad = deepcopy(good)
    history = ['旧选择任务。', '旧数值任务。', '旧解释任务。']
    for item, prompt in zip(bad.values(), history):
        item['prompt'] = prompt
    calls = []
    def response(payload, schema):
        calls.append(payload)
        return bad if len(calls) == 1 else good
    wire = Wire(response)
    budget = ModelCallBudget()
    result = generate(sample, wire, mode, history, budget)
    assert [question.prompt for question in result.questions] == [item['prompt'] for item in good.values()]
    assert all(f'q{i}.prompt' in repair_payload(wire)['error'] for i in range(1, 4))
    assert result.project_id == quiz.project_id and result.node_id == node.node_id
    assert result.assessment_id == quiz.assessment_id and result.snapshot == quiz.snapshot
    assert all(question.question_id.startswith('question_') for question in result.questions)
    assert result.questions[1].numeric_rules.expected == 2.0
    assert result.questions[1].numeric_rules.unit is None
    assert 'unit_index' not in result.model_dump_json()
    assert budget.request_count == 2 and budget.output_repair_count == 1


@pytest.mark.parametrize('mode', MODES)
def test_same_paper_duplicate_cannot_pass_by_changing_case_or_punctuation(mode):
    sample = case(('single_choice', 'text'))
    bad = deepcopy(sample[-1])
    bad['q1']['prompt'] = 'Explain STEP A!'
    bad['q2']['prompt'] = 'explain_step_a'
    wire = Wire(bad)
    budget = ModelCallBudget()
    with pytest.raises(ModelOutputValidationError) as failure:
        generate(sample, wire, mode, budget=budget)
    assert 'Content binding validation failed' in str(failure.value)
    error = repair_payload(wire)['error']
    assert 'q2.prompt' in error and 'q1.prompt' in error
    assert not re.search(r'\bquestion_[0-9a-f]{24,}\b', error)
    assert len(wire.calls) == budget.request_count == 2 and budget.output_repair_count == 1


def document_from_wire(wire):
    # The model receives this actual schema in its system message in json_mode.
    return json.loads(wire.calls[0][2][0].content.rsplit('\n', 1)[1])


def resolve(document, value):
    while '$ref' in value:
        assert value['$ref'].startswith('#/$defs/')
        value = document['$defs'][value['$ref'].split('/')[-1]]
    return value


def enums_banned(value):
    if isinstance(value, dict):
        if isinstance(value.get('not'), dict) and 'enum' in value['not']:
            yield value['not']['enum']
        for child in value.values():
            yield from enums_banned(child)
    elif isinstance(value, list):
        for child in value:
            yield from enums_banned(child)


@pytest.mark.parametrize('mode', MODES)
def test_prompt_schema_shares_history_once_and_preserves_text_limits(mode):
    sample = case()
    history = ['历史比较任务。', '历史计算任务。']
    wire = Wire(sample[-1])
    generate(sample, wire, mode, history)
    document = document_from_wire(wire)
    assert list(enums_banned(document)) == [history]
    for key in ('q1', 'q2', 'q3'):
        question_schema = resolve(document, document['properties'][key])
        prompt_schema = resolve(document, question_schema['properties']['prompt'])
        assert prompt_schema['type'] == 'string'
        assert prompt_schema['minLength'] == 1 and prompt_schema['maxLength'] == 4000
        assert prompt_schema['not']['enum'] == history


@pytest.mark.parametrize('mode', MODES)
def test_historical_prose_reaches_wire_unchanged_including_id_looking_text(mode):
    sample = case()
    history = ['请解释 question_0123456789abcdef01234567 和 assessment_abc 的区别。']
    wire = Wire(sample[-1])
    generate(sample, wire, mode, history)
    assert wire.calls[0][1]['previous_question_prompts'] == history
    assert list(enums_banned(document_from_wire(wire))) == [history]


@pytest.mark.parametrize('repeat_history', [False, True])
def test_long_history_keeps_every_prompt_and_runtime_rejection_within_context_limit(repeat_history):
    # This fits the original content-v1 input; a second history copy in the
    # wire schema would exceed 24000. Legacy's own earlier preflight rejects
    # this fixture, so do not bypass that independent context guard to test it.
    sample = case()
    history = [(str(index) + '依据资料解释变量保存值。' * 400)[:3801] for index in range(3)]
    output = deepcopy(sample[-1])
    if repeat_history:
        for item, prompt in zip(output.values(), history):
            item['prompt'] = prompt
    wire = Wire(output)
    budget = ModelCallBudget()
    if repeat_history:
        with pytest.raises(ModelOutputValidationError) as failure:
            generate(sample, wire, 'content-v1', history, budget)
        assert 'Content binding validation failed' in str(failure.value)
        assert all(f'q{i}.prompt' in repair_payload(wire)['error'] for i in range(1, 4))
        assert budget.request_count == 2 and budget.output_repair_count == 1
    else:
        result = generate(sample, wire, 'content-v1', history, budget)
        assert [question.prompt for question in result.questions] == [item['prompt'] for item in output.values()]
        assert budget.request_count == 1 and budget.output_repair_count == 0
    for _, payload, messages in wire.calls:
        assert payload['previous_question_prompts'] == history
        assert sum(len(str(message.content)) for message in messages) <= SERVER_LIMITS.max_context_characters == 24000
        sent = '\n'.join(str(message.content) for message in messages)
        assert all(sent.count(prompt) == 1 for prompt in history)
        document = json.loads(messages[0].content.rsplit('\n', 1)[1])
        assert list(enums_banned(document)) == []
        for key in ('q1', 'q2', 'q3'):
            question_schema = resolve(document, document['properties'][key])
            prompt_schema = resolve(document, question_schema['properties']['prompt'])
            assert prompt_schema['type'] == 'string'
            assert prompt_schema['minLength'] == 1 and prompt_schema['maxLength'] == 4000
