# M31 reliability remediation

Status: COMPLETE for the explicitly selected conservative publication policy.
The original automatic-confirmation release gate remains unmet.

The user explicitly selected conservative publication: claims without independent
whole-claim verification remain uncertain, including agreement by two reviewers.
The same rule preserves model-only rejections as uncertain candidates. This is a
publication guarantee, not a guarantee that every candidate is true or every bug
is detected. No independent whole-claim proof adapter currently exists, so the
canonical service does not automatically publish confirmations or advisories.

## Changes

1. Arithmetic assertions remain typed, bounded and candidate-version bound.
   Runtime renders canonical statements in the audit. Requiring the model to
   reproduce an identical sentence in prose caused the observed punctuation
   failure and has been removed. The contextual field association does not prove
   that field. Passed calculations never promote prose; unsupported syntax is
   unknown. A computed false asserted predicate may reject the complete candidate.
   Schema diagnostics identify safe known fields/constraints without echoing
   arbitrary values, within the unchanged one-repair limit.
2. Retained candidates cannot end an investigation while required source or
   contract inspection is missing. Feedback names the missing paths and the
   read/acknowledgment protocol. Existing limits apply; no receipts are fabricated.
3. Canonical verification, final acceptance, checkpoint recovery and partial
   recovery enforce conservative publication. Original candidate wording and
   model observations remain available. Old verification policies cannot bypass
   current checks. Decision evidence retains the verifier's inspected provenance.

Candidate detection and confirmed-quality scores are separate. The original
confirmed precision/recall gate remains unmet with no automatic confirmations;
its thresholds and exit behavior have not been weakened. Retained uncertain
alternatives can still count as duplicates in the original live score. A separate,
preregistered policy check permits matched uncertain alternatives but never an
unmatched false positive or missed labeled defect.

## Evidence and limits

The focused red run reproduced two failures under the former duplicate-encoding
validator; after the fix, 53 focused tests passed. The public first campaign is
preserved at `evidence/m31-public-live-run-01.json`: 3/4 policy passes, with the
remaining failure caused by exact punctuation binding after the one repair.
Its production sources are archived in `evidence/m31-public-original-production.zip`.
The subsequent campaign has a separate preregistered protocol and evidence names.

The initial full 801-test run retained four retry failures: the expanded guidance
consumed admission headroom after two conservatively charged failed calls. Compact
guidance v6.2 preserves every constraint without raising limits. A fresh 46-test
recheck passes; the entire final 801-test suite passes with zero failures, errors,
skips or omitted/duplicated identities (`evidence/m31-backend-04/summary.json`).
Frontend 57 tests, TypeScript/Vite production build, and wire-schema freshness pass.
The independent static reviewer found no Required or Critical changes; this review
did not make provider calls or replace test evidence.

| Final live scenario | Policy | Original strict score |
| --- | --- | --- |
| Public bitcount defect, full/autonomous | Pass | Fail: retained duplicate uncertain alternatives and uncertainty classification |
| Public bitcount clean, full/autonomous | Pass | Pass |
| Public bitcount defect, specialist/provided | Pass | Pass |
| Malformed arithmetic range, specialist/provided | Pass, one repair | Pass |
| Iterator defect, full/autonomous | Pass | Fail: uncertainty classification |
| Iterator clean, full/autonomous | Pass | Pass |

These six scenarios use previously exposed fixtures, not a fresh holdout. The raw
specialist outputs are proposals, not accepted positive reports. Final full reports
contain only uncertain candidates, confidence at most 0.5. Both clean controls have
no findings. All six have complete source coverage and normal completion; there
are no unmatched false positives or missed labeled defects. One duplicate uncertain
alternative remains in the public defect report and still counts as an original
false-positive/duplicate. Free-form candidate wording is still model judgment.

Across **all 11 M31 attempts**, the retained totals are **9 policy passes and
7 original strict passes**. Two failed attempts remain: the original punctuation
failure, and the fourth public-03 trial whose repair dispatch exceeded the phase's
remaining maximum-token reservation. The latter had no unknown effects and was
rechecked in its own preregistered US$0.05 phase, which passed. No failed result was
overwritten. `m31-public-02` was preflight-only, superseded before any paid calls.

M31 conservative cost is **US$0.20862375**, shared usage **US$7.524597**, remaining
**US$1.475403** of the unchanged US$9 total. The amended synthetic envelope uses
US$0.61331025 of US$0.80; the original public envelope uses US$0.79112775 of US$1.40.
All provider charges reconcile; no new unknown effects exist. Historical unknown
holds of US$0.12293325 remain included. The user approved the synthetic-envelope
increase without adding total budget; the exact answer is recorded in the approval
amendment. Its earlier transcription typo is archived separately.

Historical failed attempts and unknown-effect reservations remain retained. No
commit, push, deployment, repository-source transfer, or new LangSmith trace export
was performed. The original confirmation release gate remains unmet by design;
future automatic confirmation needs a trusted proof adapter plus fresh representative
evaluation. Broader recall and semantic accuracy are not established by these checks.

Closing integrity, credential scan, source archive and process-drain evidence is
recorded in `evidence/m31-closing-review.json`. There are no remaining implementation
issues in the three-item selected scope. A future trusted whole-claim proof adapter
is required to enable automatic confirmation; another model vote is insufficient.
