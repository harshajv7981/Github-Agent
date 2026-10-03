# Agentic Contribution Platform TODO

This checklist is the source of truth for the ten requested agentic features. An item is complete only when the backend behavior, persistence, API/UI surface where needed, security controls, and automated tests are implemented.

## Features

- [~] 1. Planner-executor workflow: durable run/step state, validated transitions, and a real acceptance -> regression -> patch -> sandbox -> review workflow exist; resume/retry UX remains.
- [~] 2. Tool-based agent actions: allow-listed registry plus bounded repository/GitHub/test tools exist; runtime wiring for model tool calls remains.
- [~] 3. Autonomous issue selection: explainable ranking, active-run exclusion, and `/api/agent-runs/next` are implemented; deeper policy/activity/duplicate signals remain.
- [~] 4. Regression-test-first workflow: the orchestrator proves a generated test fails before patching and includes it in post-patch sandbox verification; integration coverage remains.
- [~] 5. Persistent agent memory: structured facts are retrieved into prompts and review lessons are stored; broader policy/CI fact extraction remains.
- [~] 6. CI feedback agent: failed check detection, bounded log retrieval, sandbox repair proposals, and approval records are implemented; approved follow-up push remains.
- [~] 7. Human approval gates: approval records, tool enforcement, agent PR approval API, and dashboard approval UI exist; CI follow-up approval and legacy PR route hardening remain.
- [~] 8. Cost and risk budgets: model request/token limits exist; time, repair, file-count, diff-size, and side-effect limits remain.
- [~] 9. Independent final reviewer: orchestrator runs the existing structured reviewer after sandbox verification and exposes approval UI; finding persistence remains.
- [~] 10. Resume and recovery state machine: durable states, idempotency keys, and step records exist; end-to-end restart/resume remains.

## Validation requirements

- [ ] Every feature has focused unit/integration tests.
- [ ] Full backend test suite passes.
- [ ] No API key or repository credential is logged or persisted in plaintext.
- [ ] Destructive or external actions remain approval-gated.
- [ ] Documentation and dashboard status reflect the implemented workflow.

## Frontend Refactor

- [~] App.tsx shared types moved to `frontend/src/app/types.ts`.
- [~] App.tsx API boundary started in `frontend/src/app/api.ts`.
- [~] SandboxPanel moved to `frontend/src/app/SandboxPanel.tsx`.
- [ ] Extract IssueQueue, FeatureIdeas, PullRequests, RunsTelemetry, and IssueModal components.
- [ ] Extract stateful API/data hooks from App.tsx.
- [x] App.css split into ordered layout, dashboard, issue-modal, sandbox, and responsive modules.

## Backend Refactor

- [x] Shared schemas moved out of `main.py` into `schemas.py`.
- [x] Durable agent and memory routes moved into `agent_routes.py`.
- [x] PR and CI routes moved into `pr_routes.py`.
- [x] Feature routes moved into `feature_routes.py`.
- [x] Sandbox routes moved into `sandbox_routes.py`.
- [x] Agent repository/parsing helpers moved into `agent_helpers.py`.
- [x] Feature generation and feature PR logic moved into `feature_agent.py`.
