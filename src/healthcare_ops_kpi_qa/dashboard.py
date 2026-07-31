from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from healthcare_ops_kpi_qa.commentary import build_commentary_preview
from healthcare_ops_kpi_qa.db import get_connection, initialize_database, read_sql_frame
from healthcare_ops_kpi_qa.kpis import load_kpi_definitions
from healthcare_ops_kpi_qa.settings import get_app_settings, get_project_paths

ALL_FILTER = "All"
HEADLINE_KPIS = [
    "Total Records Received",
    "Completion Rate",
    "Open Backlog Count",
    "QA Issue Rate",
]
DASHBOARD_PAGES = {
    "Executive summary": "executive_summary",
    "KPI definitions": "kpi_definitions",
    "Trends": "trends",
    "Market & team": "market_team",
    "QA & tie-outs": "qa_tie_outs",
    "Forecast assumptions": "forecast_assumptions",
    "Review packet": "review_packet",
}


def dashboard_notes() -> list[str]:
    return [
        "Use one selected successful run as the context for every cockpit view.",
        "Read KPI values from persisted snapshots and formulas from repository configuration.",
        "Keep source-level filtering limited to source-linked records and validation exceptions.",
    ]


def kpi_definition_frame() -> pd.DataFrame:
    """Return the configured KPI catalog without recreating any calculations."""
    definitions = load_kpi_definitions()["kpis"]
    return pd.DataFrame(definitions).rename(
        columns={
            "code": "kpi_code",
            "name": "kpi_name",
            "formula": "how_calculated",
        }
    )[
        ["kpi_code", "kpi_name", "how_calculated", "target_direction", "display_format", "owner_role"]
    ]


def select_cut_rows(
    frame: pd.DataFrame,
    market_name: str = ALL_FILTER,
    team_code: str = ALL_FILTER,
) -> pd.DataFrame:
    """Apply V1 market/team cuts without manufacturing unsupported combined cuts."""
    if frame.empty:
        return frame.copy()
    if market_name != ALL_FILTER and team_code != ALL_FILTER:
        return frame.iloc[0:0].copy()
    if market_name != ALL_FILTER:
        return frame[(frame["market_name"] == market_name) & frame["team_code"].isna()].copy()
    if team_code != ALL_FILTER:
        return frame[(frame["team_code"] == team_code) & frame["market_name"].isna()].copy()
    return frame[frame["market_name"].isna() & frame["team_code"].isna()].copy()


def filter_source_linked_rows(
    frame: pd.DataFrame,
    source_file_type: str = ALL_FILTER,
) -> pd.DataFrame:
    if frame.empty or source_file_type == ALL_FILTER:
        return frame.copy()
    return frame[frame["source_file_type"] == source_file_type].copy()


def filter_events(
    events: pd.DataFrame,
    market_name: str = ALL_FILTER,
    team_code: str = ALL_FILTER,
) -> pd.DataFrame:
    filtered = events.copy()
    if market_name != ALL_FILTER:
        filtered = filtered[filtered["market_name"] == market_name]
    if team_code != ALL_FILTER:
        filtered = filtered[filtered["team_code"] == team_code]
    return filtered


def selected_run_is_consistent(run_id: int, bundle: dict[str, pd.DataFrame]) -> bool:
    """Guard against showing an extract from a different refresh run."""
    for name in ["events", "snapshots", "issues", "forecasts", "drafts", "source_files"]:
        frame = bundle.get(name, pd.DataFrame())
        run_column = "generated_run_id" if name == "forecasts" else "run_id"
        if not frame.empty and run_column in frame.columns and not frame[run_column].eq(run_id).all():
            return False
    return True


def workbook_export_path(reporting_period: str) -> Path:
    return get_project_paths().outputs_dir / reporting_period / f"healthcare_ops_kpi_qa_pack_{reporting_period.replace('-', '_')}.xlsx"


def workbook_summary_parity(snapshots: pd.DataFrame) -> bool:
    """The workbook summary export is sourced from the persisted overall snapshot rows."""
    overall = snapshots[snapshots["market_name"].isna() & snapshots["team_code"].isna()]
    return not overall.empty and set(HEADLINE_KPIS).issubset(set(overall["kpi_name"]))


