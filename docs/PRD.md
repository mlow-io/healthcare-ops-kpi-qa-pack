# PRD

## Product name

Healthcare Operations KPI & QA Pack

## Version

V1 scoped to provider roster, onboarding, and directory QA operations.

## One-sentence summary

A repeatable healthcare operations reporting and QA system that supports monthly review and traceable controls.

## Problem statement

Healthcare operations teams often combine multiple CSV and Excel exports by hand to produce monthly reporting. In provider operations, this commonly means reconciling roster files, onboarding trackers, and directory audit logs. The result is slow turnaround, unclear ownership, weak trust in the numbers, and poor visibility into data-quality risk.

Leaders need:

- one place for recurring KPIs
- explicit, reproducible definitions
- run-level auditability
- visible QA exceptions and tie-outs
- quick market and team drill-down
- concise monthly commentary

## Users

| User | Need | Success criteria |
|---|---|---|
| Provider Operations Manager | backlog and completion visibility | can see market/team performance and exception counts quickly |
| Provider Data Analyst | repeatable refresh process | no manual spreadsheet stitching, clear validation results |
| Director / VP | executive summary | can understand change drivers and QA risk in one pass |
| Operations Governance Lead | controlled reporting process | can trace workflow, logic, controls, and outputs end to end |

## V1 business scenario

V1 models a provider operations team that manages provider roster maintenance, onboarding progress, and directory audit follow-up across multiple markets.

### Included source files

- `provider_roster_YYYY_MM.csv`
- `onboarding_tracker_YYYY_MM.xlsx`
- `directory_audit_YYYY_MM.csv`

### Included dimensions

- market
- team
- reporting month
- source file
- KPI definition

## Goals

- Standardize multi-source provider-operations exports into a canonical schema.
- Persist validation issues and QA outcomes by run.
- Publish monthly KPI snapshots by market and team.
- Export an audit workbook that ties to dashboard totals.
- Generate a structured executive summary draft.

## Non-goals

- production integration with payer/provider systems
- real-time reporting
- role-based security
- complex ML forecasting
- autonomous AI narration with no human review

## Phase 2 expansion direction

Phase 2 should extend the same product thesis rather than reposition the repo.

The intended direction is:

- preserve the local-first reporting product shape
- add optional Postgres compatibility without degrading SQLite usability
- deepen QA/control credibility through internal reference-data validation
- add optional LLM-assisted drafting only as a reviewed assistant capability
- make the Streamlit app more stakeholder-ready without replacing it with a different frontend stack

Phase 2 is not meant to turn this repo into a hosted SaaS product. It should remain a bounded analytics-engineering and healthcare-operations system with stronger architecture, controls, and presentation depth.

## Phase 3 operating-history direction

Phase 3 should establish a multi-period operating history for recurring reporting and control analysis.

The intended direction is:

- extend the monthly archive to 18-24 periods
- preserve the same three-source-file reporting contract
- use real public backbone data where it is credible and available
- keep operational workflow facts synthetic but documented
- add recurring operational artifacts such as manifests, change summaries, tie-outs, and governance docs

Phase 3 should strengthen recurring-reporting continuity without broadening the product into a different category.

## Functional requirements

### FR-1 Ingestion

The system shall ingest up to three source files per reporting period and normalize them to a canonical record contract.

### FR-2 Validation

The system shall record validation issues for:

- missing required fields
- duplicate provider-market records
- malformed NPIs
- invalid date sequences
- stale backlog ages
- invalid status values

### FR-3 KPI calculation

The system shall calculate monthly KPI snapshots for:

- total records received
- completed records
- completion rate
- average turnaround days
- open backlog count
- backlog over SLA count
- QA issue rate
- required-field completeness rate
- unique NPI rate

### FR-4 Export

The system shall produce:

- an Excel workbook with summary, detail, variance, tie-out, and exceptions tabs
- dashboard-ready tables
- a validation output table
- a commentary draft payload

### FR-5 Auditability

The system shall persist refresh metadata including run times, source file counts, staged row counts, validation counts, and operator notes.

## Non-functional requirements

| Category | Requirement |
|---|---|
| Reliability | the same inputs produce the same KPI outputs |
| Explainability | every KPI and validation rule has visible source logic |
| Portability | the full stack runs locally on a laptop |
| Maintainability | field mappings and KPI rules live in config, not hard-coded business logic |
| Believability | synthetic fields are documented and remain operationally plausible |

## Acceptance criteria

- One command can plan or refresh a monthly run.
- Validation issues are persisted with run metadata and issue types.
- KPI snapshot totals match workbook totals for the same filter set.
- The dashboard can filter by month, market, team, and source category.
- Commentary is generated from structured KPI deltas and exception counts.
- Another user can set up the repo locally from the README and docs.

## Risks

| Risk | Mitigation |
|---|---|
| scope creep into generic BI | keep V1 centered on provider operations reporting only |
| fake data looks random | derive dimensions from public provider/facility references and document synthetic logic |
| commentary feels generic | start with deterministic templates and threshold rules |
| too many KPIs | cap V1 at 8 to 9 operational measures |
