from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from healthcare_ops_kpi_qa.db import get_engine
from healthcare_ops_kpi_qa.pipeline import run_refresh
from healthcare_ops_kpi_qa.publication_evidence import (
    FORECAST_EVIDENCE_COLUMNS,
    KPI_EVIDENCE_COLUMNS,
    VALIDATION_EVIDENCE_COLUMNS,
    build_kpi_evidence,
)
from healthcare_ops_kpi_qa.sample_data import DEMO_PERIODS, seed_demo_periods

EVIDENCE_FILES = [
    "evidence_kpi_snapshot.csv",
    "evidence_validation_issue.csv",
    "evidence_forecast.csv",
]

PROHIBITED_COLUMNS = {
    "run_id",
    "generated_run_id",
    "source_file_id",
    "stg_record_id",
    "validation_issue_id",
    "kpi_id",
    "market_id",
    "team_id",
    "created_at",
}


def test_kpi_evidence_uses_business_cut_identifiers() -> None:
    snapshots = pd.DataFrame(
        [
            {
                "kpi_code": "completion_rate",
                "kpi_name": "Completion Rate",
                "market_name": None,
                "team_code": None,
                "actual_value": 0.8,
                "target_value": None,
                "prior_period_value": 0.7,
                "variance_value": 0.1,
                "variance_pct": 0.142857,
                "numerator_value": 4,
                "denominator_value": 5,
                "notes": "Overall cut",
            },
            {
                "kpi_code": "completion_rate",
                "kpi_name": "Completion Rate",
                "market_name": "Nashville",
                "team_code": None,
                "actual_value": 1.0,
                "target_value": None,
                "prior_period_value": 1.0,
                "variance_value": 0.0,
                "variance_pct": 0.0,
                "numerator_value": 2,
                "denominator_value": 2,
                "notes": "Market cut",
            },
        ]
    )

    evidence = build_kpi_evidence("2026-04", snapshots)

    assert evidence.columns.tolist() == KPI_EVIDENCE_COLUMNS
    assert evidence[["cut_type", "cut_name"]].to_dict("records") == [
        {"cut_type": "overall", "cut_name": "All"},
        {"cut_type": "market", "cut_name": "Nashville"},
    ]
    assert PROHIBITED_COLUMNS.isdisjoint(evidence.columns)


def test_publication_evidence_rejects_unsupported_combined_cut() -> None:
    snapshots = pd.DataFrame(
        [
            {
                "kpi_code": "total_records",
                "kpi_name": "Total Records Received",
                "market_name": "Nashville",
                "team_code": "TEAM_A",
            }
        ]
    )

    with pytest.raises(ValueError, match="combined cuts"):
        build_kpi_evidence("2026-04", snapshots)


def test_repeated_demo_refresh_writes_byte_identical_publication_evidence(tmp_path: Path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    outputs_dir = tmp_path / "outputs"
    database_path = data_dir / "processed" / "healthcare_ops.sqlite3"
    monkeypatch.setenv("HEALTHCARE_OPS_DATA_DIR", str(data_dir))
    monkeypatch.setenv("HEALTHCARE_OPS_OUTPUTS_DIR", str(outputs_dir))
    monkeypatch.setenv("HEALTHCARE_OPS_SQLITE_PATH", str(database_path))
    get_engine.cache_clear()

    try:
        seed_demo_periods()
        first_results = [run_refresh(period) for period in DEMO_PERIODS]
        output_dir = outputs_dir / "2026-04"
        first_bytes = {name: (output_dir / name).read_bytes() for name in EVIDENCE_FILES}

        second_results = [run_refresh(period) for period in DEMO_PERIODS]
        second_bytes = {name: (output_dir / name).read_bytes() for name in EVIDENCE_FILES}
    finally:
        get_engine.cache_clear()

    assert first_bytes == second_bytes
    assert set(first_results[-1]["outputs"]) >= {
        "kpi_snapshot_csv",
        "validation_issue_csv",
        "forecast_csv",
        "evidence_kpi_snapshot_csv",
        "evidence_validation_issue_csv",
        "evidence_forecast_csv",
    }
    assert set(second_results[-1]["outputs"]) == set(first_results[-1]["outputs"])

    kpi = pd.read_csv(output_dir / "evidence_kpi_snapshot.csv")
    validation = pd.read_csv(output_dir / "evidence_validation_issue.csv")
    forecast = pd.read_csv(output_dir / "evidence_forecast.csv")
    assert kpi.columns.tolist() == KPI_EVIDENCE_COLUMNS
    assert validation.columns.tolist() == VALIDATION_EVIDENCE_COLUMNS
    assert forecast.columns.tolist() == FORECAST_EVIDENCE_COLUMNS
    assert PROHIBITED_COLUMNS.isdisjoint(kpi.columns)
    assert PROHIBITED_COLUMNS.isdisjoint(validation.columns)
    assert PROHIBITED_COLUMNS.isdisjoint(forecast.columns)
    assert {"overall", "market", "team"} == set(kpi["cut_type"])
    assert {"overall", "market", "team"} == set(forecast["cut_type"])
    assert "Completion Rate" in set(kpi["kpi_name"])
