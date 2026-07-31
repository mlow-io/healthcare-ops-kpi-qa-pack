create or replace view mart_provider_ops_base as
select
  e.event_id,
  r.reporting_period,
  d.calendar_date as event_date,
  m.market_name,
  t.team_code,
  t.team_name,
  e.provider_npi,
  e.provider_name,
  e.specialty_name,
  e.event_type,
  e.event_status,
  e.completion_flag,
  e.turnaround_days,
  e.backlog_flag,
  e.backlog_over_sla_flag,
  e.qa_issue_flag,
  e.required_field_complete_flag,
  e.source_system
from fact_provider_ops_event e
join etl_run r on r.run_id = e.run_id
left join dim_date d on d.date_key = e.event_date_key
left join dim_market m on m.market_id = e.market_id
left join dim_team t on t.team_id = e.team_id;

create or replace view mart_validation_summary as
select
  r.reporting_period,
  sf.source_file_name,
  v.issue_type,
  v.severity,
  count(*) as issue_count
from fact_validation_issue v
join etl_run r on r.run_id = v.run_id
left join dim_source_file sf on sf.source_file_id = v.source_file_id
group by
  r.reporting_period,
  sf.source_file_name,
  v.issue_type,
  v.severity;

create or replace view mart_kpi_snapshot_latest as
select
  r.reporting_period,
  k.kpi_code,
  k.kpi_name,
  m.market_name,
  t.team_code,
  s.actual_value,
  s.target_value,
  s.prior_period_value,
  s.variance_value,
  s.variance_pct,
  s.numerator_value,
  s.denominator_value
from fact_kpi_snapshot s
join etl_run r on r.run_id = s.run_id
join dim_kpi k on k.kpi_id = s.kpi_id
left join dim_market m on m.market_id = s.market_id
left join dim_team t on t.team_id = s.team_id
where r.run_status = 'success';

create or replace view mart_llm_commentary_latest as
select
  d.draft_id,
  d.run_id,
  d.reporting_period,
  d.draft_type,
  d.model_provider,
  d.model_name,
  d.review_status,
  d.reviewer_name,
  d.review_notes,
  d.created_at,
  d.reviewed_at
from fact_llm_commentary_draft d
join etl_run r on r.run_id = d.run_id
where r.run_status = 'success';
