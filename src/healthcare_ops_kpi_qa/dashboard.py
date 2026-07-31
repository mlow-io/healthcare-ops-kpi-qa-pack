from __future__ import annotations

import json

import pandas as pd
import plotly.express as px
import streamlit as st

from healthcare_ops_kpi_qa.commentary import build_commentary_preview
from healthcare_ops_kpi_qa.db import get_connection, initialize_database, read_sql_frame
from healthcare_ops_kpi_qa.settings import get_app_settings

DASHBOARD_PAGES = {
    "Overview": "overview",
    "Trends": "trend",
    "Breakdowns": "market_team_breakdown",
    "Forecasts": "forecast_preview",
    "Validation": "validation_exceptions",
    "Executive Review": "executive_review",
}


def dashboard_notes() -> list[str]:
    return [
        "Keep Streamlit as the product surface, but make the walkthrough more executive-friendly.",
        "Highlight run comparisons, variance context, validation drilldowns, and reviewable commentary.",
    ]


@st.cache_data(show_spinner=False)
def load_runs() -> pd.DataFrame:
    with get_connection() as connection:
        initialize_database(connection)
        return read_sql_frame(
            connection,
            """
            with latest_successful_run_per_period as (
              select
                reporting_period,
                max(run_id) as run_id
              from etl_run
              where run_status = 'success'
              group by reporting_period
            )
            select
              e.run_id,
              e.reporting_period,
              e.run_started_at,
              e.run_finished_at,
              e.source_file_count,
              e.staged_row_count,
              e.validation_issue_count
            from etl_run e
            join latest_successful_run_per_period l on l.run_id = e.run_id
            order by e.reporting_period desc
            """,
        )


@st.cache_data(show_spinner=False)
def load_run_bundle(run_id: int) -> dict[str, pd.DataFrame]:
    with get_connection() as connection:
        initialize_database(connection)
        events = read_sql_frame(
            connection,
            "select * from fact_provider_ops_event where run_id = :run_id",
            {"run_id": run_id},
        )
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
        issues = read_sql_frame(
            connection,
            """
            select
              v.*,
              sf.source_file_name,
              sf.source_file_type
            from fact_validation_issue v
            left join dim_source_file sf on sf.source_file_id = v.source_file_id
            where v.run_id = :run_id
            """,
            {"run_id": run_id},
        )
        forecasts = read_sql_frame(
            connection,
            """
            select
              f.*,
              k.kpi_name,
              m.market_name,
              t.team_code,
              d.calendar_date as forecast_period_end
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
        drafts = read_sql_frame(
            connection,
            """
            select
              draft_id,
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
        "drafts": drafts,
    }


@st.cache_data(show_spinner=False)
def load_trend_data() -> pd.DataFrame:
    with get_connection() as connection:
        initialize_database(connection)
        return read_sql_frame(
            connection,
            """
            with latest_successful_run_per_period as (
              select
                reporting_period,
                max(run_id) as run_id
              from etl_run
              where run_status = 'success'
              group by reporting_period
            )
            select
              r.reporting_period,
              k.kpi_name,
              s.actual_value,
              s.prior_period_value,
              s.variance_value,
              s.variance_pct
            from fact_kpi_snapshot s
            join etl_run r on r.run_id = s.run_id
            join latest_successful_run_per_period l on l.run_id = s.run_id
            join dim_kpi k on k.kpi_id = s.kpi_id
            where s.market_id is null
              and s.team_id is null
            order by r.reporting_period, k.kpi_name
            """,
        )


def run_dashboard() -> None:
    settings = get_app_settings()
    st.set_page_config(page_title="Healthcare Ops KPI & QA Pack", layout="wide")
    st.title("Healthcare Operations KPI & QA Pack")
    st.caption(f"{settings.database.backend.upper()} target: {settings.database.target_label}")

    runs = load_runs()
    if runs.empty:
        st.warning("No successful refresh runs found. Run the CLI refresh first.")
        return

    run_lookup = {int(row["run_id"]): str(row["reporting_period"]) for _, row in runs.iterrows()}
    selected_run = st.sidebar.selectbox(
        "Reporting run",
        runs["run_id"].tolist(),
        format_func=lambda value: f"{run_lookup[int(value)]} (run {value})",
    )
    selected_page = st.sidebar.radio("View", list(DASHBOARD_PAGES.keys()))

    bundle = load_run_bundle(int(selected_run))
    trend_data = load_trend_data()
    run_row = runs.loc[runs["run_id"] == int(selected_run)].iloc[0]

    page = DASHBOARD_PAGES[selected_page]
    if page == "overview":
        render_overview(run_row, bundle["events"], bundle["snapshots"], bundle["issues"])
    elif page == "trend":
        render_trend(trend_data)
    elif page == "market_team_breakdown":
        render_breakdown(bundle["snapshots"])
    elif page == "forecast_preview":
        render_forecasts(bundle["forecasts"])
    elif page == "validation_exceptions":
        render_validation(bundle["issues"])
    else:
        render_executive_review(run_row, bundle["snapshots"], bundle["issues"], bundle["forecasts"], bundle["drafts"])


