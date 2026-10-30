"""Only recover punctuation; complete JSON and all business guards still apply."""
import json
from types import SimpleNamespace

import pytest
from langchain_core.exceptions import OutputParserException
from pydantic import Field, create_model
from app.services.json_syntax import complete_json
from app.services.llm import ModelCallBudget
from app.v3.contracts import ContractModel
from deploy.provider import StructuredReply, StrictProvider
from tests.test_planner_task_contract import generate, proposal


@pytest.mark.parametrize('token', [r'\0', r'\d', r'\(', r'\a'])
def test_unknown_escape_preserves_literal_characters(token):
    decoded, repairs = complete_json('{"value":"' + token + '"}', repair_punctuation=True)
    assert decoded == {'value': token} and repairs == ('literal_backslash',)


@pytest.mark.parametrize('value', ['"C"', '42', '-3.5', 'true', 'false', 'null', '[1,2]', '{"x":1}'])
def test_only_missing_key_value_colon_is_inserted(value):
    decoded, repairs = complete_json('{"value" ' + value + '}', repair_punctuation=True)
    assert decoded == {'value': json.loads(value)} and repairs == ('key_value_colon',)


def test_valid_escapes_quotes_and_literals_are_not_rewritten():
    expected = {'valid': '\n', 'code': r'\0', 'quoted': '"x"', 'path': r'C:\tmp', 'plain': 'null'}
    text = json.dumps(expected)
    decoded, repairs = complete_json(text, repair_punctuation=True)
    assert decoded == expected and not repairs
    # A different error must not cause already valid escapes to be doubled.
    text = text[:-1] + ',"bad":"' + r'\0' + '"}'
    decoded, repairs = complete_json(text, repair_punctuation=True)
    assert decoded == {**expected, 'bad': r'\0'} and len(repairs) == 1


@pytest.mark.parametrize('text', ['{"value"}', '{"value":}', '{"value":1', '{"value":"x}',
    '{"value":NaN}', '{"a", "b"}', '{"a":INVALID}', r'{"a":"\uQQQQ"}',
    '{"a" [1,2]', '{"a":1} trailing'])
def test_missing_values_truncation_and_other_syntax_are_not_invented(text):
    # Python permits NaN by default; the provider's exact Pydantic schema
    # remains responsible for rejecting non-finite numeric values.
    if 'NaN' in text:
        assert not complete_json(text, repair_punctuation=True)[1]
    else:
        with pytest.raises(json.JSONDecodeError):
            complete_json(text, repair_punctuation=True)


def test_recovery_has_a_fixed_eight_insertion_limit():
    assert len(complete_json('{"a":"' + r'\0' * 8 + '"}', repair_punctuation=True)[1]) == 8
    with pytest.raises(json.JSONDecodeError):
        complete_json('{"a":"' + r'\0' * 9 + '"}', repair_punctuation=True)
    with pytest.raises(json.JSONDecodeError):
        complete_json(r'{"a":"\0"}')


@pytest.mark.parametrize('raw,expected', [
    ('{"a":1 "b":2}', {'a':1,'b':2}),
    ('[{"a":1}{"b":2}]', [{'a':1},{'b':2}]),
    ('[[1][2]]', [[1],[2]]),
])
def test_missing_structural_commas_preserve_every_existing_member(raw,expected):
    value,repairs=complete_json(raw,repair_punctuation=True)
    assert value==expected and repairs==('member_comma',)


def test_adjacent_quoted_values_and_unescaped_inner_quotes_are_not_guessed():
    for raw in ['["a" "b"]','{"a":"printf("x")"}']:
        with pytest.raises(json.JSONDecodeError):complete_json(raw,repair_punctuation=True)


class RawModel:
    def __init__(self, text, finish='stop'):
        self.text, self.finish, self.calls = text, finish, 0

    def with_structured_output(self, schema, **kwargs):
        self.schema = schema
        return self

    def invoke(self, messages):
        self.calls += 1
        return {'raw': SimpleNamespace(content=self.text, response_metadata={'finish_reason': self.finish}),
                'parsed': None, 'parsing_error': OutputParserException('Original SDK parse failed')}


def test_real_planner_adapter_validates_recovered_content_with_one_request():
    content = proposal(('text_rubric',), r'解释C代码中 \0 的含义')
    content['nodes'][0]['objectives'][0]['criterion_ids'] = ['r1']
    text = json.dumps(content, ensure_ascii=False).replace('"nodes":', '"nodes"', 1).replace(r'\\0', r'\0')
    model = RawModel(text)
    budget = ModelCallBudget()
    plan = generate(StrictProvider(model), ('text_rubric',), budget)
    assert plan.nodes[0].objectives[0].observable_outcome == r'解释C代码中 \0 的含义'
    assert plan.nodes[0].objectives[0].evidence_requirement == ['text_excerpt']
    assert model.calls == budget.request_count == 1 and budget.output_repair_count == 0


@pytest.mark.parametrize('bad,reason', [
    ('{"nodes" [],"nodes":[]}', 'unique value'),
    ('{"nodes" [],"private":"SECRET"}', 'extra_forbidden'),
    ('{"nodes" "wrong type"}', 'list_type'),
])
def test_recovery_preserves_duplicate_and_exact_schema_rejection(bad, reason):
    schema = create_model('PlanContent', __base__=ContractModel, nodes=(list, Field(min_length=1)))
    with pytest.raises(OutputParserException, match=reason):
        StrictProvider(RawModel(bad)).with_structured_output(schema).invoke([])


def test_truncated_finish_reason_blocks_even_recoverable_json():
    schema = create_model('PlanContent', __base__=ContractModel, nodes=(list, ...))
    with pytest.raises(OutputParserException, match='cut off'):
        StrictProvider(RawModel('{"nodes" []}', finish='length')).with_structured_output(schema).invoke([])


def test_automatic_punctuation_recovery_is_scoped_to_planner_only():
    schema = create_model('QuizContent', __base__=ContractModel, nodes=(list, ...))
    with pytest.raises(OutputParserException):
        StrictProvider(RawModel('{"nodes" []}')).with_structured_output(schema).invoke([])
