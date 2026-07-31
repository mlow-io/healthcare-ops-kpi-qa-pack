from __future__ import annotations

from calendar import monthrange

import pandas as pd
from sqlalchemy.engine import Connection

from .commentary import build_commentary_preview
from .db import (
    execute_sql,
    fetch_all,
    fetch_one,
    get_connection,
    initialize_database,
    read_sql_frame,
)
from .export_excel import export_workbook
from .forecast import compute_forecasts, next_period_snapshot_date_key
from .ingest import load_field_mappings, load_period_inputs
from .kpis import compute_kpi_snapshots, load_kpi_definitions, snapshot_date_key
from .llm_draft import build_draft_record, build_llm_payload, generate_llm_draft
from .reference_data import load_reference_data
from .settings import get_app_settings, get_project_paths
from .time_utils import json_dumps, utc_now_naive
from .transform import build_event_fact
from .validate import build_event_validation_issues, build_staged_validation_issues

SLA_DAYS = 30


def run_refresh(period: str, include_llm_draft: bool = False) -> dict:
    staged_inputs, source_file_rows = load_period_inputs(period)
    if staged_inputs.empty:
        raise ValueError(f"No source files found for period {period}.")

    config = load_field_mappings()
    reference_data = load_reference_data()
    run_id: int | None = None
    try:
        with get_connection() as connection:
            initialize_database(connection)
            run_id = _insert_run(connection, period)
            source_lookup = _insert_source_files(connection, run_id, source_file_rows)

            staged_inputs = staged_inputs.copy()
            staged_inputs["run_id"] = run_id
            staged_inputs["source_file_id"] = staged_inputs["source_file_name"].map(source_lookup)
            _insert_staged_records(connection, staged_inputs)

            staged_df = read_sql_frame(
                connection,
                """
                select
                  s.*,
                  sf.source_file_name
                from stg_provider_ops_record s
                join dim_source_file sf on sf.source_file_id = s.source_file_id
                where s.run_id = :run_id
                """,
                {"run_id": run_id},
            )

            staged_issues = build_staged_validation_issues(staged_df, config["status_values"], reference_data)
            if not staged_issues.empty:
                staged_issues["run_id"] = run_id
                _prepare_validation_issue_df(staged_issues).to_sql(
                    "fact_validation_issue",
                    connection,
                    if_exists="append",
                    index=False,
                )

            event_df = build_event_fact(staged_df, config["status_values"], period)
            if event_df.empty:
                raise ValueError("No canonical event rows were created from the staged input.")

            _upsert_markets(connection, event_df["market_name"].dropna().unique().tolist(), reference_data)
            _upsert_teams(connection, event_df["team_code"].dropna().unique().tolist(), reference_data)
            _upsert_dates(connection, event_df["event_date"].dropna().tolist() + [_period_end(period)])
            _upsert_kpis(connection)

            event_df = _attach_dimension_keys(connection, event_df)
            event_df["run_id"] = run_id
            event_insert_df = event_df[
                [
                    "run_id",
                    "event_date_key",
                    "market_id",
                    "team_id",
                    "provider_npi",
                    "provider_name",
                    "specialty_name",
                    "event_type",
                    "event_status",
                    "completion_flag",
                    "turnaround_days",
                    "backlog_flag",
                    "backlog_over_sla_flag",
                    "qa_issue_flag",
                    "required_field_complete_flag",
                    "source_system",
                ]
            ].copy()
            event_insert_df = _prepare_int_columns(event_insert_df, ["run_id", "event_date_key", "market_id", "team_id"])
            event_insert_df.to_sql("fact_provider_ops_event", connection, if_exists="append", index=False)

            event_issues = build_event_validation_issues(event_df.assign(run_id=run_id), SLA_DAYS)
            if not event_issues.empty:
                event_issues["run_id"] = run_id
                _prepare_validation_issue_df(event_issues).to_sql(
                    "fact_validation_issue",
                    connection,
                    if_exists="append",
                    index=False,
                )

            snapshots = compute_kpi_snapshots(event_df, period, snapshot_date_key(period))
            snapshots = _attach_snapshot_ids(connection, snapshots, run_id)
            snapshots = _apply_prior_period_comparison(connection, snapshots, period)
            snapshots = _prepare_int_columns(
                snapshots,
                ["run_id", "snapshot_date_key", "kpi_id", "market_id", "team_id"],
            )
            snapshots = _prepare_float_columns(
                snapshots,
                [
                    "actual_value",
                    "target_value",
                    "prior_period_value",
                    "variance_value",
                    "variance_pct",
                    "numerator_value",
                    "denominator_value",
                ],
            )
            snapshots.to_sql("fact_kpi_snapshot", connection, if_exists="append", index=False)

            _upsert_dates(connection, [pd.to_datetime(str(next_period_snapshot_date_key(period))).date()])
            forecast_history = _load_forecast_history(connection, snapshots, period)
            forecasts = compute_forecasts(forecast_history, run_id, period)
            if not forecasts.empty:
                forecasts = _prepare_int_columns(
                    forecasts,
                    ["generated_run_id", "forecast_period_date_key", "kpi_id", "market_id", "team_id"],
                )
                forecasts = _prepare_float_columns(
                    forecasts,
                    ["forecast_value", "lower_bound", "upper_bound"],
                )
                forecasts.to_sql("fact_forecast", connection, if_exists="append", index=False)

            validation_count = int(
                fetch_one(
                    connection,
                    "select count(*) as issue_count from fact_validation_issue where run_id = :run_id",
                    {"run_id": run_id},
                )["issue_count"]
            )
            staged_count = len(staged_df)
            _update_run(connection, run_id, len(source_lookup), staged_count, validation_count)

            validation_output = pd.concat([staged_issues, event_issues], ignore_index=True)
            output_paths = _write_outputs(period, event_df, snapshots, validation_output, forecasts)

            overall_kpis = _decorate_snapshots(connection, snapshots, overall_only=True)
            all_kpis = _decorate_snapshots(connection, snapshots, overall_only=False)
            market_kpis = all_kpis[all_kpis["market_name"].notna() & all_kpis["team_code"].isna()]
            source_files_df = read_sql_frame(
                connection,
                "select source_file_name, source_file_type, row_count from dim_source_file where run_id = :run_id",
                {"run_id": run_id},
            )
            decorated_forecasts = _decorate_forecasts(connection, forecasts)
            commentary_text = build_commentary_preview(period, overall_kpis, market_kpis, validation_output)
            workbook_path = export_workbook(
                get_project_paths().outputs_dir / period / f"healthcare_ops_kpi_qa_pack_{period.replace('-', '_')}.xlsx",
                overall_kpis,
                all_kpis,
                validation_output,
                source_files_df,
                {
                    "run_id": run_id,
                    "period": period,
                    "staged_row_count": staged_count,
                    "event_row_count": len(event_df),
                    "validation_issue_count": validation_count,
                    "kpi_snapshot_count": len(snapshots),
                    "forecast_count": len(forecasts),
                },
                commentary_text,
                decorated_forecasts,
            )
            commentary_path = _write_commentary(period, commentary_text)
            output_paths["workbook_xlsx"] = workbook_path
            output_paths["commentary_txt"] = commentary_path
    except Exception as exc:
        if run_id is not None:
            with get_connection() as failure_connection:
                initialize_database(failure_connection)
                _mark_run_failed(failure_connection, run_id, str(exc))
        raise

    llm_result = None
    if include_llm_draft:
        llm_result = generate_llm_draft_for_run(run_id)
        if llm_result.get("output_paths"):
            output_paths.update(llm_result["output_paths"])

    return {
        "run_id": run_id,
        "period": period,
        "database_backend": get_app_settings().database.backend,
        "database_target": get_app_settings().database.target_label,
        "staged_row_count": staged_count,
        "event_row_count": len(event_df),
        "validation_issue_count": validation_count,
        "kpi_snapshot_count": len(snapshots),
        "forecast_count": len(forecasts),
        "llm_draft": llm_result,
        "outputs": output_paths,
    }