def build_tie_out_frame(
    run_row: pd.Series,
    source_files: pd.DataFrame,
    events: pd.DataFrame,
    snapshots: pd.DataFrame,
    issues: pd.DataFrame,
    workbook_available: bool,
) -> pd.DataFrame:
    source_rows = int(source_files["row_count"].fillna(0).sum()) if not source_files.empty else 0
    overall_rows = snapshots[snapshots["market_name"].isna() & snapshots["team_code"].isna()]
    return pd.DataFrame(
        [
            {"control": "Selected source files", "value": len(source_files), "evidence": "dim_source_file"},
            {"control": "Selected source rows", "value": source_rows, "evidence": "dim_source_file.row_count"},
            {"control": "Run staged rows", "value": int(run_row["staged_row_count"]), "evidence": "etl_run.staged_row_count"},
            {"control": "Selected market/team canonical events", "value": len(events), "evidence": "fact_provider_ops_event"},
            {"control": "Overall KPI snapshots", "value": len(overall_rows), "evidence": "fact_kpi_snapshot"},
            {"control": "Selected-cut KPI snapshots", "value": len(snapshots), "evidence": "fact_kpi_snapshot"},
            {"control": "Validation issues", "value": len(issues), "evidence": "fact_validation_issue"},
            {"control": "Workbook export", "value": "available" if workbook_available else "not found", "evidence": "outputs workbook"},
        ]
    )


def load_runs() -> pd.DataFrame:
    with get_connection() as connection:
        initialize_database(connection)
        return read_sql_frame(
            connection,
            """
            with latest_successful_run_per_period as (
              select reporting_period, max(run_id) as run_id
              from etl_run
              where run_status = 'success'
              group by reporting_period
            )
            select e.run_id, e.reporting_period, e.run_started_at, e.run_finished_at,
                   e.source_file_count, e.staged_row_count, e.validation_issue_count, e.run_status
            from etl_run e
            join latest_successful_run_per_period l on l.run_id = e.run_id
            order by e.reporting_period desc
            """,
        )


def load_run_bundle(run_id: int) -> dict[str, pd.DataFrame]:
    with get_connection() as connection:
        initialize_database(connection)
        events = read_sql_frame(
            connection,
            """
            select e.*, m.market_name, t.team_code
            from fact_provider_ops_event e
            left join dim_market m on m.market_id = e.market_id
            left join dim_team t on t.team_id = e.team_id
            where e.run_id = :run_id
            """,
            {"run_id": run_id},
        )
        snapshots = read_sql_frame(
            connection,
            """
            select s.*, k.kpi_name, k.kpi_code, k.display_format, k.formula_text, k.target_direction,
                   m.market_name, t.team_code
            from fact_kpi_snapshot s
            join dim_kpi k on k.kpi_id = s.kpi_id
            left join dim_market m on m.market_id = s.market_id
            left join dim_team t on t.team_id = s.team_id
            where s.run_id = :run_id
            """,
            {"run_id": run_id},
        )
        issues = read_sql_frame(
            connection,
            """
            select v.*, sf.source_file_name, sf.source_file_type
            from fact_validation_issue v
            left join dim_source_file sf on sf.source_file_id = v.source_file_id
            where v.run_id = :run_id
            """,
            {"run_id": run_id},
        )
        forecasts = read_sql_frame(
            connection,
            """
            select f.*, k.kpi_name, m.market_name, t.team_code, d.calendar_date as forecast_period_end
            from fact_forecast f
            join dim_kpi k on k.kpi_id = f.kpi_id
            join dim_date d on d.date_key = f.forecast_period_date_key
            left join dim_market m on m.market_id = f.market_id
            left join dim_team t on t.team_id = f.team_id
            where f.generated_run_id = :run_id
            order by k.kpi_name, m.market_name, t.team_code
            """,
            {"run_id": run_id},
        )
        source_files = read_sql_frame(
            connection,
            """
            select source_file_id, run_id, source_file_name, source_file_type, reporting_period, row_count, loaded_at
            from dim_source_file
            where run_id = :run_id
            order by source_file_type, source_file_name
            """,
            {"run_id": run_id},
        )
        drafts = read_sql_frame(
            connection,
            """
            select draft_id, run_id, reporting_period, draft_type, model_provider, model_name,
                   prompt_payload_json, response_json, draft_text, review_status, reviewer_name,
                   review_notes, created_at, reviewed_at
            from fact_llm_commentary_draft
            where run_id = :run_id
            order by draft_id desc
            """,
            {"run_id": run_id},
        )
    return {
        "events": events,
        "snapshots": snapshots,
        "issues": issues,
        "forecasts": forecasts,
        "source_files": source_files,
        "drafts": drafts,
    }


