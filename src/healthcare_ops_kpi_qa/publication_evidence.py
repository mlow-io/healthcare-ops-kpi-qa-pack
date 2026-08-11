from __future__ import annotations

from pathlib import Path

import pandas as pd

KPI_EVIDENCE_COLUMNS = [
    "reporting_period",
    "cut_type",
    "cut_name",
    "kpi_code",
    "kpi_name",
    "actual_value",
    "target_value",
    "prior_period_value",
    "variance_value",
    "variance_pct",
    "numerator_value",
    "denominator_value",
    "notes",
]

FORECAST_EVIDENCE_COLUMNS = [
    "reporting_period",
    "forecast_period",
    "cut_type",
    "cut_name",
    "kpi_code",
    "kpi_name",
    "model_name",
    "forecast_value",
    "lower_bound",
    "upper_bound",
]

VALIDATION_EVIDENCE_COLUMNS = [
    "reporting_period",
    "row_identifier",
    "issue_type",
    "severity",
    "issue_message",
    "status",
]

_CUT_ORDER = {"overall": 0, "market": 1, "team": 2}


def build_kpi_evidence(reporting_period: str, snapshots: pd.DataFrame) -> pd.DataFrame:
    if snapshots.empty:
        return pd.DataFrame(columns=KPI_EVIDENCE_COLUMNS)
    evidence = _add_cut_fields(snapshots)
    evidence.insert(0, "reporting_period", reporting_period)
    return _sort_cuts(evidence[KPI_EVIDENCE_COLUMNS], ["kpi_code"])


def build_forecast_evidence(reporting_period: str, forecasts: pd.DataFrame) -> pd.DataFrame:
    if forecasts.empty:
        return pd.DataFrame(columns=FORECAST_EVIDENCE_COLUMNS)
    evidence = _add_cut_fields(forecasts)
    evidence.insert(0, "reporting_period", reporting_period)
    evidence["forecast_period"] = pd.to_datetime(
        evidence["forecast_period_date_key"].astype("Int64").astype(str),
        format="%Y%m%d",
    ).dt.strftime("%Y-%m-%d")
    return _sort_cuts(evidence[FORECAST_EVIDENCE_COLUMNS], ["kpi_code", "forecast_period"])


def build_validation_evidence(reporting_period: str, issues: pd.DataFrame) -> pd.DataFrame:
    evidence = issues.reindex(columns=VALIDATION_EVIDENCE_COLUMNS[1:]).copy()
    evidence.insert(0, "reporting_period", reporting_period)
    return evidence.sort_values(
        ["severity", "issue_type", "row_identifier", "issue_message"],
        kind="stable",
        na_position="last",
    ).reset_index(drop=True)


def write_publication_evidence(
    output_dir: Path,
    reporting_period: str,
    snapshots: pd.DataFrame,
    issues: pd.DataFrame,
    forecasts: pd.DataFrame,
) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    frames = {
        "evidence_kpi_snapshot_csv": (
            output_dir / "evidence_kpi_snapshot.csv",
            build_kpi_evidence(reporting_period, snapshots),
        ),
        "evidence_validation_issue_csv": (
            output_dir / "evidence_validation_issue.csv",
            build_validation_evidence(reporting_period, issues),
        ),
        "evidence_forecast_csv": (
            output_dir / "evidence_forecast.csv",
            build_forecast_evidence(reporting_period, forecasts),
        ),
    }
    output_paths: dict[str, str] = {}
    for output_key, (path, frame) in frames.items():
        frame.to_csv(path, index=False, lineterminator="\n", na_rep="", float_format="%.12g")
        output_paths[output_key] = str(path)
    return output_paths


def _add_cut_fields(frame: pd.DataFrame) -> pd.DataFrame:
    evidence = frame.copy()
    if "market_name" not in evidence:
        evidence["market_name"] = pd.Series(dtype="string")
    if "team_code" not in evidence:
        evidence["team_code"] = pd.Series(dtype="string")

    market_rows = evidence["market_name"].notna()
    team_rows = evidence["team_code"].notna()
    if (market_rows & team_rows).any():
        raise ValueError("Publication evidence supports overall, market, or team cuts, not combined cuts.")

    evidence["cut_type"] = "overall"
    evidence["cut_name"] = "All"
    evidence.loc[market_rows, "cut_type"] = "market"
    evidence.loc[market_rows, "cut_name"] = evidence.loc[market_rows, "market_name"]
    evidence.loc[team_rows, "cut_type"] = "team"
    evidence.loc[team_rows, "cut_name"] = evidence.loc[team_rows, "team_code"]
    return evidence


def _sort_cuts(frame: pd.DataFrame, trailing_columns: list[str]) -> pd.DataFrame:
    evidence = frame.copy()
    evidence["_cut_order"] = evidence["cut_type"].map(_CUT_ORDER)
    evidence = evidence.sort_values(
        ["reporting_period", "_cut_order", "cut_name", *trailing_columns],
        kind="stable",
        na_position="last",
    )
    return evidence.drop(columns="_cut_order").reset_index(drop=True)