def generate_llm_draft_for_run(run_id: int) -> dict:
    with get_connection() as connection:
        initialize_database(connection)
        run_row = fetch_one(
            connection,
            """
            select run_id, reporting_period, run_status
            from etl_run
            where run_id = :run_id
            """,
            {"run_id": run_id},
        )
        if run_row is None:
            raise ValueError(f"Run {run_id} was not found.")

        reporting_period = str(run_row["reporting_period"])
        snapshots = read_sql_frame(
            connection,
            """
            select
              s.*,
              k.kpi_name,
              k.display_format,
              m.market_name,
              t.team_code
            from fact_kpi_snapshot s
            join dim_kpi k on k.kpi_id = s.kpi_id
            left join dim_market m on m.market_id = s.market_id
            left join dim_team t on t.team_id = s.team_id
            where s.run_id = :run_id
            """,
            {"run_id": run_id},
        )
        validation_issues = read_sql_frame(
            connection,
            "select * from fact_validation_issue where run_id = :run_id",
            {"run_id": run_id},
        )
        forecasts = read_sql_frame(
            connection,
            """
            select
              f.*,
              k.kpi_name,
              m.market_name,
              t.team_code
            from fact_forecast f
            join dim_kpi k on k.kpi_id = f.kpi_id
            left join dim_market m on m.market_id = f.market_id
            left join dim_team t on t.team_id = f.team_id
            where f.generated_run_id = :run_id
            """,
            {"run_id": run_id},
        )
        overall_kpis = snapshots[snapshots["market_name"].isna() & snapshots["team_code"].isna()].copy()
        market_kpis = snapshots[snapshots["market_name"].notna() & snapshots["team_code"].isna()].copy()

        deterministic_commentary_path = get_project_paths().outputs_dir / reporting_period / "commentary_preview.txt"
        if deterministic_commentary_path.exists():
            deterministic_commentary = deterministic_commentary_path.read_text()
        else:
            deterministic_commentary = build_commentary_preview(
                reporting_period,
                overall_kpis,
                market_kpis,
                validation_issues,
            )

        payload = build_llm_payload(
            reporting_period,
            deterministic_commentary,
            overall_kpis,
            market_kpis,
            validation_issues,
            forecasts,
        )

        try:
            draft, metadata = generate_llm_draft(payload)
            record = build_draft_record(run_id, reporting_period, payload, draft, metadata)
            draft_id = _insert_llm_draft_record(connection, record)
            output_paths = _write_llm_artifacts(
                reporting_period,
                payload.model_dump(),
                draft.model_dump(),
                draft.to_text(),
                {
                    "draft_id": draft_id,
                    "review_status": "pending_review",
                    "reviewer_name": None,
                    "review_notes": None,
                    "created_at": metadata["created_at"],
                    "reviewed_at": None,
                },
            )
            return {
                "status": "generated",
                "draft_id": draft_id,
                "model": metadata["model"],
                "output_paths": output_paths,
            }
        except Exception as exc:  # noqa: BLE001 - optional drafting must not fail the deterministic refresh
            output_paths = _write_llm_error_artifact(reporting_period, str(exc))
            return {
                "status": "failed",
                "error": str(exc),
                "output_paths": output_paths,
            }