def load_trend_data() -> pd.DataFrame:
    with get_connection() as connection:
        initialize_database(connection)
        return read_sql_frame(
            connection,
            """
            with latest_successful_run_per_period as (
              select reporting_period, max(run_id) as run_id
              from etl_run
              where run_status = 'success'
              group by reporting_period
            )
            select r.reporting_period, s.run_id, k.kpi_name, k.display_format,
                   s.actual_value, s.prior_period_value, s.variance_value, s.variance_pct,
                   m.market_name, t.team_code
            from fact_kpi_snapshot s
            join etl_run r on r.run_id = s.run_id
            join latest_successful_run_per_period l on l.run_id = s.run_id
            join dim_kpi k on k.kpi_id = s.kpi_id
            left join dim_market m on m.market_id = s.market_id
            left join dim_team t on t.team_id = s.team_id
            order by r.reporting_period, k.kpi_name
            """,
        )


def run_dashboard() -> None:
    st.set_page_config(page_title="Monthly Operations Cockpit", page_icon="▦", layout="wide")
    _inject_styles()
    settings = get_app_settings()
    runs = load_runs()
    if runs.empty:
        st.warning("No successful refresh runs are available. Refresh a reporting period through the CLI before opening the cockpit.")
        return

    run_lookup = {int(row["run_id"]): str(row["reporting_period"]) for _, row in runs.iterrows()}
    with st.sidebar:
        st.markdown("<p class='rail-eyebrow'>MONTHLY OPERATIONS</p>", unsafe_allow_html=True)
        st.header("Context")
        selected_run = st.selectbox(
            "Run and period",
            runs["run_id"].tolist(),
            format_func=lambda value: f"{run_lookup[int(value)]} · run {value}",
            key="cockpit_run_id",
        )
        bundle = load_run_bundle(int(selected_run))
        markets = [ALL_FILTER] + sorted(bundle["events"]["market_name"].dropna().unique().tolist())
        teams = [ALL_FILTER] + sorted(bundle["events"]["team_code"].dropna().unique().tolist())
        sources = [ALL_FILTER] + sorted(bundle["source_files"]["source_file_type"].dropna().unique().tolist())
        market_name = st.selectbox("Market", markets, key="cockpit_market")
        team_code = st.selectbox("Team", teams, key="cockpit_team")
        source_file_type = st.selectbox("Source", sources, key="cockpit_source")
        st.caption("Market and team are applied to canonical events, KPI cuts, forecasts, and trends. Source applies to source-linked controls and exceptions.")
        selected_page = st.radio("Workspace", list(DASHBOARD_PAGES.keys()), key="cockpit_page")
        st.divider()
        st.caption(f"Backend: {settings.database.backend.upper()} · persisted mart data")

    run_row = runs.loc[runs["run_id"] == int(selected_run)].iloc[0]
    if not selected_run_is_consistent(int(selected_run), bundle):
        st.error("Selected-run consistency check failed. Refresh the page before using this cockpit.")
        return

    filtered = {
        "events": filter_events(bundle["events"], market_name, team_code),
        "snapshots": select_cut_rows(bundle["snapshots"], market_name, team_code),
        "forecasts": select_cut_rows(bundle["forecasts"], market_name, team_code),
        "issues": filter_source_linked_rows(bundle["issues"], source_file_type),
        "source_files": filter_source_linked_rows(bundle["source_files"], source_file_type),
    }
    trend_data = select_cut_rows(load_trend_data(), market_name, team_code)

    _render_header(run_row, market_name, team_code, source_file_type)
    page = DASHBOARD_PAGES[selected_page]
    if page == "executive_summary":
        render_executive_summary(run_row, filtered, source_file_type)
    elif page == "kpi_definitions":
        render_kpi_definitions(filtered["snapshots"])
    elif page == "trends":
        render_trends(trend_data, source_file_type)
    elif page == "market_team":
        render_market_team(bundle["snapshots"], market_name, team_code)
    elif page == "qa_tie_outs":
        render_qa_and_tie_outs(run_row, filtered, source_file_type)
    elif page == "forecast_assumptions":
        render_forecast_assumptions(filtered["forecasts"], source_file_type)
    else:
        render_review_packet(run_row, bundle)


