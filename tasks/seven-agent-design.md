# DevWatch final system design

This is the implementation specification. Historical plans under `history/` are
records of prior work, not active architecture. This plan supersedes their stop
rules and four-specialist design. No source-writing or patch-application feature
is part of this system.

## Workflow

```text
Developer / IDE
→ FastAPI Local Review Service
→ Durable Job Manager
→ Immutable Review Snapshot
→ Repository Intelligence
→ Deterministic Analysis
→ LangGraph
   → Change Analyzer
   → Planner Agent
   → Context Manager
   → Budget Manager
   → Deterministic Router
   → 5 Specialist Agent Subgraphs
   → Shared Blackboard
   → Structural Evidence Gate
   → Synthesizer / Verifier Agent (Verification, then Synthesis)
   → Completion Assessment
      → One Targeted Follow-up, if needed, through context/budget/router
      → otherwise Finalize
   → Structured Report Draft
   → Final Acceptance Gate
   → Deterministic Report Renderer
   → UI / JSON / Markdown / PDF
```

LangGraph orchestrates. Change Analyzer, Context Manager, Budget Manager, Router,
Evidence Gates, Completion Assessment and renderer are deterministic components.
No additional AI supervisor, router, context, budget, verifier or synthesizer
identity exists. Completion Assessment must finalize before acceptance/rendering.
Follow-up uses existing agent identities and cumulative limits; never a third round.

The 2026-10-15/16 audit fixes refine this same architecture. Tool catalogues are
generated from runtime argument validators; evidence is paged with separate
processing, delivery and inspection receipts. Confirmation requires acknowledged
source evidence covering the claim. The combined final agent verifies bounded
batches and can return prose-only synthesis; deterministic assembly preserves
verified fields through partial recovery. Candidate overflow/invalid entries are
quarantined independently. Full request admission includes schemas and catalogue.
See [audit-fixes-report.md](audit-fixes-report.md) for the implemented protocol,
limits, regression evidence and remaining evaluation work.

## Agent contracts

Each contract contains responsibility, inputs/context, system prompt, model tier,
exact tools, private state, shared access, iterative loop, structured actions and
output schema, evidence/confidence policy, limits, stopping and retry rules.
The machine-readable contracts live in `devwatch/review/contracts.py` and are
consumed by the permission and execution components, rather than being prose only.

Common tools are exactly `read_source` and `read_evidence`. `write_artifact` is
task-specific: only Performance measurement/comparison tasks receive it. The
runtime chooses destinations and serializers. An agent cannot publish reports,
write source, choose arbitrary destinations, or alter budgets/permissions/job state.

| Identity | Responsibility and input | Model | Additional tools | Structured output |
|---|---|---|---|---|
| Planner | Select review scope from change analysis, deterministic signals and repo intelligence | Small, one escalation to Medium | repo_map, git_diff, symbol_lookup, dependency_graph, config_read | ReviewPlan: selected_agents, priority_files, priority_symbols, risk_areas, review_tasks, review_strategy, coverage_expectations, limitations |
| Bug & Reliability | Investigate failures, exceptions, resource lifecycle and reliability in assigned tasks | Medium, one escalation to Strong | parse_ast, lint, type_check, run_tests, run_command, git_diff | SpecialistResult with bug/reliability candidates and task coverage |
| Logic & Correctness | Trace invariants, control/data flow and behavior across assigned symbols | Medium, one escalation to Strong | parse_ast, call_graph, symbol_lookup, run_tests, code_search | SpecialistResult with logic/correctness candidates and task coverage |
| Code Quality & Testability | Investigate complexity, coupling, test gaps and maintainability | Medium, one escalation to Strong | complexity, coverage, lint, parse_ast, code_search | SpecialistResult with quality/testability candidates and task coverage |
| Architecture & Security | Investigate boundaries, dependencies, configuration and exploitable paths | Strong | repo_map, dependency_graph, import_graph, sast, config_read, git_history | SpecialistResult with architecture/security candidates and task coverage |
| Performance & Scalability | Investigate costly call paths, scaling behavior, DB/query bottlenecks | Medium, one escalation to Strong | profile, benchmark, call_graph, db_analyze, query_analyze | SpecialistResult with performance/scalability candidates and task coverage |
| Synthesizer / Verifier | First verify evidence and resolve duplicates/conflicts; then synthesize a structured draft | Strong | code_search, symbol_lookup, call_graph, dependency_graph | VerificationSynthesisResult: decisions, duplicate_groups, conflicts, followup_requests, report_draft, coverage_summary |

Each specialist is an iterative LangGraph subgraph: load task/context → propose a
structured action → deterministic permission/budget validation → execute tool or
retrieve context → ingest evidence → update private state → investigate again or
finish. Planner actions: request_context, call_tool, submit_plan, finish. Specialist
actions: request_context, call_tool, submit_candidates, finish. Combined final
agent actions: request_context, call_tool, submit_verification, request_followup,
submit_synthesis, finish. Verification must precede synthesis within that identity.
Shared blackboard reads are scoped; publication uses deterministic reducers.