def review_llm_draft(draft_id: int, reviewer_name: str, review_status: str, review_notes: str | None) -> dict:
    if review_status not in {"approved", "rejected"}:
        raise ValueError("review_status must be `approved` or `rejected`.")

    with get_connection() as connection:
        initialize_database(connection)
        draft_row = fetch_one(
            connection,
            """
            select draft_id, run_id, reporting_period
            from fact_llm_commentary_draft
            where draft_id = :draft_id
            """,
            {"draft_id": draft_id},
        )
        if draft_row is None:
            raise ValueError(f"Draft {draft_id} was not found.")

        execute_sql(
            connection,
            """
            update fact_llm_commentary_draft
            set
              review_status = :review_status,
              reviewer_name = :reviewer_name,
              review_notes = :review_notes,
              reviewed_at = :reviewed_at
            where draft_id = :draft_id
            """,
            {
                "draft_id": draft_id,
                "review_status": review_status,
                "reviewer_name": reviewer_name,
                "review_notes": review_notes,
                "reviewed_at": utc_now_naive(),
            },
        )

        updated_row = fetch_one(
            connection,
            """
            select
              draft_id,
              review_status,
              reviewer_name,
              review_notes,
              created_at,
              reviewed_at
            from fact_llm_commentary_draft
            where draft_id = :draft_id
            """,
            {"draft_id": draft_id},
        )

        output_paths = _write_llm_review_artifact(str(draft_row["reporting_period"]), updated_row)
        return {
            "draft_id": draft_id,
            "review_status": updated_row["review_status"],
            "reviewer_name": updated_row["reviewer_name"],
            "output_paths": output_paths,
        }


