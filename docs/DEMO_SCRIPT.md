# Demo Script

## Goal

Demonstrate the core healthcare operations reporting workflow in 3-5 minutes.

## Setup

Run:

```bash
healthcare-ops-kpi-qa seed-demo-data
healthcare-ops-kpi-qa refresh-demo-data
streamlit run src/healthcare_ops_kpi_qa/dashboard.py
```

Use the latest successful `2026-04` run in the dashboard for the main walkthrough.

The optional LLM draft is not required for the demo. If a key is configured and the separate human-review workflow is in scope, run `healthcare-ops-kpi-qa generate-llm-draft --period 2026-04` after the deterministic refresh.

## Short walkthrough

1. Start with the repo framing.

Say:

`This project standardizes provider roster, onboarding, and directory-audit exports into a canonical event fact, persists validation issues, and produces both an Excel reporting pack and a Streamlit dashboard.`

2. Show the overview page.

Point out:

- `5` canonical work items in the current period
- `20%` completion rate
- `4` open backlog items
- `20%` QA issue rate

Say:

`The important point is that these metrics are computed from the canonical event fact, not directly from the raw files, so duplicate or malformed source rows can be surfaced as issues without inflating business volume.`

3. Show the validation story.

Reference the issue mix:

- invalid checksum warnings
- duplicate provider-market rows
- invalid date sequence
- missing required field

Say:

`This is where the project proves controls thinking. Bad data is visible, counted, and traceable, but it does not silently poison KPI calculations.`

4. Show the Executive Review page.

Say:

`The deterministic commentary is still the source of truth. The optional LLM path produces a separate structured draft with review metadata, which keeps the AI story controlled instead of hand-wavy.`

5. Show the Forecasts page.

Say:

`Forecasts are intentionally simple: a rolling three-period average for stable volume and backlog metrics. The short synthetic history does not support a more complex forecasting claim.`

## Technical review points

- canonical modeling and table grain
- persisted validation issues instead of ephemeral warnings
- latest-successful-run-per-period logic for trend stability
- separation of concerns across pipeline, workbook export, dashboard, and commentary
- transparent forecasting instead of opaque modeling
