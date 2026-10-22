"""M23 intent-to-evaluate metrics; no model, production detector or gold upload."""
from collections import Counter
from math import sqrt


def trial_key(row):
    return (row['case_id'], row['mode'], row.get('evidence_mode', 'autonomous'))


def wilson95(successes, total):
    if not total:
        return None
    z = 1.959963984540054
    p, denominator = successes / total, 1 + z*z/total
    center = (p + z*z/(2*total)) / denominator
    radius = z * sqrt(p*(1-p)/total + z*z/(4*total*total)) / denominator
    return [max(0., center-radius), min(1., center+radius)]


def normal_completion(row):
    """A completed job with partial/uninspected tasks is not a complete review."""
    metrics = row['metrics']
    return (row['status'] == 'completed' and not row.get('provider_error_codes')
        and not row.get('coverage', {}).get('failed') and not row.get('quarantined_candidates')
        and metrics.get('inspected_source_fraction') == 1
        and not metrics.get('unknown_provider_calls') and not metrics.get('local_budget_refusals'))


def _latency(values):
    if not values:
        return None
    values = sorted(values)
    def percentile(p):
        index = (len(values)-1)*p
        lower = int(index)
        return values[lower] + (values[min(lower+1, len(values)-1)]-values[lower])*(index-lower)
    return dict(count=len(values), p50=percentile(.5), p95=percentile(.95), total=sum(values))


def summarize_release(rows, planned, *, live):
    """Missing positives count as misses; unavailable controls remain unknown.

    Provider errors are reported, never removed to improve precision/recall or
    completion. Trials are selected once before dispatch; duplicates are errors,
    not an invitation to select the best successful attempt.
    """
    plans, observed = {}, {}
    for target, source in ((plans, planned), (observed, rows)):
        for row in source:
            key = trial_key(row)
            if key in target:
                raise ValueError('duplicate evaluation trial')
            target[key] = row
    if set(observed)-set(plans):
        raise ValueError('unplanned evaluation trial')
    for key, row in observed.items():
        if row['gold'] != plans[key]['gold']:
            raise ValueError('evaluation labels changed')
        if row['score']['true_positive'] + row['score']['false_positive'] != len(row['findings']):
            raise ValueError('inconsistent finding counts')
    tp = sum(r['score']['true_positive'] for r in rows)
    fp = sum(r['score']['false_positive'] for r in rows)
    expected = sum(len(r['gold']) for r in planned)
    fn = expected-tp
    if fn < 0:
        raise ValueError('matches exceed planned labels')
    normal = [r for r in rows if normal_completion(r)]
    clean_plans = [k for k, r in plans.items() if not r['gold']]
    known_clean = [observed[k] for k in clean_plans if k in observed and
        (normal_completion(observed[k]) or observed[k]['findings'])]
    false_clean = sum(bool(r['findings']) for r in known_clean)
    findings = sum(len(r['findings']) for r in rows)
    source_valid = sum(round((r['score']['source_evidence_correctness'] or 0)*len(r['findings'])) for r in rows)
    classified = sum(r['metrics'].get('finding_kind_evaluated', 0) for r in rows)
    correct_kind = sum(r['metrics'].get('finding_kind_correct', 0) for r in rows)
    precision = tp / (tp+fp) if tp+fp else None
    recall = tp / expected if expected else None
    fpr = false_clean / len(known_clean) if known_clean else None
    completion = len(normal)/len(planned) if planned else None
    evidence = source_valid/findings if findings else None
    kind_accuracy = correct_kind/classified if classified else None
    unavailable = sum(r['status'] != 'completed' or bool(r.get('provider_error_codes'))
        or bool(r['metrics'].get('unknown_provider_calls')) or bool(r['metrics'].get('local_budget_refusals')) for r in rows)
    matched_kind = Counter()
    expected_kind = Counter(g['kind'] for r in planned for g in r['gold'])
    for r in rows:
        gold = {g.get('defect_id'):g for g in r['gold']}
        for match in r['score']['matches']:
            item = gold.get(match['defect_id']) or (r['gold'][0] if len(r['gold']) == 1 else None)
            if item:
                matched_kind[item['kind']] += 1
    screen_pass = bool(planned) and len(rows) == len(planned) and not unavailable and (
        completion >= .95 and (precision is None or precision >= .90)
        and (recall is None or recall >= .80) and (fpr is None or fpr <= .10)
        and (kind_accuracy is None or kind_accuracy >= .90) and (evidence is None or evidence == 1.))
    known_costs = [r['metrics'].get('approximate_cost_usd') for r in rows]
    return dict(planned_reviews=len(planned), attempted_reviews=len(rows),
        unattempted_reviews=len(plans)-len(observed), unavailable_reviews=unavailable,
        normal_completions=len(normal), normal_completion_rate=completion,
        true_positive=tp, false_positive=fp, false_negative=fn,
        precision=precision, recall=recall, precision_wilson95=wilson95(tp,tp+fp), recall_wilson95=wilson95(tp,expected),
        clean_cases_planned=len(clean_plans), clean_cases_evaluable=len(known_clean),
        clean_cases_unknown=len(clean_plans)-len(known_clean), clean_case_false_positive_rate=fpr,
        source_evidence_validity=evidence, finding_classification_accuracy=kind_accuracy,
        defect_recall=matched_kind['defect']/expected_kind['defect'] if expected_kind['defect'] else None,
        advisory_recall=matched_kind['advisory']/expected_kind['advisory'] if expected_kind['advisory'] else None,
        model_calls=sum(r['metrics']['model_calls'] for r in rows), tool_calls=sum(r['metrics']['tool_calls'] for r in rows),
        prompt_tokens=sum(r['metrics']['prompt_tokens'] for r in rows), output_including_unallocated_tokens=sum(r['metrics']['completion_tokens'] for r in rows),
        known_review_cost_subtotal_usd=sum(v for v in known_costs if v is not None),
        total_estimated_cost_usd=sum(known_costs) if len(rows) == len(planned) and all(v is not None for v in known_costs) else None,
        completed_review_latency_seconds=_latency([r['metrics']['latency_seconds'] for r in normal]),
        all_attempt_latency_seconds=_latency([r['metrics']['latency_seconds'] for r in rows]),
        screening_gate_pass=screen_pass, quality_gate_pass=live and screen_pass,
        human_reviewed=False, live_model_accuracy=None, population_reliability_established=False,
        metric_scope='Fixed authored-case facet/location/source screen, not independently adjudicated population accuracy.')


