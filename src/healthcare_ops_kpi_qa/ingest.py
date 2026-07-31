from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

import pandas as pd
import yaml

from .settings import get_project_paths

CANONICAL_FIELDS = [
    "provider_name",
    "provider_npi",
    "specialty_name",
    "market_name",
    "team_code",
    "workflow_status",
    "received_date",
    "completed_date",
    "effective_date",
    "audit_date",
    "audit_result",
    "audit_issue_type",
    "owner_name",
    "phone_number",
    "address_line",
]


def load_field_mappings() -> dict:
    config_path = get_project_paths().config_dir / "field_mappings.yml"
    return yaml.safe_load(config_path.read_text())


def discover_source_files(period: str) -> dict[str, list[Path]]:
    paths = get_project_paths()
    period_dir = paths.raw_dir / period
    config = load_field_mappings()
    discovered: dict[str, list[Path]] = {}

    for file_type, spec in config["files"].items():
        discovered[file_type] = sorted(period_dir.glob(spec["pattern"]))

    return discovered


def missing_required_file_types(period: str) -> list[str]:
    config = load_field_mappings()
    discovered = discover_source_files(period)
    missing = []

    for file_type, spec in config["files"].items():
        if spec.get("required", False) and not discovered.get(file_type):
            missing.append(file_type)

    return missing


def summarize_discovery(period: str) -> Iterable[str]:
    discovered = discover_source_files(period)
    for file_type, paths in discovered.items():
        yield f"{file_type}: {len(paths)} file(s)"


def _load_frame(path: Path, loader: str) -> pd.DataFrame:
    if loader == "csv":
        return pd.read_csv(path, dtype="string")
    if loader == "excel":
        return pd.read_excel(path, dtype="string")
    raise ValueError(f"Unsupported loader: {loader}")


def _normalize_frame(path: Path, file_type: str, spec: dict, period: str) -> pd.DataFrame:
    raw = _load_frame(path, spec["loader"])
    normalized = pd.DataFrame(index=raw.index)

    for canonical_field in CANONICAL_FIELDS:
        normalized[canonical_field] = pd.NA

    for canonical_field, aliases in spec["canonical_fields"].items():
        for alias in aliases:
            if alias in raw.columns:
                normalized[canonical_field] = raw[alias]
                break

    normalized["source_file_name"] = path.name
    normalized["source_file_type"] = file_type
    normalized["source_row_num"] = range(1, len(normalized) + 1)
    normalized["reporting_period"] = period
    normalized["raw_payload_json"] = raw.apply(
        lambda row: json.dumps(row.dropna().to_dict(), default=str),
        axis=1,
    )

    for date_col in ["received_date", "completed_date", "effective_date", "audit_date"]:
        normalized[date_col] = pd.to_datetime(normalized[date_col], errors="coerce").dt.date

    for text_col in [
        "provider_name",
        "provider_npi",
        "specialty_name",
        "market_name",
        "team_code",
        "workflow_status",
        "audit_result",
        "audit_issue_type",
        "owner_name",
        "phone_number",
        "address_line",
    ]:
        normalized[text_col] = normalized[text_col].astype("string").str.strip()

    return normalized


def load_period_inputs(period: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    config = load_field_mappings()
    discovered = discover_source_files(period)
    staged_frames: list[pd.DataFrame] = []
    source_file_rows: list[dict] = []

    for file_type, paths in discovered.items():
        spec = config["files"][file_type]
        for path in paths:
            frame = _normalize_frame(path, file_type, spec, period)
            staged_frames.append(frame)
            source_file_rows.append(
                {
                    "source_file_name": path.name,
                    "source_file_type": file_type,
                    "reporting_period": period,
                    "row_count": len(frame),
                }
            )

    staged = pd.concat(staged_frames, ignore_index=True) if staged_frames else pd.DataFrame()
    source_files = pd.DataFrame(source_file_rows)
    return staged, source_files
