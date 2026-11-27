"""Bounded scalar arithmetic for source-parameter checks; never executes Python."""
import ast
import math
import operator

FUNCTIONS={name:getattr(math,name) for name in ('sqrt','exp','log','log10','sin','cos','tan','asin','acos','atan','atan2','degrees','radians','hypot')}
FUNCTIONS.update(abs=abs,min=min,max=max,round=round)
CONSTANTS={'pi':math.pi,'e':math.e}
OPERATORS={ast.Add:operator.add,ast.Sub:operator.sub,ast.Mult:operator.mul,ast.Div:operator.truediv,ast.Mod:operator.mod}


def finite(value):
    if type(value) not in (int,float) or not math.isfinite(value) or abs(value)>1e200:
        raise ValueError('Expected a finite real scalar within arithmetic bounds')
    return value


def evaluate_expression(expression: str, inputs: dict) -> float:
    if not isinstance(expression,str) or len(expression)>2000 or not isinstance(inputs,dict) or len(inputs)>80:
        raise ValueError('Invalid numerical expression/inputs')
    for name,value in inputs.items():
        if not isinstance(name,str) or not name.isidentifier() or name.startswith('_') or name in CONSTANTS or name in FUNCTIONS or name=='comb':
            raise ValueError('Invalid or reserved input name')
        finite(value)
    try:
        # This is a mathematical scalar language: ^ and ** both mean power.
        # Normalize before parsing so precedence matches exponentiation, not XOR.
        tree=ast.parse(expression.replace('^','**'),mode='eval')
        if sum(1 for _ in ast.walk(tree))>300:raise ValueError('Expression too complex')
        def visit(node):
            if isinstance(node,ast.Constant):return finite(node.value)
            if isinstance(node,ast.Name):
                if node.id in inputs:return inputs[node.id]
                if node.id in CONSTANTS:return CONSTANTS[node.id]
                raise ValueError('Unknown numerical input')
            if isinstance(node,ast.UnaryOp) and type(node.op) in (ast.USub,ast.UAdd):
                value=visit(node.operand)
                return -value if isinstance(node.op,ast.USub) else value
            if isinstance(node,ast.BinOp):
                left,right=visit(node.left),visit(node.right)
                if isinstance(node.op,ast.Pow):
                    if abs(right)>1000:raise ValueError('Exponent exceeds arithmetic bound')
                    return finite(left**right)
                if type(node.op) in OPERATORS:return finite(OPERATORS[type(node.op)](left,right))
            if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and not node.keywords and 1<=len(node.args)<=20:
                args=[visit(arg) for arg in node.args]
                if node.func.id=='comb':
                    if len(args)!=2 or any(int(v)!=v for v in args) or not 0<=args[1]<=args[0]<=1000:raise ValueError('Invalid bounded combination')
                    return finite(math.comb(*(int(v) for v in args)))
                if node.func.id in FUNCTIONS:return finite(FUNCTIONS[node.func.id](*args))
            raise ValueError('Unsupported numerical syntax')
        return float(finite(visit(tree.body)))
    except (ArithmeticError,TypeError,SyntaxError,RecursionError,ValueError) as error:
        raise ValueError('Cannot safely recompute numerical expression: '+str(error)) from None


def audit_numerical_check(check: dict) -> dict:
    computed=evaluate_expression(check['expression'],check.get('inputs',{}))
    atol=finite(check.get('atol',0.000001));rtol=finite(check.get('rtol',0.001))
    if atol<0 or rtol<0:raise ValueError('Negative numerical tolerance')
    reported=check.get('source_value')
    verdict='not_reported'
    if reported is not None:
        finite(reported)
        verdict='agrees' if math.isclose(computed,reported,rel_tol=rtol,abs_tol=atol) else 'mismatch'
    return {**check,'computed_value':computed,'comparison':verdict}