def _render_header(run_row: pd.Series, market_name: str, team_code: str, source_file_type: str) -> None:
    st.markdown("<p class='eyebrow'>SYNTHETIC HEALTHCARE OPERATIONS DATA</p>", unsafe_allow_html=True)
    st.title("Monthly Operations Cockpit")
    st.caption("Synthetic demonstration data only — no real patient, member, or provider records are included.")
    context = " · ".join(
        [
            f"Period {run_row['reporting_period']}",
            f"Run {int(run_row['run_id'])}",
            f"Market {market_name}",
            f"Team {team_code}",
            f"Source {source_file_type}",
        ]
    )
    st.markdown(f"<div class='context-strip'>{context}</div>", unsafe_allow_html=True)


def render_executive_summary(
    run_row: pd.Series,
    filtered: dict[str, pd.DataFrame],
    source_file_type: str,
) -> None:
    snapshots = filtered["snapshots"]
    st.subheader("Executive summary")
    if source_file_type != ALL_FILTER:
        st.info("Headline KPI snapshots are not source-grained in V1, so the source filter does not change this summary.")
    left, middle, right = st.columns(3)
    left.metric("Refresh health", "Successful")
    middle.metric("Source files", int(run_row["source_file_count"]))
    right.metric("Validation issues", int(run_row["validation_issue_count"]))
    st.caption(f"Completed: {run_row['run_finished_at'] or 'not recorded'} · Staged rows: {int(run_row['staged_row_count'])}")

    if snapshots.empty:
        st.info("No persisted KPI cut is available for this market/team combination. V1 stores overall, market, and team cuts separately; it does not calculate a combined market-and-team cut.")
        return

    metrics = {row["kpi_name"]: row for _, row in snapshots.iterrows()}
    columns = st.columns(4)
    for column, metric_name in zip(columns, HEADLINE_KPIS, strict=True):
        _metric_card(column, metrics.get(metric_name), metric_name)

    st.markdown("#### Persisted KPI snapshot")
    display = snapshots[["kpi_name", "actual_value", "prior_period_value", "variance_value", "variance_pct", "notes"]].copy()
    st.dataframe(display, width="stretch", hide_index=True)
    _download_csv("Download selected KPI snapshot", snapshots, f"kpi_snapshot_{run_row['reporting_period']}.csv")


def render_kpi_definitions(snapshots: pd.DataFrame) -> None:
    st.subheader("KPI definitions")
    st.caption("Definitions and formulas are read directly from `config/kpi_definitions.yml`; values remain persisted mart snapshots.")
    definitions = kpi_definition_frame()
    st.dataframe(definitions, width="stretch", hide_index=True)
    if not snapshots.empty:
        st.markdown("#### Selected-cut audit detail")
        detail = snapshots[["kpi_name", "numerator_value", "denominator_value", "actual_value", "formula_text", "notes"]]
        st.dataframe(detail, width="stretch", hide_index=True)
    _download_csv("Download KPI definitions", definitions, "kpi_definitions.csv")


