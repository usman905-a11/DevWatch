"""Held-out labels have executable, independently checked synthetic witnesses."""
from types import SimpleNamespace

import pytest

from scripts.evaluate_agents import review_input


def corpus():
    from scripts.specialist_corpus import load_specialist_corpus
    return load_specialist_corpus()


def pair(family):
    cases = [case for case in corpus() if case['family']==family and case['split']=='held-out']
    assert len(cases)==2
    return sorted(cases,key=lambda case:not bool(case['gold']))


def namespace(case):
    result = {}
    exec(case['files']['subject.py'],result)
    return result


def test_corpus_keeps_original_regressions_and_balanced_held_out_roles_without_label_leaks():
    cases = corpus()
    assert len(cases)==22 and len({case['case_id'] for case in cases})==22
    assert sum(case['split']=='regression' for case in cases)==12
    held_out = [case for case in cases if case['split']=='held-out']
    assert len({case['specialist'] for case in held_out})==5
    for family in {case['family'] for case in held_out}:
        broken,clean = pair(family)
        assert len(broken['gold'])==1 and clean['gold']==[]
        assert broken['contract']==clean['contract']
        for case in (broken,clean):
            assert set(review_input(case))=={'files','contract'}
            for defect in case['gold']:
                assert 1<=defect['start_line']<=defect['end_line']<=len(case['files'][defect['file_path']].splitlines())


def test_cleanup_label_matches_exception_path_and_clean_finally():
    class Handle:
        closed = 0
        def read(self): return 'payload'
        def close(self): self.closed += 1
    def decode(_): raise ValueError('synthetic decode failure')
    for case,closed in zip(pair('cleanup'),(0,1)):
        handle = Handle()
        with pytest.raises(ValueError): namespace(case)['load'](handle,decode)
        assert handle.closed==closed


def test_window_label_matches_documented_limit():
    for case,expected in zip(pair('window'),([10,20,30],[10,20])):
        assert namespace(case)['page']([10,20,30],0,2)==expected


def test_tautology_label_matches_wrong_return_value_that_still_passes(monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules,'subject',SimpleNamespace(total=lambda values:7))
    broken,clean = pair('tautology')
    def run(case):
        scope={}
        exec(case['files']['test_subject.py'],scope)
        scope['test_total']()
    run(broken)
    with pytest.raises(AssertionError): run(clean)


def test_indirect_query_label_matches_untrusted_syntax_versus_bound_data():
    class DB:
        def execute(self,*arguments): self.arguments=arguments; return self
        def fetchone(self): return None
    value="' OR 1=1 --"
    for case in pair('indirect_query'):
        db=DB()
        namespace(case)['lookup'](db,{'query':value})
        if case['gold']:
            assert value in db.arguments[0] and len(db.arguments)==1
        else:
            assert db.arguments==('SELECT id FROM users WHERE name = ?', (value,))


def test_prefix_label_is_repeated_work_without_wrong_output_or_wall_clock_claim():
    class Values(list):
        copied=0
        def __getitem__(self,key):
            result=super().__getitem__(key)
            if isinstance(key,slice): self.copied+=len(result)
            return result
    for case,copied in zip(pair('prefix'),(10,0)):
        values=Values([1,2,3,4])
        assert namespace(case)['prefixes'](values)==[1,3,6,10]
        assert values.copied==copied
