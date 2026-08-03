# Technical Spec

## Target architecture

```text
data/raw/YYYY-MM/*
  -> ingest normalization
  -> stg_provider_ops_record
  -> fact_provider_ops_event
  -> fact_validation_issue
  -> fact_kpi_snapshot / fact_forecast / fact_llm_commentary_draft
  -> workbook + dashboard + commentary outputs
```

## Runtime configuration

The repo now supports one resolved runtime backend per execution:

- `sqlite` is the default local backend
- `postgres` is optional via environment configuration

Current config surface:

- `HEALTHCARE_OPS_DB_BACKEND`
- `HEALTHCARE_OPS_SQLITE_PATH`
- `HEALTHCARE_OPS_DATA_DIR`
- `HEALTHCARE_OPS_OUTPUTS_DIR`
- `HEALTHCARE_OPS_POSTGRES_URL`
- `HEALTHCARE_OPS_ENABLE_LLM_DRAFT`
- `HEALTHCARE_OPS_OPENAI_MODEL`

## V1 source contracts

### 1. Provider roster

- file pattern: `provider_roster_*.csv`
- minimum columns:
  - provider_name
  - provider_npi
  - specialty_name
  - market_name
  - team_code
  - workflow_status
  - effective_date

### 2. Onboarding tracker

- file pattern: `onboarding_tracker_*.xlsx`
- minimum columns:
  - provider_npi
  - market_name
  - received_date
  - completed_date
  - onboarding_stage
  - owner_name

### 3. Directory audit

- file pattern: `directory_audit_*.csv`
- minimum columns:
  - provider_npi
  - market_name
  - audit_result
  - audit_issue_type
  - audit_date

## Canonical record contract

Every staged row must produce the following logical fields when available:

- `reporting_period`
- `source_file_name`
- `source_row_num`
- `provider_name`
- `provider_npi`
- `specialty_name`
- `market_name`
- `team_code`
- `workflow_status`
- `received_date`
- `completed_date`
- `effective_date`
- `audit_result`
- `audit_issue_type`
- `owner_name`
- `phone_number`
- `address_line`

## Processing steps

### Step 1: Discover files

- read the target period directory under `data/raw/YYYY-MM/`
- match files using `config/field_mappings.yml`
- fail fast if any required file pattern is missing

### Step 2: Normalize columns

- load CSV/XLSX inputs with pandas
- rename source columns to canonical names using config mappings
- add `source_file_name`, `source_row_num`, and `reporting_period`
- union normalized rows into `stg_provider_ops_record`

### Step 3: Validation

Persist one row per issue in `fact_validation_issue`.

Validation rules currently implemented:

1. `missing_required_field`
   - required: `provider_npi`, `market_name`, `workflow_status`
2. `duplicate_provider_market`
   - duplicate key: `provider_npi + market_name + workflow_status`
3. `invalid_npi_format`
   - NPI must be 10 digits
4. `invalid_npi_checksum`
   - when a 10-digit NPI is present, validate checksum using the standard `80840` prefix rule
5. `invalid_date_sequence`
   - `completed_date` cannot be earlier than `received_date`
6. `invalid_status_value`
   - value must be in the configured status set
7. `invalid_market_reference`
   - market should exist in repo-owned reference data
8. `invalid_team_reference`
   - team should exist in repo-owned reference data
9. `invalid_market_team_mapping`
   - team should be allowed for the referenced market
10. `provider_reference_conflict`
   - known provider reference attributes should align with incoming rows
11. `missing_owner_assignment`
   - open onboarding work should have an assigned owner
12. `unexpected_status_transition`
   - audit publication should not conflict with upstream open workflow states
13. `audit_onboarding_mismatch`
   - passing or published audit states should align with completed onboarding state
14. `stale_backlog_record`
   - open records with backlog age greater than configured SLA threshold

Reference inputs are stored in `config/reference_data.yml`.

### Step 4: Canonical event model

Create one normalized event row per provider-work item with these derived fields:

- `completion_flag`
- `turnaround_days`
- `backlog_flag`
- `backlog_over_sla_flag`
- `qa_issue_flag`
- `required_field_complete_flag`

### Step 5: KPI snapshot calculation

For each reporting month and optional cut:

- overall
- by market
- by team

Compute KPI values from the canonical event fact.

## KPI formulas