def render_trends(trend_data: pd.DataFrame, source_file_type: str) -> None:
    st.subheader("Trend and variance")
    if source_file_type != ALL_FILTER:
        st.info("Trend snapshots are not source-grained in V1, so the source filter does not change this view.")
    if trend_data.empty:
        st.info("No trend data is available for the selected cut. Run sequential refreshes for this cut before interpreting a trend.")
        return
    selected_metric = st.selectbox("Metric", sorted(trend_data["kpi_name"].unique()), key="trend_metric")
    plot_df = trend_data[trend_data["kpi_name"] == selected_metric].copy()
    left, right = st.columns(2)
    with left:
        figure = px.line(plot_df, x="reporting_period", y="actual_value", markers=True, title=selected_metric)
        figure.update_layout(margin={"l": 12, "r": 12, "t": 46, "b": 12})
        st.plotly_chart(figure, width="stretch")
    with right:
        figure = px.bar(plot_df, x="reporting_period", y="variance_value", title=f"{selected_metric} variance vs prior period")
        figure.update_layout(margin={"l": 12, "r": 12, "t": 46, "b": 12})
        st.plotly_chart(figure, width="stretch")
    st.dataframe(plot_df[["reporting_period", "actual_value", "prior_period_value", "variance_value", "variance_pct"]], width="stretch", hide_index=True)


def render_market_team(snapshots: pd.DataFrame, market_name: str, team_code: str) -> None:
    st.subheader("Market and team comparison")
    if market_name != ALL_FILTER or team_code != ALL_FILTER:
        st.info("This comparison view uses all persisted segment cuts so selected filters can be compared with their peer cuts.")
    selected_metric = st.selectbox("Comparison metric", sorted(snapshots["kpi_name"].unique()), key="breakdown_metric")
    metric_rows = snapshots[snapshots["kpi_name"] == selected_metric]
    market_rows = metric_rows[metric_rows["market_name"].notna() & metric_rows["team_code"].isna()]
    team_rows = metric_rows[metric_rows["team_code"].notna() & metric_rows["market_name"].isna()]
    left, right = st.columns(2)
    with left:
        st.markdown("#### Market")
        _render_segment_chart(market_rows, "market_name", selected_metric, "No market rows are available for this metric.")
    with right:
        st.markdown("#### Team")
        _render_segment_chart(team_rows, "team_code", selected_metric, "No team rows are available for this metric.")


