"""Independent arithmetic must never inherit a model's verdict or scope."""
import pytest
from pydantic import ValidationError

from devwatch.review.arithmetic import ArithmeticClaim, check_claim, check_counterexample


def claim(expression, **domains):
    return ArithmeticClaim(field='description', expression=expression,
        variables={name: dict(start=span[0], stop=span[1], step=span[2] if len(span) > 2 else 1)
                   for name, span in domains.items()})


def test_odd_xor_predecessor_is_one_not_unchanged_input():
    assertion = claim('(n ^ (n - 1)) == 1', n=(1, 31, 2))
    result = check_claim(assertion)
    assert result.status == 'supported'
    assert result.checked_assignments == 16
    assert result.counterexample is None
    assert check_counterexample(assertion, {'n': 3}) == 'does_not_contradict'
    assert check_counterexample(assertion, {'n': 2}) == 'out_of_domain'
    assert check_counterexample(assertion, {'n': -1}) == 'out_of_domain'


def test_false_low_bit_clause_has_an_actual_in_domain_counterexample():
    result = check_claim(claim('((n ^ (n - 1)) & 1) == 0', n=(1, 31, 2)))
    assert result.status == 'contradicted'
    assert result.counterexample == {'n': 1}
    assert result.checked_assignments == 1


def test_wrong_generalization_cannot_hide_zero_sum_counterexample():
    assertion = claim('a + b != 0', a=(-1, 1), b=(-1, 1))
    result = check_claim(assertion)
    assert result.status == 'contradicted'
    assert result.counterexample == {'a': -1, 'b': 1}
    assert check_counterexample(assertion, result.counterexample) == 'contradicts'


def test_point_proof_never_certifies_an_unenumerated_domain():
    assert check_claim(claim('(n ^ (n - 1)) == 1', n=(3, 3))).checked_assignments == 1
    result = check_claim(claim('(n ^ (n - 1)) == 1', n=(1, 2147483647, 2)))
    assert result.status == 'unknown'
    assert result.checked_assignments == 0


@pytest.mark.parametrize('expression', [
    '__import__("os").getcwd() == 1', '(1).__class__ == 1', '[1][0] == 1',
    '2 ** 1000000 == 0', '1 << 1000000 == 0', '1 // 0 == 0', '1 / 2 == 0',
    'True == 1', '1.0 == 1', 'unknown == 1', 'n + 1',
    '1 == 1 or __import__("os")', '(x for x in n)',
])
def test_unsupported_or_unsafe_calculations_are_unknown_not_executed(expression):
    result = check_claim(claim(expression, n=(1, 1)))
    assert result.status == 'unknown'
    assert result.counterexample is None


def test_integer_growth_and_expression_nesting_are_bounded():
    assert check_claim(claim('(n * n) * (n * n) == 0', n=(2147483647, 2147483647))).status == 'contradicted'
    assert check_claim(claim('((n * n) * (n * n)) * n == 0', n=(2147483647, 2147483647))).status == 'unknown'
    assert check_claim(claim('(' * 40 + '1 == 1' + ')' * 40)).status == 'unknown'


@pytest.mark.parametrize('domain', [dict(start=2, stop=1), dict(start=1, stop=2, step=0),
                                   dict(start=True, stop=3), dict(start=0, stop=2**64)])
def test_empty_ambiguous_or_unbounded_domains_cannot_be_proofs(domain):
    with pytest.raises(ValidationError):
        ArithmeticClaim(field='description', expression='n == n', variables={'n': domain})


def test_forged_counterexample_requires_exact_names_and_integer_values():
    assertion = claim('n == 1', n=(1, 3))
    assert check_counterexample(assertion, {'n': 2}) == 'contradicts'
    for point in ({'n': True}, {'n': 1.0}, {}, {'n': 2, 'm': 1}, {'n': 4}):
        assert check_counterexample(assertion, point) == 'out_of_domain'


def test_candidate_binding_does_not_certify_a_different_prose_clause(tmp_path):
    from tests.test_m20_verification import setup
    from devwatch.review.contracts import FindingCandidate
    _, _, _, candidate = setup(tmp_path)
    assertion = claim('(n ^ (n - 1)) == 1', n=(3, 3))
    candidate['arithmetic_claims'] = [assertion.model_dump()]
    candidate['description'] = 'XOR flips the lowest set bit.'
    with pytest.raises(ValidationError, match='canonical'):
        FindingCandidate.model_validate(candidate)
    candidate['description'] = 'For integers n in [3, 3] step 1: (n ^ (n - 1)) == 1.'
    assert FindingCandidate.model_validate(candidate).arithmetic_claims[0] == assertion
