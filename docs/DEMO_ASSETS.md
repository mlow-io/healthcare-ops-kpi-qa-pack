# Demo Assets

## Primary visuals

- Dashboard overview: `docs/demo_assets/dashboard_overview.png` — April reporting context, `Ready with reviewable exceptions` trust state, direction-aware headline KPIs, and next action.
- Dashboard trend: `docs/demo_assets/dashboard_trend.png` — formatted actual and prior-period comparison for a selected KPI.
- Dashboard QA: `docs/demo_assets/dashboard_qa.png` — source-to-workbook control ledger with counts, statuses, drilldowns, and human-readable exception categories.
- Dashboard forecast: `docs/demo_assets/dashboard_forecast.png` — actual history, distinct next-period forecast point, observed range, and displayed rolling-average method.
- Dashboard commentary: `docs/demo_assets/dashboard_commentary.png` — readable deterministic commentary beside clearly labeled optional draft and human-review requirement.

## Versioned output evidence

- Workbook: `outputs/2026-04/healthcare_ops_kpi_qa_pack_2026_04.xlsx`
- KPI evidence: `outputs/2026-04/evidence_kpi_snapshot.csv`
- Validation evidence: `outputs/2026-04/evidence_validation_issue.csv`
- Forecast evidence: `outputs/2026-04/evidence_forecast.csv`
- Commentary preview: `outputs/2026-04/commentary_preview.txt`

The three versioned CSVs are deterministic publication evidence: they use business identifiers and exclude run IDs, surrogate keys, and refresh timestamps. Runtime fact exports retain those audit fields but are not versioned. The workbook and screenshots represent one selected successful run and may change when intentionally recaptured. The evidence set excludes LLM artifacts; deterministic commentary remains the reproducible default.

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
- The cockpit reads persisted run outputs and configuration; it does not recalculate KPI values in the user interface.