def render_qa_and_tie_outs(run_row: pd.Series, filtered: dict[str, pd.DataFrame], source_file_type: str) -> None:
    st.subheader("QA controls and tie-outs")
    events = filtered["events"]
    snapshots = filtered["snapshots"]
    issues = filtered["issues"]
    source_files = filtered["source_files"]
    workbook_path = workbook_export_path(str(run_row["reporting_period"]))
    workbook_available = workbook_path.exists()
    tie_out = build_tie_out_frame(run_row, source_files, events, snapshots, issues, workbook_available)

    st.markdown("#### Refresh lineage")
    st.caption("Source files → staged rows → canonical events → persisted KPI snapshots → workbook export")
    st.dataframe(tie_out, width="stretch", hide_index=True)
    st.markdown("#### Source and validation controls")
    left, right = st.columns([1.1, 1.4])
    with left:
        st.dataframe(source_files[["source_file_type", "source_file_name", "row_count", "loaded_at"]], width="stretch", hide_index=True)
    with right:
        if issues.empty:
            st.success("No validation issues match the selected source filter.")
        else:
            counts = issues.groupby(["severity", "issue_type"], dropna=False).size().reset_index(name="count")
            st.dataframe(counts, width="stretch", hide_index=True)
    st.markdown("#### Exception detail")
    if issues.empty:
        st.caption("No persisted exceptions are available for this selected run/source context.")
    else:
        st.dataframe(issues[["severity", "issue_type", "source_file_name", "row_identifier", "issue_message", "status"]], width="stretch", hide_index=True)

    st.markdown("#### Canonical event and export parity")
    if events.empty:
        st.info("No canonical events match the selected market/team context.")
    else:
        st.dataframe(events[["provider_name", "market_name", "team_code", "event_status", "completion_flag", "backlog_flag", "qa_issue_flag"]], width="stretch", hide_index=True)
    parity = workbook_summary_parity(filtered["snapshots"])
    st.success("Workbook summary uses the selected run's persisted overall snapshot rows.") if parity else st.info("Workbook summary parity is only available for the overall cut; choose All market and All team to inspect it.")
    _download_csv("Download selected validation exceptions", issues, f"validation_exceptions_{run_row['reporting_period']}.csv")
    _download_csv("Download selected canonical events", events, f"canonical_events_{run_row['reporting_period']}.csv")
    if workbook_available:
        st.download_button(
            "Download workbook for selected run",
            data=workbook_path.read_bytes(),
            file_name=workbook_path.name,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    elif source_file_type == ALL_FILTER:
        st.warning("The expected workbook output is not available for this run. Refresh the selected period through the CLI to regenerate it.")


def render_forecast_assumptions(forecasts: pd.DataFrame, source_file_type: str) -> None:
    st.subheader("Forecast assumptions and limitations")
    if source_file_type != ALL_FILTER:
        st.info("Forecast rows are not source-grained in V1, so the source filter does not change this view.")
    st.markdown(
        """
        - **Method:** rolling three-period average (`rolling_avg_3`).
        - **Coverage:** stable volume and backlog metrics only.
        - **Bounds:** the minimum and maximum observed values in the same three-period history.
        - **Limitations:** this is a transparent baseline, not a causal or clinical forecast; QA issue rate is intentionally not forecast in V1.
        """
    )
    if forecasts.empty:
        st.info("No forecast rows are available for this selected cut. Forecasts require three sequential successful reporting periods.")
        return
    overall = forecasts[forecasts["market_name"].isna() & forecasts["team_code"].isna()]
    if not overall.empty:
        figure = px.bar(
            overall,
            x="kpi_name",
            y="forecast_value",
            error_y=overall["upper_bound"] - overall["forecast_value"],
            error_y_minus=overall["forecast_value"] - overall["lower_bound"],
            title="Next-period forecast range",
        )
        figure.update_layout(margin={"l": 12, "r": 12, "t": 46, "b": 12})
        st.plotly_chart(figure, width="stretch")
    st.dataframe(forecasts[["forecast_period_end", "kpi_name", "market_name", "team_code", "forecast_value", "lower_bound", "upper_bound", "model_name"]], width="stretch", hide_index=True)


def render_review_packet(run_row: pd.Series, bundle: dict[str, pd.DataFrame]) -> None:
    st.subheader("Review packet")
    st.caption("This packet is canonical for the selected run and intentionally uses the full persisted run context rather than segment or source filters.")
    snapshots = bundle["snapshots"]
    issues = bundle["issues"]
    forecasts = bundle["forecasts"]
    drafts = bundle["drafts"]
    overall = snapshots[snapshots["market_name"].isna() & snapshots["team_code"].isna()]
    market = snapshots[snapshots["market_name"].notna() & snapshots["team_code"].isna()]
    deterministic = build_commentary_preview(str(run_row["reporting_period"]), overall, market, issues)

    left, right = st.columns(2)
    with left:
        st.markdown("#### Deterministic commentary")
        st.caption("Canonical review text generated from persisted KPI and validation extracts.")
        st.code(deterministic, language="text")
        st.download_button("Download deterministic commentary", deterministic, f"commentary_{run_row['reporting_period']}.txt", mime="text/plain")
    with right:
        st.markdown("#### Optional LLM draft")
        st.caption("A separate optional draft; it never replaces deterministic commentary.")
        if drafts.empty:
            st.info("No optional LLM draft has been generated for this selected run.")
        else:
            latest = drafts.iloc[0]
            st.write(f"Review status: `{latest['review_status']}`")
            st.write(f"Model: `{latest['model_provider']} / {latest['model_name']}`")
            st.write(f"Reviewer: `{latest['reviewer_name'] or 'pending'}`")
            if latest["review_notes"]:
                st.write(f"Notes: {latest['review_notes']}")
            st.code(str(latest["draft_text"] or ""), language="text")
            with st.expander("Structured input payload"):
                st.json(json.loads(str(latest["prompt_payload_json"])))

    st.markdown("#### Selected-run package")
    st.dataframe(
        pd.DataFrame(
            [
                {"field": "run_id", "value": int(run_row["run_id"])},
                {"field": "reporting_period", "value": run_row["reporting_period"]},
                {"field": "run_status", "value": run_row["run_status"]},
                {"field": "completed_at", "value": run_row["run_finished_at"]},
                {"field": "source_files", "value": int(run_row["source_file_count"])},
                {"field": "validation_issues", "value": int(run_row["validation_issue_count"])},
            ]
        ),
        width="stretch",
        hide_index=True,
    )
    first, second, third = st.columns(3)
    with first:
        _download_csv("KPI snapshots", snapshots, f"kpi_snapshot_{run_row['reporting_period']}.csv")
    with second:
        _download_csv("Validation exceptions", issues, f"validation_exceptions_{run_row['reporting_period']}.csv")
    with third:
        _download_csv("Forecast rows", forecasts, f"forecasts_{run_row['reporting_period']}.csv")


def _render_segment_chart(rows: pd.DataFrame, category: str, metric_name: str, empty_message: str) -> None:
    if rows.empty:
        st.info(empty_message)
        return
    figure = px.bar(rows, x=category, y="actual_value", color=category, title=metric_name)
    figure.update_layout(showlegend=False, margin={"l": 12, "r": 12, "t": 46, "b": 12})
    st.plotly_chart(figure, width="stretch")
    st.dataframe(rows[[category, "actual_value", "prior_period_value", "variance_value", "variance_pct"]], width="stretch", hide_index=True)


def _metric_card(column, metric_row: pd.Series | None, label: str) -> None:
    if metric_row is None:
        column.metric(label, "Unavailable")
        return
    value = _format_value(float(metric_row["actual_value"]), str(metric_row["display_format"]))
    prior = metric_row.get("prior_period_value")
    variance = metric_row.get("variance_value")
    delta = None if pd.isna(variance) else _format_delta(float(variance), str(metric_row["display_format"]))
    column.metric(label, value, delta)
    if not pd.isna(prior):
        column.caption(f"Prior: {_format_value(float(prior), str(metric_row['display_format']))}")


def _format_value(value: float, display_format: str) -> str:
    if display_format == "percent":
        return f"{value:.0%}"
    if display_format == "days":
        return f"{value:.1f} days"
    return f"{value:,.0f}"


def _format_delta(value: float, display_format: str) -> str:
    if display_format == "percent":
        return f"{value:+.0%}"
    if display_format == "days":
        return f"{value:+.1f} days"
    return f"{value:+.0f}"


def _download_csv(label: str, frame: pd.DataFrame, file_name: str) -> None:
    st.download_button(label, frame.to_csv(index=False).encode("utf-8"), file_name, mime="text/csv")


def _inject_styles() -> None:
    st.markdown(
        """
        <style>
          :root { --ink: #16303a; --teal: #006d77; --coral: #d35e46; --paper: #f7f4ed; --line: #d7ddd7; }
          .stApp { background: var(--paper); color: var(--ink); }
          [data-testid="stSidebar"] { background: #16303a; }
          [data-testid="stSidebar"] * { color: #f7f4ed !important; }
          .rail-eyebrow, .eyebrow { letter-spacing: .15em; font-weight: 700; font-size: .72rem; margin-bottom: .35rem; }
          .rail-eyebrow { color: #9ed8d7 !important; }
          .eyebrow { color: #006d77; }
          .context-strip { border-left: 4px solid #d35e46; background: #fffdf8; padding: .75rem 1rem; margin: .8rem 0 1.35rem; color: #16303a; font-weight: 600; }
          [data-testid="stMetric"] { background: #fffdf8; border: 1px solid #d7ddd7; border-radius: .35rem; padding: .8rem; min-height: 112px; }
          [data-testid="stMetricLabel"] { letter-spacing: .04em; text-transform: uppercase; font-size: .72rem; }
          .stButton > button, .stDownloadButton > button { border-radius: .2rem; border: 1px solid #006d77; color: #006d77; background: transparent; font-weight: 650; }
          .stButton > button:hover, .stDownloadButton > button:hover { color: white; background: #006d77; border-color: #006d77; }
          [data-testid="stDataFrame"] { border: 1px solid #d7ddd7; border-radius: .3rem; }
          @media (max-width: 700px) {
            .context-strip { font-size: .82rem; line-height: 1.5; }
            [data-testid="stMetric"] { min-height: 92px; padding: .65rem; }
            h1 { font-size: 2rem !important; }
          }
        </style>
        """,
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    run_dashboard()