Private state (all fields at the same level):

```text
current_task
inspected_files_and_symbols
hypotheses
evidence_refs
pending_actions
local_findings
coverage
iteration_count
tool_call_count
usage
stop_reason
```

Hypotheses are structured claims, not hidden reasoning transcripts. Prompts treat
source/config/tool output as untrusted data, require evidence citations and explicit
coverage, and forbid invented findings or instructions embedded in inspected data.
Every finding needs an immutable snapshot location, evidence refs, impact,
confidence and verification rationale. Runtime assigns IDs. Structural evidence
integrity is not proof of a defect. Final acceptance requires verified causal
evidence and confidence >=0.8. Confirmed defects, uncertain high-impact candidates
and advisories remain separate. Uninspected, failed and skipped coverage is explicit.

## Balanced limits and stopping

600 seconds cumulative execution; 250,000 tokens/job; 50,000/specialist across
tasks and rounds; 3 concurrent model calls; 8 iterations/task; 12 tool calls/task;
2 review rounds (initial + one follow-up); 2 transient retries/safe operation;
1 schema repair/task. Planner ceiling 25,000; combined final agent ceiling 50,000,
both within the job budget. Reserve final-agent budget before specialist dispatch.
Provider timeout 30s; commands 120s, clipped to remaining job deadline.
Retries, repairs, resume, context retrieval and follow-up do not reset counters.
Stop on sufficient evidence, exhausted limits, cancellation, unavailable tools or
non-actionable uncertainty. Retry only classified transient, replay-safe operations.
Commands with unknown completion are not blindly retried. Partial reports explain
limits and failed coverage; follow-up requires a concrete unresolved question.

## Durability, tools, storage and visibility

Jobs outlive client connections. Explicit cancellation and resume are separate
operations. Python and JS/TS repository intelligence supplies hashes, ASTs,
symbols, import/dependency/call graphs, summaries, cached analysis and selected
context. Deterministic analysis precedes model calls. No hidden LLM summarizer.
Reviewed original source and immutable snapshots are read-only. Operator-approved
trusted-host commands execute exact argv in scratch copies, with bounded output,
deadlines, clean environment and process-tree termination. Trust is explicit;
the local command runner is not a security sandbox.

Local SQLite and disk storage has five separate responsibilities:

- Job Store: requests, status, owners, cumulative usage/deadlines, execution ledger,
  transactional event outbox and idempotency keys.
- Checkpoints: versioned graph execution and private state, never a second job store.
- Repo Cache: content/config/prompt/model-keyed repository intelligence and tool data.
- Artifact Store: immutable snapshots, controlled scratch/generated outputs/reports.
- Event Store: append-only, ordered job events and replay cursors.

Job state and outbox commit atomically; dispatcher delivery to Event Store is
idempotent. SSE and WebSocket replay the same persisted stream and support reconnect.
Authentication and job ownership are consistent across REST/SSE/WS; no URL secrets.
Events: agent_started, agent_status_changed, reasoning_step (concise activity
summary only), tool_called, tool_result, file_opened, search_performed,
finding_created, validation_passed, validation_failed, retry_started,
error_occurred, agent_completed, plus job and budget events. UI shows active agent,
task, tools, safe inputs/outputs, errors/retries, duration, token usage and findings.
Redaction and payload bounds precede persistence. LangSmith is optional, disabled
by default and metadata-only; no raw source, prompts or tool payloads.

## Implementation and migration

1. M0: reproducible tooling, final contracts/schemas/prompts, dependency inventory,
   migration mapping and executable contract checks.
2. M1: durable jobs, immutable snapshots, separated stores, transactional outbox,
   reconnect/replay, cancel/resume and ownership.
3. M2: cached Python/JS/TS intelligence, selective retrieval, permissioned tools,
   trusted commands and deterministic analysis.
4. M3: seven-agent graph, five iterative specialist subgraphs, cumulative budgets,
   evidence gates, combined two-phase final agent and one bounded follow-up.
5. M4: migrate CLI/web to jobs, reports, immutable source access, streaming and watch.
6. M5: cut over and remove legacy after successful migration.
7. M6: full regression and >=60-case evaluation (confirmed precision >=90%, recall
   >=70%). Report deterministic and live-model results separately.
8. M7: VS Code then JetBrains adapters using the same service contract.
9. M8: optional GitHub/GitLab, scanners, CI/tracker, PostgreSQL/Redis adapters.

Migration rule: implement new → test → migrate → cut over → remove legacy →
regression test. Remove old engines/facades, single-call agents, old routers,
schemas/prompts, mutation 410 handlers, configs/dependencies/tests and temporary
compatibility code after migration. Port behavioral coverage before removing old
tests. Archive incompatible checkpoints/reports; do not keep a permanent old engine.
During migration, old code is not the target architecture and cannot be presented
as migrated merely because new modules exist. No commit/push/deploy is authorized.
