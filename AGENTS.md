# Repository Working Agreement

## Purpose

This repository implements a healthcare operations reporting pipeline for provider roster, onboarding, and directory-quality workflows. SQLite is the reproducible default backend. PostgreSQL and structured LLM drafting are optional paths.

## Read First

1. `README.md` for scope, setup, outputs, and limitations.
2. `docs/TECHNICAL_SPEC.md` and `docs/DATA_MODEL.md` for system contracts.
3. `docs/DECISIONS.md` for architectural boundaries.
4. `docs/DEMO_SCRIPT.md` and `docs/DEMO_ASSETS.md` for the verified walkthrough.

## Required Checks

Run from the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
ruff check src tests
pytest -q
healthcare-ops-kpi-qa seed-demo-data
healthcare-ops-kpi-qa refresh-demo-data
```

For dashboard changes, also start Streamlit and confirm the health endpoint and latest successful April run load correctly.

## Data and Security Boundaries

- Keep the committed demo synthetic and clearly labeled.
- Do not commit raw runtime inputs, local databases, credentials, secret files, or LLM payload/error artifacts.
- Keep deterministic commentary canonical; optional model output requires separate review metadata.
- Do not send raw source files through the LLM path.
- Use relative paths in committed documentation.

## Change Discipline

- Update documentation only when behavior, commands, contracts, or limitations change.
- Record consequential architecture decisions in `docs/DECISIONS.md`; rely on Git history for routine changes.
- Keep generated evidence limited to the allowlisted April workbook and compact extracts.
- Before committing, review `git status --short`, run the relevant checks, and scan the staged diff for local paths or credentials.
