import pandas as pd

from healthcare_ops_kpi_qa.dashboard import (
    ALL_FILTER,
    build_tie_out_frame,
    filter_events,
    filter_source_linked_rows,
    kpi_definition_frame,
    select_cut_rows,
    selected_run_is_consistent,
    workbook_summary_parity,
)
from healthcare_ops_kpi_qa.db import get_connection, get_engine, read_sql_frame
from healthcare_ops_kpi_qa.pipeline import run_refresh
from healthcare_ops_kpi_qa.sample_data import DEMO_PERIODS, seed_demo_periods


def _snapshot_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"run_id": 7, "kpi_name": "Total Records Received", "market_name": None, "team_code": None},
            {"run_id": 7, "kpi_name": "Completion Rate", "market_name": None, "team_code": None},
            {"run_id": 7, "kpi_name": "Open Backlog Count", "market_name": None, "team_code": None},
            {"run_id": 7, "kpi_name": "QA Issue Rate", "market_name": None, "team_code": None},
            {"run_id": 7, "kpi_name": "Total Records Received", "market_name": "Nashville", "team_code": None},
            {"run_id": 7, "kpi_name": "Total Records Received", "market_name": None, "team_code": "TEAM_A"},
        ]
    )


def test_cockpit_filters_preserve_v1_cut_grain() -> None:
    snapshots = _snapshot_frame()
    events = pd.DataFrame(
        [
            {"market_name": "Nashville", "team_code": "TEAM_A", "provider_name": "A"},
            {"market_name": "Memphis", "team_code": "TEAM_B", "provider_name": "B"},
        ]
    )
    source_rows = pd.DataFrame(
        [
            {"source_file_type": "provider_roster", "source_file_name": "roster.csv"},
            {"source_file_type": "directory_audit", "source_file_name": "audit.csv"},
        ]
    )

    assert len(select_cut_rows(snapshots, "Nashville", ALL_FILTER)) == 1
    assert len(select_cut_rows(snapshots, ALL_FILTER, "TEAM_A")) == 1
    assert select_cut_rows(snapshots, "Nashville", "TEAM_A").empty
    assert len(filter_events(events, "Nashville", "TEAM_A")) == 1
    assert filter_source_linked_rows(source_rows, "directory_audit")["source_file_name"].tolist() == ["audit.csv"]


def test_selected_run_consistency_rejects_mixed_extracts() -> None:
    bundle = {
        "events": pd.DataFrame([{"run_id": 7}]),
        "snapshots": pd.DataFrame([{"run_id": 7}]),
        "issues": pd.DataFrame([{"run_id": 7}]),
        "forecasts": pd.DataFrame([{"generated_run_id": 7}]),
        "drafts": pd.DataFrame([{"run_id": 7}]),
        "source_files": pd.DataFrame([{"run_id": 7}]),
    }

    assert selected_run_is_consistent(7, bundle)
    bundle["issues"] = pd.DataFrame([{"run_id": 8}])
    assert not selected_run_is_consistent(7, bundle)


def test_definition_catalog_and_export_parity_use_configured_and_persisted_data() -> None:
    definitions = kpi_definition_frame()
    snapshots = _snapshot_frame()

    assert {"kpi_name", "how_calculated", "target_direction"}.issubset(definitions.columns)
    assert "Completion Rate" in set(definitions["kpi_name"])
    assert workbook_summary_parity(snapshots)
    assert not workbook_summary_parity(snapshots[snapshots["market_name"].notna()])


def test_tie_out_frame_connects_source_run_mart_and_workbook_counts() -> None:
    run_row = pd.Series({"staged_row_count": 13})
    source_files = pd.DataFrame(
        [
            {"row_count": 6, "source_file_type": "provider_roster"},
            {"row_count": 4, "source_file_type": "onboarding_tracker"},
            {"row_count": 3, "source_file_type": "directory_audit"},
        ]
    )
    events = pd.DataFrame([{"event_id": number} for number in range(5)])
    issues = pd.DataFrame([{"validation_issue_id": number} for number in range(14)])

    tie_out = build_tie_out_frame(run_row, source_files, events, _snapshot_frame(), issues, workbook_available=True)
    values = dict(zip(tie_out["control"], tie_out["value"], strict=True))

    assert values["Selected source rows"] == 13
    assert values["Run staged rows"] == 13
    assert values["Selected market/team canonical events"] == 5
    assert values["Workbook export"] == "available"


def test_exported_workbook_summary_matches_persisted_overall_snapshot(tmp_path, monkeypatch) -> None:
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
        with get_connection() as connection:
            expected = read_sql_frame(
                connection,
                """
                select k.kpi_name, s.actual_value
                from fact_kpi_snapshot s
                join dim_kpi k on k.kpi_id = s.kpi_id
                where s.run_id = :run_id
                  and s.market_id is null
                  and s.team_id is null
                """,
                {"run_id": results[-1]["run_id"]},
            )
    finally:
        get_engine.cache_clear()

    output_dir = outputs_dir / "2026-04"
    workbook = pd.read_excel(
        output_dir / "healthcare_ops_kpi_qa_pack_2026_04.xlsx",
        sheet_name="summary",
        skiprows=2,
        usecols="A:B",
    )

    actual = workbook[workbook["kpi_name"].isin(expected["kpi_name"])][["kpi_name", "actual_value"]]
    actual = actual.sort_values("kpi_name").reset_index(drop=True)
    expected = expected.sort_values("kpi_name").reset_index(drop=True)
    pd.testing.assert_frame_equal(actual, expected, check_dtype=False)
