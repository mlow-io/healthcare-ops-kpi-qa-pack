# User Acceptance Testing (UAT) Test Matrix & Defect Log

**Project:** Healthcare Operations KPI & QA Reporting Engine  
**Document ID:** UAT-QA-2026-04  
**Release Target:** v0.1.0 / v0.2.0  
**Test Lead:** Matthew Brooks (Operations / Data QA Analyst)  
**Stakeholders:** Provider Network Operations, Reporting & Analytics, Credentialing Services  
**Environment:** Staging / Local SQLite Validation Suite  

---

## 1. Test Execution Summary

| Total Scenarios | Passed | Failed (Logged as Defects) | Blocked | Pass Rate |
| :---: | :---: | :---: | :---: | :---: |
| 15 | 13 | 2 (Resolved in v0.1.0) | 0 | 100% (Post-Remediation) |

---

## 2. Comprehensive UAT Scenario Matrix

| Test ID | Business Domain / Requirement | Test Scenario Description | Expected Outcome | Execution Result | Defect Ref |
| :--- | :--- | :--- | :--- | :---: | :---: |
| **UAT-001** | Multi-Source Ingestion | Ingest monthly clinic roster with mixed whitespace and formatting | Fields normalized, leading/trailing whitespace trimmed, phone digits standardized to 10 digits | **PASS** | — |
| **UAT-002** | Data Quality / NPI | Ingest record with 9-digit NPI | System flags `INVALID_NPI_LENGTH` at Error severity; record quarantined from KPI calculations | **PASS** | — |
| **UAT-003** | Data Quality / NPI Checksum | Ingest 10-digit NPI failing Luhn checksum algorithm | System flags `NPI_CHECKSUM_WARNING` at Warning severity; record allowed to proceed with audit note | **PASS** | — |
| **UAT-004** | Duplicate Detection | Ingest two roster records with identical NPI but differing clinic suite numbers | Flags `DUPLICATE_CANDIDATE`; creates single consolidated provider fact with multi-location association | **PASS** | — |
| **UAT-005** | Identity Resolution | Ingest two distinct physicians sharing identical last name at same facility | Matches on NPI Type 1; distinguishes individual physician identities without merging records | **PASS** | — |
| **UAT-006** | Taxonomy Validation | Ingest provider with deprecated or non-standard CMS taxonomy code | Flags `INACTIVE_TAXONOMY`; routes record to Operations Review Queue | **PASS** | — |
| **UAT-007** | Reconciliation Tie-Out | Run monthly pipeline on 250 raw source records | Exact sum of processed events (236) + quarantined exceptions (14) equals raw source count (250) | **PASS** | — |
| **UAT-008** | Queue Aging / Buckets | Calculate turnaround time for uncompleted onboarding cases | Cases correctly partitioned into `<30`, `31–60`, `61–90`, and `90+` day aging buckets | **PASS** | — |
| **UAT-009** | SLA Breach Detection | Onboarding event exceeds 30-day target threshold | System automatically asserts `backlog_over_sla_flag = 1`; increments SLA breach KPI numerator | **PASS** | — |
| **UAT-010** | Monthly KPI Snapshot | Calculate monthly time-to-billable across urgent care clinics | Snapshot persists accurate average cycle time with numerator and denominator in `fact_kpi_snapshot` | **PASS** | — |
| **UAT-011** | MoM Variance Calculation | Compare April performance to March baseline | System calculates directional delta and percentage variance matching manual Excel check | **PASS** | — |
| **UAT-012** | Forecast Range Bounds | Generate 3-period rolling average forecast for queue volume | System computes transparent point forecast, lower bound, and upper bound without negative values | **PASS** | — |
| **UAT-013** | Audit Workbook Export | Export monthly reporting package to Excel | Multi-tab workbook generates with summary cards, variance tables, and audit tie-out sheet matching SQLite | **PASS** | DEF-001 |
| **UAT-014** | Reporting Trust Gate | Inject artificial 5% variance between staged records and mart | Cockpit reporting trust status shifts from "Verified" to "Blocked: Reconciliation Failure" | **PASS** | DEF-002 |
| **UAT-015** | Commentary Guardrails | Request automated executive commentary draft | Generated text strictly cites persisted KPI metrics; does not invent ungrounded financial figures | **PASS** | — |

---

## 3. Defect Log & Corrective Actions

### Defect DEF-001: Excel Workbook Header Value Drift on Multi-Run Re-Export
* **Severity:** Medium (P3)
* **Description:** Re-running the monthly export script without clearing the output directory caused Excel audit tie-out sheet to retain prior batch run timestamps.
* **Root Cause:** File handle append mode rather than clean workbook initialization in export routine.
* **Corrective Action:** Updated `export_workbook.py` to enforce deterministic clean file write and added automated test assertion in `test_export.py`. Re-verified in UAT-013: **RESOLVED**.

### Defect DEF-002: Reconciliation Tie-Out Threshold Rounding Error
* **Severity:** High (P2)
* **Description:** Floating-point rounding on average cycle time caused a 0.001 delta discrepancy, triggering an accidental reporting trust warning on clean demo runs.
* **Root Cause:** Division result not cast to fixed decimal precision before equality assertion.
* **Corrective Action:** Enforced explicit `ROUND(..., 2)` precision on all KPI ratio calculations and tie-out checks. Re-verified in UAT-014: **RESOLVED**.

---

## 4. Sign-Off & Release Recommendation
All 15 test scenarios have achieved passing status with zero outstanding P1/P2 blockers. The data pipeline and operational reporting outputs satisfy core healthcare data governance standards. Recommended for production operational deployment.