def latest_successful_run_id_for_period(period: str) -> int | None:
    with get_connection() as connection:
        initialize_database(connection)
        row = fetch_one(
            connection,
            """
            select max(run_id) as run_id
            from etl_run
            where run_status = 'success'
              and reporting_period = :period
            """,
            {"period": period},
        )
    if row is None or row["run_id"] is None:
        return None
    return int(row["run_id"])


def _insert_run(connection: Connection, period: str) -> int:
    payload = {
        "reporting_period": period,
        "run_started_at": utc_now_naive(),
        "run_status": "running",
    }
    if get_app_settings().database.backend == "postgres":
        result = execute_sql(
            connection,
            """
            insert into etl_run (
              reporting_period,
              run_started_at,
              run_status
            ) values (:reporting_period, :run_started_at, :run_status)
            returning run_id
            """,
            payload,
        )
        return int(result.scalar_one())

    result = execute_sql(
        connection,
        """
        insert into etl_run (
          reporting_period,
          run_started_at,
          run_status
        ) values (:reporting_period, :run_started_at, :run_status)
        """,
        payload,
    )
    return int(result.lastrowid)


def _insert_source_files(
    connection: Connection,
    run_id: int,
    source_file_rows: pd.DataFrame,
) -> dict[str, int]:
    if source_file_rows.empty:
        return {}

    rows = source_file_rows.copy()
    rows["run_id"] = run_id
    rows["loaded_at"] = utc_now_naive()
    rows.to_sql("dim_source_file", connection, if_exists="append", index=False)

    lookup_rows = fetch_all(
        connection,
        "select source_file_id, source_file_name from dim_source_file where run_id = :run_id",
        {"run_id": run_id},
    )
    return {str(row["source_file_name"]): int(row["source_file_id"]) for row in lookup_rows}


def _insert_staged_records(connection: Connection, staged_inputs: pd.DataFrame) -> None:
    insert_df = staged_inputs[
        [
            "run_id",
            "source_file_id",
            "source_file_type",
            "source_row_num",
            "reporting_period",
            "provider_name",
            "provider_npi",
            "specialty_name",
            "market_name",
            "team_code",
            "workflow_status",
            "received_date",
            "completed_date",
            "effective_date",
            "audit_date",
            "audit_result",
            "audit_issue_type",
            "owner_name",
            "phone_number",
            "address_line",
            "raw_payload_json",
        ]
    ].copy()
    insert_df.to_sql("stg_provider_ops_record", connection, if_exists="append", index=False)


