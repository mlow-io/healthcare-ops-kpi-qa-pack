# Implementation Plan

## Milestones

| Milestone | Deliverable | Definition of done |
|---|---|---|
| M1 | input contracts and config | source files, field mappings, KPI list, and status values locked |
| M2 | SQL schema and staging loader | `ddl.sql` created, staging loads one sample period successfully |
| M3 | validation engine | issue logging works for all V1 rule types |
| M4 | KPI pipeline | snapshot table populated and tied to source totals |
| M5 | workbook export | Excel pack generated with all required tabs |
| M6 | dashboard | overview, trend, breakdown, and exceptions pages working |
| M7 | commentary | deterministic summary generated from structured KPI deltas |
| M8 | polish | README, screenshots, sample outputs, and demo script finalized |

## Status

- `M1-M8`: complete for the current V1 scope
- `P2-M1`: implemented and verified on both SQLite and local Postgres
- `P2-M2`: implemented
- `P2-M3`: implemented with CLI workflow and persisted review metadata
- `P2-M4`: implemented in the current Streamlit app
- `P3-M1`: planned
- `P3-M2`: planned
- `P3-M3`: planned
- `P3-M4`: planned
- `P3-M5`: planned
- `P3-M6`: planned

## First implementation slice

If you want to start coding immediately, do this first:

1. Create sample input files that match `config/field_mappings.yml`.
2. Implement file discovery and normalization.
3. Load `stg_provider_ops_record`.
4. Implement validation rule persistence.
5. Compute `fact_provider_ops_event`.

That slice gets the highest architectural leverage because every later feature depends on it.

## Decisions made

- SQLite remains the local default for V1.
- Streamlit remains the official dashboard/presentation layer for V1.
- NPI checksum validation is included as a warning-level quality rule.
- Deterministic commentary remains the only V1 publishing path.
- Transparent rolling-average forecast persistence is included for stable volume and backlog metrics.

## Release checkpoints

- After M4, capture a schema diagram and mart screenshots.
- After M5, capture workbook screenshots and tie-out proof.
- After M7, capture the commentary view and explain the human-review gate.
- After the multi-period demo is stable, capture dashboard trend screenshots from `2026-02` to `2026-04`.

## Phase 2 roadmap

### P2-M1 Runtime abstraction + optional Postgres mode

Deliverable:

- backend-aware connection and initialization flow with SQLite default and Postgres opt-in

Definition of done:

- one resolved runtime backend is selected via config or environment
- SQLite remains the default local path
- schema/init flow works for both SQLite and Postgres
- demo refresh runs successfully on both backends with equivalent row counts and core KPI outputs
- workbook and dashboard continue to work against the selected backend

### P2-M2 Internal reference-data validation

Deliverable:

- repo-owned reference inputs and richer validation rules for markets, teams, statuses, and provider attributes

Definition of done:

- reference data artifacts are versioned in the repo alongside existing config
- new persisted rule types cover cross-file consistency, provider uniqueness conflicts, missing ownership, unexpected status transitions, and audit/onboarding mismatches
- current severity model and persisted issue pattern remain intact
- workbook and dashboard exception surfaces include the new issue classes

### P2-M3 Optional LLM draft mode

Deliverable:

- opt-in structured-JSON commentary draft path with explicit human review status

Definition of done:

- deterministic commentary remains the default and canonical output
- LLM mode accepts structured JSON only, derived from KPI deltas, forecasts, and validation aggregates
- generated draft text, prompt payload, model metadata, and review status are persisted separately from deterministic commentary
- one CLI or dashboard workflow can produce deterministic commentary plus optional reviewed LLM draft output

### P2-M4 Streamlit product polish

Deliverable:

- stronger stakeholder-facing Streamlit application without replacing the current stack

Definition of done:

- navigation, labels, and layout support a polished dashboard walkthrough
- run comparison views, KPI variance context, validation drilldowns, and forecast visualization are all present
- executive-summary presentation is clearer and less dependent on raw table inspection
- the app supports a complete demo without opening CSV files

## Phase 2 non-goals

- no external provider API integration
- no autonomous publishing of LLM commentary
- no full SaaS auth or multitenancy layer
- no replacement of Streamlit with a custom web app in this phase
- no advanced ML forecasting beyond transparent statistical methods

## Phase 3 roadmap

### P3-M1 Operating history buildout

Deliverable:

- an 18-24 month archived operating history for recurring reporting, trend analysis, control validation, and regression testing

Definition of done:

- at least 18 monthly periods exist in `data/raw/YYYY-MM/`
- each period has the three core source files:
  - `provider_roster_YYYY_MM.csv`
  - `onboarding_tracker_YYYY_MM.xlsx`
  - `directory_audit_YYYY_MM.csv`
- each period refreshes successfully and writes the standard workbook, commentary, KPI, validation, and forecast outputs
- each period also has a short `change_summary.md` and `run_manifest.json`
- the history preserves realistic month-over-month changes such as provider churn, ownership changes, backlog swings, and QA campaigns

### P3-M2 Controls matrix and tie-out pack

Deliverable:

- explicit control documentation that maps source files to validation rules, KPI definitions, mart outputs, and workbook/dashboard surfaces

Definition of done:

- `docs/CONTROLS_MATRIX.md` exists and maps:
  - source files -> canonical fields
  - canonical fields -> validation rules
  - validation rules -> output artifacts
  - KPI formulas -> workbook/dashboard views
- `docs/TIE_OUTS.md` exists with row-count, metric, and reconciliation checks
- tie-out examples are demonstrated against at least one monthly run

### P3-M3 Operational delivery and governance artifacts

Deliverable:

- operational delivery and governance documentation that supports routine release and change management

Definition of done:

- `docs/UAT_SCRIPT.md`
- `docs/REQUIREMENTS_TRACE.md`
- `docs/CHANGE_REQUEST_LOG.md`
- `docs/STEERING_SUMMARY.md`
- each document is filled with realistic, bounded content tied to the actual product and run history

### P3-M4 Semantic layer and BI export surface

Deliverable:

- stable mart views and field definitions designed for Power BI or Tableau consumption

Definition of done:

- semantic-layer views are documented and versioned
- field naming and grain are stable enough for BI use
- a BI-facing export folder or semantic-layer doc set exists
- one BI-oriented example is included, even if Streamlit remains the main app

### P3-M5 Reproducible runtime packaging and CI

Deliverable:

- one-command local runtime packaging plus automated release checks

Definition of done:

- `docker-compose.yml` supports the standard local runtime
- a CI workflow runs tests and demo refresh checks
- at minimum, CI verifies:
  - `pytest`
  - demo refresh success
  - key row-count / KPI parity checks

### P3-M6 Additional healthcare scenario

Deliverable:

- one more healthcare-specific scenario that reuses the same architecture without turning the repo into a generic project pile

Definition of done:

- exactly one additional scenario is selected
- the scenario is documented as either:
  - provider directory accuracy SLA monitoring
  - revenue cycle denials and exception analytics
- reuse of the existing pipeline patterns is explicit in the docs

## Recommended Phase 3 order

1. `P3-M1` operating history
2. `P3-M2` controls matrix and tie-outs
3. `P3-M3` consulting delivery artifacts
4. `P3-M4` semantic layer / BI exports
5. `P3-M5` runtime packaging and CI
6. `P3-M6` additional healthcare scenario
