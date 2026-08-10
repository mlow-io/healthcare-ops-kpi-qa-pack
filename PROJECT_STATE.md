# Project State

Updated: 2026-08-10

This is the living execution summary for the repository. Keep it short and current. Replace stale statements instead of appending a work journal; Git history preserves earlier versions.

## What This Project Proves

The project demonstrates a controlled healthcare operations reporting workflow: synthetic roster, onboarding, and directory-audit files become validated canonical events, persisted KPI and forecast marts, an audit workbook, deterministic commentary, and a stakeholder-facing monthly cockpit.

For a portfolio reviewer, the strongest signals are operational controls, source-to-output traceability, transparent KPI definitions, explicit exception handling, and clear communication of limitations.

## Current State

- V1 and Phase 2 capabilities are implemented on the `feat/monthly-operations-cockpit` release branch.
- The cockpit includes executive summary, KPI definitions, trend and segment views, QA tie-outs, forecast assumptions, and a review packet.
- A compact April evidence set and five dashboard screenshots are versioned.
- SQLite is the reproducible default. PostgreSQL is optional and not exercised in CI.
- Deterministic commentary is canonical. Optional LLM drafts are separate and require human review.
- The release branch is represented by an open draft PR and is not yet merged or tagged.

## Next Three Priorities

1. Decide how tracked demo evidence should handle volatile run and surrogate identifiers so reruns do not create misleading business-data changes.
2. Complete final release review, merge the current draft PR, and tag the resulting portfolio V1.
3. Improve the public case-study presentation only where it helps an employer understand the implemented controls and evidence quickly.

## Current Concerns

- Regenerating the same synthetic periods can change run IDs and dimension surrogate IDs in tracked evidence even when business facts are unchanged.
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
