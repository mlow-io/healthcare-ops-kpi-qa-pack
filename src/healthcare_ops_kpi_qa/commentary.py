from __future__ import annotations

import pandas as pd


def commentary_sections() -> list[str]:
    return [
        "headline_performance_change",
        "largest_negative_variance",
        "largest_positive_variance",
        "qa_risk_summary",
        "backlog_summary",
    ]


def build_commentary_preview(
    reporting_period: str,
    overall_kpis: pd.DataFrame,
    market_kpis: pd.DataFrame,
    validation_issues: pd.DataFrame,
) -> str:
    overall = _metric_lookup(overall_kpis)
    issue_counts = validation_issues["issue_type"].value_counts().to_dict() if not validation_issues.empty else {}
    top_issue = next(iter(issue_counts.items()), ("none", 0))
    completion_delta = _metric_delta(overall_kpis, "Completion Rate")
    backlog_delta = _metric_delta(overall_kpis, "Open Backlog Count")

    risk_summary = "No market-level risk outliers identified."
    qa_rows = market_kpis[market_kpis["kpi_name"] == "QA Issue Rate"].sort_values("actual_value", ascending=False)
    if not qa_rows.empty:
        top_market = qa_rows.iloc[0]
        risk_summary = (
            f"{top_market['market_name']} had the highest QA issue rate at "
            f"{top_market['actual_value']:.0%}."
        )

    lines = [
        f"{reporting_period} operations summary:",
        (
            f"Processed {overall.get('Total Records Received', 0):.0f} records with a "
            f"{overall.get('Completion Rate', 0):.0%} completion rate."
        ),
        _format_delta_line("Completion rate", completion_delta, percent=True),
        (
            f"Open backlog closed the month at {overall.get('Open Backlog Count', 0):.0f} records, "
            f"with {overall.get('Backlog Over SLA Count', 0):.0f} over SLA."
        ),
        _format_delta_line("Open backlog", backlog_delta, percent=False),
        (
            f"QA issue rate was {overall.get('QA Issue Rate', 0):.0%}; "
            f"top logged issue type was `{top_issue[0]}` ({top_issue[1]} occurrence(s))."
        ),
        risk_summary,
    ]
    return "\n".join(lines)


def _metric_lookup(frame: pd.DataFrame) -> dict[str, float]:
    if frame.empty:
        return {}
    return {row["kpi_name"]: float(row["actual_value"]) for _, row in frame.iterrows()}


def _metric_delta(frame: pd.DataFrame, metric_name: str) -> float | None:
    metric_row = frame[frame["kpi_name"] == metric_name]
    if metric_row.empty:
        return None
    value = metric_row.iloc[0]["variance_value"]
    return None if pd.isna(value) else float(value)


def _format_delta_line(label: str, delta: float | None, percent: bool) -> str:
    if delta is None:
        return f"{label} has no prior-period baseline yet."
    if percent:
        return f"{label} changed by {delta:+.0%} versus the prior period."
    return f"{label} changed by {delta:+.0f} versus the prior period."
