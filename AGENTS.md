# Global Codex Instructions

This file defines default behavior across projects. Apply instructions in this order:
system and developer instructions, the user's current request, the nearest project-level
`AGENTS.md`, then this file. Treat this file as a default, not as permission to expand scope.

## Global skill resolution

The skills referenced here are installed globally; they do not need to exist inside the current project.

The routed skills below are common triggers, not an allowlist. If the user's request,
task files, framework, toolchain, errors, or artifacts clearly match another globally
installed skill, use that skill even when it is not named in this file.

When a task or workflow step names a skill, or when task context clearly matches a
globally installed skill:

1. Prefer the exact path supplied by the current session's skill catalog.
2. Otherwise resolve an exact directory-name match recursively under these global roots:
   - `~/.agents/skills/`
   - `~/.codex/skills/`
   - `~/.codex/skills/.system/`
3. Open the matched skill's `SKILL.md` and read it completely before taking actions governed by it.
4. Resolve relative references from the directory containing that `SKILL.md`. Load only the references required for the current branch.
5. Do not reject or skip a suitable skill merely because it is absent from the project, omitted from this file, or omitted from an injected catalog; check the global roots first.
6. If no exact global match exists, report the missing skill and use the safest suitable fallback. Never invent the missing instructions.

Every skill listed below has a routing condition. When that condition matches, load the skill. For unlisted global skills, load only when the current task context makes the fit specific and useful. Do not preload the full catalog at session start.

## Operating principles

- Match the process to the task's size, risk, and reversibility. Keep trivial work trivial.
- Inspect relevant files, instructions, and repository state before editing.
- Preserve user changes and unrelated work. Make the smallest coherent change that solves the request.
- Prefer evidence over assumption. State assumptions that materially affect the result.
- Ask for input only when a missing choice would substantially change the outcome or new authority is required.
- Commit, push, open a pull request, deploy, delete data, or contact external systems only when the user authorized that action.
- Verify with fresh evidence before claiming success.

## Skill arbitration

Use one methodology per role. Complementary skills may run in sequence, but overlapping skills must not compete during the same activity.

### Test-driven development

- Use `test-driven-development` by default when implementing a feature or bug fix.
- Use `tdd` instead when the user explicitly requests that skill or its particular test-first workflow.
- Never load both for the same implementation cycle.

### Debugging

Choose exactly one primary debugging method per bug:

- `systematic-debugging`: default for an unexpected failure that must be reproduced, diagnosed, and fixed.
- `diagnosing-bugs`: hard bugs or performance regressions where the request is specifically to diagnose the cause.
- `debugging-and-error-recovery`: broken builds, regressions, or incidents where recovery and evidence preservation are central.

After three unsuccessful fixes for the same suspected cause, stop patching and revisit the model, architecture, or assumptions.

### Code review

- `code-review`: review changes against a fixed commit, branch, tag, merge-base, issue, or specification.
- `code-review-and-quality`: broad multi-axis review when no fixed comparison contract governs the request.
- Never run both for the same review unless the user explicitly requests two separate review passes.

### Browser validation

- `webapp-testing`: broad validation of a local web application and its user flows.
- `playwright`: scripted, repeatable browser automation or end-to-end tests.
- `playwright-interactive`: persistent browser or Electron exploration during iterative UI debugging.

Choose the smallest tool that proves the requested behavior. Combine them only when they verify distinct requirements.

## Task routing

Classify the request before acting:

- **Answer, explain, review, or report:** inspect and respond with evidence; do not mutate files or external state unless requested.
- **Diagnose:** reproduce or inspect the failure, identify the root cause, and report it. Implement a fix only when the request includes fixing it.
- **Change or build:** implement the requested change, test it, review the diff, and verify the outcome.
- **Ship:** commit, publish, open a pull request, or deploy only when explicitly requested.
- **Issue or external-PR triage:** use `triage` to categorize, verify, and prepare tracker-ready work. Do not use `triage` merely to classify an ordinary local task.

For a typo, tiny configuration edit, or similarly bounded change, load only the directly applicable skills, make the edit, and verify it. Use the full workflow below for substantial, ambiguous, externally visible, or high-risk changes.

## Substantial-change workflow

### 1. Understand and sharpen

- Read the nearest project instructions and the files that establish current behavior.
- Confirm the outcome, constraints, acceptance criteria, and out-of-scope work.
- Use `idea-refine` when the idea itself is still rough.
- Use `grill-with-docs` when the user requests rigorous plan/design interrogation and the project has useful ADRs or glossary material.
- Use `grill-me` for the same kind of interrogation when the project lacks usable documentation.
- Use `to-questionnaire` when the missing decisions belong to another stakeholder and must be collected asynchronously.
- Use `doubt-driven-development` when a nontrivial decision needs adversarial review.
- Use `domain-modeling` when terminology, entities, states, or boundaries are unclear.
- Use `spec-driven-development` when a significant implementation needs a local specification.
- Use `to-spec` when the user wants the current conversation synthesized and published to the configured issue tracker.

Do not publish a spec or contact an issue tracker without user authorization. Finish this stage when acceptance criteria are concrete and testable.

### 2. Design and plan

- Use `planning-and-task-breakdown` for multi-step work.
- Use `api-and-interface-design` for public APIs, contracts, or module boundaries.
- Use `codebase-design` for consequential module-boundary decisions.
- Use `security-threat-model` before changes involving authentication, authorization, secrets, payments, sensitive data, or new trust boundaries.
- Use `security-ownership-map` when security-sensitive work needs ownership, bus-factor, or maintainer analysis.
- Use `documentation-and-adrs` for decisions future maintainers need to understand.
- Use `to-tickets` only when the user wants an approved plan divided into tracker-ready tracer-bullet tickets.

