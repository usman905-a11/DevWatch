"""Release metrics never turn missing/unavailable reviews into successful controls."""
import importlib
import json
from pathlib import Path

import pytest

from scripts.evaluate_agents import review_input
from scripts.release_corpus import load_release_corpus, load_repository_pair


def api(name):
    spec = importlib.util.find_spec('scripts.evaluate_release')
    assert spec, 'M23 release metric module is required'
    return getattr(importlib.import_module('scripts.evaluate_release'), name)


def planned():
    return [dict(case_id='broken', mode='full', evidence_mode='autonomous', gold=[dict(kind='defect')]),
        dict(case_id='clean', mode='full', evidence_mode='autonomous', gold=[])]


def row(identity='broken', **updates):
    data = dict(case_id=identity, mode='full', evidence_mode='autonomous', status='completed',
        provider_error_codes=[], coverage={'failed':{}}, quarantined_candidates=[],
        gold=[dict(kind='defect')] if identity == 'broken' else [],
        findings=[dict(kind='defect')] if identity == 'broken' else [],
        score=dict(true_positive=int(identity == 'broken'), false_positive=0, false_negative=0,
            source_evidence_correctness=1.0 if identity == 'broken' else None,
            matches=[dict(defect_id='a', finding_index=0)] if identity == 'broken' else []),
        metrics=dict(inspected_source_fraction=1.0, finding_kind_evaluated=int(identity == 'broken'),
            finding_kind_correct=int(identity == 'broken'), unknown_provider_calls=0, local_budget_refusals=0,
            latency_seconds=2., model_calls=2, tool_calls=1, prompt_tokens=100, completion_tokens=50,
            approximate_cost_usd=.001))
    data.update(updates)
    return data


def test_complete_paired_screen_passes_with_explicit_small_sample_uncertainty():
    result = api('summarize_release')([row(), row('clean')], planned(), live=True)
    assert result['quality_gate_pass']
    assert result['planned_reviews'] == result['attempted_reviews'] == result['normal_completions'] == 2
    assert result['recall'] == result['precision'] == 1
    assert result['clean_case_false_positive_rate'] == 0
    assert 0 < result['recall_wilson95'][0] < 1
    assert result['human_reviewed'] is False and result['population_reliability_established'] is False


def test_unattempted_positive_is_a_miss_and_missing_clean_case_is_unknown():
    result = api('summarize_release')([], planned(), live=True)
    assert not result['quality_gate_pass']
    assert result['false_negative'] == 1 and result['recall'] == 0
    assert result['unattempted_reviews'] == 2 and result['normal_completion_rate'] == 0
    assert result['clean_case_false_positive_rate'] is None


@pytest.mark.parametrize('change', [dict(status='failed'), dict(provider_error_codes=['provider_timeout']),
    dict(coverage={'failed': {'task':'invalid_schema'}}), dict(quarantined_candidates=[{'reason':'schema'}]),
    dict(metrics={**row()['metrics'], 'inspected_source_fraction':0.5}),
    dict(metrics={**row()['metrics'], 'unknown_provider_calls':1}),
    dict(metrics={**row()['metrics'], 'local_budget_refusals':1})])
def test_partial_or_unavailable_run_stays_in_completion_denominator(change):
    result = api('summarize_release')([row(**change), row('clean')], planned(), live=True)
    assert not result['quality_gate_pass']
    assert result['planned_reviews'] == result['attempted_reviews'] == 2
    assert result['normal_completion_rate'] == .5


def test_duplicate_trial_keys_are_rejected_instead_of_selecting_best_attempt():
    with pytest.raises(ValueError, match='duplicate'):
        api('summarize_release')([row(), row()], planned(), live=True)


def test_offline_programmed_responses_cannot_pass_the_live_release_gate():
    result = api('summarize_release')([row(), row('clean')], planned(), live=False)
    assert result['screening_gate_pass'] and not result['quality_gate_pass']
    assert result['live_model_accuracy'] is None


def test_false_positive_negative_controls_fail_fixed_gate():
    clean = row('clean', findings=[dict(kind='advisory')],
        score={**row('clean')['score'], 'false_positive':1, 'source_evidence_correctness':1.0})
    result = api('summarize_release')([row(), clean], planned(), live=True)
    assert not result['quality_gate_pass']
    assert result['clean_case_false_positive_rate'] == 1


def test_public_manifest_has_no_gold_and_covers_all_new_pairs():
    cases = load_release_corpus() + load_repository_pair()
    manifest = json.loads(Path('tasks/m23-live-inputs.json').read_text())
    assert len(cases) == len(manifest['cases']) == 22
    assert len({c['case_id'] for c in cases}) == 22
    assert sum(bool(c['gold']) for c in cases) == 11
    assert all(set(review_input(c)) == {'files','contract'} for c in cases)
    assert {c['case_id']:review_input(c) for c in cases} == {c['case_id']:c['payload'] for c in manifest['cases']}
    assert all(len(c['files']) == 12 for c in load_repository_pair())


def test_tool_recovery_requires_a_later_success_in_the_same_task_and_tool():
    def event(task, outcome, error=None):
        return dict(kind='tool_result', payload=dict(agent_id='logic_correctness', task_id=task,
            tool='read_source', outcome=outcome, error_code=error))
    metrics = api('trace_metrics')([event('a','failed','recoverable_tool_error'), event('b','succeeded')])
    assert metrics['tool_recovery_rate'] == 0 and metrics['tool_call_success_rate'] == .5
    metrics = api('trace_metrics')([event('a','failed','recoverable_tool_error'), event('a','succeeded')])
    assert metrics['tool_recovery_rate'] == 1
    assert api('trace_metrics')([])['tool_recovery_rate'] is None


def test_original_regression_gate_requires_every_target_not_the_heldout_threshold():
    plans, rows = [], []
    for i in range(10):
        target = {**planned()[0], 'case_id':f'known-{i}'}
        plans.append(target)
        current = row(target['case_id'], gold=target['gold'], findings=[dict(kind='defect')],
            score=row()['score'], metrics=row()['metrics'])
        if i == 0:
            current.update(findings=[], score={**current['score'], 'true_positive':0, 'false_negative':1, 'matches':[]},
                metrics={**current['metrics'], 'finding_kind_evaluated':0,'finding_kind_correct':0})
        rows.append(current)
    assert api('summarize_release')(rows, plans, live=True)['quality_gate_pass']
    assert not api('strict_regression_gate')(rows, plans, live=True)
