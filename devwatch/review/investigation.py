"""Runtime-owned specialist goals, source requirements and retained candidates."""
from hashlib import sha256
import json

from devwatch.review.contracts import CandidateRejection, EvidenceProgress, InvestigationProgress
from devwatch.review.tool_errors import ToolFailure


class EvidenceInspectionRequired(ValueError):
    def __init__(self, rejections):
        super().__init__('Read source covering each candidate location and acknowledge its delivered pages with inspected_evidence.')
        self.rejections = rejections


def begin(task, private):
    if private.investigation is not None and private.investigation.required_files != sorted(set(task.files)):
        raise ValueError('investigation progress belongs to another source scope')
    if private.investigation is None:
        private.investigation = InvestigationProgress(goal=task.focus, required_files=sorted(set(task.files)))
    private.investigation.goal = task.focus
    refresh(private)


def remaining(private):
    inspected = {receipt.source_file for receipt in private.evidence_progress.values()
                 if receipt.source_file is not None and receipt.fully_inspected()}
    return sorted(set(private.investigation.required_files) - inspected)


def refresh(private):
    private.investigation.stage = 'investigating' if remaining(private) else 'ready'


def context(private):
    return dict(required_files=private.investigation.required_files, remaining_files=remaining(private),
                stage=private.investigation.stage)


def finish(private, reason):
    missing = remaining(private)
    for path in missing:
        private.coverage.skipped[path] = 'not_inspected'
    if reason == 'evidence_complete' and missing:
        reason = 'evidence_incomplete'
    private.investigation.stage = 'complete' if reason == 'evidence_complete' else 'stopped'
    return reason


def _inspection(private):
    value = [(ref, sorted(receipt.inspected)) for ref, receipt in sorted(private.evidence_progress.items())]
    return sha256(json.dumps(value).encode()).hexdigest()


def stalled(private, fingerprint):
    progress = private.investigation
    ref = progress.successful_actions.get(fingerprint)
    if ref is not None and private.evidence_progress.get(ref, EvidenceProgress()).fully_inspected():
        return True
    return (progress.last_action == fingerprint and progress.last_inspection == _inspection(private)
            and progress.stagnant_calls >= 1)


def observed(private, fingerprint, evidence_ref):
    progress = private.investigation
    inspected = _inspection(private)
    progress.stagnant_calls = (progress.stagnant_calls + 1 if progress.last_action == fingerprint
                              and progress.last_inspection == inspected else 0)
    progress.last_action, progress.last_inspection = fingerprint, inspected
    actions = dict(progress.successful_actions)
    actions.pop(fingerprint, None)
    actions[fingerprint] = evidence_ref
    progress.successful_actions = dict(list(actions.items())[-8:])


def retain(private, candidates):
    """Merge validated claim siblings without erasing earlier admitted work."""
    retained = {}
    for candidate in [*private.local_findings, *candidates]:
        claim = candidate.model_dump(mode='json', exclude={'evidence_refs', 'confidence', 'remediation'})
        key = sha256(json.dumps(claim, sort_keys=True).encode()).hexdigest()
        previous = retained.get(key)
        if previous is not None:
            candidate = candidate.model_copy(update={
                'evidence_refs':list(dict.fromkeys(previous.evidence_refs + candidate.evidence_refs))[:8],
                'confidence':min(previous.confidence, candidate.confidence)})
        retained[key] = candidate
    private.local_findings = list(retained.values())


def admit(task, private, output, validate):
    rejected = []
    for index, candidate in enumerate(output.candidates):
        try:
            if validate is not None:
                validate(candidate, task, private)
            elif not any(private.evidence_progress.get(ref, EvidenceProgress()).fully_inspected()
                         and private.evidence_progress[ref].source_file == candidate.location.file_path
                         for ref in candidate.evidence_refs):
                raise ValueError('candidate source not inspected')
        except ToolFailure as exc:
            if exc.code != 'evidence_not_found':
                raise
            rejected.append(CandidateRejection(index=index, title=candidate.title,
                reason='Candidate requires acknowledged source evidence covering its location.'))
        except (ValueError, LookupError) as exc:
            rejected.append(CandidateRejection(index=index, title=candidate.title,
                reason='Candidate requires acknowledged source evidence covering its location.'))
        else:
            retain(private, [candidate])
    private.quarantined_candidates.extend(item for item in output.quarantined if item not in private.quarantined_candidates)
    if rejected:
        raise EvidenceInspectionRequired(rejected)
    return output.model_copy(update={'candidates':list(private.local_findings),
                                     'quarantined':list(private.quarantined_candidates)})
