create table if not exists etl_run (
  run_id integer primary key,
  reporting_period text not null,
  run_started_at timestamp not null,
  run_finished_at timestamp,
  source_file_count integer default 0,
  staged_row_count integer default 0,
  validation_issue_count integer default 0,
  run_status text not null,
  operator_name text,
  notes text
);

create table if not exists dim_date (
  date_key integer primary key,
  calendar_date date not null unique,
  year_num integer not null,
  quarter_num integer not null,
  month_num integer not null,
  month_name text not null,
  week_num integer not null,
  is_month_end boolean not null default false
);

create table if not exists dim_market (
  market_id integer primary key,
  market_name text not null unique,
  state_code text,
  region_name text,
  active_flag boolean not null default true
);

create table if not exists dim_team (
  team_id integer primary key,
  team_code text not null unique,
  team_name text not null,
  manager_name text,
  active_flag boolean not null default true
);

create table if not exists dim_source_file (
  source_file_id integer primary key,
  run_id integer not null references etl_run(run_id),
  source_file_name text not null,
  source_file_type text not null,
  reporting_period text not null,
  row_count integer,
  loaded_at timestamp not null
);

create table if not exists dim_kpi (
  kpi_id integer primary key,
  kpi_code text not null unique,
  kpi_name text not null,
  kpi_description text,
  formula_text text not null,
  target_direction text not null,
  display_format text not null,
  owner_role text
);

create table if not exists stg_provider_ops_record (
  stg_record_id integer primary key,
  run_id integer not null references etl_run(run_id),
  source_file_id integer not null references dim_source_file(source_file_id),
  source_file_type text not null,
  source_row_num integer not null,
  reporting_period text not null,
  provider_name text,
  provider_npi text,
  specialty_name text,
  market_name text,
  team_code text,
  workflow_status text,
  received_date date,
  completed_date date,
  effective_date date,
  audit_date date,
  audit_result text,
  audit_issue_type text,
  owner_name text,
  phone_number text,
  address_line text,
  raw_payload_json text
);

create table if not exists fact_provider_ops_event (
  event_id integer primary key,
  run_id integer not null references etl_run(run_id),
  event_date_key integer references dim_date(date_key),
  market_id integer references dim_market(market_id),
  team_id integer references dim_team(team_id),
  provider_npi text,
  provider_name text,
  specialty_name text,
  event_type text not null,
  event_status text not null,
  completion_flag boolean not null default false,
  turnaround_days numeric,
  backlog_flag boolean not null default false,
  backlog_over_sla_flag boolean not null default false,
  qa_issue_flag boolean not null default false,
  required_field_complete_flag boolean not null default false,
  source_system text not null
);

create table if not exists fact_validation_issue (
  validation_issue_id integer primary key,
  run_id integer not null references etl_run(run_id),
  source_file_id integer references dim_source_file(source_file_id),
  stg_record_id integer references stg_provider_ops_record(stg_record_id),
  issue_type text not null,
  severity text not null,
  row_identifier text,
  issue_message text not null,
  status text not null default 'open',
  created_at timestamp not null
);

create table if not exists fact_kpi_snapshot (
  snapshot_id integer primary key,
  run_id integer not null references etl_run(run_id),
  snapshot_date_key integer not null references dim_date(date_key),
  kpi_id integer not null references dim_kpi(kpi_id),
  market_id integer references dim_market(market_id),
  team_id integer references dim_team(team_id),
  actual_value numeric not null,
  target_value numeric,
  prior_period_value numeric,
  variance_value numeric,
  variance_pct numeric,
  numerator_value numeric,
  denominator_value numeric,
  notes text
);

create table if not exists fact_forecast (
  forecast_id integer primary key,
  generated_run_id integer not null references etl_run(run_id),
  forecast_period_date_key integer not null references dim_date(date_key),
  kpi_id integer not null references dim_kpi(kpi_id),
  market_id integer references dim_market(market_id),
  team_id integer references dim_team(team_id),
  model_name text not null,
  forecast_value numeric not null,
  lower_bound numeric,
  upper_bound numeric
);

create table if not exists fact_llm_commentary_draft (
  draft_id integer primary key,
  run_id integer not null references etl_run(run_id),
  reporting_period text not null,
  draft_type text not null,
  model_provider text not null,
  model_name text not null,
  prompt_payload_json text not null,
  response_json text,
  draft_text text,
  review_status text not null default 'pending_review',
  reviewer_name text,
  review_notes text,
  created_at timestamp not null,
  reviewed_at timestamp
);

create index if not exists idx_stg_provider_npi
  on stg_provider_ops_record (provider_npi);

create index if not exists idx_event_run_market_team
  on fact_provider_ops_event (run_id, market_id, team_id);

create index if not exists idx_validation_run_issue_type
  on fact_validation_issue (run_id, issue_type);

create index if not exists idx_kpi_snapshot_run_kpi
  on fact_kpi_snapshot (run_id, kpi_id);

create index if not exists idx_llm_draft_run_status
  on fact_llm_commentary_draft (run_id, review_status);
