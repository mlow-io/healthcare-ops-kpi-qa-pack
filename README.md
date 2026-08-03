# Healthcare Operations KPI & QA Pack

This repository implements a healthcare operations analytics pipeline for provider roster, onboarding, and directory-accuracy reporting.

## Capabilities

- Repeatable healthcare operations reporting from CSV/XLSX inputs
- Canonical SQL-backed event and KPI models
- Persisted validation, tie-out, and QA exception outputs
- Controlled AI-assisted commentary with explicit human review

## V1 scenario

The first version is framed as a provider operations / directory QA reporting asset. Source files are synthetic but realistic:

- `provider_roster_YYYY_MM.csv`
- `onboarding_tracker_YYYY_MM.xlsx`
- `directory_audit_YYYY_MM.csv`

The system standardizes those files into a canonical event model, computes KPI snapshots, logs validation issues, exports an audit workbook, and drafts an executive summary.

A built-in three-period demo dataset is available for `2026-02`, `2026-03`, and `2026-04` so trend and prior-period comparisons are meaningful instead of single-period placeholders.

## Outputs

- Validation report with row-level issues and run-level counts
- KPI mart with monthly snapshots by market and team
- Excel workbook with summary, detail, variance, tie-out, and exceptions tabs
- Monthly Operations Cockpit with persisted run context, KPI definitions, trend and segment analysis, QA tie-outs, forecast assumptions, and a review packet
- Draft commentary for a monthly operations review

## Architecture

```text
raw files
  -> staged normalized records
  -> canonical event facts + dimensions
  -> KPI / forecast / validation marts
  -> workbook, dashboard, commentary outputs
```

## Repo map

