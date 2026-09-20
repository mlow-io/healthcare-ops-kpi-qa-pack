# Power BI Build Guide — Healthcare Operations Cockpit (.pbix)

Purpose: turn this repo's existing KPI mart outputs into the `Healthcare_Operations_Cockpit.pbix`
required by the Track 1 portfolio plan. Budgeted at one working day. Power BI Desktop runs on
Windows (use a VM, a loaner machine, or Power BI Service in the browser if Desktop is unavailable).

## 1. Data sources (already generated — do not rebuild)

Load from the latest `outputs/<YYYY-MM>/` snapshot:

| Power BI table | Source file | Grain |
| --- | --- | --- |
| `fact_kpi_snapshot` | `fact_kpi_snapshot.csv` | metric × period |
| `fact_forecast` | `fact_forecast.csv` (via `evidence_forecast.csv`) | metric × period |
| `fact_provider_ops_event` | `fact_provider_ops_event.csv` | event |
| `fact_validation_issue` | `fact_validation_issue.csv` | issue |

Create a `dim_date` table in Power Query (Calendar table from MIN to MAX snapshot date),
mark it as the official date table.

## 2. Model

Star schema: the three fact tables relate to `dim_date` on the snapshot date. Keep relationships
single-directional. No bidirectional filters — this is a documented repo principle (see
`docs/DECISIONS.md`), keep the .pbix consistent with it.

## 3. Measures (copy-paste DAX)

```dax
KPI Current = SELECTEDVALUE('fact_kpi_snapshot'[metric_value])
KPI Prior Period =
CALCULATE(
    [KPI Current],
    DATEADD('dim_date'[Date], -1, MONTH)
)
KPI Delta % =
DIVIDE([KPI Current] - [KPI Prior Period], [KPI Prior Period])
Open Issues =
CALCULATE(
    COUNTROWS('fact_validation_issue'),
    'fact_validation_issue'[status] = "open"
)
Events YTD =
TOTALYTD(COUNTROWS('fact_provider_ops_event'), 'dim_date'[Date])
```

Mirror the exact metric definitions in `sql/marts/` — if the SQL and the DAX ever disagree,
the SQL is the truth.

## 4. Report pages (3, not 4 — keep it tight)

1. **Executive KPI scorecard** — card visuals for each KPI with delta %, one slicer (period).
2. **Trend & forecast** — line chart actual vs `fact_forecast`, consistent metric selector.
3. **Validation & QA** — open issues by severity, events over time. This page is the differentiator:
   it proves the dashboard carries its own audit view.

## 5. Finish line

- Export `Healthcare_Operations_Cockpit.pbix` + a PDF of page 1 into this `bi/` directory.
- Reference both from the README (Track 1 portfolio evidence).
- Delete nothing in `outputs/` — the workbook is a view, not a source.