| KPI code | Formula |
|---|---|
| `total_records_received` | `count(*)` |
| `completed_records` | `sum(completion_flag)` |
| `completion_rate` | `sum(completion_flag) / count(*)` |
| `avg_turnaround_days` | `avg(turnaround_days where completion_flag = true)` |
| `open_backlog_count` | `sum(backlog_flag)` |
| `backlog_over_sla_count` | `sum(backlog_over_sla_flag)` |
| `qa_issue_rate` | `sum(qa_issue_flag) / count(*)` |
| `required_field_completeness_rate` | `sum(required_field_complete_flag) / count(*)` |
| `unique_npi_rate` | `count(distinct provider_npi) / count(*)` |

## Forecast logic

V1 supports simple transparent forecasts only:

- rolling 3-period average for volume metrics
- rolling 3-period average for backlog metrics
- no forecast for QA issue rate until at least 3 full periods exist

Current status:

- multi-period demo data now exists for `2026-02`, `2026-03`, and `2026-04`
- prior-period comparisons are populated in KPI snapshots for the latest successful run per reporting period
- forecast persistence is implemented in `fact_forecast` for stable volume and backlog metrics using a rolling three-period average

## Commentary generation

### Phase 1

Deterministic template output based on:

- biggest positive variance
- biggest negative variance
- highest-risk QA metric
- backlog change versus prior period

Current status:

- deterministic commentary is implemented and exported to `outputs/YYYY-MM/commentary_preview.txt`
- optional LLM drafting is implemented as a separate structured-output path with distinct payload, draft, and review artifacts
- deterministic commentary remains the canonical output

### Phase 2

Optional LLM prompt receives structured JSON only:

- reporting period
- metric deltas
- validation counts by issue type
- top market outliers

Human review is mandatory before publishing commentary.

Persisted draft artifact contract:

- `fact_llm_commentary_draft` stores prompt payload, model metadata, draft text, and review metadata
- output files include:
  - `llm_commentary_payload.json`
  - `llm_commentary_draft.json`
  - `llm_commentary_draft.txt`
  - `llm_commentary_review.json`

## CLI surface

### `healthcare-ops-kpi-qa plan --period YYYY-MM`

- validates directory structure
- discovers source files
- prints planned steps, expected outputs, and config paths

### `healthcare-ops-kpi-qa refresh --period YYYY-MM`

- runs the full monthly refresh
- writes backend-selected records, CSV outputs, workbook export, and deterministic commentary output
- optional `--llm-draft` also attempts structured LLM draft generation

### `healthcare-ops-kpi-qa seed-demo-data`

- creates a three-period synthetic demo dataset for `2026-02`, `2026-03`, and `2026-04`

### `healthcare-ops-kpi-qa refresh-demo-data`

- refreshes the demo periods sequentially so prior-period comparisons are stable

### `healthcare-ops-kpi-qa show-config`

- prints resolved config and project paths

### `healthcare-ops-kpi-qa generate-llm-draft --period YYYY-MM`

- generates a structured LLM commentary draft for the latest successful run in the period
- writes separate prompt/draft/review artifacts

### `healthcare-ops-kpi-qa review-llm-draft --draft-id ...`

- persists review status, reviewer name, and notes for a generated draft

## Dashboard spec

Current dashboard pages:

- Executive summary
- KPI definitions
- Trends
- Market & team
- QA & tie-outs
- Forecast assumptions
- Review packet

Preferred implementation: Streamlit with SQL-backed extracts from the mart tables.

Current status:

- implemented
- trend views use the latest successful run per reporting period rather than every rerun
- persistent run, market, team, and source filters are applied only where the persisted V1 data grain supports them
- executive summary uses persisted KPI snapshot values, prior values, and variances, with a run-level trust state that distinguishes Ready, Ready with reviewable exceptions, and Not ready
- KPI formulas are read from `config/kpi_definitions.yml` rather than duplicated in the dashboard
- favorable, unfavorable, and neutral variance presentation is derived from the configured KPI target direction; rate variance is displayed in percentage points
- QA controls connect source-file inventory, staged rows, canonical events, validation issues, persisted snapshots, workbook availability, and a direct workbook-summary comparison against persisted overall snapshot values
- forecast views use persisted actual history plus the persisted forecast point and range; the dashboard does not generate forecast values
- review packet shows deterministic commentary separately from optional LLM draft metadata, states that human review is required for drafts, and provides matching selected-run downloads
