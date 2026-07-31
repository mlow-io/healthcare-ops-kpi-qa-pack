# Demo Assets

## Primary visuals

- Dashboard overview: `docs/demo_assets/dashboard_overview.png`
- Dashboard forecast: `docs/demo_assets/dashboard_forecast.png`
- Dashboard commentary: `docs/demo_assets/dashboard_commentary.png`

## Versioned output evidence

- Workbook: `outputs/2026-04/healthcare_ops_kpi_qa_pack_2026_04.xlsx`
- KPI snapshots: `outputs/2026-04/fact_kpi_snapshot.csv`
- Validation issues: `outputs/2026-04/fact_validation_issue.csv`
- Forecast output: `outputs/2026-04/fact_forecast.csv`
- Commentary preview: `outputs/2026-04/commentary_preview.txt`

The versioned evidence set excludes LLM artifacts. Those files are generated only when a key is configured and the optional workflow is run. Deterministic commentary remains the reproducible default.

## Stable demo state

The demo uses three sequential periods:

- `2026-02`
- `2026-03`
- `2026-04`

Use the latest successful run for each period from `etl_run` when reviewing trend and variance behavior.

## Interpretation boundaries

- All operational records are synthetic.
- Public or production provider truth is not inferred from these outputs.
- Forecasts use a transparent three-period rolling average.
- PostgreSQL is optional and is not part of the default demo path.
- Model-assisted commentary is optional and requires human review.
