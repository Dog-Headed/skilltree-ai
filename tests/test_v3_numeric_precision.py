from decimal import localcontext

import pytest

from app.v3.evaluators import evaluate_numeric_scalar
from app.v3.guard import decide_progress
from tests.test_v3_evaluators import setup
from tests.test_v3_guard import numeric_case


def question(**rules):
    quiz,*_=setup(('numeric_scalar',))
    value=quiz.questions[0].model_dump()
    value['numeric_rules'].update(expected=2.0,abs_tolerance=0.0,rel_tolerance=0.0,**rules)
    return value


@pytest.mark.parametrize('answer',[
    '2.000000000000000000000000001','2.0000000000000000000000000001',
    '1.9999999999999999999999999999','20000000000000000000000000001e-28',
    '2.'+'0'*350+'1'])
def test_exact_numeric_comparison_never_rounds_an_unequal_answer_into_full_score(answer):
    result=evaluate_numeric_scalar(question(),answer)
    assert result.grading_status=='graded' and result.result.score==0.0
    assert result.evidence[0].quote==answer
    # A forged old rounded full-score record is rejected by the same guard.
    with pytest.raises(ValueError,match='数值评分'):
        decide_progress(**numeric_case(answer=answer,numeric_value=2.0,score=90.0))
    assert not decide_progress(**numeric_case(answer=answer,numeric_value=2.0,score=0.0)).passed


@pytest.mark.parametrize('answer',['2','2.0000000000000000000000000000','20000000000000000000000000000e-28'])
def test_exact_equivalent_scalar_still_passes(answer):
    result=evaluate_numeric_scalar(question(),answer)
    assert result.result.score==result.result.max_score
    assert decide_progress(**numeric_case(answer=answer)).passed


@pytest.mark.parametrize('answer,correct',[
    ('200 cm',True),('2e3 mm',True),('200.00000000000000000000000001 cm',False),
    ('2000.0000000000000000000000001 mm',False)])
def test_unit_normalization_preserves_all_decimal_digits(answer,correct):
    result=evaluate_numeric_scalar(question(unit='m',allowed_units=['m','cm','mm']),answer)
    assert (result.result.score==result.result.max_score)==correct


@pytest.mark.parametrize('relative,answer,correct',[
    (False,'2.01',True),(False,'2.0100000000000000000000000001',False),
    (True,'2.000002',True),(True,'2.0000020000000000000000000001',False)])
def test_absolute_and_relative_tolerance_edges_are_exact(relative,answer,correct):
    value=question();value['numeric_rules']['rel_tolerance' if relative else 'abs_tolerance']=0.000001 if relative else 0.01
    outcome=evaluate_numeric_scalar(value,answer)
    assert (outcome.result.score==outcome.result.max_score)==correct


def test_mutating_decimal_context_cannot_change_grading_or_conversion():
    with localcontext() as context:
        context.prec=2
        result=evaluate_numeric_scalar(question(unit='m',allowed_units=['m','cm']),'200.001 cm')
        assert result.result.score==0.0
        assert evaluate_numeric_scalar(question(unit='m',allowed_units=['m','cm']),'200 cm').result.score>0
