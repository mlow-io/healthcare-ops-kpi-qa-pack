# Data Provenance Notes — Public vs. Synthetic

This note documents the data policy for this repository: which data is synthetic,
which public sources could back the reference tables, and where the seam sits.

## Current state

All operational inputs (`provider_roster_YYYY_MM.csv`, `onboarding_tracker_YYYY_MM.xlsx`,
`directory_audit_YYYY_MM.csv`) are **synthetic but realistic**, and the three-period demo
dataset (`2026-02` through `2026-04`) is generated deterministically so trend comparisons
are reproducible.

## Architecture principle

The high-signal pattern for analytics projects in domains where internal data is never
published:

- **Real public data for dimensions and backbone tables** — provider identifiers,
  facility reference data, geography.
- **Synthetic data for operational events** — onboarding stages, QA pass/fail workflow,
  queue aging, internal ownership states. No public dataset exists for these, and
  pretending otherwise would be less credible than modeling them honestly.
- **Document the seam explicitly** — every consumer of the mart should be able to tell
  which tables represent reference truth and which represent simulated operations.

## Public backbone sources considered

| Source | Best for | Reference |
| --- | --- | --- |
| CMS NPPES / NPI Registry | NPI, taxonomy, practice locations, deactivation checks | [CMS Data Dissemination](https://www.cms.gov/medicare/regulations-guidance/administrative-simplification/data-dissemination) |
| CMS Provider Data Catalog / Care Compare | Clinician, hospital, and facility reference data | [Data Available to Everyone](https://www.cms.gov/data-research/cms-data/data-available-everyone) |
| HRSA HPSA | Workforce shortage and underserved-area context | [HRSA Data](https://data.hrsa.gov/) |
| Census TIGER/Line + county population | Map geometry, service-area rollups | [TIGER/Line](https://www.census.gov/programs-surveys/geography/technical-documentation/complete-technical-documentation/file-availability.html) |

## Why synthetic operational layers remain

Internal workflow states — credentialing queues, audit dispositions, backlog aging,
ownership transitions — are almost never present in public data. Modeling them
synthetically with realistic distributions, while keeping reference tables traceable to
public sources where used, demonstrates the modeling judgment operational reporting
requires: knowing both what data exists and what a defensible system design looks like.
