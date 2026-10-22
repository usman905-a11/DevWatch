"""Executable witnesses for pre-labelled, locally authored M23 fixtures only."""
import ast
from collections import Counter
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from scripts.release_corpus import load_release_corpus, load_repository_pair


FAMILIES = sorted({case['family'] for case in load_release_corpus()})


def namespace(case):
    path = next(p for p in case['files'] if p not in {'constants.py','clamp.py'})
    values = {'__name__':'authored_release_fixture'}
    constants = SimpleNamespace(MILLISECONDS_PER_SECOND=1000)
    # These exact fixture literals were authored locally; never execute an
    # arbitrary reviewed repository or provider-generated command in a witness.
    with patch.dict('sys.modules', {'constants':constants, 'shop.config':constants,
            'clamp':SimpleNamespace(clamp=lambda *args:42)}):
        exec(compile(case['files'][path], '<authored-M23-fixture>', 'exec'), values)
    return values


def satisfies(case, tmp_path):
    ns, family = namespace(case), case['family']
    if family == 'null-fallback':
        return all(ns['choose'](value, 'fallback') == value for value in (0, False, ''))
    if family == 'retry-limit':
        calls = []
        def operation():
            calls.append(1)
            raise RuntimeError('synthetic failure')
        with pytest.raises(RuntimeError):
            ns['retry'](operation, 2)
        return len(calls) == 2
    if family == 'cross-file-units':
        return ns['schedule'](1000, 2) == 3000
    if family == 'exclusive-bound':
        return ns['contains'](0,1,0) and not ns['contains'](0,1,1)
    if family == 'sibling-path':
        return not ns['allows'](tmp_path/'data', tmp_path/'data-other')
    if family == 'secret-log':
        calls = []
        ns['record_login'](SimpleNamespace(info=lambda *args:calls.append(args)), 'alice', 'synthetic-secret-817')
        return 'synthetic-secret-817' not in repr(calls)
    if family == 'nested-copy':
        order = {'items':[1]}
        result = ns['with_item'](order, 2)
        return order['items'] == [1] and result['items'] == [1,2]
    if family == 'default-history':
        first, second = ns['add_event']('a'), ns['add_event']('b')
        return first == ['a'] and second == ['b']
    if family == 'weak-assertion':
        try:
            ns['test_inside']()
        except AssertionError:
            return True
        return False
    if family == 'prefix-sums':
        operations = Counter()
        class Counted:
            def __init__(self, value): self.value = value
            def __add__(self, other):
                operations['add'] += 1
                return Counted(self.value + (other.value if isinstance(other, Counted) else other))
            __radd__ = __add__
        result = ns['prefix_sums']([Counted(i) for i in range(20)])
        assert [v.value for v in result] == [sum(range(i+1)) for i in range(20)]
        return operations['add'] <= 20
    raise AssertionError('Missing independent witness')


@pytest.mark.parametrize('family', FAMILIES)
def test_each_prelabelled_defect_fails_and_its_repair_satisfies_contract(family, tmp_path):
    rows = [c for c in load_release_corpus() if c['family'] == family]
    assert len(rows) == 2
    broken, repaired = rows
    assert broken['gold'] and not repaired['gold']
    assert broken['contract'] == repaired['contract']
    assert not satisfies(broken, tmp_path)
    assert satisfies(repaired, tmp_path)
    label = broken['gold'][0]
    ast.parse(broken['files'][label['file_path']])
    assert 1 <= label['start_line'] <= label['end_line'] <= len(broken['files'][label['file_path']].splitlines())


def test_larger_repository_pair_has_same_public_contract_and_independent_units_witness():
    broken, repaired = load_repository_pair()
    def deadline(case):
        source = case['files']['shop/schedule.py']
        with patch.dict('sys.modules', {'shop.config':SimpleNamespace(MILLISECONDS_PER_SECOND=1000)}):
            values = {}
            exec(compile(source, '<authored-repository-schedule>', 'exec'), values)
        return values['schedule'](1000,2)
    assert broken['contract'] == repaired['contract']
    assert deadline(broken) == 1002 and deadline(repaired) == 3000
