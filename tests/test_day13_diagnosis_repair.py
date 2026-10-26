"""Regression for real structured-parser failures and bounded diagnosis repair."""

from copy import deepcopy
import json

from langchain_core.exceptions import OutputParserException
from langchain_core.output_parsers import PydanticOutputParser
import pytest

from app.services.llm import ModelCallBudget, ModelOutputValidationError
from app.v3.diagnosis import DiagnosisDecision, diagnose
from tests.test_v3_guard import make_case


PRIVATE_MARKER = "PRIVATE_WHOLE_MODEL_OUTPUT_DO_NOT_ECHO"


class ParsingFinalModel:
    """Use the actual LangChain parser, not a fabricated validation error."""

    def __init__(self, outputs):
        self.outputs = iter(outputs)
        self.calls = []
        self.parser = PydanticOutputParser(pydantic_object=DiagnosisDecision)

    def with_structured_output(self, schema, **_kwargs):
        assert schema is DiagnosisDecision
        return self

    def invoke(self, messages):
        self.calls.append(messages)
        output = next(self.outputs)
        if isinstance(output, Exception):
            raise output
        return self.parser.parse(json.dumps(output, ensure_ascii=False))


def run(model, *, case=None, budget=None):
    case = case or make_case()
    return diagnose(
        quiz=case["quiz"], evaluation=case["evaluation"], node=case["node"],
        policy=case["policy"], completed_node_ids=case["completed_node_ids"],
        history=[], llm=model, budget=budget,
    )


def decisions():
    case = make_case()
    good = {**deepcopy(case["diagnosis"]), "action": "remediate", "review_node_id": None}
    bad = {**good, "review_node_id": case["node"]["node_id"], "reason": PRIVATE_MARKER}
    return case, bad, good


def test_parser_action_validation_reason_reaches_repair_without_private_output(caplog):
    case, bad, good = decisions()
    model = ParsingFinalModel([bad, good])
    budget = ModelCallBudget()

    result = run(model, case=case, budget=budget)

    assert result.action == "remediate" and result.review_node_id is None
    assert (budget.request_count, budget.output_repair_count) == (2, 1)
    repair = model.calls[1][-1].content
    assert "只有先修回顾可以指定复习节点" in repair
    assert '"loc"' in repair and '"type": "value_error"' in repair
    assert PRIVATE_MARKER not in repair
    assert json.dumps(bad, ensure_ascii=False) not in repair
    assert PRIVATE_MARKER not in caplog.text
    assert "review_node_id必须是JSON null" in model.calls[0][0].content


def test_nested_parser_field_error_keeps_field_location_but_not_input_value():
    case, _, good = decisions()
    bad = {**good, "action": "SECRET_UNSUPPORTED_ACTION", "reason": PRIVATE_MARKER}
    model = ParsingFinalModel([bad, good])

    run(model, case=case)

    repair = model.calls[1][-1].content
    assert '"loc": ["action"]' in repair
    assert "literal_error" in repair
    assert "SECRET_UNSUPPORTED_ACTION" not in repair
    assert PRIVATE_MARKER not in repair
    assert '"input"' not in repair


def test_copied_internal_context_is_named_as_forbidden_without_echoing_values():
    case, _, good = decisions()
    bad = {**good, "reason": PRIVATE_MARKER, "internal_state": {"private_answer": PRIVATE_MARKER}}
    model = ParsingFinalModel([bad, good])

    run(model, case=case)

    repair = model.calls[1][-1].content
    assert '"loc": ["internal_state"]' in repair
    assert "extra_forbidden" in repair
    assert PRIVATE_MARKER not in repair
    assert "private_answer" not in repair


def test_identity_repair_names_expected_values_without_accepting_foreign_identity():
    case, _, good = decisions()
    bad = {**good, 'project_id': 'foreign_project', 'reason': PRIVATE_MARKER}
    model = ParsingFinalModel([bad, good])
    budget = ModelCallBudget()
    result = run(model, case=case, budget=budget)
    assert result.project_id == case['quiz']['project_id']
    assert (budget.request_count, budget.output_repair_count) == (2, 1)
    repair = model.calls[1][-1].content
    for key in ('project_id', 'node_id', 'assessment_id'):
        assert json.dumps({key: case['quiz'][key]}, ensure_ascii=False)[1:-1] in repair
    assert PRIVATE_MARKER not in repair and 'foreign_project' not in repair
    assert '不能添加type' in repair


def test_continuous_current_node_for_remediate_stops_after_one_repair(caplog):
    case, bad, good = decisions()
    model = ParsingFinalModel([bad, bad, good])
    budget = ModelCallBudget()

    with pytest.raises(ModelOutputValidationError, match="只有先修回顾可以指定复习节点") as caught:
        run(model, case=case, budget=budget)

    assert len(model.calls) == 2
    assert (budget.request_count, budget.output_repair_count) == (2, 1)
    assert PRIVATE_MARKER not in str(caught.value)
    assert PRIVATE_MARKER not in caplog.text


def test_continuous_non_prerequisite_review_node_stops_without_third_request():
    case = make_case(prerequisites=["foundation"])
    bad = {**deepcopy(case["diagnosis"]), "action": "revisit_prerequisite", "review_node_id": "ghost"}
    model = ParsingFinalModel([bad, bad, case["diagnosis"]])
    budget = ModelCallBudget()

    with pytest.raises(ModelOutputValidationError, match="合法前置"):
        run(model, case=case, budget=budget)

    assert len(model.calls) == 2
    assert (budget.request_count, budget.output_repair_count) == (2, 1)


def test_unstructured_parser_error_falls_back_to_schema_advice_without_raw_echo():
    case, _, good = decisions()
    error = OutputParserException(
        "provider parser included " + PRIVATE_MARKER,
        llm_output="RAW_PRIVATE_RESPONSE " + PRIVATE_MARKER,
    )
    model = ParsingFinalModel([error, good])

    run(model, case=case)

    repair = model.calls[1][-1].content
    assert "只有revisit_prerequisite可填写review_node_id" in repair
    assert PRIVATE_MARKER not in repair
    assert "RAW_PRIVATE_RESPONSE" not in repair
