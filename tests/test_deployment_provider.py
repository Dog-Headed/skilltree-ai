import json

from langchain_core.exceptions import OutputParserException
from pydantic import BaseModel, ConfigDict, ValidationError
import pytest

from deploy.provider import StrictProvider, compact_parse_error
from deploy.provider import StructuredReply
from types import SimpleNamespace


class RequiredScore(BaseModel):
    model_config = ConfigDict(strict=True)
    score: float


class Model:
    def __init__(self, result):
        self.result, self.calls = result, 0

    def with_structured_output(self, schema, **kwargs):
        assert schema is RequiredScore
        assert kwargs == {'method': 'json_mode', 'include_raw': True}
        return self

    def invoke(self, messages):
        self.calls += 1
        return self.result


def test_validated_object_is_returned_without_raw_private_fields():
    expected = RequiredScore(score=0.8)
    model = Model({'parsed': expected, 'raw': 'PRIVATE_ANSWER', 'parsing_error': None})
    result = StrictProvider(model).with_structured_output(RequiredScore, method='json_mode').invoke([])
    assert result is expected and model.calls == 1


def test_schema_repair_error_contains_field_but_never_entire_invalid_output():
    secret = 'PRIVATE_REFERENCE_' * 1000
    with pytest.raises(ValidationError) as caught:
        RequiredScore.model_validate({'score': secret})
    parser_error = OutputParserException('Full completion: ' + secret)
    parser_error.__cause__ = caught.value
    model = Model({'parsed': None, 'raw': secret, 'parsing_error': parser_error})
    bound = StrictProvider(model).with_structured_output(RequiredScore, method='json_mode')
    with pytest.raises(OutputParserException) as repair:
        bound.invoke([])
    message = str(repair.value)
    assert 'score' in message and 'float_type' in message
    assert 'PRIVATE_REFERENCE_' not in message and len(message) < 1000
    assert model.calls == 1  # The existing business budget owns all retries.


def test_invalid_json_reports_location_without_guessing_or_repairing_values():
    try:
        json.loads('{"score":PRIVATE_REFERENCE}')
    except json.JSONDecodeError as error:
        message = compact_parse_error(error)
    assert 'column' in message and 'PRIVATE_REFERENCE' not in message


def test_missing_parsed_output_remains_an_error():
    bound = StrictProvider(Model({'parsed': None, 'parsing_error': None})).with_structured_output(RequiredScore, method='json_mode')
    with pytest.raises(OutputParserException):
        bound.invoke([])


@pytest.mark.parametrize('kind', ['single_choice', 'multiple_choice', 'numeric_scalar'])
def test_non_text_rubric_is_rejected_before_an_ungradable_quiz_is_saved(kind):
    question = SimpleNamespace(question_type=kind, rubric=['private criterion'])
    parsed = SimpleNamespace(questions=[question])
    model = Model({'parsed': parsed, 'parsing_error': None})
    with pytest.raises(OutputParserException, match=r'questions.0.rubric must be') as error:
        StructuredReply(model, 'AssessmentQuiz').invoke([])
    assert question.rubric == ['private criterion']  # Reject; never silently rewrite model data.
    assert 'private criterion' not in str(error.value) and model.calls == 1


def test_valid_choice_and_text_rubrics_pass_without_mutation():
    parsed = SimpleNamespace(questions=[SimpleNamespace(question_type='single_choice', rubric=[]),
                                        SimpleNamespace(question_type='text', rubric=['criterion'])])
    model = Model({'parsed': parsed, 'parsing_error': None})
    assert StructuredReply(model, 'AssessmentQuiz').invoke([]) is parsed


def test_unexecutable_choice_objective_criteria_are_rejected_before_plan_freeze():
    objective = SimpleNamespace(required_capability_ids=['choice_exact'], criterion_ids=['invented_criterion'])
    plan = SimpleNamespace(nodes=[SimpleNamespace(objectives=[objective])])
    model = Model({'parsed': plan, 'parsing_error': None})
    with pytest.raises(OutputParserException, match=r'criterion_ids must be \[\]'):
        StructuredReply(model, 'LearningPlan').invoke([])
    assert objective.criterion_ids == ['invented_criterion'] and model.calls == 1
    objective.criterion_ids = []
    assert StructuredReply(model, 'LearningPlan').invoke([]) is plan


def test_production_notes_receive_the_same_course_instructions_as_local():
    from app.services.llm import ModelCallBudget
    from app.v3.onboarding import generate_notes, StudyNotes

    class Capture:
        def with_structured_output(self, schema, **kwargs):
            assert schema is StudyNotes
            self.include_raw = kwargs.get('include_raw', False)
            return self

        def invoke(self, messages):
            self.messages = [(m.type, m.content) for m in messages]
            result = StudyNotes(content='Synthetic notes for isolated contract testing. ' * 10)
            return {'parsed': result, 'parsing_error': None} if self.include_raw else result

    local, production = Capture(), Capture()
    payload = {'profile': {'goal': 'synthetic broad route', 'time_budget_minutes': 1440}}
    generate_notes(local, ModelCallBudget(), payload)
    generate_notes(StrictProvider(production), ModelCallBudget(), payload)
    assert local.messages == production.messages


def test_production_does_not_add_a_separate_curriculum_prompt_to_shared_planning():
    from langchain_core.messages import SystemMessage, HumanMessage

    class Capture:
        def invoke(self, messages):
            self.messages = messages
            return {'parsed': SimpleNamespace(nodes=[]), 'parsing_error': None}

    messages = [SystemMessage(content='shared planning instructions'), HumanMessage(content='synthetic input')]
    model = Capture()
    StructuredReply(model, 'LearningPlan').invoke(messages)
    assert model.messages == messages


def test_auto_closed_partial_json_is_not_accepted_as_a_complete_business_result():
    from langchain_core.messages import AIMessage
    from langchain_core.output_parsers import JsonOutputParser
    partial = '{"score":0.8'
    assert JsonOutputParser().parse(partial) == {'score': 0.8}
    parsed = RequiredScore(score=0.8)
    model = Model({'parsed': parsed, 'raw': AIMessage(content=partial), 'parsing_error': None})
    with pytest.raises(OutputParserException, match='json_error'):
        StrictProvider(model).with_structured_output(RequiredScore, method='json_mode').invoke([])


def test_output_cut_off_at_token_limit_is_rejected_even_if_its_prefix_parses():
    from langchain_core.messages import AIMessage
    model = Model({'parsed': RequiredScore(score=0.8),
        'raw': AIMessage(content='{"score":0.8}', response_metadata={'finish_reason': 'length'}), 'parsing_error': None})
    with pytest.raises(OutputParserException, match='cut off'):
        StrictProvider(model).with_structured_output(RequiredScore, method='json_mode').invoke([])


@pytest.mark.parametrize('content', ['{"score":0.8}', '```json\n{"score":0.8}\n```'])
def test_complete_provider_json_remains_compatible(content):
    from langchain_core.messages import AIMessage
    parsed = RequiredScore(score=0.8)
    model = Model({'parsed': parsed, 'raw': AIMessage(content=content), 'parsing_error': None})
    assert StrictProvider(model).with_structured_output(RequiredScore, method='json_mode').invoke([]) is parsed
