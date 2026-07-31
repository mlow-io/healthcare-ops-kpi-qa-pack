from __future__ import annotations

from calendar import monthrange
from datetime import date

import pandas as pd
import yaml

from .settings import get_project_paths


def load_kpi_definitions() -> dict:
    config_path = get_project_paths().config_dir / "kpi_definitions.yml"
    return yaml.safe_load(config_path.read_text())


def list_kpi_codes() -> list[str]:
    definitions = load_kpi_definitions()
    return [kpi["code"] for kpi in definitions["kpis"]]


def compute_kpi_snapshots(
    event_df: pd.DataFrame,
    reporting_period: str,
    snapshot_date_key: int,
) -> pd.DataFrame:
    if event_df.empty:
        return pd.DataFrame()

    rows: list[dict] = []
    definitions = {kpi["code"]: kpi for kpi in load_kpi_definitions()["kpis"]}

    cuts = [("overall", None)]
    cuts.extend((f"market::{market}", event_df[event_df["market_name"] == market]) for market in sorted(event_df["market_name"].dropna().unique()))
    cuts.extend((f"team::{team}", event_df[event_df["team_code"] == team]) for team in sorted(event_df["team_code"].dropna().unique()))

    for cut_name, subset in cuts:
        cut_df = event_df if subset is None else subset
        if cut_df.empty:
            continue

        market_name = None
        team_code = None
        if cut_name.startswith("market::"):
            market_name = cut_name.split("::", 1)[1]
        elif cut_name.startswith("team::"):
            team_code = cut_name.split("::", 1)[1]

        metrics = _calculate_metrics(cut_df)
        for code, actual_value in metrics.items():
            definition = definitions[code]
            numerator, denominator = _numerator_denominator(code, cut_df, actual_value)
            rows.append(
                {
                    "snapshot_date_key": snapshot_date_key,
                    "kpi_code": code,
                    "kpi_name": definition["name"],
                    "market_name": market_name,
                    "team_code": team_code,
                    "actual_value": actual_value,
                    "target_value": None,
                    "prior_period_value": None,
                    "variance_value": None,
                    "variance_pct": None,
                    "numerator_value": numerator,
                    "denominator_value": denominator,
                    "notes": f"Computed for {reporting_period} cut `{cut_name}`.",
                }
            )

    return pd.DataFrame(rows)


def snapshot_date_key(period: str) -> int:
    year_str, month_str = period.split("-")
    year = int(year_str)
    month = int(month_str)
    last_day = monthrange(year, month)[1]
    return int(date(year, month, last_day).strftime("%Y%m%d"))


def _calculate_metrics(event_df: pd.DataFrame) -> dict[str, float]:
    total_records = float(len(event_df))
    completed = float(event_df["completion_flag"].sum())
    open_backlog = float(event_df["backlog_flag"].sum())
    backlog_over_sla = float(event_df["backlog_over_sla_flag"].sum())
    qa_issue_count = float(event_df["qa_issue_flag"].sum())
    completeness_count = float(event_df["required_field_complete_flag"].sum())
    unique_npis = float(event_df["provider_npi"].nunique(dropna=True))
    turnaround = event_df.loc[event_df["completion_flag"], "turnaround_days"].dropna()
    avg_turnaround = float(turnaround.mean()) if not turnaround.empty else 0.0

    return {
        "total_records_received": total_records,
        "completed_records": completed,
        "completion_rate": completed / total_records if total_records else 0.0,
        "avg_turnaround_days": avg_turnaround,
        "open_backlog_count": open_backlog,
        "backlog_over_sla_count": backlog_over_sla,
        "qa_issue_rate": qa_issue_count / total_records if total_records else 0.0,
        "required_field_completeness_rate": completeness_count / total_records if total_records else 0.0,
        "unique_npi_rate": unique_npis / total_records if total_records else 0.0,
    }


def _numerator_denominator(code: str, event_df: pd.DataFrame, actual_value: float) -> tuple[float | None, float | None]:
    total_records = float(len(event_df))
    if code == "completion_rate":
        return float(event_df["completion_flag"].sum()), total_records
    if code == "qa_issue_rate":
        return float(event_df["qa_issue_flag"].sum()), total_records
    if code == "required_field_completeness_rate":
        return float(event_df["required_field_complete_flag"].sum()), total_records
    if code == "unique_npi_rate":
        return float(event_df["provider_npi"].nunique(dropna=True)), total_records
    return actual_value, None
