# M22 Streaming, Observability, and Recovery

Baseline: clean `1dac4bc` (M21). Status: complete for engineering and scoped live recovery verification.

Operational questions:

1. Which root or private graph node is running, for which role/task/attempt?
2. Did a model or tool fail, with which bounded diagnostic and charged usage?
3. Can nested events be replayed and correlated after interruption without
   repeating completed work or exporting source, arguments, or reasoning?
4. Does the existing browser still consume both historical and current events?

Slices, each with failing behavior tests before implementation:

1. Add paired graph-node events around real root and private graph execution.
   Preserve existing event names and metadata; node names/scopes are bounded.
   Verify starts are visible before work completes, correlated ends include
   elapsed time/outcome, and failures/cancellation retain safe diagnostics.
2. Improve opt-in LangSmith export with durable review/agent ancestry and
   chronological event runs, reconstructed from the local journal across
   exporter restarts. Keep inputs/outputs empty, private identifiers local,
   ambient tracing disabled, and unknown exports non-retryable.
3. Exercise real interruption/resume, nested stream/replay, source privacy,
   failure settlement, and old/new browser wire compatibility. Reuse existing
   recovery mechanisms rather than add a second checkpoint system.
4. Freeze sources, run backend checks and browser tests/build, review the diff,
   and perform bounded live observation/recovery using previously approved
   synthetic source/contracts only. Record every paid attempt and close the
   report with explicit limits; stop before M23.

Budget: shared conservative total US$3.74075775 of US$4. M22 allocation at most
US$0.15, leaving at least US$0.10924225 for later work. All prior unknown holds
remain charged. Reserve durably before dispatch, verified TLS, no telemetry
uploads to LangSmith during verification, no working-repository source or gold
labels sent to Gemini. Optional exporter is verified at its SDK boundary locally.

No new dependencies, model policy changes, broader data grants, authority changes,
quality-gate relaxation, commits, publication, or M23 execution are in scope.
