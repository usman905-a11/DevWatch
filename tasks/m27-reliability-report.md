# M27 - Broader evidence and telemetry availability

PARTIAL, 2026-10-21. Engineering and measurement work is verified; the original
quality gate failed and follow-up M28 is required. No failed case is relabelled.

The SDK now retains missing/null reasoning usage as unavailable while preserving
explicit zero/positive values. Five SDK HTTP-boundary controls pass after three
missing/null cases reproduced zero invention. Eighty returned live observations
all have unavailable reasoning counts: zero explicit zeros and zero positives.
That does not establish zero internal thinking. Severity and causal tool necessity
remain unavailable without predictions/labels and a causal experiment.

The deprecated LangSmith wrapper import originated in a provider test. A synthetic
forbidden-wrapper module keeps raw-tracing attempts failing without importing the
deprecated package. Focused warning-as-error checks pass; no dependency update or
warning suppression was added. A follow-up deadline test's five-second setup guard
was raised to 30 seconds; its simulated 600-second deadline and recovery assertions
are unchanged. Another CLI polling guard timed out in the full run and is handled
in M28. Neither guard represents a production latency SLA.

Eight pinned MIT-licensed QuixBugs Python/Java defect/clean programs were tested
in full, autonomous-specialist and provided-specialist modes. Revision:
4257f44b0ff1181dedaedee6a447e133219fcebf. Raw hashes, license and normalization are
retained; upstream JSONL and owned math witnesses support labels. Downloaded
programs were not executed. Java uses source fallback, not a claimed native AST.
Upstream: [QuixBugs](https://github.com/jkoppel/QuixBugs).

Live primary gates: **23/24**, full **7/8**, autonomous specialist **8/8**, provided
specialist **8/8**. All code/license source ranges were inspected. The Python
bitcount clean full review incorrectly reports negative input as a defect, despite
the nonnegative contract. One specialist and both verifier passes saw only the
code; another specialist saw the contract and correctly returned no defect. This
is a concrete loss of caller context, not a gold-label change. M28 adds explicit
pinned shared context. A raw bitcount description also overgeneralizes n-1=0 to all
odd integers; n=3 is a counterexample. M28's quantified-claim checks include it.
Author review covered all 13 emitted findings; it is not independent human gold.

Backend: **749 passed, 1 failed** out of the complete 750-test collection. The
failure is the CLI test's five-second polling guard; every test identity is
accounted for and no test was skipped. Source freeze, wire parity, compilation,
diff and credential checks pass. Frontend was unchanged from M24's earlier
55-test/build verification; no fresh frontend claim is made.

Two separately approved synthetic LangSmith traces were sent once and both read
back with ancestry and empty inputs/outputs. Transient read errors preceded
successful readback; writes were not replayed. Exporter and installed SDK client
hashes remain unchanged. This proves API ingestion for those two traces, not UI
rendering or delivery under every fault. No source, prompt, secret or model call
was involved in that probe.

M27 cost **US$0.34953300**. Conservative shared spend **US$6.77127000 / US$9**,
remaining **US$2.22873000**. No new unknown effects or cap refusals; historical
US$0.09968775 holds remain charged. M28 will use approved payloads inside both
existing envelopes and the same total, without another budget grant.

Small public programs may be memorized and are not broad production repositories.
Independent whole-claim human accuracy, alternate providers and production SLAs
remain unproven. Evidence: evidence/m27-closing-review.json (complete=false,
phase_drained=true), m27-live-run-01.json, m27-whole-claim-review.json,
m27-backend-01/summary.json, m27-source-archive.json and the metadata probe receipt.
No commit, push, PR or deployment was performed.