def _prepare_int_columns(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    prepared = frame.copy()
    for column in columns:
        if column in prepared.columns:
            prepared[column] = pd.array(prepared[column], dtype="Int64")
    return prepared


def _prepare_datetime_columns(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    prepared = frame.copy()
    for column in columns:
        if column in prepared.columns:
            prepared[column] = pd.to_datetime(prepared[column])
    return prepared


def _prepare_float_columns(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    prepared = frame.copy()
    for column in columns:
        if column in prepared.columns:
            prepared[column] = pd.to_numeric(prepared[column], errors="coerce").astype("Float64")
    return prepared


def _prepare_validation_issue_df(frame: pd.DataFrame) -> pd.DataFrame:
    prepared = _prepare_int_columns(frame, ["run_id", "source_file_id", "stg_record_id"])
    return _prepare_datetime_columns(prepared, ["created_at"])


def _upsert_markets(connection: Connection, markets: list[str], reference_data: dict) -> None:
    existing = {
        str(row["market_name"])
        for row in fetch_all(connection, "select market_name from dim_market")
    }
    for market_name in sorted({market for market in markets if market and market not in existing}):
        market_ref = reference_data.get("markets", {}).get(market_name, {})
        execute_sql(
            connection,
            """
            insert into dim_market (market_name, state_code, region_name, active_flag)
            values (:market_name, :state_code, :region_name, :active_flag)
            """,
            {
                "market_name": market_name,
                "state_code": market_ref.get("state_code"),
                "region_name": market_ref.get("region_name"),
                "active_flag": True,
            },
        )


def _upsert_teams(connection: Connection, teams: list[str], reference_data: dict) -> None:
    existing = {
        str(row["team_code"])
        for row in fetch_all(connection, "select team_code from dim_team")
    }
    for team_code in sorted({team for team in teams if team and team not in existing}):
        team_ref = reference_data.get("teams", {}).get(team_code, {})
        execute_sql(
            connection,
            """
            insert into dim_team (team_code, team_name, manager_name, active_flag)
            values (:team_code, :team_name, :manager_name, :active_flag)
            """,
            {
                "team_code": team_code,
                "team_name": team_ref.get("team_name", team_code),
                "manager_name": team_ref.get("manager_name"),
                "active_flag": True,
            },
        )


def _upsert_dates(connection: Connection, dates: list) -> None:
    existing = {
        int(row["date_key"])
        for row in fetch_all(connection, "select date_key from dim_date")
    }
    unique_dates = sorted({pd.to_datetime(value).date() for value in dates if pd.notna(value)})
    for current_date in unique_dates:
        date_key = int(current_date.strftime("%Y%m%d"))
        if date_key in existing:
            continue
        execute_sql(
            connection,
            """
            insert into dim_date (
              date_key,
              calendar_date,
              year_num,
              quarter_num,
              month_num,
              month_name,
              week_num,
              is_month_end
            ) values (
              :date_key,
              :calendar_date,
              :year_num,
              :quarter_num,
              :month_num,
              :month_name,
              :week_num,
              :is_month_end
            )
            """,
            {
                "date_key": date_key,
                "calendar_date": current_date,
                "year_num": current_date.year,
                "quarter_num": ((current_date.month - 1) // 3) + 1,
                "month_num": current_date.month,
                "month_name": current_date.strftime("%B"),
                "week_num": int(current_date.strftime("%V")),
                "is_month_end": current_date.day == monthrange(current_date.year, current_date.month)[1],
            },
        )


def _upsert_kpis(connection: Connection) -> None:
    existing = {
        str(row["kpi_code"])
        for row in fetch_all(connection, "select kpi_code from dim_kpi")
    }
    for definition in load_kpi_definitions()["kpis"]:
        if definition["code"] in existing:
            continue
        execute_sql(
            connection,
            """
            insert into dim_kpi (
              kpi_code,
              kpi_name,
              kpi_description,
              formula_text,
              target_direction,
              display_format,
              owner_role
            ) values (
              :kpi_code,
              :kpi_name,
              :kpi_description,
              :formula_text,
              :target_direction,
              :display_format,
              :owner_role
            )
            """,
            {
                "kpi_code": definition["code"],
                "kpi_name": definition["name"],
                "kpi_description": definition.get("description"),
                "formula_text": definition["formula"],
                "target_direction": definition["target_direction"],
                "display_format": definition["display_format"],
                "owner_role": definition["owner_role"],
            },
        )


def _attach_dimension_keys(connection: Connection, event_df: pd.DataFrame) -> pd.DataFrame:
    market_lookup = {
        row["market_name"]: int(row["market_id"])
        for row in fetch_all(connection, "select market_id, market_name from dim_market")
    }
    team_lookup = {
        row["team_code"]: int(row["team_id"])
        for row in fetch_all(connection, "select team_id, team_code from dim_team")
    }
    event_df = event_df.copy()
    event_df["market_id"] = event_df["market_name"].map(market_lookup)
    event_df["team_id"] = event_df["team_code"].map(team_lookup)
    event_df["event_date_key"] = pd.to_datetime(event_df["event_date"]).dt.strftime("%Y%m%d").astype(int)
    return event_df


def _attach_snapshot_ids(connection: Connection, snapshots: pd.DataFrame, run_id: int) -> pd.DataFrame:
    kpi_lookup = {
        row["kpi_code"]: int(row["kpi_id"])
        for row in fetch_all(connection, "select kpi_id, kpi_code from dim_kpi")
    }
    market_lookup = {
        row["market_name"]: int(row["market_id"])
        for row in fetch_all(connection, "select market_id, market_name from dim_market")
    }
    team_lookup = {
        row["team_code"]: int(row["team_id"])
        for row in fetch_all(connection, "select team_id, team_code from dim_team")
    }

    snapshots = snapshots.copy()
    snapshots["run_id"] = run_id
    snapshots["kpi_id"] = snapshots["kpi_code"].map(kpi_lookup)
    snapshots["market_id"] = snapshots["market_name"].map(market_lookup)
    snapshots["team_id"] = snapshots["team_code"].map(team_lookup)

    return snapshots[
        [
            "run_id",
            "snapshot_date_key",
            "kpi_id",
            "market_id",
            "team_id",
            "actual_value",
            "target_value",
            "prior_period_value",
            "variance_value",
            "variance_pct",
            "numerator_value",
            "denominator_value",
            "notes",
        ]
    ]


def _update_run(
    connection: Connection,
    run_id: int,
    source_file_count: int,
    staged_row_count: int,
    validation_issue_count: int,
) -> None:
    execute_sql(
        connection,
        """
        update etl_run
        set
          run_finished_at = :run_finished_at,
          source_file_count = :source_file_count,
          staged_row_count = :staged_row_count,
          validation_issue_count = :validation_issue_count,
          run_status = :run_status
        where run_id = :run_id
        """,
        {
            "run_finished_at": utc_now_naive(),
            "source_file_count": source_file_count,
            "staged_row_count": staged_row_count,
            "validation_issue_count": validation_issue_count,
            "run_status": "success",
            "run_id": run_id,
        },
    )


def _mark_run_failed(connection: Connection, run_id: int, note: str) -> None:
    execute_sql(
        connection,
        """
        update etl_run
        set
          run_finished_at = :run_finished_at,
          run_status = :run_status,
          notes = :notes
        where run_id = :run_id
        """,
        {
            "run_finished_at": utc_now_naive(),
            "run_status": "failed",
            "notes": note[:500],
            "run_id": run_id,
        },
    )


def _write_outputs(
    period: str,
    event_df: pd.DataFrame,
    snapshots: pd.DataFrame,
    validation_issues: pd.DataFrame,
    forecasts: pd.DataFrame,
) -> dict[str, str]:
    paths = get_project_paths()
    output_dir = paths.outputs_dir / period
    output_dir.mkdir(parents=True, exist_ok=True)

    event_path = output_dir / "fact_provider_ops_event.csv"
    snapshot_path = output_dir / "fact_kpi_snapshot.csv"
    validation_path = output_dir / "fact_validation_issue.csv"
    forecast_path = output_dir / "fact_forecast.csv"

    event_df.to_csv(event_path, index=False)
    snapshots.to_csv(snapshot_path, index=False)
    validation_issues.to_csv(validation_path, index=False)
    forecasts.to_csv(forecast_path, index=False)

    return {
        "event_fact_csv": str(event_path),
        "kpi_snapshot_csv": str(snapshot_path),
        "validation_issue_csv": str(validation_path),
        "forecast_csv": str(forecast_path),
    }


def _write_llm_artifacts(
    period: str,
    payload_json: dict,
    response_json: dict,
    draft_text: str,
    review_metadata: dict,
) -> dict[str, str]:
    output_dir = get_project_paths().outputs_dir / period
    output_dir.mkdir(parents=True, exist_ok=True)

    payload_path = output_dir / "llm_commentary_payload.json"
    response_path = output_dir / "llm_commentary_draft.json"
    draft_text_path = output_dir / "llm_commentary_draft.txt"
    review_path = output_dir / "llm_commentary_review.json"

    payload_path.write_text(json_dumps(payload_json))
    response_path.write_text(json_dumps(response_json))
    draft_text_path.write_text(draft_text)
    review_path.write_text(json_dumps(review_metadata))

    return {
        "llm_payload_json": str(payload_path),
        "llm_draft_json": str(response_path),
        "llm_draft_txt": str(draft_text_path),
        "llm_review_json": str(review_path),
    }


def _write_llm_review_artifact(period: str, review_metadata: dict) -> dict[str, str]:
    output_dir = get_project_paths().outputs_dir / period
    output_dir.mkdir(parents=True, exist_ok=True)
    review_path = output_dir / "llm_commentary_review.json"
    review_path.write_text(json_dumps(review_metadata))
    return {"llm_review_json": str(review_path)}


def _write_llm_error_artifact(period: str, error_message: str) -> dict[str, str]:
    output_dir = get_project_paths().outputs_dir / period
    output_dir.mkdir(parents=True, exist_ok=True)
    error_path = output_dir / "llm_commentary_error.json"
    error_path.write_text(json_dumps({"error": error_message}))
    return {"llm_error_json": str(error_path)}


def _period_end(period: str):
    year_str, month_str = period.split("-")
    year = int(year_str)
    month = int(month_str)
    return pd.Timestamp(year=year, month=month, day=monthrange(year, month)[1]).date()


def _decorate_snapshots(connection: Connection, snapshots: pd.DataFrame, overall_only: bool) -> pd.DataFrame:
    if snapshots.empty:
        return pd.DataFrame()

    kpi_lookup = read_sql_frame(connection, "select kpi_id, kpi_name from dim_kpi")
    market_lookup = read_sql_frame(connection, "select market_id, market_name from dim_market")
    team_lookup = read_sql_frame(connection, "select team_id, team_code from dim_team")

    decorated = snapshots.merge(kpi_lookup, on="kpi_id", how="left")
    decorated = decorated.merge(market_lookup, on="market_id", how="left")
    decorated = decorated.merge(team_lookup, on="team_id", how="left")

    if overall_only:
        return decorated[decorated["market_name"].isna() & decorated["team_code"].isna()].copy()
    return decorated


def _write_commentary(period: str, commentary_text: str) -> str:
    output_dir = get_project_paths().outputs_dir / period
    output_dir.mkdir(parents=True, exist_ok=True)
    commentary_path = output_dir / "commentary_preview.txt"
    commentary_path.write_text(commentary_text)
    return str(commentary_path)


def _decorate_forecasts(connection: Connection, forecasts: pd.DataFrame) -> pd.DataFrame:
    if forecasts.empty:
        return pd.DataFrame()

    kpi_lookup = read_sql_frame(connection, "select kpi_id, kpi_name from dim_kpi")
    market_lookup = read_sql_frame(connection, "select market_id, market_name from dim_market")
    team_lookup = read_sql_frame(connection, "select team_id, team_code from dim_team")

    decorated = forecasts.merge(kpi_lookup, on="kpi_id", how="left")
    decorated = decorated.merge(market_lookup, on="market_id", how="left")
    decorated = decorated.merge(team_lookup, on="team_id", how="left")
    return decorated


def _apply_prior_period_comparison(
    connection: Connection,
    snapshots: pd.DataFrame,
    reporting_period: str,
) -> pd.DataFrame:
    if snapshots.empty:
        return snapshots

    previous = read_sql_frame(
        connection,
        """
        with latest_successful_run_per_period as (
          select
            reporting_period,
            max(run_id) as run_id
          from etl_run
          where run_status = 'success'
            and reporting_period < :reporting_period
          group by reporting_period
        )
        select
          s.kpi_id,
          s.market_id,
          s.team_id,
          s.actual_value as prior_period_value,
          r.reporting_period
        from fact_kpi_snapshot s
        join latest_successful_run_per_period l on l.run_id = s.run_id
        join etl_run r on r.run_id = s.run_id
        """,
        {"reporting_period": reporting_period},
    )

    if previous.empty:
        return snapshots

    previous = previous.sort_values("reporting_period").drop_duplicates(
        subset=["kpi_id", "market_id", "team_id"],
        keep="last",
    )
    previous = previous.rename(columns={"prior_period_value": "matched_prior_period_value"})

    current = snapshots.copy()
    current["market_key"] = current["market_id"].fillna(-1).astype(int)
    current["team_key"] = current["team_id"].fillna(-1).astype(int)
    previous["market_key"] = previous["market_id"].fillna(-1).astype(int)
    previous["team_key"] = previous["team_id"].fillna(-1).astype(int)

    merged = current.merge(
        previous[["kpi_id", "market_key", "team_key", "matched_prior_period_value"]],
        on=["kpi_id", "market_key", "team_key"],
        how="left",
    )
    merged["prior_period_value"] = merged["matched_prior_period_value"]
    merged["variance_value"] = merged["actual_value"] - merged["prior_period_value"]
    merged["variance_pct"] = merged["variance_value"] / merged["prior_period_value"]
    zero_prior_mask = merged["prior_period_value"].fillna(0) == 0
    merged.loc[zero_prior_mask, "variance_pct"] = pd.NA

    return merged[snapshots.columns]


def _load_forecast_history(
    connection: Connection,
    current_snapshots: pd.DataFrame,
    reporting_period: str,
) -> pd.DataFrame:
    previous = read_sql_frame(
        connection,
        """
        with latest_successful_run_per_period as (
          select
            reporting_period,
            max(run_id) as run_id
          from etl_run
          where run_status = 'success'
            and reporting_period < :reporting_period
          group by reporting_period
        )
        select
          r.reporting_period,
          s.kpi_id,
          s.market_id,
          s.team_id,
          s.actual_value,
          k.kpi_name
        from fact_kpi_snapshot s
        join latest_successful_run_per_period l on l.run_id = s.run_id
        join etl_run r on r.run_id = s.run_id
        join dim_kpi k on k.kpi_id = s.kpi_id
        """,
        {"reporting_period": reporting_period},
    )

    current = current_snapshots.copy()
    current["reporting_period"] = reporting_period
    current = current.merge(
        read_sql_frame(connection, "select kpi_id, kpi_name from dim_kpi"),
        on="kpi_id",
        how="left",
    )
    columns = ["reporting_period", "kpi_id", "market_id", "team_id", "actual_value", "kpi_name"]
    frames = []
    if not previous.empty:
        frames.append(previous[columns])
    if not current.empty:
        frames.append(current[columns])
    if not frames:
        return pd.DataFrame(columns=columns)
    return pd.concat(frames, ignore_index=True)


def _insert_llm_draft_record(connection: Connection, record: dict) -> int:
    if get_app_settings().database.backend == "postgres":
        result = execute_sql(
            connection,
            """
            insert into fact_llm_commentary_draft (
              run_id,
              reporting_period,
              draft_type,
              model_provider,
              model_name,
              prompt_payload_json,
              response_json,
              draft_text,
              review_status,
              reviewer_name,
              review_notes,
              created_at,
              reviewed_at
            ) values (
              :run_id,
              :reporting_period,
              :draft_type,
              :model_provider,
              :model_name,
              :prompt_payload_json,
              :response_json,
              :draft_text,
              :review_status,
              :reviewer_name,
              :review_notes,
              :created_at,
              :reviewed_at
            )
            returning draft_id
            """,
            record,
        )
        return int(result.scalar_one())

    result = execute_sql(
        connection,
        """
        insert into fact_llm_commentary_draft (
          run_id,
          reporting_period,
          draft_type,
          model_provider,
          model_name,
          prompt_payload_json,
          response_json,
          draft_text,
          review_status,
          reviewer_name,
          review_notes,
          created_at,
          reviewed_at
        ) values (
          :run_id,
          :reporting_period,
          :draft_type,
          :model_provider,
          :model_name,
          :prompt_payload_json,
          :response_json,
          :draft_text,
          :review_status,
          :reviewer_name,
          :review_notes,
          :created_at,
          :reviewed_at
        )
        """,
        record,
    )
    return int(result.lastrowid)
