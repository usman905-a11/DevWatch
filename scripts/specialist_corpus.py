"""M19 held-out cases; labels and split metadata stay outside reviewer inputs."""
from scripts.evaluate_agents import load_corpus


def load_specialist_corpus():
    cases=[dict(case,split='regression') for case in load_corpus()]
    families=[
        ('cleanup','bug_reliability','subject.py',
         'Read and decode the acquired handle. Close it exactly once on success and when decode raises; propagate the decode exception.',
         'def load(handle, decode):\n    value = decode(handle.read())\n    handle.close()\n    return value\n',
         'def load(handle, decode):\n    try:\n        return decode(handle.read())\n    finally:\n        handle.close()\n',
         2,3,[['clos','leak','cleanup'],['except','rais','fail']], 'medium','defect',
         'A decode exception exits before close, leaving the acquired handle open.'),
        ('window','logic_correctness','subject.py',
         'Given a list of integer rows, a nonnegative zero-based cursor and a positive integer limit, return at most limit rows starting at cursor.',
         'def page(rows, cursor, limit):\n    return rows[cursor:cursor + limit + 1]\n',
         'def page(rows, cursor, limit):\n    return rows[cursor:cursor + limit]\n',
         2,2,[['limit'],['extra','one','bound','slice','exceed']], 'medium','defect',
         'The exclusive stop includes one extra row, exceeding the documented positive limit.'),
        ('tautology','quality_testability','test_subject.py',
         'total returns the normal integer sum of a list of integers. This test must fail if total([2, 3]) returns an incorrect integer.',
         'def test_total():\n    from subject import total\n    actual = total([2, 3])\n    assert actual == actual\n',
         'def test_total():\n    from subject import total\n    actual = total([2, 3])\n    assert actual == 5\n',
         4,4,[['assert','tautolog','itself','same'],['test','result','actual']], 'low','advisory',
         'Comparing the returned normal integer with itself cannot detect an incorrect integer sum.'),
        ('indirect_query','architecture_security','subject.py',
         'request is a mapping whose query value is untrusted text. Look up a user by that name and keep SQL data separate from query syntax.',
         'def lookup(db, request):\n    name = request["query"]\n    statement = "SELECT id FROM users WHERE name = \'" + name + "\'"\n    return db.execute(statement).fetchone()\n',
         'def lookup(db, request):\n    name = request["query"]\n    statement = "SELECT id FROM users WHERE name = ?"\n    return db.execute(statement, (name,)).fetchone()\n',
         3,4,[['sql','query'],['untrusted','inject','concatenat','parameter']], 'high','defect',
         'The request value propagates through name into SQL syntax instead of a bound data parameter.'),
        ('prefix','performance_scalability','subject.py',
         'Return inclusive prefix sums for a list of integers; input may have millions of values. Report unmeasured complexity concerns as advisories, not measured timing claims.',
         'def prefixes(values):\n    return [sum(values[:i + 1]) for i in range(len(values))]\n',
         'def prefixes(values):\n    result, total = [], 0\n    for value in values:\n        total += value\n        result.append(total)\n    return result\n',
         2,2,[['quadratic','o(n^2)','o(n²)','repeated','recomput'],['sum','prefix','slice']], 'medium','advisory',
         'Repeated growing slices and sums perform quadratic work although one running total suffices; outputs remain correct.'),
    ]
    for family,role,path,contract,broken,clean,start,end,facets,severity,kind,explanation in families:
        for defective,source in ((True,broken),(False,clean)):
            files={path:source}
            if family=='tautology': files['subject.py']='def total(values):\n    return sum(values)\n'
            cases.append(dict(case_id=family+('-defect' if defective else '-clean'),family=family,
                split='held-out',language='python',specialist=role,files=files,contract=contract,
                gold=[dict(defect_id=family,file_path=path,start_line=start,end_line=end,facets=facets,
                    severity=severity,kind=kind,explanation=explanation)] if defective else []))
    return cases
