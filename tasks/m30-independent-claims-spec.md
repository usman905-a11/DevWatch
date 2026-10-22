# M30: independent arithmetic evidence and preserved disagreements

## Objective and authority

The user authorized implementing the independent-evidence approach after the
M29 diagnosis. This milestone addresses two issues: unchecked arithmetic and
automatic loss of a candidate when model judgments conflict. It does not claim
to prove unrestricted natural language or arbitrary program behavior.

The seven existing identities, read-only source access, call/time/token limits,
source inspection, candidate binding and budget accounting remain authoritative.
No additional provider, dependency, source execution or external publication.

## Contract and architecture

1. An optional bounded `arithmetic_claims` list on a candidate declares integer
   predicates and finite domains. Each assertion must appear verbatim in its
   associated field using the runtime's canonical rendering. This prevents an
   unrelated correct calculation from certifying a false explanatory sentence.
2. A pure checker enumerates the entire declared domain, or returns unknown.
   A concrete witness proves only that point. A finite domain never proves a
   larger domain, caller precondition, program semantics or remediation safety.
   No model-generated success flags are trusted. Runtime receipts bind the
   candidate digest, assertion, outcome, checked count and any counterexample.
3. False predicates veto positive admission. Unsupported syntax, resource bounds
   or undefined arithmetic yield uncertainty, not falsehood. Passing assertions
   cannot promote a model verdict or certify surrounding prose.
4. Conflicting model verdicts become uncertain with both original judgments
   retained. A computed contradiction can reject. Rejected candidates also get
   the bounded second pass; disagreement is symmetric. No third model vote.
5. Acceptance recomputes arithmetic evidence. Reports expose coverage and state
   that unencoded prose remains model-reviewed. Historical reports and failed
   campaigns remain immutable. Checkpoint policy changes invalidate old decisions.

## Trust model

The attacker/model controls expressions, domains, prose and returned judgments.
Assets are host execution authority, availability and report integrity. The new
boundary accepts only strict integers, bounded variable names, finite ranges and
an AST allowlist. No calls, attributes, subscripts, containers, comprehensions,
imports, eval, exec or compilation. Bound input bytes, nesting, AST size, integer
bits, shifts and total assignments before work. Validate every AST branch even
if runtime evaluation would short circuit. Never execute reviewed source.

The official [Python AST documentation](https://docs.python.org/3/library/ast.html)
warns that even literal evaluation can exhaust resources. Parsing is bounded
before AST creation; arithmetic is interpreted explicitly with operation limits.
An assertion is about mathematical integers, not implicit Java overflow or any
other source-language execution model. Source relevance remains a separate review.

## Slices and acceptance

- Checker and candidate contract (arithmetic module, contracts, focused tests):
  correct point/universal results, real in-domain counterexamples, no vacuous
  success, unknown on excess work, exact text binding, hostile syntax refused.
- Admission and reconciliation (verification, subgraphs, focused tests): both
  judgments retained, symmetric disagreement, computed falsehood wins, no upgrade
  from a passing calculation, old checkpoint cannot bypass new policy.
- Reporting and verification (finalization, wire export/types, report tests):
  recomputed receipts and explicit coverage survive JSON/Markdown/PDF consumers;
  full regression and approved live inputs only after offline checks pass.

## Commands, structure and style

Use `.venv/Scripts/python.exe -m pytest tests/test_m30_arithmetic_claims.py -q`
and the focused verification/finalization tests, then the existing full-suite
shard runner with a new immutable freeze. Export contracts with
`.venv/Scripts/python.exe scripts/export_review_contracts.py` and use the existing
frontend test/build commands. Production code lives in `devwatch/review`; tests
in `tests`; milestone evidence in `tasks/evidence`.

Prefer pure functions and immutable results, e.g. `check_claim(claim)` returns
an outcome rather than logging or writing state. Use existing Pydantic contracts
with forbidden extra keys and additive defaults. Preserve caller-owned objects.

## Boundaries and remaining work

Always retain failures, recompute evidence and distinguish mathematical coverage
from whole-claim correctness. Never execute generated/source code, silently
rewrite candidates, sample a universal claim and call it proven, or spend beyond
the US$9 total and narrower approved envelopes. Ask only for genuinely new data
transfer authority after preparing the exact payload.

M31 must assess natural model adoption and remaining unencoded explanations,
then finish the three previously skipped synthetic reviews within approved caps.
M30 cannot honestly close arbitrary free-form semantic reliability by itself.
