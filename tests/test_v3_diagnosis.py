from copy import deepcopy
import json

import httpx
from langchain_core.messages import AIMessage
from openai import APITimeoutError
import pytest

from app.services.llm import ModelCallBudget, ModelOutputValidationError
from app.v3.diagnosis import diagnose
from tests.test_v3_guard import make_case


class FinalOnly:
    def __init__(self, outputs):
        self.outputs = iter(outputs)
        self.final_calls = []

    def with_structured_output(self, *args, **kwargs):
        return self

    def invoke(self, messages):
        self.final_calls.append(messages)
        output = next(self.outputs)
        if isinstance(output, Exception):
            raise output
        return output(messages) if callable(output) else output


class ToolModel(FinalOnly):
    def __init__(self, selections, outputs):
        super().__init__(outputs)
        self.selections = iter(selections)
        self.tool_calls = []

    def bind_tools(self, tools):
        parent = self

        class Selector:
            def invoke(self, messages):
                parent.tool_calls.append(messages)
                output = next(parent.selections)
                if isinstance(output, Exception):
                    raise output
                return output
        return Selector()


def run(model, *, case=None, history=None, budget=None):
    case = case or make_case()
    return diagnose(quiz=case["quiz"], evaluation=case["evaluation"], node=case["node"],
                    policy=case["policy"], completed_node_ids=case["completed_node_ids"],
                    history=history or [], llm=model, budget=budget)


def history_record(case, *, project_id="project", node_id="foundation"):
    record = {"project_id": project_id, "node_id": node_id, "assessment_id": "previous_assessment",
              "evaluation": deepcopy(case["evaluation"]), "quiz": deepcopy(case["quiz"]), "answers": deepcopy(case["answers"])}
    for value in (record["evaluation"], record["quiz"]):
        value.update(project_id=project_id, node_id=node_id, assessment_id="previous_assessment")
    return record


def query(identity, *, node_id="foundation", name="get_learning_history", args=None):
    return {"id": identity, "name": name, "args": {"node_id": node_id} if args is None else args}


def ai(*calls):
    return AIMessage(content="", tool_calls=list(calls))


def malformed(*valid_calls):
    return AIMessage(content="", tool_calls=list(valid_calls), invalid_tool_calls=[{
        "name": "get_learning_history", "args": '{"node_id":', "id": "broken", "error": "invalid json"}])


def test_final_business_error_repairs_once_and_second_bad_output_stops():
    valid = make_case()["diagnosis"]
    bad = {**valid, "evidence_ids": ["invented"]}
    budget = ModelCallBudget()
    model = FinalOnly([bad, valid])
    assert run(model, budget=budget).action == "advance"
    assert budget.request_count == 2 and budget.output_repair_count == 1
    assert "evidence_id" in model.final_calls[1][-1].content
    with pytest.raises(ModelOutputValidationError):
        run(FinalOnly([bad, bad]))


@pytest.mark.parametrize("bad_change", [{"action": "execute_code"},
    {"action": "revisit_prerequisite", "review_node_id": "ghost"}, {"assessment_id": "another_assessment"}])
def test_illegal_action_review_or_assessment_identity_repairs_or_stops(bad_change):
    case = make_case(prerequisites=["foundation"])
    good = deepcopy(case["diagnosis"])
    bad = {**good, **bad_change}
    assert run(FinalOnly([bad, good]), case=case).action == "advance"
    with pytest.raises(ModelOutputValidationError):
        run(FinalOnly([bad, bad]), case=case)


def test_network_and_output_repair_share_at_most_three_requests():
    case = make_case()
    valid = case["diagnosis"]
    invalid = {**valid, "evidence_ids": ["invented"]}
    timeout = APITimeoutError(request=httpx.Request("POST", "https://example.invalid"))
    budget = ModelCallBudget()
    assert run(FinalOnly([timeout, invalid, valid]), budget=budget).action == "advance"
    assert (budget.request_count, budget.network_retry_count, budget.output_repair_count) == (3, 1, 1)


@pytest.mark.parametrize("mixed", [False, True])
def test_invalid_tool_call_repairs_before_any_partial_execution(mixed):
    case = make_case(prerequisites=["foundation"])
    broken = malformed(query("must_not_execute")) if mixed else malformed()
    model = ToolModel([broken, ai(query("repaired"))], [case["diagnosis"]])
    budget = ModelCallBudget()
    result = run(model, case=case, history=[history_record(case)], budget=budget)
    final_context = json.loads(model.final_calls[0][1].content)
    assert result.action == "advance"
    assert budget.request_count == 3 and budget.output_repair_count == 1
    assert "invalid_tool_calls" in model.tool_calls[1][-1].content
    assert final_context["tool_summary"]["tool_executions"] == 1
    assert final_context["tool_summary"]["tool_rounds"] == 1
    assert final_context["tool_summary"]["stopped_reason"] == "reserved_final_request"


def test_continuously_bad_tool_parameters_stop_before_final_diagnosis():
    case = make_case(prerequisites=["foundation"])
    model = ToolModel([malformed(), malformed()], [case["diagnosis"]])
    budget = ModelCallBudget()
    with pytest.raises(ModelOutputValidationError):
        run(model, case=case, history=[history_record(case)], budget=budget)
    assert budget.request_count == 2 and budget.output_repair_count == 1
    assert model.final_calls == []


def test_continuous_tool_requests_stay_within_two_rounds_three_executions():
    case = make_case(prerequisites=["foundation"])
    model = ToolModel([ai(query("a"), query("b")), ai(query("c"), query("d"))], [case["diagnosis"]])
    budget = ModelCallBudget()
    run(model, case=case, history=[history_record(case)], budget=budget)
    context = json.loads(model.final_calls[0][1].content)
    assert (context["tool_summary"]["tool_rounds"], context["tool_summary"]["tool_executions"]) == (2, 3)
    assert context["tool_summary"]["stopped_reason"] == "tool_limit"
    assert budget.request_count == 3


