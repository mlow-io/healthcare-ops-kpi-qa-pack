# Project State

Updated: 2026-08-11

This is the living execution summary for the repository. Keep it short and current. Replace stale statements instead of appending a work journal; Git history preserves earlier versions.

## What This Project Proves

The project demonstrates a controlled healthcare operations reporting workflow: synthetic roster, onboarding, and directory-audit files become validated canonical events, persisted KPI and forecast marts, an audit workbook, deterministic commentary, and a stakeholder-facing monthly cockpit.

For a portfolio reviewer, the strongest signals are operational controls, source-to-output traceability, transparent KPI definitions, explicit exception handling, and clear communication of limitations.

## Current State

- V1 and Phase 2 capabilities are merged to `main` in PR #1.
- The cockpit includes executive summary, KPI definitions, trend and segment views, QA tie-outs, forecast assumptions, and a review packet.
- A compact April evidence set and five dashboard screenshots are versioned.
- Deterministic publication CSVs use stable business identifiers while runtime facts retain audit and surrogate keys.
- SQLite is the reproducible default. PostgreSQL is optional and not exercised in CI.
- Deterministic commentary is canonical. Optional LLM drafts are separate and require human review.
- The verified release content is on `main` and designated as release `v0.1.0`.

## Next Three Priorities

1. Improve the public case-study presentation only where it helps an employer understand the implemented controls and evidence quickly.
2. Collect reviewer feedback on whether the workflow, controls, and business decisions are understandable in a short portfolio review.
3. Keep operating-history expansion deferred until the released case study has been evaluated as a portfolio artifact.

## Current Concerns

- The committed history contains only three synthetic periods, so forecasting claims must remain modest and transparent.
- `dashboard.py` is large; decomposition is useful maintenance work but is not a V1 release requirement.
- PostgreSQL parity has been checked locally but is not an automated release gate.

## Deferred Work

- The 18-24 month operating-history plan remains valid but starts after the current V1 release.
- Controls-matrix, governance, BI semantic-layer, Docker, and additional-scenario work remain later phases.
- Do not add advanced forecasting, a replacement frontend, autonomous LLM publishing, authentication, or multitenancy to the current release.

## Release Gate

Before calling V1 released:

- required lint, tests, and deterministic demo refresh pass;
- selected workbook values tie to persisted overall KPI snapshots;
- committed screenshots and evidence match the selected demo run;
- synthetic-data, privacy, and limitation language remains visible;
- the release branch is merged and the merged commit is tagged.

## Update Rule

Update this file only when implemented capabilities, verified release state, material concerns, priorities, or deferrals change. Technical contracts belong in the existing specifications, durable architecture reasoning belongs in `docs/DECISIONS.md`, and routine work belongs in commits and PRs.