def render_overview(run_row: pd.Series, events: pd.DataFrame, snapshots: pd.DataFrame, issues: pd.DataFrame) -> None:
    overall = snapshots[snapshots["market_name"].isna() & snapshots["team_code"].isna()].copy()
    metrics = {row["kpi_name"]: row for _, row in overall.iterrows()}

    st.subheader("Run summary")
    top_left, top_mid, top_right = st.columns(3)
    top_left.caption(f"Reporting period: {run_row['reporting_period']}")
    top_mid.caption(f"Source files: {int(run_row['source_file_count'])}")
    top_right.caption(f"Validation issues: {int(run_row['validation_issue_count'])}")

    col1, col2, col3, col4 = st.columns(4)
    _metric_card(col1, metrics, "Total Records Received", "Total Records")
    _metric_card(col2, metrics, "Completion Rate", "Completion Rate", percent=True)
    _metric_card(col3, metrics, "Open Backlog Count", "Open Backlog")
    _metric_card(col4, metrics, "QA Issue Rate", "QA Issue Rate", percent=True)

    st.subheader("KPI comparison")
    comparison_rows = overall[
        ["kpi_name", "actual_value", "prior_period_value", "variance_value", "variance_pct"]
    ].copy()
    st.dataframe(comparison_rows, width="stretch")

    left, right = st.columns([1.3, 1.7])
    with left:
        st.subheader("Validation issue mix")
        issue_counts = issues["issue_type"].value_counts().rename_axis("issue_type").reset_index(name="count")
        if issue_counts.empty:
            st.success("No validation issues for this run.")
        else:
            fig = px.bar(issue_counts, x="issue_type", y="count", title="Issues by type")
            st.plotly_chart(fig, width="stretch")
    with right:
        st.subheader("Canonical event preview")
        st.dataframe(
            events[
                [
                    "provider_name",
                    "provider_npi",
                    "event_status",
                    "completion_flag",
                    "backlog_flag",
                    "qa_issue_flag",
                ]
            ],
            width="stretch",
        )


def render_trend(trend_data: pd.DataFrame) -> None:
    st.subheader("Overall trend and variance")
    if trend_data.empty:
        st.info("No trend data available yet.")
        return

    selected_metric = st.selectbox("Metric", sorted(trend_data["kpi_name"].unique()))
    plot_df = trend_data[trend_data["kpi_name"] == selected_metric].copy()

    left, right = st.columns(2)
    with left:
        fig = px.line(plot_df, x="reporting_period", y="actual_value", markers=True, title=selected_metric)
        st.plotly_chart(fig, width="stretch")
    with right:
        variance_fig = px.bar(
            plot_df,
            x="reporting_period",
            y="variance_value",
            title=f"{selected_metric} variance vs prior period",
        )
        st.plotly_chart(variance_fig, width="stretch")

    st.dataframe(plot_df, width="stretch")


def render_breakdown(snapshots: pd.DataFrame) -> None:
    st.subheader("Market and team breakdowns")
    selected_metric = st.selectbox("Breakdown metric", sorted(snapshots["kpi_name"].unique()))
    market_rows = snapshots[(snapshots["kpi_name"] == selected_metric) & snapshots["market_name"].notna()]
    team_rows = snapshots[(snapshots["kpi_name"] == selected_metric) & snapshots["team_code"].notna()]

    left, right = st.columns(2)
    with left:
        st.markdown("**By Market**")
        if market_rows.empty:
            st.info("No market rows available.")
        else:
            fig = px.bar(market_rows, x="market_name", y="actual_value", color="market_name", title=selected_metric)
            st.plotly_chart(fig, width="stretch")
            st.dataframe(
                market_rows[["market_name", "actual_value", "prior_period_value", "variance_value", "variance_pct"]],
                width="stretch",
            )
    with right:
        st.markdown("**By Team**")
        if team_rows.empty:
            st.info("No team rows available.")
        else:
            fig = px.bar(team_rows, x="team_code", y="actual_value", color="team_code", title=selected_metric)
            st.plotly_chart(fig, width="stretch")
            st.dataframe(
                team_rows[["team_code", "actual_value", "prior_period_value", "variance_value", "variance_pct"]],
                width="stretch",
            )