@pytest.mark.parametrize("bad_call", [query("unauthorized", node_id="other_node"),
    query("unauthorized", name="execute_code"), query("unauthorized", args={"node_id": {"bad": "shape"}}),
    query("unauthorized", args={"node_id": "foundation", "project_id": "another_project"})])
def test_unauthorized_tool_or_argument_shape_repairs_without_execution(bad_call):
    case = make_case(prerequisites=["foundation"])
    model = ToolModel([ai(bad_call), ai()], [case["diagnosis"]])
    run(model, case=case, history=[history_record(case)])
    context = json.loads(model.final_calls[0][1].content)
    assert context["tool_summary"]["tool_executions"] == 0


def test_cross_project_history_is_never_returned_or_used_as_evidence():
    case = make_case(prerequisites=["foundation"])
    forbidden = history_record(case, project_id="FORBIDDEN_TENANT")
    forbidden["evaluation"]["question_results"][0]["feedback"] = "PRIVATE_TENANT_SECRET"
    model = ToolModel([ai(query("read")), ai()], [case["diagnosis"]])
    run(model, case=case, history=[forbidden])
    context = json.loads(model.final_calls[0][1].content)
    serialized = json.dumps(context)
    assert "FORBIDDEN_TENANT" not in serialized and "PRIVATE_TENANT_SECRET" not in serialized
    assert context["queried_history_evidence"] == []
    assert context["tool_summary"]["queries"][0]["status"] == "no_history"


def test_queried_question_and_feedback_survive_into_fresh_final_call_without_private_key():
    case=make_case(prerequisites=['foundation'])
    record=history_record(case)
    record['quiz']['questions'][0]['prompt']='计算-8除以-2并解释。'
    record['evaluation']['question_results'][0]['feedback']='历史符号判断有误。'
    model=ToolModel([ai(query('read')),ai()],[case['diagnosis']])
    run(model,case=case,history=[record])
    context=json.loads(model.final_calls[0][1].content)
    historical=context['queried_history_records'][0]
    assert historical['questions'][0]['prompt']=='计算-8除以-2并解释。'
    assert historical['question_results'][0]['feedback']=='历史符号判断有误。'
    assert 'answer_key' not in json.dumps(context) and 'rubric' not in json.dumps(historical['questions'])
    unqueried=ToolModel([ai()],[case['diagnosis']])
    run(unqueried,case=case,history=[record])
    assert json.loads(unqueried.final_calls[0][1].content)['queried_history_records']==[]


def test_current_diagnosis_receives_frozen_criterion_meanings_not_just_numbers():
    from tests.test_v3_guard import text_case
    case=text_case()
    model=FinalOnly([case['diagnosis']])
    run(model,case=case)
    context=json.loads(model.final_calls[0][1].content)
    question=context['frozen_questions'][0]
    assert question['rubric'][0]['description']=='解释必要联系'
    assert question['rubric'][0]['criterion_id']=='essential'
    assert 'answer_key' not in json.dumps(question)


def test_queried_history_ids_are_namespaced_and_completion_does_not_exclude_weakness():
    case = make_case(prerequisites=["foundation"])
    case["completed_node_ids"] = ["foundation"]

    def final(messages):
        context = json.loads(messages[1].content)
        evidence = context["queried_history_evidence"][0]["evidence_id"]
        assert evidence.startswith("history:") and evidence not in {"e1", "e2"}
        return {**case["diagnosis"], "action": "revisit_prerequisite", "review_node_id": "foundation",
                "evidence_ids": ["e1", evidence], "reason": "当前错误与相关历史一致；过去完成不排除当前薄弱点。"}

    model = ToolModel([ai(query("read")), ai()], [final])
    result = run(model, case=case, history=[history_record(case)])
    assert result.action == "revisit_prerequisite" and result.review_node_id == "foundation"
    assert "过去完成不证明当前没有薄弱点" in model.final_calls[0][0].content


def test_non_graded_evaluation_cannot_be_repaired_into_advance():
    case = make_case()
    case["evaluation"].update(grading_status="needs_review", question_results=[], objective_results=[], evidence=[], uncertainty_reasons=["资料冲突"])
    valid = {**case["diagnosis"], "action": "collect_more_evidence", "evidence_ids": []}
    model = FinalOnly([case["diagnosis"], valid])
    assert run(model, case=case).action == "collect_more_evidence"


def test_history_without_original_quiz_still_checks_real_answer_anchors():
    case = make_case(prerequisites=["foundation"])
    record = history_record(case)
    del record["quiz"]
    record["answers"]["q1"] = "B"
    model = ToolModel([ai(query("read")), ai()], [case["diagnosis"]])
    run(model, case=case, history=[record])
    context = json.loads(model.final_calls[0][1].content)
    assert context["queried_history_evidence"] == []
    assert context["tool_summary"]["queries"][0]["status"] == "no_history"


@pytest.mark.parametrize("field,value", [("request_count", -1), ("max_requests", 4),
    ("max_requests", 0), ("max_output_repairs", 2), ("request_count", True)])
def test_diagnosis_rejects_tampered_budget_before_any_model_call(field, value):
    budget = ModelCallBudget()
    setattr(budget, field, value)
    model = FinalOnly([make_case()["diagnosis"]])
    with pytest.raises(ValueError, match="预算"):
        run(model, budget=budget)
    assert model.final_calls == []
