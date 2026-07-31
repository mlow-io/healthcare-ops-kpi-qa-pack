from __future__ import annotations

from pathlib import Path

import pandas as pd

WORKBOOK_TABS = [
    "summary",
    "kpi_detail",
    "variance",
    "forecast",
    "audit_tie_out",
    "validation_exceptions",
]


def workbook_contract() -> dict[str, str]:
    return {
        "summary": "Executive KPI view for the reporting period.",
        "kpi_detail": "Metric values with numerator and denominator where applicable.",
        "variance": "Current vs target and prior period movement.",
        "forecast": "Simple next-period forecast for stable volume and backlog metrics.",
        "audit_tie_out": "Source counts and mart reconciliation.",
        "validation_exceptions": "Persisted issue list and grouped counts.",
    }


def export_workbook(
    workbook_path: Path,
    overall_kpis: pd.DataFrame,
    all_kpis: pd.DataFrame,
    validation_issues: pd.DataFrame,
    source_files: pd.DataFrame,
    run_summary: dict,
    commentary_text: str,
    forecast_df: pd.DataFrame,
) -> str:
    workbook_path.parent.mkdir(parents=True, exist_ok=True)

    summary_sheet = overall_kpis[["kpi_name", "actual_value", "numerator_value", "denominator_value", "notes"]].copy()
    variance_sheet = all_kpis[
        [
            "market_name",
            "team_code",
            "kpi_name",
            "actual_value",
            "target_value",
            "prior_period_value",
            "variance_value",
            "variance_pct",
        ]
    ].copy()
    audit_summary = pd.DataFrame(
        [
            {"metric": "run_id", "value": run_summary["run_id"]},
            {"metric": "reporting_period", "value": run_summary["period"]},
            {"metric": "staged_row_count", "value": run_summary["staged_row_count"]},
            {"metric": "event_row_count", "value": run_summary["event_row_count"]},
            {"metric": "validation_issue_count", "value": run_summary["validation_issue_count"]},
            {"metric": "kpi_snapshot_count", "value": run_summary["kpi_snapshot_count"]},
            {"metric": "forecast_count", "value": run_summary["forecast_count"]},
        ]
    )
    commentary_df = pd.DataFrame({"commentary": commentary_text.splitlines()})
    forecast_sheet = forecast_df[
        [
            "kpi_name",
            "market_name",
            "team_code",
            "forecast_value",
            "lower_bound",
            "upper_bound",
            "model_name",
        ]
    ].copy() if not forecast_df.empty else pd.DataFrame(
        columns=["kpi_name", "market_name", "team_code", "forecast_value", "lower_bound", "upper_bound", "model_name"]
    )

    with pd.ExcelWriter(workbook_path, engine="xlsxwriter") as writer:
        summary_sheet.to_excel(writer, sheet_name="summary", index=False, startrow=2)
        commentary_df.to_excel(writer, sheet_name="summary", index=False, startrow=12)
        all_kpis.to_excel(writer, sheet_name="kpi_detail", index=False)
        variance_sheet.to_excel(writer, sheet_name="variance", index=False)
        forecast_sheet.to_excel(writer, sheet_name="forecast", index=False)
        audit_summary.to_excel(writer, sheet_name="audit_tie_out", index=False, startrow=0)
        source_files.to_excel(writer, sheet_name="audit_tie_out", index=False, startrow=10)
        validation_issues.to_excel(writer, sheet_name="validation_exceptions", index=False)

        workbook = writer.book
        for sheet_name in WORKBOOK_TABS:
            worksheet = writer.sheets[sheet_name]
            worksheet.set_default_row(18)
            worksheet.set_column(0, 10, 18)

        summary_ws = writer.sheets["summary"]
        title_fmt = workbook.add_format({"bold": True, "font_size": 14})
        note_fmt = workbook.add_format({"italic": True, "text_wrap": True})
        summary_ws.write(0, 0, "Healthcare Operations KPI & QA Pack", title_fmt)
        summary_ws.write(1, 0, "Overall KPI summary", note_fmt)
        summary_ws.write(11, 0, "Commentary preview", title_fmt)

    return str(workbook_path)
