import json

from langchain_core.exceptions import OutputParserException
from pydantic import BaseModel, ConfigDict, ValidationError
import pytest

from deploy.provider import StrictProvider, compact_parse_error


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
