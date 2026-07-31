# Data Model

## Modeling approach

The model uses a classic staged-to-mart reporting pattern:

- `stg_*` tables preserve normalized source rows
- `fact_*` tables hold canonical events and computed outputs
- `dim_*` tables hold reusable business descriptors
- `etl_run` records refresh metadata

## Table grains

| Table | Grain |
|---|---|
| `etl_run` | one row per refresh run |
| `dim_date` | one row per calendar date |
| `dim_market` | one row per market |
| `dim_team` | one row per team |
| `dim_source_file` | one row per loaded source file |
| `dim_kpi` | one row per KPI definition |
| `stg_provider_ops_record` | one row per normalized source row |
| `fact_provider_ops_event` | one row per provider work item for the reporting period |
| `fact_validation_issue` | one row per validation issue |
| `fact_kpi_snapshot` | one row per KPI per cut per reporting month |
| `fact_forecast` | one row per forecasted KPI per cut per month |
| `fact_llm_commentary_draft` | one row per generated commentary draft and review state |

## Core dimensions

### `dim_market`

- business key: `market_name`
- purpose: support market-level drill-down and outlier analysis

### `dim_team`

- business key: `team_code`
- purpose: ownership and throughput analysis

### `dim_source_file`

- business key: `source_file_name + reporting_period`
- purpose: tie-outs, lineage, refresh debugging

### `dim_kpi`

- business key: `kpi_code`
- purpose: store definitions, display metadata, and owner context

## Reference inputs

Phase 2 also uses repo-owned reference data in `config/reference_data.yml`.

These are not persisted as runtime dimension tables yet, but they act as control-plane inputs for:

- allowed markets
- allowed teams
- provider reference attributes
- market/team mappings
- status-transition validation

## Canonical fact

### `fact_provider_ops_event`

This is the main operational fact table. It should contain one normalized row per provider work item in the reporting period.

Required business fields:

- `provider_npi`
- `market_id`
- `team_id`
- `event_date_key`
- `event_status`
- `completion_flag`
- `turnaround_days`
- `backlog_flag`
- `backlog_over_sla_flag`
- `qa_issue_flag`
- `required_field_complete_flag`

## Validation fact

### `fact_validation_issue`

Each row records one exception found during refresh.

Required fields:

- `run_id`
- `source_file_id`
- `issue_type`
- `severity`
- `row_identifier`
- `issue_message`
- `status`

## KPI fact

### `fact_kpi_snapshot`

Each row stores one KPI value for one reporting month and one cut.

Supported cuts in V1:

- overall
- market
- team

Implementation note:

- represent overall rows with nullable `market_id` and `team_id`
- use `numerator_value` and `denominator_value` so rate KPIs can be audited

## Forecast fact

### `fact_forecast`

Stores transparent baseline forecasts only.

Required fields:

- `forecast_period_date_key`
- `kpi_id`
- `forecast_value`
- `model_name`
- `generated_run_id`

## LLM draft fact

### `fact_llm_commentary_draft`

Stores optional structured-output commentary drafts and review metadata.

Required fields:

- `run_id`
- `reporting_period`
- `draft_type`
- `model_provider`
- `model_name`
- `prompt_payload_json`
- `review_status`
- `created_at`

Important optional fields:

- `response_json`
- `draft_text`
- `reviewer_name`
- `review_notes`
- `reviewed_at`

## Referential rules

- `fact_provider_ops_event.market_id -> dim_market.market_id`
- `fact_provider_ops_event.team_id -> dim_team.team_id`
- `fact_provider_ops_event.run_id -> etl_run.run_id`
- `fact_validation_issue.run_id -> etl_run.run_id`
- `fact_kpi_snapshot.run_id -> etl_run.run_id`
- `fact_forecast.generated_run_id -> etl_run.run_id`
- `fact_llm_commentary_draft.run_id -> etl_run.run_id`

## Audit rules

- workbook totals must tie to `fact_kpi_snapshot`
- exception tab totals must tie to `fact_validation_issue`
- latest dashboard extracts must reference one successful `etl_run`
