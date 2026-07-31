# Operating History Plan

## Goal

Establish reproducible multi-period reporting history for trend analysis, control validation, regression testing, and recurring operations reporting.

## Target horizon

Default target:

- `18-24` closed monthly periods
- recommended planning range: `2024-09` through `2026-04`

Why this range:

- it preserves the current `2026-02` through `2026-04` demo periods
- it avoids inventing many future periods
- it is long enough to show seasonality, operational drift, QA campaigns, and backlog cycles

## Data strategy

### 1. Real or public-reference backbone data

Use public-reference data where it adds realism to dimensions and validation logic.

Recommended sources:

- `NPPES / NPI registry`
  - provider NPI
  - provider name
  - taxonomy / specialty
  - practice address context
- `CMS public provider or facility files`
  - facility context
  - public provider participation context
- `HRSA shortage / access reference`
  - market realism
  - gap-pressure context
- `Census county or geography reference`
  - county names
  - population rollups
  - map-ready geography fields

Use these as:

- control-plane reference inputs
- dimension seeds
- realism constraints for synthetic monthly events

### 2. Synthetic monthly operational facts

Keep these operational tables synthetic but realistic:

- provider roster workflow state
- onboarding intake and completion timing
- directory audit outcomes
- ownership assignments
- backlog age
- QA campaigns
- market/team staffing changes

Why:

- these are the types of internal operating data that are rarely public
- documenting the synthetic-generation rules is more credible than pretending this data is publicly available

## Monthly raw source contract

Each period should keep the same three source-file shapes:

- `provider_roster_YYYY_MM.csv`
- `onboarding_tracker_YYYY_MM.xlsx`
- `directory_audit_YYYY_MM.csv`

Each month should differ intentionally, not randomly.

Recommended month-over-month realism patterns:

- modest provider additions and removals
- specialty and market mix changes
- ownership reassignments
- periodic audit pushes that temporarily increase QA issue volume
- holiday or year-end slowdown
- quarter-start onboarding spikes
- one or two controlled incidents, such as a directory cleanup backlog or ownership gap

## Required archived artifacts per month

### Raw and processed artifacts

- raw source files under `data/raw/YYYY-MM/`
- `fact_provider_ops_event.csv`
- `fact_kpi_snapshot.csv`
- `fact_validation_issue.csv`
- `fact_forecast.csv`
- workbook export
- `commentary_preview.txt`

### Operating-history artifacts

- `run_manifest.json`
- `change_summary.md`

Recommended `run_manifest.json` contents:

- reporting period
- run id
- source file inventory
- row counts by source
- validation counts by issue type
- KPI highlight summary
- forecast summary
- config or schema version
- backend used

Recommended `change_summary.md` contents:

- what changed this month
- main KPI movements
- major validation or QA issues
- whether any business rule or reference-data updates affected interpretation

## Quarterly or periodic artifacts

These do not need to exist every single month.

Recommended cadence:

- quarterly screenshots of workbook and dashboard
- quarterly steering-summary memo
- cumulative change-request log for logic and control changes
- tie-out examples when business rules change

## Recommended implementation order

1. Extend the sample-data generator to produce the full monthly period range.
2. Add realistic month-over-month change logic and event scenarios.
3. Add `run_manifest.json` generation at refresh time.
4. Add `change_summary.md` generation at refresh time.
5. Backfill all monthly periods and refresh them in sequence.
6. Add archive index documentation summarizing the full history.

## Phase boundaries

This operating-history plan should come before:

- major frontend work
- more AI features
- multi-scenario expansion

It should come after:

- stable dual-backend verification
- stable KPI and forecast logic

## Definition of success

The operating history is successful when:

- operators can compare multiple months and trace plausible operational evolution
- recurring refresh history supports trend analysis, control validation, and regression testing
- controls, tie-outs, and commentary remain connected to a recurring reporting cadence
- archived records remain consistent with the documented source contracts and processing rules
