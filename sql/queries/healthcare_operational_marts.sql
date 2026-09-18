-- ==============================================================================
-- Healthcare Operational Analytics & Mart Query Showcase
-- Repository: healthcare-ops-kpi-qa-pack
-- Author: Matthew Brooks
-- Target Standards: ANSI SQL / PostgreSQL / SQLite compatible
-- ==============================================================================

-- ------------------------------------------------------------------------------
-- 1. LATEST PROVIDER STATE DEDUPLICATION
-- Business Context: Providers submit multiple roster updates over time. Extract
-- the most recent verified state per NPI without data loss or duplicate joins.
-- ------------------------------------------------------------------------------
WITH ranked_provider_updates AS (
    SELECT
        e.event_id,
        e.provider_npi,
        e.provider_name,
        e.specialty_name,
        e.event_status,
        d.calendar_date AS effective_date,
        e.source_system,
        ROW_NUMBER() OVER (
            PARTITION BY e.provider_npi 
            ORDER BY d.calendar_date DESC, e.event_id DESC
        ) AS recency_rank
    FROM fact_provider_ops_event e
    JOIN dim_date d ON d.date_key = e.event_date_key
    WHERE e.provider_npi IS NOT NULL
)
SELECT
    provider_npi,
    provider_name,
    specialty_name,
    event_status,
    effective_date,
    source_system
FROM ranked_provider_updates
WHERE recency_rank = 1;


-- ------------------------------------------------------------------------------
-- 2. MULTI-SOURCE RECONCILIATION & TIE-OUT (SOURCE VS. TARGET AUDIT)
-- Business Context: Reconcile incoming clinic roster rows against processed
-- event facts. Isolate missing records, exceptions, and verify population parity.
-- ------------------------------------------------------------------------------
WITH staged_counts AS (
    SELECT
        reporting_period,
        source_file_id,
        COUNT(*) AS staged_row_count
    FROM stg_provider_ops_record
    GROUP BY reporting_period, source_file_id
),
processed_event_counts AS (
    SELECT
        r.reporting_period,
        e.source_file_id,
        COUNT(*) AS event_count,
        SUM(CASE WHEN e.completion_flag = 1 THEN 1 ELSE 0 END) AS completed_count,
        SUM(CASE WHEN e.qa_issue_flag = 1 THEN 1 ELSE 0 END) AS exception_count
    FROM fact_provider_ops_event e
    JOIN etl_run r ON r.run_id = e.run_id
    GROUP BY r.reporting_period, e.source_file_id
)
SELECT
    COALESCE(s.reporting_period, p.reporting_period) AS reporting_period,
    sf.source_file_name,
    COALESCE(s.staged_row_count, 0) AS raw_input_count,
    COALESCE(p.event_count, 0) AS processed_event_count,
    COALESCE(p.completed_count, 0) AS clean_completed_count,
    COALESCE(p.exception_count, 0) AS exception_quarantine_count,
    (COALESCE(s.staged_row_count, 0) - COALESCE(p.event_count, 0)) AS reconciliation_variance,
    CASE 
        WHEN COALESCE(s.staged_row_count, 0) = COALESCE(p.event_count, 0) THEN 'TIED_OUT'
        ELSE 'VARIANCE_FLAGGED'
    END AS audit_tie_out_status
FROM staged_counts s
FULL OUTER JOIN processed_event_counts p 
    ON s.reporting_period = p.reporting_period 
   AND s.source_file_id = p.source_file_id
LEFT JOIN dim_source_file sf 
    ON sf.source_file_id = COALESCE(s.source_file_id, p.source_file_id)
ORDER BY reporting_period DESC;


-- ------------------------------------------------------------------------------
-- 3. WORK QUEUE AGING & SLA BREACH ANALYSIS
-- Business Context: Partition active provider onboarding cases into operational
-- aging buckets (<30, 31-60, 61-90, 90+ days) and calculate SLA compliance.
-- ------------------------------------------------------------------------------
SELECT
    m.market_name,
    t.team_name,
    COUNT(*) AS total_active_cases,
    SUM(CASE WHEN e.turnaround_days <= 30 THEN 1 ELSE 0 END) AS aging_under_30_days,
    SUM(CASE WHEN e.turnaround_days BETWEEN 31 AND 60 THEN 1 ELSE 0 END) AS aging_31_to_60_days,
    SUM(CASE WHEN e.turnaround_days BETWEEN 61 AND 90 THEN 1 ELSE 0 END) AS aging_61_to_90_days,
    SUM(CASE WHEN e.turnaround_days > 90 THEN 1 ELSE 0 END) AS aging_over_90_days,
    SUM(CASE WHEN e.backlog_over_sla_flag = 1 THEN 1 ELSE 0 END) AS total_sla_breaches,
    ROUND(
        100.0 * SUM(CASE WHEN e.backlog_over_sla_flag = 0 THEN 1 ELSE 0 END) / COUNT(*), 
        2
    ) AS sla_compliance_pct
FROM fact_provider_ops_event e
JOIN dim_market m ON m.market_id = e.market_id
JOIN dim_team t ON t.team_id = e.team_id
WHERE e.completion_flag = 0
GROUP BY m.market_name, t.team_name
ORDER BY total_sla_breaches DESC;


-- ------------------------------------------------------------------------------
-- 4. MONTH-OVER-MONTH KPI PERFORMANCE & VARIANCE DRIFT
-- Business Context: Calculate directional variance and percentage drift across
-- consecutive monthly snapshots to support executive briefing scorecards.
-- ------------------------------------------------------------------------------
SELECT
    r.reporting_period,
    k.kpi_code,
    k.kpi_name,
    m.market_name,
    s.actual_value,
    s.target_value,
    s.prior_period_value,
    s.variance_value,
    s.variance_pct,
    CASE 
        WHEN s.actual_value <= s.target_value THEN 'ON_TARGET'
        WHEN s.actual_value > s.target_value AND s.variance_pct <= 5.0 THEN 'WITHIN_TOLERANCE'
        ELSE 'SLA_RISK_ACTION_REQUIRED'
    END AS operational_health_status
FROM fact_kpi_snapshot s
JOIN etl_run r ON r.run_id = s.run_id
JOIN dim_kpi k ON k.kpi_id = s.kpi_id
LEFT JOIN dim_market m ON m.market_id = s.market_id
WHERE r.reporting_period = '2026-04'
ORDER BY k.kpi_code, m.market_name;


-- ------------------------------------------------------------------------------
-- 5. EXCEPTION FREQUENCY & PARETO ROOT-CAUSE ANALYSIS
-- Business Context: Identify top recurring data quality failures across files
-- to drive upstream process improvement with clinic onboarding coordinators.
-- ------------------------------------------------------------------------------
WITH exception_counts AS (
    SELECT
        v.issue_type,
        v.severity,
        sf.source_file_name,
        COUNT(*) AS occurrence_count
    FROM fact_validation_issue v
    JOIN etl_run r ON r.run_id = v.run_id
    LEFT JOIN dim_source_file sf ON sf.source_file_id = v.source_file_id
    WHERE r.reporting_period = '2026-04'
    GROUP BY v.issue_type, v.severity, sf.source_file_name
)
SELECT
    issue_type,
    severity,
    source_file_name,
    occurrence_count,
    ROUND(
        100.0 * occurrence_count / SUM(occurrence_count) OVER (), 
        2
    ) AS pct_of_total_exceptions,
    SUM(occurrence_count) OVER (
        ORDER BY occurrence_count DESC 
        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    ) AS cumulative_exception_volume
FROM exception_counts
ORDER BY occurrence_count DESC;
