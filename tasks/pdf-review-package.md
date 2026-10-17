# Deterministic PDF continuation review

Authority: tasks/seven-agent-design.md; ledger: tasks/progress.md, PDF continuation.
Scope: new review/pdf.py, report PDF methods in stores.py, executor render_report
and two FinalizationWorkflow renderer arguments, service PDF branch, client PDF
and CLI format/output handling, browser bounded-byte request and PDF method,
DurableApp download branch/button, pyproject/constraints and associated tests.
README/inventory/todo record this slice. Previous unrelated dirty work is outside
scope; no separate agent identity, prompt, budget, schema or graph order changes.

Focus: accepted-only rendering; Completion before acceptance/PDF; normal and
partial/deadline paths; immutable source separation; owned report directories,
hash/size/tamper checks; path/symlink confinement and atomic writes; cancellation/
thread work; persisted references and restart/reconnect; Unicode/font policy;
literal XML/URL handling (no remote resources or active links); deterministic bytes,
thread safety and bounded work; long paragraphs/pagination/no blank pages; finalized
only HTTP/downloads, client binary/MIME/size checks, exclusive CLI output, missing
PDF behavior and dependency declarations. Do not confuse PDF support with live
provider accuracy, tagged accessibility, watch migration or full M5 completion.

Tests: new test_pdf_reports; added store integrity and service owned/deterministic
PDF assertions; two CLI cases; two browser client tests; real Chrome download with
actual ASGI/graph/stores and scripted provider. 377 backend tests passed before a
visually found trailing-Spacer fix; its targeted regression now passes; final
full suite rerun underway. 46 frontend tests/build pass. Actual accepted sample
and six-page long literal/coverage sample rendered and inspected.

Review source only. Do not edit, run code/network/providers, install, or delegate.
Report Critical/Important/Minor findings and declined-to-judge items, with exact
file/line and practical effect. One fresh final review, then at most one required
RED->GREEN fix pass. Two previous UI minors remain deferred and outside this slice.

Review disposition: two Important findings fixed in one RED->GREEN pass through
isolated/reaped runtime workers and locked direct document builds. Repeated-space
finding regraded Important because literals can change meaning; RED->GREEN fixed.
Final full backend: 381 passed, three existing Windows symlink skips; frontend 46
passed/build green; real browser PDF/other export/recovery flow green. No re-review.