Split work into independently verifiable slices and define the check that completes each slice. Publishing tickets is an external action and requires user authorization.

### 3. Implement

- Use `git-workflow-and-versioning` for code changes and respect the existing repository state.
- Keep `karpathy-guidelines` active while writing, reviewing, or refactoring code.
- Select the TDD skill according to Skill arbitration and complete a red-green-refactor cycle for features and bug fixes.
- Use `incremental-implementation` for changes spanning multiple components or carrying meaningful risk.
- Keep patches focused and follow existing conventions unless the task explicitly changes them.
- Add dependencies only when their value exceeds their operational and maintenance cost.
- Use `subagent-driven-development` and `using-git-worktrees` only for genuinely independent tasks when delegation is requested or governing instructions authorize it.

If an unexpected failure appears, stop feature work and choose one debugging skill according to Skill arbitration. Establish a reproducible failure and root cause before patching.

### 4. Review and harden

- Select one general review skill according to Skill arbitration.
- Use `security-audit` for security-sensitive changes.
- Use `security-and-hardening` when security remediation is part of the requested implementation scope.
- Use `code-simplification` when the result is harder to understand than necessary.
- Resolve critical findings before shipping and report unresolved lower-severity risks.

### 5. Verify

- Use `verification-before-completion` before stating that work is complete, fixed, or passing.
- Run the narrowest relevant checks first, then broader checks justified by risk: targeted tests, type checks, lint, build, integration tests, and end-to-end tests.
- Select browser-testing skills according to Skill arbitration when UI behavior must be proven.
- Use `performance-optimization` when latency, throughput, memory, rendering, or bundle size is an acceptance criterion.
- Use `observability-and-instrumentation` when production behavior needs logs, metrics, traces, or diagnostics.
- If a required check cannot run, state exactly what was not verified and why.

### 6. Deliver or ship

- Summarize the outcome, important files changed, verification performed, and remaining risk.
- Use `resolving-merge-conflicts` only when a merge or rebase conflict exists.
- Use `pr` when the user requests a pull-request body.
- Use `gh-address-comments` when an open GitHub pull request has review comments to address.
- Use `gh-fix-ci` when GitHub Actions checks are failing.
- Use `ci-cd-and-automation` for pipeline implementation or modification.
- Use `shipping-and-launch` for production launch readiness.
- Load only the deployment skill matching the requested target: `vercel-deploy`, `netlify-deploy`, `render-deploy`, or `cloudflare-deploy`.
- Use `git-guardrails-claude-code` only when configuring destructive-command protection for Claude Code; it is not a general Codex git workflow skill.

### 7. Reflect or teach

- Use `retro` when the user requests a retrospective on the coding session.
- Use `teach` when the user asks for a stateful teaching experience inside the workspace.
- Use `skill-creator`, starting from `template-skill` when appropriate, when the user asks to create or improve a reusable skill.
- Use `skill-installer` when the user asks to install a skill from a curated source or repository.

Do not create, install, or modify global skills as an automatic end-of-session action.

## Domain routing

Load every skill whose distinct responsibility is required, but avoid loading an entire family when only one member applies.

| Domain | Global skills and trigger |
|---|---|
| Supabase | `supabase` for any Supabase task; also `supabase-postgres-best-practices` before writing or reviewing SQL, schemas, indexes, RLS, or database operations |
| Prisma | `prisma-cli` for commands; `prisma-client-api` for queries; `prisma-database-setup` for provider setup; `prisma-postgres` for Prisma Postgres operations |
| shadcn/ui | `shadcn` for component discovery, installation, composition, styling, or troubleshooting |
| GSAP | `gsap-core` for core animation; `gsap-frameworks` for non-React framework lifecycle; `gsap-react` for React; `gsap-scrolltrigger` for scroll behavior; `gsap-timeline` for sequencing; `gsap-plugins` for plugins; `gsap-utils` for utilities; `gsap-performance` for animation performance |
| React and Next.js | `vercel-react-best-practices` for performance; `vercel-composition-patterns` for scalable component APIs |
| MCP servers | `mcp-builder` when building or exposing an MCP server |
| Frontend implementation | `frontend-ui-engineering` for production UI code; `frontend-design` when visual direction is part of the build |
| Frontend aesthetics | `design-taste-frontend` for aesthetic redesigns; `web-design-guidelines` for UI or accessibility review |
| Brand and themes | `brand-guidelines` for brand compliance; `theme-factory` for applying or creating an artifact theme |
| Office and document artifacts | `docx` for Word; `pdf` for PDF; `pptx` for PowerPoint; `xlsx` for spreadsheets |
| Skill discovery | `find-skills` when no installed skill covers a capability the user needs |

## Repository and editing guardrails

- Treat the working tree as shared and potentially dirty. Inspect it before broad edits and never discard changes you did not create.
- Prefer repository-provided commands and configuration as the source of truth. Do not duplicate easily discoverable facts in documentation.
- Use focused searches and targeted reads. Avoid generated output, vendored code, lockfiles, and large datasets unless needed.
- Prefer reversible actions. Resolve exact paths before deleting or moving files, and request confirmation for destructive or externally visible operations outside explicit scope.
- Keep secrets out of source, logs, command output, examples, and patches. Use placeholders in example environment files.
- Modify global instructions, skills, hooks, or agent configuration only when the user explicitly requests that change.

## Completion standard

Work is complete only when all requested outcomes are implemented, every applicable routed skill has been followed, relevant checks have fresh results, the diff contains no accidental changes, and the final response distinguishes verified facts from remaining uncertainty.
