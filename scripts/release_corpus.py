"""Fresh M23 authored pairs; never used by production prompts or detectors.

Gold is authored before any model trial. Public inputs use the evaluator's
files/contract allowlist. These small pairs are scoped generalization probes,
not statistically independent samples of real repositories.
"""
from copy import deepcopy


def load_release_corpus():
    families = [
        dict(family='null-fallback', specialist='logic_correctness',
            contract='Use the fallback only when value is None. Preserve 0, False and the empty string.',
            path='settings.py', broken='def choose(value, fallback):\n    return value or fallback\n',
            repaired='def choose(value, fallback):\n    return fallback if value is None else value\n', line=2,
            facets=[['false','zero','0','falsy'],['fallback','default','replac']], kind='defect'),
        dict(family='retry-limit', specialist='bug_reliability',
            contract='Call operation at most max_attempts times, including the first try. Return on success; otherwise propagate the final RuntimeError. max_attempts is a positive integer.',
            path='retry.py', broken='def retry(operation, max_attempts):\n    for attempt in range(max_attempts + 1):\n        try:\n            return operation()\n        except RuntimeError:\n            if attempt == max_attempts:\n                raise\n',
            repaired='def retry(operation, max_attempts):\n    for attempt in range(max_attempts):\n        try:\n            return operation()\n        except RuntimeError:\n            if attempt == max_attempts - 1:\n                raise\n', line=2,
            facets=[['attempt','retr'],['extra','one','+ 1','limit','exceed']], kind='defect'),
        dict(family='cross-file-units', specialist='logic_correctness',
            contract='schedule(now_ms, delay_seconds) returns the deadline in milliseconds. now_ms and delay_seconds are nonnegative numbers; constants.py defines the conversion.',
            path='schedule.py', extras={'constants.py':'MILLISECONDS_PER_SECOND = 1000\n'},
            broken='from constants import MILLISECONDS_PER_SECOND\n\ndef schedule(now_ms, delay_seconds):\n    return now_ms + delay_seconds\n',
            repaired='from constants import MILLISECONDS_PER_SECOND\n\ndef schedule(now_ms, delay_seconds):\n    return now_ms + delay_seconds * MILLISECONDS_PER_SECOND\n', line=4,
            facets=[['millisecond','1000'],['second','unit','convert']], kind='defect'),
        dict(family='exclusive-bound', specialist='logic_correctness',
            contract='contains(start, end, point) tests a half-open interval [start, end): start is included and end is excluded. Integers satisfy start <= end.',
            path='ranges.py', broken='def contains(start, end, point):\n    return start <= point <= end\n',
            repaired='def contains(start, end, point):\n    return start <= point < end\n', line=2,
            facets=[['end','upper','bound'],['includ','exclud','equal','exclusive']], kind='defect'),
        dict(family='sibling-path', specialist='architecture_security',
            contract='allows(root, candidate) returns True only for root or a path beneath root after resolving dot segments and symlinks. A sibling whose name merely starts with the root name must be rejected. Paths are local filesystem paths; no operation is performed by this predicate.',
            path='access.py', broken='from pathlib import Path\n\ndef allows(root, candidate):\n    return str(Path(candidate).resolve()).startswith(str(Path(root).resolve()))\n',
            repaired='from pathlib import Path\n\ndef allows(root, candidate):\n    return Path(candidate).resolve().is_relative_to(Path(root).resolve())\n', line=4,
            facets=[['prefix','startswith','sibling'],['allow','outside','boundary','reject']], kind='defect'),
        dict(family='secret-log', specialist='architecture_security',
            contract='record_login logs the username only. A password must never be included in log arguments or formatted log messages, even when authentication succeeds.',
            path='audit.py', broken='def record_login(logger, username, password):\n    logger.info("Login %s password=%s", username, password)\n',
            repaired='def record_login(logger, username, password):\n    logger.info("Login %s", username)\n', line=2,
            facets=[['password','secret'],['log','expos','disclos']], kind='defect'),
        dict(family='nested-copy', specialist='logic_correctness',
            contract='with_item(order, item) returns an independent order with item appended to its items list. The caller-owned order and nested items list must remain unchanged. Orders contain only ordinary dictionaries, lists, numbers and strings.',
            path='orders.py', broken='def with_item(order, item):\n    updated = dict(order)\n    updated["items"].append(item)\n    return updated\n',
            repaired='from copy import deepcopy\n\ndef with_item(order, item):\n    updated = deepcopy(order)\n    updated["items"].append(item)\n    return updated\n', line=3,
            facets=[['shallow','nested','list'],['mutat','shared','original','caller']], kind='defect'),
        dict(family='default-history', specialist='bug_reliability',
            contract='add_event(event) with no supplied history starts a fresh independent list on every call. When history is explicitly supplied, append to that list and return it.',
            path='history.py', broken='def add_event(event, history=[]):\n    history.append(event)\n    return history\n',
            repaired='def add_event(event, history=None):\n    if history is None:\n        history = []\n    history.append(event)\n    return history\n', line=1,
            facets=[['default','shared'],['list','histor','call']], kind='defect'),
        dict(family='weak-assertion', specialist='quality_testability',
            contract='The test must detect clamp(5, 0, 10) incorrectly returning 42. clamp returns the input bounded to the inclusive low/high range. Report inadequate test assertions as advisories.',
            path='test_clamp.py', extras={'clamp.py':'def clamp(value, low, high):\n    return min(high, max(low, value))\n'},
            broken='from clamp import clamp\n\ndef test_inside():\n    assert clamp(5, 0, 10) is not None\n',
            repaired='from clamp import clamp\n\ndef test_inside():\n    assert clamp(5, 0, 10) == 5\n', line=4,
            facets=[['assert','check'],['42','incorrect','wrong','value','result']], kind='advisory'),
        dict(family='prefix-sums', specialist='performance_scalability',
            contract='prefix_sums(values) returns all inclusive prefix sums in order. Input can contain millions of integers. Report unmeasured algorithmic complexity as an advisory; do not invent measured latency or memory limits.',
            path='totals.py', broken='def prefix_sums(values):\n    return [sum(values[:i + 1]) for i in range(len(values))]\n',
            repaired='from itertools import accumulate\n\ndef prefix_sums(values):\n    return list(accumulate(values))\n', line=2,
            facets=[['quadratic','o(n^2)','o(n²)','repeated'],['sum','prefix','slice']], kind='advisory'),
    ]
    cases = []
    for family in families:
        for defective in (True, False):
            files = {family['path']: family['broken' if defective else 'repaired'], **family.get('extras', {})}
            cases.append(dict(case_id=family['family']+('-defect' if defective else '-clean'),
                family=family['family'], language='python', specialist=family['specialist'], files=files,
                contract=family['contract'], split='m23-fresh-heldout',
                gold=[dict(defect_id=family['family'], file_path=family['path'], start_line=family['line'],
                    end_line=family['line'], facets=family['facets'], kind=family['kind'],
                    explanation=family['contract'])] if defective else []))
    return deepcopy(cases)