def render_validation(issues: pd.DataFrame) -> None:
    st.subheader("Validation drilldown")
    if issues.empty:
        st.success("No validation issues for this run.")
        return

    severity_options = ["all"] + sorted(issues["severity"].dropna().unique())
    selected_severity = st.selectbox("Severity", severity_options)
    issue_options = ["all"] + sorted(issues["issue_type"].dropna().unique())
    selected_issue_type = st.selectbox("Issue type", issue_options)

    filtered = issues.copy()
    if selected_severity != "all":
        filtered = filtered[filtered["severity"] == selected_severity]
    if selected_issue_type != "all":
        filtered = filtered[filtered["issue_type"] == selected_issue_type]

    left, right = st.columns(2)
    with left:
        issue_counts = filtered["issue_type"].value_counts().rename_axis("issue_type").reset_index(name="count")
        fig = px.bar(issue_counts, x="issue_type", y="count", color="issue_type", title="Filtered issue counts")
        st.plotly_chart(fig, width="stretch")
    with right:
        by_source = (
            filtered.groupby(["source_file_type", "issue_type"], dropna=False)
            .size()
            .reset_index(name="count")
            .sort_values(["count", "source_file_type"], ascending=[False, True])
        )
        st.dataframe(by_source, width="stretch")

    st.dataframe(
        filtered[
            [
                "severity",
                "issue_type",
                "source_file_name",
                "row_identifier",
                "issue_message",
                "created_at",
            ]
        ],
        width="stretch",
    )


def render_forecasts(forecasts: pd.DataFrame) -> None:
    st.subheader("Forecast preview")
    if forecasts.empty:
        st.info("No forecasts available yet. Run at least three sequential periods first.")
        return

    overall = forecasts[forecasts["market_name"].isna() & forecasts["team_code"].isna()].copy()
    if not overall.empty:
        fig = px.bar(
            overall,
            x="kpi_name",
            y="forecast_value",
            error_y=overall["upper_bound"] - overall["forecast_value"],
            error_y_minus=overall["forecast_value"] - overall["lower_bound"],
            title="Next-period overall forecasts",
        )
        st.plotly_chart(fig, width="stretch")

    st.dataframe(
        forecasts[
            [
                "forecast_period_end",
                "kpi_name",
                "market_name",
                "team_code",
                "forecast_value",
                "lower_bound",
                "upper_bound",
                "model_name",
            ]
        ],
        width="stretch",
    )


def render_executive_review(
    run_row: pd.Series,
    snapshots: pd.DataFrame,
    issues: pd.DataFrame,
    forecasts: pd.DataFrame,
    drafts: pd.DataFrame,
) -> None:
    st.subheader("Executive review")
    reporting_period = str(run_row["reporting_period"])
    overall = snapshots[snapshots["market_name"].isna() & snapshots["team_code"].isna()]
    market = snapshots[snapshots["market_name"].notna() & snapshots["team_code"].isna()]
    deterministic = build_commentary_preview(reporting_period, overall, market, issues)

    left, right = st.columns(2)
    with left:
        st.markdown("**Deterministic commentary**")
        st.code(deterministic)
    with right:
        st.markdown("**LLM draft status**")
        if drafts.empty:
            st.info("No LLM draft has been generated for this run.")
        else:
            latest = drafts.iloc[0]
            st.write(f"Status: `{latest['review_status']}`")
            st.write(f"Model: `{latest['model_provider']} / {latest['model_name']}`")
            st.write(f"Reviewer: `{latest['reviewer_name'] or 'pending'}`")
            if latest["review_notes"]:
                st.write(f"Notes: {latest['review_notes']}")
            st.code(str(latest["draft_text"] or ""))
            with st.expander("Structured prompt payload"):
                st.json(json.loads(str(latest["prompt_payload_json"])))

    st.markdown("**Forecast and risk context**")
    if forecasts.empty:
        st.caption("No forecast rows are available for this run.")
    else:
        st.dataframe(
            forecasts[["kpi_name", "forecast_value", "lower_bound", "upper_bound"]].head(10),
            width="stretch",
        )


def _metric_card(column, metrics: dict[str, pd.Series], key: str, label: str, percent: bool = False) -> None:
    metric_row = metrics.get(key)
    if metric_row is None:
        column.metric(label, "0")
        return

    actual_value = float(metric_row["actual_value"])
    variance_value = metric_row.get("variance_value")
    delta = None if pd.isna(variance_value) else float(variance_value)

    if percent:
        value = f"{actual_value:.0%}"
        delta_text = None if delta is None else f"{delta:+.0%}"
    else:
        value = f"{actual_value:.0f}"
        delta_text = None if delta is None else f"{delta:+.1f}"
    column.metric(label, value, delta_text)


if __name__ == "__main__":
    run_dashboard()
