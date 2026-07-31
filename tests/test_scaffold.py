from datetime import date

import pandas as pd

from healthcare_ops_kpi_qa.db import get_engine
from healthcare_ops_kpi_qa.kpis import list_kpi_codes
from healthcare_ops_kpi_qa.llm_draft import build_llm_payload
from healthcare_ops_kpi_qa.pipeline import run_refresh
from healthcare_ops_kpi_qa.sample_data import DEMO_PERIODS, seed_demo_periods
from healthcare_ops_kpi_qa.validate import (
    V1_RULES,
    build_staged_validation_issues,
    npi_checksum_is_valid,
)


def test_kpi_catalog_is_not_empty() -> None:
    assert list_kpi_codes()


def test_validation_rules_are_defined() -> None:
    assert "invalid_npi_format" in V1_RULES


def test_npi_checksum_validation() -> None:
    assert npi_checksum_is_valid("1234567893")
    assert not npi_checksum_is_valid("1234567890")


def test_reference_validation_detects_phase2_issues() -> None:
    staged_df = pd.DataFrame(
        [
            {
                "run_id": 1,
                "source_file_id": 1,
                "source_file_name": "onboarding_tracker_2026_04.xlsx",
                "source_row_num": 1,
                "source_file_type": "onboarding_tracker",
                "provider_npi": "1234567893",
                "provider_name": "Allied Cardiology Group",
                "specialty_name": "Cardiology",
                "market_name": "Nashville",
                "team_code": "TEAM_A",
                "workflow_status": "in_review",
                "received_date": date(2026, 4, 1),
                "completed_date": pd.NaT,
                "owner_name": "",
            },
            {
                "run_id": 1,
                "source_file_id": 2,
                "source_file_name": "directory_audit_2026_04.csv",
                "source_row_num": 1,
                "source_file_type": "directory_audit",
                "provider_npi": "1234567893",
                "provider_name": "Allied Cardiology Group",
                "specialty_name": "Cardiology",
                "market_name": "Nashville",
                "team_code": "TEAM_A",
                "workflow_status": "published",
                "audit_result": "pass",
                "received_date": pd.NaT,
                "completed_date": pd.NaT,
                "owner_name": "",
            },
        ]
    )
    status_values = {"open": ["pending", "in_review", "onboarding"], "complete": ["completed", "ready_for_directory", "published"]}
    reference_data = {
        "markets": {"Nashville": {"allowed_teams": ["TEAM_A"]}},
        "teams": {"TEAM_A": {"team_name": "Provider Onboarding East"}},
        "providers": {"1234567893": {"provider_name": "Allied Cardiology Group", "market_name": "Nashville", "team_code": "TEAM_A", "specialty_name": "Cardiology"}},
    }

    issues = build_staged_validation_issues(staged_df, status_values, reference_data)

    assert "missing_owner_assignment" in set(issues["issue_type"])
    assert "audit_onboarding_mismatch" in set(issues["issue_type"])


def test_reference_validation_ignores_nullable_optional_fields() -> None:
    staged_df = pd.DataFrame(
        [
            {
                "run_id": 1,
                "source_file_id": 1,
                "source_file_name": "directory_audit_2026_04.csv",
                "source_row_num": 1,
                "source_file_type": "directory_audit",
                "provider_npi": "1234567893",
                "provider_name": pd.NA,
                "specialty_name": pd.NA,
                "market_name": "Nashville",
                "team_code": pd.NA,
                "workflow_status": "published",
                "audit_result": "pass",
                "received_date": pd.NaT,
                "completed_date": pd.NaT,
                "owner_name": pd.NA,
            }
        ]
    )
    status_values = {
        "open": ["pending", "in_review", "onboarding"],
        "complete": ["completed", "ready_for_directory", "published"],
    }
    reference_data = {
        "markets": {"Nashville": {"allowed_teams": ["TEAM_A"]}},
        "teams": {"TEAM_A": {"team_name": "Provider Onboarding East"}},
        "providers": {
            "1234567893": {
                "provider_name": "Allied Cardiology Group",
                "market_name": "Nashville",
                "team_code": "TEAM_A",
                "specialty_name": "Cardiology",
            }
        },
    }

    issues = build_staged_validation_issues(staged_df, status_values, reference_data)

    assert issues.empty


def test_build_llm_payload_uses_structured_inputs() -> None:
    overall_kpis = pd.DataFrame(
        [
            {"kpi_name": "Completion Rate", "actual_value": 0.8, "prior_period_value": 0.7, "variance_value": 0.1, "variance_pct": 0.142857},
            {"kpi_name": "Open Backlog Count", "actual_value": 4, "prior_period_value": 5, "variance_value": -1, "variance_pct": -0.2},
        ]
    )
    market_kpis = pd.DataFrame([{"kpi_name": "QA Issue Rate", "market_name": "Nashville", "actual_value": 0.2}])
    validation_issues = pd.DataFrame([{"issue_type": "invalid_npi_checksum"}, {"issue_type": "invalid_npi_checksum"}])
    forecasts = pd.DataFrame(
        [
            {
                "kpi_name": "Open Backlog Count",
                "forecast_value": 3.5,
                "lower_bound": 3.0,
                "upper_bound": 4.0,
                "market_name": None,
                "team_code": None,
            }
        ]
    )

    payload = build_llm_payload(
        "2026-04",
        "Deterministic commentary.",
        overall_kpis,
        market_kpis,
        validation_issues,
        forecasts,
    )

    assert payload.reporting_period == "2026-04"
    assert payload.validation_counts[0].issue_type == "invalid_npi_checksum"
    assert payload.forecast_highlights[0].kpi_name == "Open Backlog Count"


def test_demo_refresh_runs_end_to_end_in_temporary_workspace(tmp_path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    outputs_dir = tmp_path / "outputs"
    database_path = data_dir / "processed" / "healthcare_ops.sqlite3"

    monkeypatch.setenv("HEALTHCARE_OPS_DATA_DIR", str(data_dir))
    monkeypatch.setenv("HEALTHCARE_OPS_OUTPUTS_DIR", str(outputs_dir))
    monkeypatch.setenv("HEALTHCARE_OPS_SQLITE_PATH", str(database_path))
    get_engine.cache_clear()

    try:
        seed_demo_periods()
        results = [run_refresh(period) for period in DEMO_PERIODS]
    finally:
        get_engine.cache_clear()

    assert [result["period"] for result in results] == DEMO_PERIODS
    assert [result["validation_issue_count"] for result in results] == [12, 10, 14]
    assert results[-1]["forecast_count"] == 32
    assert (outputs_dir / "2026-04" / "healthcare_ops_kpi_qa_pack_2026_04.xlsx").exists()
