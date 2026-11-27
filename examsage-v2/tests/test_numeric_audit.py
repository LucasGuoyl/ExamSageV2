import pytest
from examsage.numeric_audit import evaluate_expression, audit_numerical_check


def test_recompute_from_conditions_and_compare_answer():
    result=audit_numerical_check({'label':'voltage','expression':'sqrt(3)*I*R','inputs':{'I':10,'R':2},
        'unit':'V','source_value':34.64,'atol':.01,'rtol':0})
    assert result['computed_value']==pytest.approx(34.641016)
    assert result['comparison']=='agrees'
    result=audit_numerical_check({**result,'source_value':40,'computed_value':40,'comparison':'agrees'})
    assert result['comparison']=='mismatch' and result['computed_value']!=40
    assert audit_numerical_check({**result,'source_value':None})['comparison']=='not_reported'


def test_safe_math_supports_power_probability_and_angles():
    assert evaluate_expression('comb(n,k)*p**k*(1-p)**(n-k)',{'n':3,'k':2,'p':.5})==.375
    assert evaluate_expression('degrees(atan2(1,1))',{})==45
    assert evaluate_expression('cos(pi)*exp(0)+log(e)',{})==pytest.approx(0)


@pytest.mark.parametrize('expression,expected', [
    ('2^3', 8), ('2^3^2', 512), ('-2^2', -4), ('(-2)^2', 4),
    ('2^(-677886.0457341605/300000)', 0.2088269547228607),
])
def test_mathematical_caret_means_bounded_exponentiation(expression, expected):
    assert evaluate_expression(expression, {}) == pytest.approx(expected)


@pytest.mark.parametrize('expression,inputs',[
    ('__import__("os").getcwd()',{}),('x.real',{'x':1}),('[1][0]',{}),
    ('sum(x for x in [1])',{}),('float("inf")',{}),('1e309',{}),
    ('1/0',{}),('(-1)**0.5',{}),('2**999999',{}),('comb(999999,9)',{}),
    ('x',{'x':float('nan')}),('x',{'x':True}),('pi',{'pi':3}),
    ('abs(x)',{'x':'1'}),('2 if 1 else 0',{}),('missing',{}),
    ('2^999999',{}),('(-1)^0.5',{}),('2^__import__("os").getpid()',{}),
])
def test_untrusted_expressions_rejected(expression,inputs):
    with pytest.raises(ValueError):evaluate_expression(expression,inputs)


@pytest.mark.parametrize('changes',[{'atol':-1},{'rtol':float('nan')},{'source_value':True},{'source_value':float('inf')}])
def test_invalid_answer_comparison_rejected(changes):
    with pytest.raises(ValueError):audit_numerical_check({'expression':'1','inputs':{},'source_value':1,**changes})
