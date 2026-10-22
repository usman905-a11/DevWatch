"""Bounded mathematical assertions, never execution of reviewed or generated code.

The seam accepts a predicate over explicit finite integer domains. Receipts prove
only that predicate on that domain, not its relevance to source or nearby prose.
"""
import ast
from itertools import product
import operator
import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator


class ArithmeticModel(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)


class IntegerRange(ArithmeticModel):
    start: StrictInt = Field(ge=-(2**31), le=2**31 - 1)
    stop: StrictInt = Field(ge=-(2**31), le=2**31 - 1)
    step: StrictInt = Field(default=1, ge=1, le=2**31 - 1)

    @model_validator(mode='after')
    def nonempty(self):
        if self.start > self.stop:
            raise ValueError('integer domain must be nonempty')
        return self


class ArithmeticClaim(ArithmeticModel):
    field: Literal['title', 'description', 'impact', 'remediation']
    expression: str = Field(min_length=1, max_length=256)
    variables: dict[str, IntegerRange] = Field(default_factory=dict, max_length=4)

    @field_validator('variables')
    @classmethod
    def names(cls, value):
        if any(not re.fullmatch(r'[a-z][a-z0-9_]{0,15}', name)
               or name in {'and', 'or', 'not', 'in', 'is', 'for', 'if', 'else'} for name in value):
            raise ValueError('invalid integer variable name')
        return value

    def statement(self):
        domain = ', '.join(f'{name} in [{span.start}, {span.stop}] step {span.step}'
                           for name, span in sorted(self.variables.items()))
        return (f'For integers {domain}: ' if domain else 'Integer assertion: ') + self.expression + '.'


class ArithmeticCheck(ArithmeticModel):
    status: Literal['supported', 'contradicted', 'unknown']
    checked_assignments: int = Field(ge=0, le=4096)
    counterexample: dict[str, int] | None = None
    reason: str


class ArithmeticCounterexample(ArithmeticModel):
    claim_index: StrictInt = Field(ge=0, le=7)
    point: dict[str, Annotated[StrictInt, Field(ge=-(2**31), le=2**31 - 1)]] = Field(max_length=4)


_BINARY = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
           ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod,
           ast.BitAnd: operator.and_, ast.BitOr: operator.or_, ast.BitXor: operator.xor,
           ast.LShift: operator.lshift, ast.RShift: operator.rshift}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg, ast.Invert: operator.invert}
_COMPARE = {ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.Lt: operator.lt,
            ast.LtE: operator.le, ast.Gt: operator.gt, ast.GtE: operator.ge}
_NODES = {ast.Expression, ast.Constant, ast.Name, ast.Load, ast.BinOp, ast.UnaryOp,
          ast.Compare, ast.BoolOp, ast.And, ast.Or, ast.Not, *_BINARY, *_UNARY, *_COMPARE}


class _Unknown(ValueError):
    """A controlled reason code; never include raw expressions in diagnostics."""


def _integer(value):
    if type(value) is not int or value.bit_length() > 128:
        raise _Unknown('integer_limit_or_type')
    return value


def _boolean(value):
    if type(value) is not bool:
        raise _Unknown('predicate_requires_boolean')
    return value


def _parse(claim):
    expression = claim.expression
    if not expression.isascii() or len(expression) > 256:
        raise _Unknown('expression_limit')
    depth = 0
    for char in expression:
        if char == '(':
            depth += 1
        elif char == ')':
            depth -= 1
        if depth > 24 or depth < 0:
            raise _Unknown('expression_depth')
    try:
        tree = ast.parse(expression, mode='eval')
    except (SyntaxError, ValueError, RecursionError):
        raise _Unknown('unsupported_syntax') from None
    pending, count = [(tree, 0)], 0
    while pending:
        node, depth = pending.pop()
        count += 1
        if count > 64 or depth > 16:
            raise _Unknown('expression_complexity')
        if type(node) not in _NODES:
            raise _Unknown('unsupported_syntax')
        if isinstance(node, ast.Constant):
            _integer(node.value)
        if isinstance(node, ast.Name) and node.id not in claim.variables:
            raise _Unknown('unbound_variable')
        pending.extend((child, depth + 1) for child in ast.iter_child_nodes(node))
    return tree.body


def _evaluate(node, point):
    if isinstance(node, ast.Constant):
        return _integer(node.value)
    if isinstance(node, ast.Name):
        return _integer(point[node.id])
    if isinstance(node, ast.UnaryOp):
        value = _evaluate(node.operand, point)
        if isinstance(node.op, ast.Not):
            return not _boolean(value)
        return _integer(_UNARY[type(node.op)](_integer(value)))
    if isinstance(node, ast.BinOp):
        left, right = _integer(_evaluate(node.left, point)), _integer(_evaluate(node.right, point))
        if isinstance(node.op, (ast.LShift, ast.RShift)) and not 0 <= right < 128:
            raise _Unknown('shift_limit')
        if isinstance(node.op, (ast.FloorDiv, ast.Mod)) and right == 0:
            raise _Unknown('undefined_arithmetic')
        return _integer(_BINARY[type(node.op)](left, right))
    if isinstance(node, ast.Compare):
        left = _integer(_evaluate(node.left, point))
        for op, right_node in zip(node.ops, node.comparators):
            right = _integer(_evaluate(right_node, point))
            if not _COMPARE[type(op)](left, right):
                return False
            left = right
        return True
    if isinstance(node, ast.BoolOp):
        for child in node.values:
            value = _boolean(_evaluate(child, point))
            if isinstance(node.op, ast.And) and not value:
                return False
            if isinstance(node.op, ast.Or) and value:
                return True
        return isinstance(node.op, ast.And)
    raise _Unknown('unsupported_syntax')


def check_claim(claim: ArithmeticClaim) -> ArithmeticCheck:
    """Exhaust a bounded domain or return unknown; never sample a proof."""
    claim = ArithmeticClaim.model_validate(claim.model_dump())
    checked = 0
    try:
        tree = _parse(claim)
        names = sorted(claim.variables)
        domains, count = [], 1
        for name in names:
            span = claim.variables[name]
            domain = range(span.start, span.stop + 1, span.step)
            count *= len(domain)
            if count > 4096:
                raise _Unknown('domain_limit')
            domains.append(domain)
        for values in product(*domains):
            point = dict(zip(names, values))
            truth = _boolean(_evaluate(tree, point))
            checked += 1
            if not truth:
                return ArithmeticCheck(status='contradicted', checked_assignments=checked,
                    counterexample=point, reason='in_domain_counterexample')
        return ArithmeticCheck(status='supported', checked_assignments=checked,
            reason='entire_declared_domain_checked')
    except _Unknown as exc:
        return ArithmeticCheck(status='unknown', checked_assignments=checked, reason=str(exc))


def check_counterexample(claim: ArithmeticClaim, point: dict[str, int]) -> str:
    """A point refutes only the exact predicate, with the exact declared domain."""
    claim = ArithmeticClaim.model_validate(claim.model_dump())
    if set(point) != set(claim.variables):
        return 'out_of_domain'
    for name, span in claim.variables.items():
        value = point[name]
        if type(value) is not int or not span.start <= value <= span.stop or (value - span.start) % span.step:
            return 'out_of_domain'
    try:
        return 'does_not_contradict' if _boolean(_evaluate(_parse(claim), point)) else 'contradicts'
    except _Unknown:
        return 'unknown'