def load_repository_pair():
    """A larger synthetic repository, separate from the current working source."""
    common = {
        'shop/__init__.py':'"""Small synthetic order service."""\n',
        'shop/config.py':'MAX_ITEMS = 1000\nMILLISECONDS_PER_SECOND = 1000\n',
        'shop/labels.py':'def label(order):\n    return str(order["id"])\n',
        'shop/counts.py':'def count_items(order):\n    return len(order["items"])\n',
        'shop/validation.py':'def valid_quantity(quantity):\n    return isinstance(quantity, int) and not isinstance(quantity, bool) and quantity > 0\n',
        'shop/currency.py':'def cents_to_units(cents):\n    return cents / 100\n',
        'shop/lookup.py':'def by_id(orders, identity):\n    return next((order for order in orders if order["id"] == identity), None)\n',
        'shop/status.py':'def is_open(order):\n    return order["status"] == "open"\n',
        'shop/summary.py':'from shop.counts import count_items\nfrom shop.labels import label\n\ndef summarize(order):\n    return {"label": label(order), "count": count_items(order)}\n',
        'shop/ids.py':'def normalize_id(value):\n    return str(value).strip()\n',
    }
    rows = []
    source = next(c for c in load_release_corpus() if c['case_id'] == 'cross-file-units-defect')
    for defective in (True, False):
        schedule = ('from shop.config import MILLISECONDS_PER_SECOND\n\ndef schedule(now_ms, delay_seconds):\n'
            + ('    return now_ms + delay_seconds\n' if defective else '    return now_ms + delay_seconds * MILLISECONDS_PER_SECOND\n'))
        files = {**common, 'shop/schedule.py': schedule,
            'shop/service.py':'from shop.schedule import schedule\nfrom shop.summary import summarize\n\ndef response(order, now_ms, delay_seconds):\n    return {**summarize(order), "deadline_ms": schedule(now_ms, delay_seconds)}\n'}
        gold = [{**source['gold'][0], 'file_path':'shop/schedule.py'}] if defective else []
        rows.append(dict(case_id='repository-units'+('-defect' if defective else '-clean'),
            family='repository-units', specialist='logic_correctness', language='python', files=files,
            contract=source['contract']+' This repository is a synthetic order service. All orders contain id, items and status. Response must expose the correct deadline_ms. Other helpers are within the stated contracts.',
            gold=gold, split='m23-larger-synthetic'))
    return rows