```text
healthcare-ops-kpi-qa-pack/
  AGENTS.md
  README.md
  pyproject.toml
  requirements.txt
  config/
    field_mappings.yml
    kpi_definitions.yml
    reference_data.yml
  docs/
    PRD.md
    TECHNICAL_SPEC.md
    DATA_MODEL.md
    IMPLEMENTATION_PLAN.md
    OPERATING_HISTORY_PLAN.md
    PROCESS_FLOW.md
    DECISIONS.md
    DEMO_SCRIPT.md
    DEMO_ASSETS.md
    demo_assets/
  sql/
    ddl.sql
    ddl_postgres.sql
    marts.sql
    marts_postgres.sql
  src/healthcare_ops_kpi_qa/
    __init__.py
    main.py
    settings.py
    ingest.py
    validate.py
    transform.py
    kpis.py
    forecast.py
    commentary.py
    llm_draft.py
    reference_data.py
    export_excel.py
    dashboard.py
  data/
    raw/
    sample/
    processed/
  outputs/
  tests/
```

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
healthcare-ops-kpi-qa seed-demo-data
healthcare-ops-kpi-qa refresh-demo-data
pytest -q
streamlit run src/healthcare_ops_kpi_qa/dashboard.py
```

Run these commands from the repository root. The deterministic demo does not require credentials or external services.

## Monthly Operations Cockpit

The Streamlit cockpit is a read-only operational review surface over persisted SQLite mart data. Select one successful reporting run, then apply market, team, and source filters where the underlying V1 data grain supports them.

- **Executive summary:** run health, headline KPI values, prior-period context, and persisted variance.
- **Briefing trust state:** `Ready`, `Ready with reviewable exceptions`, or `Not ready`, with an explicit next operational action. Refresh success is supporting evidence, not a claim that the period is exception-free.
- **KPI definitions:** formulas and display rules from `config/kpi_definitions.yml`, plus selected-cut numerator/denominator detail.
- **Trends and market/team:** latest successful run per period with direction-aware, human-readable comparisons and explicit unavailable states for unsupported combined cuts.
- **QA & tie-outs:** a source-to-workbook trust chain with source receipt, staging, canonical events, persisted snapshots, validation exceptions, workbook availability, and workbook-summary value parity.
- **Forecast assumptions:** actual history, a distinct next-period forecast point, observed range, transparent three-period rolling-average method, and limits.
- **Review packet:** deterministic commentary, separately labeled optional LLM draft status requiring human review, selected-run metadata, and matching downloads including the audit workbook.

All displayed operations data is synthetic. The cockpit does not recalculate KPIs, alter the refresh pipeline, or display local file paths.

The refresh writes:

- SQLite data to `data/processed/healthcare_ops_kpi_qa.sqlite3`
- event, KPI, and validation CSV outputs to `outputs/YYYY-MM/`
- forecast CSV output to `outputs/YYYY-MM/fact_forecast.csv`
- an audit workbook to `outputs/YYYY-MM/healthcare_ops_kpi_qa_pack_YYYY_MM.xlsx`
- a commentary preview to `outputs/YYYY-MM/commentary_preview.txt`
- optional LLM draft artifacts to `outputs/YYYY-MM/llm_commentary_*` when explicitly enabled and configured

The LLM path is not part of the deterministic demo. It requires an `OPENAI_API_KEY`, writes separate draft/review artifacts, and never replaces the templated commentary:

```bash
healthcare-ops-kpi-qa generate-llm-draft --period 2026-04
```

## Recommended build order

1. Lock the sample input contracts in `config/field_mappings.yml`.
2. Implement staging and validation using the canonical schema in `sql/ddl.sql`.
3. Implement KPI calculation and snapshot loading.
4. Export the Excel pack.
5. Add Streamlit dashboard views.
6. Add templated commentary.
7. Persist transparent rolling-average forecasts for stable metrics.
8. Capture demo assets and reproducible evidence.

## Current status

- `M1-M8` are complete for the original V1 scope.
- Phase 2 runtime abstraction, internal reference validation, optional LLM draft artifacts, and Streamlit polish are now implemented.
- SQLite is the reproducible default backend and the path used by the public demo.
- The optional Postgres path was exercised locally against PostgreSQL 16 with matching demo-period row counts and overall KPI outputs. It is not currently covered by automated CI.

## Phase 2 delivered surface

The current repo now includes:

1. SQLite-default runtime config with optional Postgres connection support.
2. Repo-owned `reference_data.yml` inputs for markets, teams, provider attributes, and status-transition validation.
3. Optional structured-JSON LLM commentary drafting with separate payload, draft, and review artifacts.
4. A more stakeholder-facing Streamlit app with run summary, KPI comparison, validation drilldowns, forecast views, and executive-review surfaces.

## Case study

**Problem:** Provider operations teams often receive roster, onboarding, and directory-audit exports with inconsistent fields and quality problems. Directly calculating KPIs from those files can hide exceptions or inflate counts.

**Inputs:** Three periods of synthetic CSV/XLSX source files shaped like operational exports. The repository contains no real patient, member, or provider data.

**Controls:** Required-file checks, canonical field mappings, reference-data checks, duplicate detection, NPI format/checksum checks, date-sequence checks, status validation, and persisted row-level exceptions.

**Outputs:** SQLite reporting tables, KPI and forecast extracts, an audit workbook, a Streamlit dashboard, and deterministic executive commentary. A compact `2026-04` evidence set is intentionally versioned; runtime databases and other generated files are excluded.

**Intended users:** Provider-data, network-operations, implementation, reporting, and data-quality teams that need a repeatable monthly review pack.

**Limitations:** All operational facts are synthetic. Forecasts use a transparent rolling average, duplicate detection is rule-based, the Postgres path is not in CI, and LLM commentary remains optional and human-reviewed.

## Next horizon

The highest-value next phase is not more app surface. It is stronger operational evidence.

Planned next moves:

1. Build an 18-24 month operating history with archived monthly packs.
2. Add controls-matrix and tie-out documentation.
3. Add operational delivery and governance artifacts such as UAT, change log, and steering-summary docs.
4. Add a BI-facing semantic layer and exports.
5. Add Docker and CI for reproducible runtime checks.

See [the operating-history plan](docs/OPERATING_HISTORY_PLAN.md) and [the implementation plan](docs/IMPLEMENTATION_PLAN.md) for the concrete sequence.