def trace_metrics(events):
    """Count real tool outcomes and scoped recoveries, not success-by-absence."""
    tools = [e['payload'] for e in events if e['kind'] == 'tool_result']
    recoverable = recovered = 0
    for index, call in enumerate(tools):
        if call.get('error_code') != 'recoverable_tool_error':
            continue
        recoverable += 1
        scope = tuple(call.get(k) for k in ('agent_id','task_id','tool'))
        recovered += any(later.get('outcome') == 'succeeded' and
            tuple(later.get(k) for k in ('agent_id','task_id','tool')) == scope for later in tools[index+1:])
    model_ends = [e['payload'] for e in events if e['kind'] == 'model_call_completed']
    return dict(tool_attempts=len(tools), tool_successes=sum(t.get('outcome') == 'succeeded' for t in tools),
        tool_call_success_rate=sum(t.get('outcome') == 'succeeded' for t in tools)/len(tools) if tools else None,
        recoverable_tool_failures=recoverable, recovered_tool_failures=recovered,
        tool_recovery_rate=recovered/recoverable if recoverable else None,
        model_outcomes=dict(Counter(p.get('outcome') for p in model_ends)))


def strict_regression_gate(rows, planned, *, live):
    """Known-case release gate: every label/control must pass, not just 80% recall."""
    result = summarize_release(rows, planned, live=live)
    return (result['quality_gate_pass'] and result['normal_completions'] == len(planned)
        and result['false_negative'] == result['false_positive'] == 0
        and result['finding_classification_accuracy'] in (None, 1.))
