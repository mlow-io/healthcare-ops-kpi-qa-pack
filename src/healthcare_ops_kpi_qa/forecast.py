from __future__ import annotations

from calendar import monthrange
from datetime import date

import pandas as pd

FORECAST_METHODS = {
    "rolling_avg_3": "Three-period rolling average for stable volume and backlog metrics.",
}

FORECASTABLE_KPI_NAMES = {
    "Total Records Received",
    "Completed Records",
    "Open Backlog Count",
    "Backlog Over SLA Count",
}


def forecast_notes() -> list[str]:
    return [
        "Use transparent forecasts only in V1.",
        "Persist forecasts for volume and backlog metrics when at least three periods exist.",
        "Do not forecast QA rate metrics in V1.",
    ]


def next_period_snapshot_date_key(period: str) -> int:
    year_str, month_str = period.split("-")
    year = int(year_str)
    month = int(month_str)
    if month == 12:
        year += 1
        month = 1
    else:
        month += 1
    last_day = monthrange(year, month)[1]
    return int(date(year, month, last_day).strftime("%Y%m%d"))


def compute_forecasts(history: pd.DataFrame, generated_run_id: int, reporting_period: str) -> pd.DataFrame:
    if history.empty:
        return pd.DataFrame()

    eligible = history[history["kpi_name"].isin(FORECASTABLE_KPI_NAMES)].copy()
    if eligible.empty:
        return pd.DataFrame()

    eligible["market_key"] = eligible["market_id"].fillna(-1).astype(int)
    eligible["team_key"] = eligible["team_id"].fillna(-1).astype(int)

    rows: list[dict] = []
    group_columns = ["kpi_id", "market_key", "team_key"]
    forecast_period_date_key = next_period_snapshot_date_key(reporting_period)

    for _, group in eligible.sort_values("reporting_period").groupby(group_columns, dropna=False):
        latest = group.sort_values("reporting_period").tail(3)
        if len(latest) < 3:
            continue

        latest_row = latest.iloc[-1]
        forecast_value = float(latest["actual_value"].mean())
        rows.append(
            {
                "generated_run_id": generated_run_id,
                "forecast_period_date_key": forecast_period_date_key,
                "kpi_id": int(latest_row["kpi_id"]),
                "market_id": None if int(latest_row["market_key"]) == -1 else int(latest_row["market_key"]),
                "team_id": None if int(latest_row["team_key"]) == -1 else int(latest_row["team_key"]),
                "model_name": "rolling_avg_3",
                "forecast_value": forecast_value,
                "lower_bound": float(latest["actual_value"].min()),
                "upper_bound": float(latest["actual_value"].max()),
            }
        )

    return pd.DataFrame(rows)
