from __future__ import annotations

import json
import re
from dataclasses import dataclass
from html import escape
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
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

RISK_COLOR = "#b84b3b"
CAUTION_COLOR = "#a86e1a"
FAVORABLE_COLOR = "#16735c"
NEUTRAL_COLOR = "#5d6d71"
INK_COLOR = "#16303a"
TEAL_COLOR = "#006d77"
KPI_CALCULATION_SUMMARIES = {
    "Total Records Received": "Count of received records",
    "Completed Records": "Count of records completed during the period",
    "Completion Rate": "Completed records as a share of received records",
    "Average Turnaround Days": "Average elapsed days for completed records",
    "Open Backlog Count": "Count of records remaining open at period end",
    "Backlog Over SLA Count": "Count of open records beyond the service-level target",
    "QA Issue Rate": "Records with a logged QA issue as a share of received records",
    "Required Field Completeness Rate": "Records with all required fields as a share of received records",
    "Unique NPI Rate": "Records with a unique provider NPI as a share of received records",
}


@dataclass(frozen=True)
class TrustSummary:
    """A presentation-only assessment of whether a persisted run is usable."""

    label: str
    tone: str
    detail: str
    next_action: str


def dashboard_notes() -> list[str]:
    return [
        "Use one selected successful run as the context for every cockpit view.",
        "Read KPI values from persisted snapshots and formulas from repository configuration.",
        "Keep source-level filtering limited to source-linked records and validation exceptions.",
    ]


def format_reporting_period(reporting_period: str) -> str:
    """Format persisted period keys for an operational audience."""
    try:
        return pd.Period(str(reporting_period), freq="M").strftime("%b %Y")
    except ValueError:
        return str(reporting_period)


def format_timestamp(value: object) -> str:
    if value is None or pd.isna(value):
        return "Not recorded"
    timestamp = pd.to_datetime(value)
    return timestamp.strftime("%b %d, %Y · %H:%M")


def forecast_display_period_date(value: object) -> pd.Timestamp:
    """Position month-end forecast records alongside month-grained actual history."""
    return pd.to_datetime(value).to_period("M").to_timestamp()


def calculation_summary(kpi_name: str) -> str:
    """Return a plain-language display definition without changing configured logic."""
    return KPI_CALCULATION_SUMMARIES.get(kpi_name, "Definition available in the KPI catalog")


def variance_state(variance_value: object, target_direction: str) -> str:
    """Classify a persisted variance without changing its value or formula."""
    if variance_value is None or pd.isna(variance_value):
        return "no_prior"
    value = float(variance_value)
    if abs(value) < 1e-9:
        return "neutral"
    if target_direction == "lower_is_better":
        return "favorable" if value < 0 else "unfavorable"
    return "favorable" if value > 0 else "unfavorable"


def format_variance(value: object, display_format: str) -> str:
    if value is None or pd.isna(value):
        return "No prior period"
    numeric_value = float(value)
    if display_format == "percent":
        return f"{numeric_value * 100:+.0f} pp"
    if display_format == "days":
        return f"{numeric_value:+.1f} days"
    return f"{numeric_value:+,.0f}"


def variance_label(state: str, variance_value: object, display_format: str) -> str:
    labels = {
        "favorable": "Favorable",
        "unfavorable": "Needs attention",
        "neutral": "No material change",
        "no_prior": "No prior period",
    }
    if state == "no_prior":
        return labels[state]
    return f"{labels[state]} · {format_variance(variance_value, display_format)}"


def classify_run_trust(
    run_row: pd.Series,
    snapshots: pd.DataFrame,
    source_files: pd.DataFrame,
    workbook_available: bool,
) -> TrustSummary:
    """Classify readiness from persisted run evidence, not refresh success alone."""
    blockers: list[str] = []
    if str(run_row.get("run_status", "")) != "success":
        blockers.append("the refresh did not complete successfully")
    if source_files.empty:
        blockers.append("source receipt evidence is missing")
    if snapshots.empty:
        blockers.append("persisted KPI snapshots are missing")
    if not workbook_available:
        blockers.append("the expected workbook is unavailable")
    if blockers:
        return TrustSummary(
            label="Not ready",
            tone="not-ready",
            detail="; ".join(blockers).capitalize() + ".",
            next_action="Restore the missing run evidence before using this reporting period.",
        )

    issue_count = int(run_row.get("validation_issue_count", 0) or 0)
    if issue_count:
        return TrustSummary(
            label="Ready with reviewable exceptions",
            tone="reviewable",
            detail=f"Refresh completed with {issue_count:,} logged validation exception(s).",
            next_action="Review the logged exceptions before the operating review.",
        )
    return TrustSummary(
        label="Ready",
        tone="ready",
        detail="Required sources, persisted KPI snapshots, and the workbook are available.",
        next_action="Use this reporting period for the monthly operating review.",
    )


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


def workbook_values_match_snapshot(workbook_path: Path, snapshots: pd.DataFrame) -> bool:
    """Compare the exported workbook summary to persisted overall rows without recalculating KPIs."""
    if not workbook_path.exists() or not workbook_summary_parity(snapshots):
        return False
    try:
        workbook = pd.read_excel(workbook_path, sheet_name="summary", skiprows=2, usecols="A:B")
    except (OSError, ValueError):
        return False
    expected = snapshots[snapshots["market_name"].isna() & snapshots["team_code"].isna()][
        ["kpi_name", "actual_value"]
    ].copy()
    actual = workbook[workbook["kpi_name"].isin(expected["kpi_name"])][["kpi_name", "actual_value"]].copy()
    actual = actual.sort_values("kpi_name").reset_index(drop=True)
    expected = expected.sort_values("kpi_name").reset_index(drop=True)
    return actual.equals(expected)


