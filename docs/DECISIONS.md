# Product Decisions

## Current defaults

### Storage default: SQLite

SQLite is the official local default for this repo.

Why:

- it keeps the project easy to run on a laptop with no service setup
- it is enough for a single-user local reporting workflow
- the schema, SQL, and pipeline shape still translate cleanly to Postgres later

Postgres support is now implemented as an optional runtime path, while SQLite remains the verified default local backend.

### Presentation default: Streamlit

Streamlit is the primary presentation layer for V1.

Why:

- it is the fastest way to expose real SQL-backed outputs
- it keeps the demo tied to the same run artifacts as the workbook
- it proves product thinking without over-investing in frontend infrastructure

A heavier app stack is not the right tradeoff for the current scope.

### NPI checksum validation: included

Checksum validation is now part of V1 as a warning-level rule when a 10-digit NPI is present.

Why:

- it adds real healthcare-domain credibility
- it is a meaningful quality signal without turning the project into a compliance product
- warning severity is the right level because checksum failure is important but should not automatically block the entire run

### Commentary mode: deterministic by default

Deterministic commentary remains the only publishing path in V1.

Why:

- the output stays auditable and traceable to KPI deltas and issue counts
- it is easier to review and trace back to source metrics
- it avoids introducing model-quality questions into the core reporting story

Optional LLM-assisted drafting is now implemented as a separate structured-output path and should only receive structured JSON, never raw files.

### Forecasting: persist simple forecasts

V1 now persists forecasts to `fact_forecast` using a three-period rolling average for stable volume and backlog metrics.

Why:

- the schema already supported it
- the multi-period history supports transparent forecast comparison instead of single-period extrapolation
- a transparent method matches the short synthetic operating history

No advanced ML forecasting is planned for V1.

## Phase 2 implementation defaults

### Runtime model

The repo now uses a dual-backend model:

- SQLite remains the default local backend
- Postgres becomes an optional supported backend selected through one resolved runtime config

Why:

- this improves portability without making local setup heavier by default
- it turns storage-engine support into an architecture win instead of a deployment mandate

### Presentation model

The repo retains Streamlit as the primary product surface.

Why:

- the goal is stronger stakeholder polish, not a full frontend stack replacement
- keeping the current surface reduces stack churn and preserves product behavior

### Commentary model

The repo now supports an optional structured-JSON LLM draft mode, but deterministic commentary remains canonical.

Why:

- deterministic output stays easiest to audit and defend
- optional drafting adds modern awareness without making model output the source of truth

Required boundaries:

- no raw source files should be sent to the LLM path
- structured payloads only
- explicit review and approval metadata before any draft is considered publishable

### Validation model

Validation now expands through internal reference tables and cross-file logic.

Why:

- repo-owned reference data adds domain realism without introducing external service dependencies
- this keeps the project local-first and testable while making the controls story much stronger

Target areas:

- markets and teams
- allowed statuses and transitions
- provider reference attributes
- ownership and cross-file consistency rules

## Phase 2 non-goals

- no external provider API integration
- no autonomous publishing of LLM commentary
- no full SaaS auth or multitenancy layer
- no replacement of Streamlit with a custom web app in this phase
- no advanced ML forecasting beyond transparent statistical methods

## Phase 3 operating-history defaults

### Data strategy: hybrid backbone plus synthetic monthly operations

The operating-history buildout should use a hybrid data model:

- real or public-reference backbone data for provider, facility, market, and geography context
- synthetic monthly operational facts for onboarding, directory QA, backlog, ownership, and workflow state

Why:

- public data is strongest for dimensions and reference context
- internal operational states are rarely published in a form suitable for rule validation
- this keeps the repo realistic without pretending that confidential workflow data would be publicly available

Recommended backbone sources:

- NPPES / NPI registry subsets for provider identifiers, taxonomy, and addresses
- CMS provider or facility public files where useful for facility context
- HRSA shortage-area or access context where useful for market realism
- Census county or geography reference inputs where useful for county and market rollups

### Operating-history horizon: 18-24 closed monthly periods

The next horizon should be a real-looking historical archive, not just a larger random sample.

Default target:

- build 18-24 closed monthly periods
- preserve the existing three-source-file contract
- design month-over-month behavior deliberately, including seasonality, churn, QA campaigns, and operational incidents

Why:

- repeated monthly artifacts make the product look used over time
- closed periods are easier to defend than future-dated placeholders
- trend and control stories become more convincing when they span many periods

### Artifact strategy: archive operational traces, not just dashboard outputs

Each monthly period should preserve more than CSV outputs.

Required monthly artifacts:

- raw source files in `data/raw/YYYY-MM/`
- workbook export
- KPI, validation, event, and forecast CSV outputs
- deterministic commentary output
- `run_manifest.json`
- `change_summary.md`

Recommended recurring artifacts:

- quarterly screenshots
- steering-summary rollups
- change-log references to notable rule or process changes

Why:

- operational systems leave a paper trail
- monthly traces provide stronger operational evidence than one dashboard snapshot alone

### Product-surface strategy: keep Streamlit, add BI-friendly semantics

Streamlit remains the main demo surface, but the next layer should expose stable BI-oriented marts and field definitions.

Why:

- downstream analytics consumers require stable BI-oriented marts and semantic definitions
- stable semantic definitions are higher signal than replacing the frontend stack

### Phase 3 non-goals

- no attempt to turn all monthly operational events into claimed real data
- no large-scale external data ingestion platform
- no replacement of the existing source-file contract with a totally new product
- no expansion into multiple unrelated healthcare scenarios at once
