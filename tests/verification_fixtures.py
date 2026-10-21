"""External-provider review fixtures, never automatic production attestations."""
from hashlib import sha256
import json

from devwatch.review.contracts import FindingCandidate


def reviewed(candidate, refs, *, statuses=None):
    claim = FindingCandidate.model_validate(candidate).model_dump(mode='json')
    digest = sha256(json.dumps(claim, sort_keys=True, ensure_ascii=False,
                              separators=(',', ':')).encode()).hexdigest()
    return dict(candidate_digest=digest,
        causal_basis='For items=[], indexing element zero raises IndexError before a value can be returned.',
        assessments=[dict(field=field, status=(statuses or {}).get(field, 'supported'),
            explanation=('No additional remediation claim.' if not claim[field] else
                'The supplied source and input contract establish this complete field.'),
            evidence_refs=list(refs)) for field in ('title', 'description', 'impact', 'remediation')])


def decision(candidate, refs, *, identity='f1', verdict='confirmed', statuses=None, confidence=.9):
    return dict(finding_id=identity, verdict=verdict, confidence=confidence,
        rationale='Empty input reaches unguarded index zero.', evidence_refs=list(refs),
        causal_review=reviewed(candidate, refs, statuses=statuses))