def build_tie_out_frame(
    run_row: pd.Series,
    source_files: pd.DataFrame,
    events: pd.DataFrame,
    snapshots: pd.DataFrame,
    issues: pd.DataFrame,
    workbook_available: bool,
    workbook_parity: bool | None = None,
) -> pd.DataFrame:
    source_rows = int(source_files["row_count"].fillna(0).sum()) if not source_files.empty else 0
    overall_rows = snapshots[snapshots["market_name"].isna() & snapshots["team_code"].isna()]
    expected_source_files = int(run_row.get("source_file_count", len(source_files)))
    source_status = "Passed" if len(source_files) == expected_source_files else "Filtered"
    snapshot_status = "Passed" if not snapshots.empty else "Incomplete"
    issue_status = "Passed with exceptions" if not issues.empty else "Passed"
    workbook_status = "Passed" if workbook_parity else ("Available" if workbook_available else "Incomplete")
    return pd.DataFrame(
        [
            {"stage": "Source receipt", "value": f"{len(source_files):,} file(s)", "status": source_status, "detail": f"{source_rows:,} source row(s) received"},
            {"stage": "Staging", "value": f"{int(run_row['staged_row_count']):,} rows", "status": "Passed", "detail": "Persisted refresh staging count"},
            {"stage": "Canonical events", "value": f"{len(events):,} events", "status": "Passed" if not events.empty else "Incomplete", "detail": "Selected market and team context"},
            {"stage": "KPI snapshot", "value": f"{len(snapshots):,} rows", "status": snapshot_status, "detail": f"{len(overall_rows):,} overall KPI row(s) available"},
            {"stage": "Validation", "value": f"{len(issues):,} logged", "status": issue_status, "detail": "Reviewable exceptions remain visible" if not issues.empty else "No logged exceptions"},
            {"stage": "Workbook", "value": "Exported" if workbook_available else "Unavailable", "status": workbook_status, "detail": "Summary values match persisted overall KPIs" if workbook_parity else "Export availability check"},
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
            select r.reporting_period, s.run_id, k.kpi_name, k.display_format, k.target_direction,
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

    selected_workbook = workbook_export_path(str(run_row["reporting_period"]))
    trust = classify_run_trust(
        run_row,
        bundle["snapshots"],
        bundle["source_files"],
        selected_workbook.exists(),
    )

    filtered = {
        "events": filter_events(bundle["events"], market_name, team_code),
        "snapshots": select_cut_rows(bundle["snapshots"], market_name, team_code),
        "forecasts": select_cut_rows(bundle["forecasts"], market_name, team_code),
        "issues": filter_source_linked_rows(bundle["issues"], source_file_type),
        "source_files": filter_source_linked_rows(bundle["source_files"], source_file_type),
    }
    trend_data = select_cut_rows(load_trend_data(), market_name, team_code)

    _render_header(run_row, market_name, team_code, source_file_type, trust)
    _render_active_filters(market_name, team_code, source_file_type)
    page = DASHBOARD_PAGES[selected_page]
    if page == "executive_summary":
        render_executive_summary(run_row, filtered, bundle["issues"], source_file_type, trust)
    elif page == "kpi_definitions":
        render_kpi_definitions(filtered["snapshots"])
    elif page == "trends":
        render_trends(trend_data, source_file_type)
    elif page == "market_team":
        render_market_team(bundle["snapshots"], market_name, team_code)
    elif page == "qa_tie_outs":
        render_qa_and_tie_outs(run_row, filtered, bundle["snapshots"], source_file_type)
    elif page == "forecast_assumptions":
        render_forecast_assumptions(filtered["forecasts"], trend_data, source_file_type)
    else:
        render_review_packet(run_row, bundle)


def _render_header(
    run_row: pd.Series,
    market_name: str,
    team_code: str,
    source_file_type: str,
    trust: TrustSummary,
) -> None:
    st.markdown("<p class='eyebrow'>SYNTHETIC HEALTHCARE OPERATIONS DATA</p>", unsafe_allow_html=True)
    st.title("Monthly Operations Cockpit")
    st.caption("Synthetic demonstration data only — no real patient, member, or provider records are included.")
    st.markdown(
        """
        <section class="briefing-strip" aria-label="Selected reporting context">
          <div class="briefing-item">
            <span class="briefing-label">Reporting period</span>
            <strong>{period}</strong>
            <span>Run {run_id} · refreshed {refreshed}</span>
          </div>
          <div class="briefing-item trust-{tone}">
            <span class="briefing-label">Reporting trust</span>
            <strong>{trust_label}</strong>
            <span>{trust_detail}</span>
          </div>
          <div class="briefing-item">
            <span class="briefing-label">Next operational action</span>
            <strong>{next_action}</strong>
            <span>Filters: {market} · {team} · {source}</span>
          </div>
        </section>
        """.format(
            period=escape(format_reporting_period(str(run_row["reporting_period"]))),
            run_id=int(run_row["run_id"]),
            refreshed=escape(format_timestamp(run_row["run_finished_at"])),
            tone=trust.tone,
            trust_label=escape(trust.label),
            trust_detail=escape(trust.detail),
            next_action=escape(trust.next_action),
            market=escape(market_name),
            team=escape(team_code),
            source=escape(source_file_type),
        ),
        unsafe_allow_html=True,
    )


def _render_active_filters(market_name: str, team_code: str, source_file_type: str) -> None:
    active_filters = [
        ("Market", "cockpit_market", market_name),
        ("Team", "cockpit_team", team_code),
        ("Source", "cockpit_source", source_file_type),
    ]
    active_filters = [item for item in active_filters if item[2] != ALL_FILTER]
    if not active_filters:
        return
    st.caption("Active filters")
    columns = st.columns(len(active_filters))
    for column, (label, key, value) in zip(columns, active_filters, strict=True):
        with column:
            st.button(
                f"{label}: {value} ×",
                key=f"clear_{key}",
                help=f"Clear {label.lower()} filter",
                on_click=_clear_filter,
                args=(key,),
            )


def _clear_filter(key: str) -> None:
    st.session_state[key] = ALL_FILTER


def _set_workspace(workspace: str) -> None:
    st.session_state["cockpit_page"] = workspace


def render_executive_summary(
    run_row: pd.Series,
    filtered: dict[str, pd.DataFrame],
    run_issues: pd.DataFrame,
    source_file_type: str,
    trust: TrustSummary,
) -> None:
    snapshots = filtered["snapshots"]
    st.subheader("Executive summary")
    if source_file_type != ALL_FILTER:
        st.info("Headline KPI snapshots are not source-grained in V1, so the source filter does not change this summary.")

    if snapshots.empty:
        st.info("No persisted KPI cut is available for this market/team combination. V1 stores overall, market, and team cuts separately; it does not calculate a combined market-and-team cut.")
        return

    metrics = {row["kpi_name"]: row for _, row in snapshots.iterrows()}
    columns = st.columns(4)
    for column, metric_name in zip(columns, HEADLINE_KPIS, strict=True):
        _metric_card(column, metrics.get(metric_name), metric_name)

    changes, actions = build_operating_briefing(snapshots, len(run_issues), trust)
    left, right = st.columns([1.25, 1])
    with left:
        st.markdown("#### What changed")
        for change in changes:
            st.markdown(f"- {change}")
    with right:
        st.markdown("#### What to do next")
        for action in actions:
            st.markdown(f"- {action}")
        destination = "QA & tie-outs" if trust.tone != "ready" else "Trends"
        st.button(
            f"Open {destination}",
            key="executive_next_action",
            on_click=_set_workspace,
            args=(destination,),
        )

    with st.expander("See full KPI table and download", expanded=False):
        st.caption("Human-readable persisted snapshot values for the selected cut.")
        st.dataframe(snapshot_display_frame(snapshots), width="stretch", hide_index=True)
        _download_csv("Download selected KPI snapshot", snapshots, f"kpi_snapshot_{run_row['reporting_period']}.csv")


def build_operating_briefing(
    snapshots: pd.DataFrame,
    issue_count: int,
    trust: TrustSummary,
) -> tuple[list[str], list[str]]:
    """Turn persisted deltas into brief, readable operating-review prompts."""
    changes: list[str] = []
    attention_rows: list[pd.Series] = []
    for _, row in snapshots.iterrows():
        state = variance_state(row.get("variance_value"), str(row.get("target_direction", "higher_is_better")))
        if state == "unfavorable":
            attention_rows.append(row)
    for row in attention_rows[:2]:
        changes.append(
            f"**{row['kpi_name']}** moved {format_variance(row['variance_value'], row['display_format'])} versus the prior period."
        )
    if not changes:
        changes.append("Headline persisted KPIs showed no unfavorable period-over-period movement for this cut.")

    actions = [trust.next_action]
    if issue_count:
        actions.append(f"Use QA & tie-outs to review {issue_count:,} logged validation exception(s) and their source context.")
    else:
        actions.append("Use the trend and segment views to confirm where the period changed.")
    return changes, actions


def snapshot_display_frame(snapshots: pd.DataFrame) -> pd.DataFrame:
    """Format persisted snapshot rows for people while retaining their exact values in downloads."""
    if snapshots.empty:
        return pd.DataFrame(columns=["KPI", "Current", "Prior period", "Change", "Interpretation"])
    rows: list[dict[str, str]] = []
    for _, row in snapshots.iterrows():
        display_format = str(row["display_format"])
        state = variance_state(row.get("variance_value"), str(row.get("target_direction", "higher_is_better")))
        rows.append(
            {
                "KPI": str(row["kpi_name"]),
                "Current": _format_value(float(row["actual_value"]), display_format),
                "Prior period": _format_value(float(row["prior_period_value"]), display_format)
                if not pd.isna(row["prior_period_value"])
                else "No prior period",
                "Change": format_variance(row.get("variance_value"), display_format),
                "Interpretation": variance_label(state, row.get("variance_value"), display_format),
            }
        )
    return pd.DataFrame(rows)


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
    definition = kpi_definition_frame().set_index("kpi_name").loc[selected_metric]
    display_format = str(definition["display_format"])
    st.caption(
        f"**Calculated as:** {calculation_summary(selected_metric)} · "
        f"**Desired direction:** {'Higher is better' if definition['target_direction'] == 'higher_is_better' else 'Lower is better'}"
    )
    st.markdown(f"#### Is {selected_metric} moving in the intended direction?")
    st.plotly_chart(_build_trend_figure(plot_df, selected_metric, display_format), width="stretch")
    st.markdown("#### Period comparison")
    st.dataframe(snapshot_display_frame(plot_df), width="stretch", hide_index=True)
    st.button(
        "Compare market and team drivers",
        key="trend_to_breakdown",
        on_click=_set_workspace,
        args=("Market & team",),
    )


def _build_trend_figure(plot_df: pd.DataFrame, metric_name: str, display_format: str) -> go.Figure:
    history = plot_df.copy()
    history["period_date"] = pd.to_datetime(history["reporting_period"].astype(str) + "-01")
    figure = go.Figure()
    figure.add_trace(
        go.Scatter(
            x=history["period_date"],
            y=history["actual_value"],
            mode="lines+markers",
            name="Actual",
            line={"color": INK_COLOR, "width": 3},
            marker={"color": INK_COLOR, "size": 8},
            hovertext=history["actual_value"].map(lambda value: _format_value(float(value), display_format)),
            hovertemplate="%{x|%b %Y}<br>Actual: %{hovertext}<extra></extra>",
        )
    )
    prior = history.dropna(subset=["prior_period_value"])
    if not prior.empty:
        figure.add_trace(
            go.Scatter(
                x=prior["period_date"],
                y=prior["prior_period_value"],
                mode="lines+markers",
                name="Prior-period comparison",
                line={"color": "#9aa6a6", "width": 2, "dash": "dot"},
                marker={"color": "#9aa6a6", "size": 6},
                hovertext=prior["prior_period_value"].map(lambda value: _format_value(float(value), display_format)),
                hovertemplate="%{x|%b %Y}<br>Prior period: %{hovertext}<extra></extra>",
            )
        )
    latest = history.iloc[-1]
    figure.add_annotation(
        x=latest["period_date"],
        y=latest["actual_value"],
        text=_format_value(float(latest["actual_value"]), display_format),
        showarrow=False,
        yshift=20,
        font={"color": INK_COLOR, "size": 12},
    )
    tick_format = ".0%" if display_format == "percent" else None
    figure.update_layout(
        margin={"l": 18, "r": 18, "t": 54, "b": 18},
        paper_bgcolor="#fffdf8",
        plot_bgcolor="#fffdf8",
        legend={"orientation": "h", "y": 1.1, "x": 0, "yanchor": "bottom"},
        hovermode="x unified",
    )
    figure.update_xaxes(tickformat="%b\n%Y", dtick="M1", title_text=None, showgrid=False)
    figure.update_yaxes(tickformat=tick_format, title_text=None, gridcolor="#d7ddd7", zeroline=False)
    return figure


def render_market_team(snapshots: pd.DataFrame, market_name: str, team_code: str) -> None:
    st.subheader("Market and team comparison")
    if market_name != ALL_FILTER or team_code != ALL_FILTER:
        st.info("This comparison view uses all persisted segment cuts so selected filters can be compared with their peer cuts.")
    selected_metric = st.selectbox("Comparison metric", sorted(snapshots["kpi_name"].unique()), key="breakdown_metric")
    metric_rows = snapshots[snapshots["kpi_name"] == selected_metric]
    market_rows = metric_rows[metric_rows["market_name"].notna() & metric_rows["team_code"].isna()]
    team_rows = metric_rows[metric_rows["team_code"].notna() & metric_rows["market_name"].isna()]
    definition = kpi_definition_frame().set_index("kpi_name").loc[selected_metric]
    left, right = st.columns(2)
    with left:
        st.markdown("#### Market")
        _render_segment_chart(
            market_rows,
            "market_name",
            selected_metric,
            str(definition["display_format"]),
            str(definition["target_direction"]),
            "No market rows are available for this metric.",
        )
    with right:
        st.markdown("#### Team")
        _render_segment_chart(
            team_rows,
            "team_code",
            selected_metric,
            str(definition["display_format"]),
            str(definition["target_direction"]),
            "No team rows are available for this metric.",
        )


def render_qa_and_tie_outs(
    run_row: pd.Series,
    filtered: dict[str, pd.DataFrame],
    full_run_snapshots: pd.DataFrame,
    source_file_type: str,
) -> None:
    st.subheader("QA controls and tie-outs")
    events = filtered["events"]
    snapshots = filtered["snapshots"]
    issues = filtered["issues"]
    source_files = filtered["source_files"]
    workbook_path = workbook_export_path(str(run_row["reporting_period"]))
    workbook_available = workbook_path.exists()
    workbook_parity = workbook_values_match_snapshot(workbook_path, full_run_snapshots)
    tie_out = build_tie_out_frame(
        run_row,
        source_files,
        events,
        snapshots,
        issues,
        workbook_available,
        workbook_parity,
    )

    st.markdown("#### Reporting trust chain")
    st.caption("Source receipt → staging → canonical events → KPI snapshot → validation → workbook")
    _render_trust_chain(tie_out)

    detail = st.session_state.get("qa_drilldown", "Validation")
    st.markdown(f"#### {detail} detail")
    if detail == "Source receipt":
        source_display = source_files.rename(
            columns={
                "source_file_type": "Source type",
                "source_file_name": "Source file",
                "row_count": "Rows received",
                "loaded_at": "Loaded",
            }
        )[["Source type", "Source file", "Rows received", "Loaded"]]
        st.dataframe(source_display, width="stretch", hide_index=True)
    elif detail == "Staging":
        st.info(f"{int(run_row['staged_row_count']):,} source rows were staged during the selected refresh.")
        st.caption("Source-row detail remains in the controlled pipeline outputs; this review surface shows the run-level tie-out.")
    elif detail == "Canonical events":
        if events.empty:
            st.info("No canonical events match the selected market/team context.")
        else:
            event_display = pd.DataFrame(
                {
                    "Provider work item": events["provider_name"],
                    "Market": events["market_name"],
                    "Team": events["team_code"],
                    "Workflow status": events["event_status"].map(_humanize_label),
                    "Completed": events["completion_flag"].map(_yes_no),
                    "Open backlog": events["backlog_flag"].map(_yes_no),
                    "QA flag": events["qa_issue_flag"].map(_yes_no),
                }
            )
            st.dataframe(event_display, width="stretch", hide_index=True)
            _download_csv("Download selected canonical events", events, f"canonical_events_{run_row['reporting_period']}.csv")
    elif detail == "KPI snapshot":
        if snapshots.empty:
            st.info("No persisted KPI rows are available for this selected market/team combination.")
        else:
            st.dataframe(snapshot_display_frame(snapshots), width="stretch", hide_index=True)
            _download_csv("Download selected KPI snapshot", snapshots, f"kpi_snapshot_{run_row['reporting_period']}.csv")
    elif detail == "Workbook":
        if workbook_parity:
            st.success("Workbook summary values match the persisted overall KPI snapshot for this selected run.")
        elif workbook_available:
            st.warning("Workbook is present, but its summary did not match the persisted overall KPI snapshot.")
        else:
            st.warning("The expected workbook is not available for this selected run.")
        if workbook_available:
            st.download_button(
                "Download workbook for selected run",
                data=workbook_path.read_bytes(),
                file_name=workbook_path.name,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
    else:
        if issues.empty:
            st.success("No validation issues match the selected source filter.")
        else:
            issue_counts = issues.groupby(["severity", "issue_type"], dropna=False).size().reset_index(name="Logged exceptions")
            issue_display = pd.DataFrame(
                {
                    "Severity": issue_counts["severity"].map(_humanize_label),
                    "Control area": issue_counts["issue_type"].map(_humanize_label),
                    "Logged exceptions": issue_counts["Logged exceptions"],
                }
            )
            st.dataframe(issue_display, width="stretch", hide_index=True)
            with st.expander("See technical exception detail", expanded=False):
                st.dataframe(
                    issues[["severity", "issue_type", "source_file_name", "row_identifier", "issue_message", "status"]],
                    width="stretch",
                    hide_index=True,
                )
            _download_csv("Download selected validation exceptions", issues, f"validation_exceptions_{run_row['reporting_period']}.csv")
    if source_file_type != ALL_FILTER:
        st.caption("The source filter changes source receipt and exception detail; run-level staging and workbook checks remain full-run controls.")


def _render_trust_chain(tie_out: pd.DataFrame) -> None:
    columns = st.columns(len(tie_out))
    for column, (_, row) in zip(columns, tie_out.iterrows(), strict=True):
        status_class = str(row["status"]).lower().replace(" ", "-")
        with column:
            st.markdown(
                """
                <article class="trust-stage trust-{status_class}">
                  <span class="trust-stage-label">{stage}</span>
                  <strong>{value}</strong>
                  <span class="trust-stage-status">{status}</span>
                  <span class="trust-stage-detail">{detail}</span>
                </article>
                """.format(
                    status_class=escape(status_class),
                    stage=escape(str(row["stage"])),
                    value=escape(str(row["value"])),
                    status=escape(str(row["status"])),
                    detail=escape(str(row["detail"])),
                ),
                unsafe_allow_html=True,
            )
            if st.button(f"Inspect {row['stage']}", key=f"inspect_{str(row['stage']).lower().replace(' ', '_')}"):
                st.session_state["qa_drilldown"] = str(row["stage"])
                st.rerun()


def _humanize_label(value: object) -> str:
    label = str(value).replace("_", " ").replace("-", " ").title()
    return label.replace("Npi", "NPI").replace("Qa", "QA").replace("Sla", "SLA")


def commentary_display_text(text: str) -> str:
    """Keep the downloaded deterministic artifact canonical while making visible rule names readable."""
    return re.sub(r"`([a-z0-9_]+)`", lambda match: _humanize_label(match.group(1)), text)


def _yes_no(value: object) -> str:
    return "Yes" if bool(value) else "No"


def review_packet_metadata_frame(run_row: pd.Series) -> pd.DataFrame:
    """Present selected-run evidence with operational labels, not persistence fields."""
    refresh_status = str(run_row["run_status"])
    status_label = "Successful" if refresh_status == "success" else _humanize_label(refresh_status)
    return pd.DataFrame(
        [
            {"Item": "Run", "Details": f"Run {int(run_row['run_id']):,}"},
            {"Item": "Reporting period", "Details": format_reporting_period(str(run_row['reporting_period']))},
            {"Item": "Refresh status", "Details": status_label},
            {"Item": "Refresh completed", "Details": format_timestamp(run_row["run_finished_at"])},
            {"Item": "Source files", "Details": f"{int(run_row['source_file_count']):,} file(s)"},
            {
                "Item": "Logged validation exceptions",
                "Details": f"{int(run_row['validation_issue_count']):,} exception(s)",
            },
        ]
    ).astype({"Details": "string"})


def render_forecast_assumptions(
    forecasts: pd.DataFrame,
    trend_data: pd.DataFrame,
    source_file_type: str,
) -> None:
    st.subheader("Forecast assumptions and limitations")
    if source_file_type != ALL_FILTER:
        st.info("Forecast rows are not source-grained in V1, so the source filter does not change this view.")
    st.markdown(
        """
        - **Method:** rolling three-period average.
        - **Coverage:** stable volume and backlog metrics only.
        - **Bounds:** the minimum and maximum observed values in the same three-period history.
        - **Limitations:** this is a transparent baseline, not a causal or clinical forecast; QA issue rate is intentionally not forecast in V1.
        """
    )
    if forecasts.empty:
        st.info("No forecast rows are available for this selected cut. Forecasts require three sequential successful reporting periods.")
        return
    metric_options = sorted(forecasts["kpi_name"].unique())
    default_index = metric_options.index("Open Backlog Count") if "Open Backlog Count" in metric_options else 0
    selected_metric = st.selectbox("Forecast metric", metric_options, index=default_index, key="forecast_metric")
    forecast_row = forecasts[forecasts["kpi_name"] == selected_metric].iloc[0]
    definition = kpi_definition_frame().set_index("kpi_name").loc[selected_metric]
    display_format = str(definition["display_format"])
    history = trend_data[trend_data["kpi_name"] == selected_metric].copy()
    if history.empty:
        st.info("No persisted actual history is available for this forecast metric and selected cut.")
        return

    latest_actual = history.sort_values("reporting_period").iloc[-1]
    left, middle, right = st.columns(3)
    left.markdown(
        f"<div class='forecast-stat'><span>Last actual</span><strong>{_format_value(float(latest_actual['actual_value']), display_format)}</strong><small>{format_reporting_period(str(latest_actual['reporting_period']))}</small></div>",
        unsafe_allow_html=True,
    )
    middle.markdown(
        f"<div class='forecast-stat'><span>Next-period forecast</span><strong>{_format_value(float(forecast_row['forecast_value']), display_format)}</strong><small>{format_reporting_period(str(forecast_row['forecast_period_end'])[:7])}</small></div>",
        unsafe_allow_html=True,
    )
    right.markdown(
        f"<div class='forecast-stat'><span>Observed range</span><strong>{_format_value(float(forecast_row['lower_bound']), display_format)}–{_format_value(float(forecast_row['upper_bound']), display_format)}</strong><small>Three-period history</small></div>",
        unsafe_allow_html=True,
    )
    st.markdown(f"#### What should the team plan for next month? · {selected_metric}")
    st.plotly_chart(_build_forecast_figure(history, forecast_row, selected_metric, display_format), width="stretch")
    forecast_display = pd.DataFrame(
        [
            {
                "Next period": format_reporting_period(str(forecast_row["forecast_period_end"])[:7]),
                "Metric": selected_metric,
                "Forecast": _format_value(float(forecast_row["forecast_value"]), display_format),
                "Observed range": f"{_format_value(float(forecast_row['lower_bound']), display_format)}–{_format_value(float(forecast_row['upper_bound']), display_format)}",
                "Method": "Rolling three-period average",
            }
        ]
    )
    st.dataframe(forecast_display, width="stretch", hide_index=True)


def _build_forecast_figure(
    history: pd.DataFrame,
    forecast_row: pd.Series,
    metric_name: str,
    display_format: str,
) -> go.Figure:
    actuals = history.sort_values("reporting_period").copy()
    actuals["period_date"] = pd.to_datetime(actuals["reporting_period"].astype(str) + "-01")
    forecast_date = forecast_display_period_date(forecast_row["forecast_period_end"])
    latest_actual = actuals.iloc[-1]
    forecast_value = float(forecast_row["forecast_value"])
    lower_bound = float(forecast_row["lower_bound"])
    upper_bound = float(forecast_row["upper_bound"])
    figure = go.Figure()
    figure.add_trace(
        go.Scatter(
            x=actuals["period_date"],
            y=actuals["actual_value"],
            mode="lines+markers",
            name="Actual history",
            line={"color": INK_COLOR, "width": 3},
            marker={"color": INK_COLOR, "size": 8},
            hovertext=actuals["actual_value"].map(lambda value: _format_value(float(value), display_format)),
            hovertemplate="%{x|%b %Y}<br>Actual: %{hovertext}<extra></extra>",
        )
    )
    range_width = pd.Timedelta(days=9)
    figure.add_shape(
        type="rect",
        x0=forecast_date - range_width,
        x1=forecast_date + range_width,
        y0=lower_bound,
        y1=upper_bound,
        fillcolor=TEAL_COLOR,
        opacity=0.16,
        line={"width": 0},
        layer="below",
    )
    figure.add_trace(
        go.Scatter(
            x=[latest_actual["period_date"], forecast_date],
            y=[latest_actual["actual_value"], forecast_value],
            mode="lines+markers+text",
            name="Forecast point",
            line={"color": TEAL_COLOR, "width": 3, "dash": "dash"},
            marker={"color": TEAL_COLOR, "size": [7, 10]},
            text=[None, f"Forecast {_format_value(forecast_value, display_format)}"],
            textposition="top center",
            hovertemplate="%{x|%b %Y}<br>Forecast: %{y}<extra></extra>",
        )
    )
    figure.add_annotation(
        x=forecast_date,
        y=upper_bound,
        text=f"Observed range {_format_value(lower_bound, display_format)}–{_format_value(upper_bound, display_format)}",
        showarrow=False,
        yshift=18,
        font={"color": TEAL_COLOR, "size": 11},
    )
    tick_format = ".0%" if display_format == "percent" else None
    figure.update_layout(
        margin={"l": 18, "r": 18, "t": 54, "b": 18},
        paper_bgcolor="#fffdf8",
        plot_bgcolor="#fffdf8",
        legend={"orientation": "h", "y": 1.1, "x": 0, "yanchor": "bottom"},
        hovermode="x unified",
    )
    figure.update_xaxes(tickformat="%b\n%Y", dtick="M1", title_text=None, showgrid=False)
    figure.update_yaxes(tickformat=tick_format, title_text=None, gridcolor="#d7ddd7", zeroline=False)
    return figure


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
    displayed_commentary = commentary_display_text(deterministic)

    left, right = st.columns(2)
    with left:
        st.markdown("#### Deterministic commentary")
        st.caption("Canonical review text generated from persisted KPI and validation extracts.")
        st.markdown(
            f"<div class='commentary-preview'>{escape(displayed_commentary).replace(chr(10), '<br>')}</div>",
            unsafe_allow_html=True,
        )
        st.download_button("Download deterministic commentary", deterministic, f"commentary_{run_row['reporting_period']}.txt", mime="text/plain")
    with right:
        st.markdown("#### Optional LLM draft")
        st.caption("Draft only — human review is required. It never replaces deterministic commentary.")
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
    packet_metadata = review_packet_metadata_frame(run_row)
    st.dataframe(
        packet_metadata,
        width="stretch",
        hide_index=True,
    )
    first, second, third, fourth = st.columns(4)
    with first:
        _download_csv("KPI snapshots", snapshots, f"kpi_snapshot_{run_row['reporting_period']}.csv")
    with second:
        _download_csv("Validation exceptions", issues, f"validation_exceptions_{run_row['reporting_period']}.csv")
    with third:
        _download_csv("Forecast rows", forecasts, f"forecasts_{run_row['reporting_period']}.csv")
    with fourth:
        workbook_path = workbook_export_path(str(run_row["reporting_period"]))
        if workbook_path.exists():
            st.download_button(
                "Audit workbook",
                data=workbook_path.read_bytes(),
                file_name=workbook_path.name,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )


def _render_segment_chart(
    rows: pd.DataFrame,
    category: str,
    metric_name: str,
    display_format: str,
    target_direction: str,
    empty_message: str,
) -> None:
    if rows.empty:
        st.info(empty_message)
        return
    display_rows = rows.copy()
    display_rows["variance_state"] = display_rows["variance_value"].map(
        lambda value: variance_state(value, target_direction)
    )
    display_rows = display_rows.sort_values("actual_value", ascending=True)
    colors = {
        "favorable": FAVORABLE_COLOR,
        "unfavorable": RISK_COLOR,
        "neutral": NEUTRAL_COLOR,
        "no_prior": NEUTRAL_COLOR,
    }
    display_rows["color"] = display_rows["variance_state"].map(colors)
    display_rows["label"] = display_rows["actual_value"].map(lambda value: _format_value(float(value), display_format))
    display_rows["hover"] = display_rows.apply(
        lambda row: "<br>".join(
            [
                f"Current: {_format_value(float(row['actual_value']), display_format)}",
                f"Prior: {_format_value(float(row['prior_period_value']), display_format)}"
                if not pd.isna(row["prior_period_value"])
                else "Prior: No prior period",
                variance_label(row["variance_state"], row["variance_value"], display_format),
            ]
        ),
        axis=1,
    )
    figure = go.Figure(
        go.Bar(
            y=display_rows[category],
            x=display_rows["actual_value"],
            orientation="h",
            marker_color=display_rows["color"],
            text=display_rows["label"],
            textposition="outside",
            hovertext=display_rows["hover"],
            hovertemplate="%{y}<br>%{hovertext}<extra></extra>",
        )
    )
    tick_format = ".0%" if display_format == "percent" else None
    figure.update_layout(
        title=f"Where is {metric_name} concentrated?",
        paper_bgcolor="#fffdf8",
        plot_bgcolor="#fffdf8",
        margin={"l": 12, "r": 48, "t": 48, "b": 12},
        showlegend=False,
    )
    figure.update_xaxes(tickformat=tick_format, title_text=None, gridcolor="#d7ddd7", zeroline=False)
    figure.update_yaxes(title_text=None, showgrid=False)
    st.plotly_chart(figure, width="stretch")
    driver = display_rows[display_rows["variance_state"] == "unfavorable"]
    driver = driver.iloc[-1] if not driver.empty else display_rows.iloc[-1]
    driver_change = format_variance(driver["variance_value"], display_format)
    st.caption(f"Largest current driver: {driver[category]} · {driver_change} versus the prior period.")
    segment_table = pd.DataFrame(
        {
            "Segment": display_rows[category],
            "Current": display_rows["actual_value"].map(lambda value: _format_value(float(value), display_format)),
            "Prior period": display_rows["prior_period_value"].map(
                lambda value: _format_value(float(value), display_format) if not pd.isna(value) else "No prior period"
            ),
            "Change": display_rows["variance_value"].map(lambda value: format_variance(value, display_format)),
            "Interpretation": display_rows.apply(
                lambda row: variance_label(row["variance_state"], row["variance_value"], display_format), axis=1
            ),
        }
    )
    if display_format == "integer" and display_rows["actual_value"].sum() > 0:
        segment_table["Share of displayed total"] = display_rows["actual_value"].map(
            lambda value: f"{value / display_rows['actual_value'].sum():.0%}"
        )
    st.dataframe(segment_table, width="stretch", hide_index=True)


def _metric_card(column, metric_row: pd.Series | None, label: str) -> None:
    if metric_row is None:
        column.markdown(
            f"<article class='metric-card metric-unavailable'><span>{escape(label)}</span><strong>Unavailable</strong><small>No persisted cut available</small></article>",
            unsafe_allow_html=True,
        )
        return
    value = _format_value(float(metric_row["actual_value"]), str(metric_row["display_format"]))
    prior = metric_row.get("prior_period_value")
    variance = metric_row.get("variance_value")
    display_format = str(metric_row["display_format"])
    state = variance_state(variance, str(metric_row.get("target_direction", "higher_is_better")))
    prior_text = _format_value(float(prior), display_format) if not pd.isna(prior) else "No prior period"
    tone_icon = {
        "favorable": "✓",
        "unfavorable": "!",
        "neutral": "—",
        "no_prior": "·",
    }[state]
    column.markdown(
        """
        <article class="metric-card metric-{state}">
          <span>{label}</span>
          <strong>{value}</strong>
          <small>{delta}</small>
          <em>Prior: {prior}</em>
          <b>{icon} {interpretation}</b>
        </article>
        """.format(
            state=state,
            label=escape(label),
            value=escape(value),
            delta=escape(format_variance(variance, display_format)),
            prior=escape(prior_text),
            icon=tone_icon,
            interpretation=escape(variance_label(state, variance, display_format).split(" · ")[0]),
        ),
        unsafe_allow_html=True,
    )


def _format_value(value: float, display_format: str) -> str:
    if display_format == "percent":
        return f"{value:.0%}"
    if display_format == "days":
        return f"{value:.1f} days"
    return f"{value:,.0f}"


def _download_csv(label: str, frame: pd.DataFrame, file_name: str) -> None:
    st.download_button(label, frame.to_csv(index=False).encode("utf-8"), file_name, mime="text/csv")


def _inject_styles() -> None:
    st.markdown(
        """
        <style>
          :root {
            --ink: #16303a;
            --teal: #006d77;
            --coral: #b84b3b;
            --amber: #a86e1a;
            --green: #16735c;
            --paper: #f7f4ed;
            --panel: #fffdf8;
            --line: #d7ddd7;
            --muted: #61757a;
          }
          .stApp { background: var(--paper); color: var(--ink); font-family: "Avenir Next", "Helvetica Neue", sans-serif; }
          h1, h2, h3 { font-family: "Iowan Old Style", "Palatino Linotype", Georgia, serif; color: var(--ink); letter-spacing: -.025em; }
          h1 { font-size: clamp(2.2rem, 4vw, 3.3rem) !important; margin-bottom: .35rem !important; }
          [data-testid="stSidebar"] { background: var(--ink); border-right: 1px solid #244550; }
          [data-testid="stSidebar"] * { color: #f7f4ed !important; }
          [data-testid="stSidebar"] [data-baseweb="select"] *, [data-testid="stSidebar"] [role="combobox"], [data-testid="stSidebar"] input { color: var(--ink) !important; }
          .rail-eyebrow, .eyebrow { letter-spacing: .16em; font-weight: 750; font-size: .71rem; margin-bottom: .35rem; }
          .rail-eyebrow { color: #9ed8d7 !important; }
          .eyebrow { color: var(--teal); }
          .briefing-strip { display: grid; grid-template-columns: 1fr 1.25fr 1.25fr; background: var(--panel); border: 1px solid var(--line); border-left: 4px solid var(--teal); margin: 1rem 0 1.35rem; }
          .briefing-item { min-height: 108px; padding: .9rem 1rem; display: flex; flex-direction: column; gap: .28rem; border-right: 1px solid var(--line); }
          .briefing-item:last-child { border-right: 0; }
          .briefing-item strong { color: var(--ink); font-size: 1.04rem; line-height: 1.25; }
          .briefing-item span:last-child { color: var(--muted); font-size: .81rem; line-height: 1.45; }
          .briefing-label, .trust-stage-label { color: var(--muted) !important; font-size: .68rem !important; font-weight: 750; letter-spacing: .1em; text-transform: uppercase; }
          .briefing-item.trust-ready { box-shadow: inset 0 3px 0 var(--green); }
          .briefing-item.trust-reviewable { box-shadow: inset 0 3px 0 var(--amber); }
          .briefing-item.trust-not-ready { box-shadow: inset 0 3px 0 var(--coral); }
          .metric-card { background: var(--panel); border: 1px solid var(--line); border-top: 3px solid var(--teal); min-height: 168px; padding: .88rem .9rem .82rem; display: flex; flex-direction: column; gap: .3rem; }
          .metric-card > span { color: var(--muted); font-size: .68rem; font-weight: 750; letter-spacing: .09em; text-transform: uppercase; }
          .metric-card > strong { color: var(--ink); font-family: "Iowan Old Style", "Palatino Linotype", Georgia, serif; font-size: 2rem; font-weight: 600; line-height: 1; }
          .metric-card small, .metric-card em { color: var(--muted); font-size: .8rem; font-style: normal; }
          .metric-card b { align-self: flex-start; font-size: .73rem; font-weight: 750; letter-spacing: .02em; }
          .metric-favorable { border-top-color: var(--green); }
          .metric-favorable b { color: var(--green); }
          .metric-unfavorable { border-top-color: var(--coral); }
          .metric-unfavorable b { color: var(--coral); }
          .metric-neutral { border-top-color: var(--muted); }
          .metric-neutral b, .metric-no_prior b { color: var(--muted); }
          .metric-no_prior, .metric-unavailable { border-top-color: var(--amber); }
          .trust-stage { height: 150px; border: 1px solid var(--line); border-top: 3px solid var(--teal); background: var(--panel); padding: .7rem; display: flex; flex-direction: column; gap: .28rem; }
          .trust-stage strong { color: var(--ink); font-family: "Iowan Old Style", "Palatino Linotype", Georgia, serif; font-size: 1.4rem; line-height: 1.1; }
          .trust-stage-status { font-size: .72rem; font-weight: 750; color: var(--green); }
          .trust-stage-detail { color: var(--muted); font-size: .71rem; line-height: 1.35; }
          .trust-passed-with-exceptions { border-top-color: var(--amber); }
          .trust-passed-with-exceptions .trust-stage-status, .trust-filtered .trust-stage-status { color: var(--amber); }
          .trust-incomplete { border-top-color: var(--coral); }
          .trust-incomplete .trust-stage-status { color: var(--coral); }
          .forecast-stat { background: var(--panel); border: 1px solid var(--line); border-top: 3px solid var(--teal); min-height: 108px; padding: .72rem .85rem; display: flex; flex-direction: column; gap: .24rem; }
          .forecast-stat span, .forecast-stat small { color: var(--muted); font-size: .76rem; }
          .forecast-stat strong { color: var(--ink); font-family: "Iowan Old Style", "Palatino Linotype", Georgia, serif; font-size: 1.55rem; }
          .commentary-preview { background: var(--panel); border-left: 3px solid var(--teal); color: var(--ink); line-height: 1.65; padding: 1rem 1.1rem; }
          .stButton > button, .stDownloadButton > button { border-radius: 0; border: 1px solid var(--teal); color: var(--teal); background: transparent; font-weight: 700; min-height: 2.3rem; }
          .stButton > button:hover, .stDownloadButton > button:hover { color: #fff; background: var(--teal); border-color: var(--teal); }
          [data-testid="stSelectbox"] [data-baseweb="select"] > div:focus-within { border-color: var(--teal) !important; box-shadow: 0 0 0 2px rgba(0, 109, 119, .24) !important; }
          button:focus-visible, .stButton > button:focus-visible, .stDownloadButton > button:focus-visible, [role="combobox"]:focus-visible, input:focus-visible { outline: 3px solid #e8b15e !important; outline-offset: 2px; }
          [data-testid="stDataFrame"] { border: 1px solid var(--line); border-radius: 0; }
          [data-testid="stExpander"] { border-color: var(--line); background: rgba(255, 253, 248, .55); }
          @media (max-width: 1100px) {
            .briefing-strip { grid-template-columns: 1fr; }
            .briefing-item { min-height: auto; border-right: 0; border-bottom: 1px solid var(--line); }
            .briefing-item:last-child { border-bottom: 0; }
            .trust-stage { height: auto; min-height: 124px; }
          }
          @media (max-width: 700px) {
            h1 { font-size: 2.15rem !important; }
            .briefing-item { padding: .82rem .9rem; }
            .metric-card { min-height: 142px; padding: .75rem; }
            .metric-card > strong { font-size: 1.72rem; }
            .trust-stage { min-height: 0; padding: .65rem; }
            .forecast-stat { min-height: 92px; }
          }
          @media (prefers-reduced-motion: reduce) {
            *, *::before, *::after { animation-duration: .01ms !important; animation-iteration-count: 1 !important; transition-duration: .01ms !important; scroll-behavior: auto !important; }
          }
        </style>
        """,
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    run_dashboard()
