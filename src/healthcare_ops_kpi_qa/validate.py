from __future__ import annotations

import pandas as pd

from .time_utils import utc_now_naive

V1_RULES = [
    "missing_required_field",
    "duplicate_provider_market",
    "invalid_npi_format",
    "invalid_npi_checksum",
    "invalid_date_sequence",
    "invalid_status_value",
    "invalid_market_reference",
    "invalid_team_reference",
    "invalid_market_team_mapping",
    "provider_reference_conflict",
    "missing_owner_assignment",
    "unexpected_status_transition",
    "audit_onboarding_mismatch",
    "stale_backlog_record",
]


def validation_rule_descriptions() -> dict[str, str]:
    return {
        "missing_required_field": "Provider NPI, market, and workflow status must be present.",
        "duplicate_provider_market": "The same provider-market-workflow combination should not appear more than once.",
        "invalid_npi_format": "NPI must be exactly 10 digits in V1.",
        "invalid_npi_checksum": "NPI should pass the standard checksum validation when 10 digits are present.",
        "invalid_date_sequence": "Completed date cannot be earlier than received date.",
        "invalid_status_value": "Workflow status must map to a configured value.",
        "invalid_market_reference": "Market should exist in the repo-owned reference data.",
        "invalid_team_reference": "Team should exist in the repo-owned reference data.",
        "invalid_market_team_mapping": "Team should be allowed for the referenced market.",
        "provider_reference_conflict": "Known provider reference attributes should match the incoming record.",
        "missing_owner_assignment": "Open onboarding work should have an assigned owner.",
        "unexpected_status_transition": "Cross-file statuses should move through a believable operational sequence.",
        "audit_onboarding_mismatch": "Published or passing audit records should align with completed onboarding state.",
        "stale_backlog_record": "Open records above the SLA threshold should be surfaced explicitly.",
    }


def npi_checksum_is_valid(provider_npi: str) -> bool:
    normalized = _clean_text(provider_npi)
    if len(normalized) != 10 or not normalized.isdigit():
        return False
    return _luhn_valid(f"80840{normalized}")


def _luhn_valid(number: str) -> bool:
    checksum = 0
    double_digit = False
    for char in reversed(number):
        digit = int(char)
        if double_digit:
            digit *= 2
            if digit > 9:
                digit -= 9
        checksum += digit
        double_digit = not double_digit
    return checksum % 10 == 0


def _issue_row(
    staged_row: pd.Series | None,
    issue_type: str,
    severity: str,
    issue_message: str,
    source_file_id: int | None = None,
    stg_record_id: int | None = None,
) -> dict:
    return {
        "run_id": int(staged_row["run_id"]) if staged_row is not None else None,
        "source_file_id": source_file_id if source_file_id is not None else _int_or_none(staged_row, "source_file_id"),
        "stg_record_id": stg_record_id if stg_record_id is not None else _int_or_none(staged_row, "stg_record_id"),
        "issue_type": issue_type,
        "severity": severity,
        "row_identifier": (
            f"{staged_row['source_file_name']}:{staged_row['source_row_num']}"
            if staged_row is not None
            else None
        ),
        "issue_message": issue_message,
        "status": "open",
        "created_at": utc_now_naive(),
    }


def _int_or_none(row: pd.Series | None, column: str) -> int | None:
    if row is None or pd.isna(row.get(column)):
        return None
    return int(row[column])


def _clean_text(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def build_staged_validation_issues(
    staged_df: pd.DataFrame,
    status_values: dict[str, list[str]],
    reference_data: dict | None = None,
) -> pd.DataFrame:
    if staged_df.empty:
        return pd.DataFrame()

    issues: list[dict] = []
    required_fields = ["provider_npi", "market_name", "workflow_status"]
    allowed_statuses = {status for values in status_values.values() for status in values}

    for _, row in staged_df.iterrows():
        for field_name in required_fields:
            value = row.get(field_name)
            if pd.isna(value) or str(value).strip() == "":
                issues.append(
                    _issue_row(
                        row,
                        "missing_required_field",
                        "error",
                        f"Required field `{field_name}` is missing.",
                    )
                )

        provider_npi = _clean_text(row.get("provider_npi"))
        if provider_npi and (not provider_npi.isdigit() or len(provider_npi) != 10):
            issues.append(
                _issue_row(
                    row,
                    "invalid_npi_format",
                    "error",
                    f"NPI `{provider_npi}` must contain exactly 10 digits.",
                )
            )
        elif provider_npi and not npi_checksum_is_valid(provider_npi):
            issues.append(
                _issue_row(
                    row,
                    "invalid_npi_checksum",
                    "warning",
                    f"NPI `{provider_npi}` failed checksum validation.",
                )
            )

        workflow_status = _clean_text(row.get("workflow_status"))
        if workflow_status and workflow_status not in allowed_statuses:
            issues.append(
                _issue_row(
                    row,
                    "invalid_status_value",
                    "warning",
                    f"Status `{workflow_status}` is not in the configured status set.",
                )
            )

        received_date = row.get("received_date")
        completed_date = row.get("completed_date")
        if pd.notna(received_date) and pd.notna(completed_date) and completed_date < received_date:
            issues.append(
                _issue_row(
                    row,
                    "invalid_date_sequence",
                    "error",
                    "Completed date cannot be earlier than received date.",
                )
            )

    duplicate_mask = staged_df.duplicated(
        subset=["source_file_type", "provider_npi", "market_name", "workflow_status"],
        keep=False,
    )
    for _, row in staged_df[duplicate_mask].iterrows():
        issues.append(
            _issue_row(
                row,
                "duplicate_provider_market",
                "warning",
                "Duplicate provider-market-workflow combination detected within the same source type.",
            )
        )

    if reference_data:
        issues.extend(_build_reference_validation_issues(staged_df, status_values, reference_data))

    return pd.DataFrame(issues)


def build_event_validation_issues(event_df: pd.DataFrame, sla_days: int) -> pd.DataFrame:
    if event_df.empty:
        return pd.DataFrame()

    issues: list[dict] = []
    stale_events = event_df[event_df["backlog_age_days"].fillna(0) > sla_days]
    for _, row in stale_events.iterrows():
        issues.append(
            {
                "run_id": int(row["run_id"]),
                "source_file_id": None,
                "stg_record_id": None,
                "issue_type": "stale_backlog_record",
                "severity": "warning",
                "row_identifier": row["provider_npi"],
                "issue_message": (
                    f"Provider `{row['provider_npi']}` backlog age is {int(row['backlog_age_days'])} days, "
                    f"which exceeds the SLA threshold of {sla_days}."
                ),
                "status": "open",
                "created_at": utc_now_naive(),
            }
        )

    return pd.DataFrame(issues)


def _build_reference_validation_issues(
    staged_df: pd.DataFrame,
    status_values: dict[str, list[str]],
    reference_data: dict,
) -> list[dict]:
    issues: list[dict] = []
    markets = reference_data.get("markets", {})
    teams = reference_data.get("teams", {})
    providers = reference_data.get("providers", {})
    open_statuses = set(status_values["open"])
    complete_statuses = set(status_values["complete"])
    market_names = set(markets)
    team_codes = set(teams)

    for _, row in staged_df.iterrows():
        market_name = _clean_text(row.get("market_name"))
        team_code = _clean_text(row.get("team_code"))
        provider_npi = _clean_text(row.get("provider_npi"))

        if market_name and market_name not in market_names:
            issues.append(
                _issue_row(
                    row,
                    "invalid_market_reference",
                    "error",
                    f"Market `{market_name}` is not present in the repo-owned reference data.",
                )
            )

        if team_code and team_code not in team_codes:
            issues.append(
                _issue_row(
                    row,
                    "invalid_team_reference",
                    "error",
                    f"Team `{team_code}` is not present in the repo-owned reference data.",
                )
            )

        if market_name in markets and team_code:
            allowed_teams = set(markets[market_name].get("allowed_teams", []))
            if allowed_teams and team_code not in allowed_teams:
                issues.append(
                    _issue_row(
                        row,
                        "invalid_market_team_mapping",
                        "warning",
                        f"Team `{team_code}` is not an allowed team for market `{market_name}`.",
                    )
                )

        if provider_npi in providers:
            provider_ref = providers[provider_npi]
            mismatches = []
            for field_name in ["provider_name", "market_name", "team_code", "specialty_name"]:
                actual_value = _clean_text(row.get(field_name))
                reference_value = _clean_text(provider_ref.get(field_name))
                if actual_value and reference_value and actual_value != reference_value:
                    mismatches.append(f"{field_name}: `{actual_value}` != `{reference_value}`")
            if mismatches:
                issues.append(
                    _issue_row(
                        row,
                        "provider_reference_conflict",
                        "warning",
                        "Known provider reference mismatch detected: " + "; ".join(mismatches),
                    )
                )

        if row.get("source_file_type") == "onboarding_tracker":
            workflow_status = _clean_text(row.get("workflow_status"))
            owner_name = _clean_text(row.get("owner_name"))
            if workflow_status in open_statuses and not owner_name:
                issues.append(
                    _issue_row(
                        row,
                        "missing_owner_assignment",
                        "warning",
                        "Open onboarding work item is missing an assigned owner.",
                    )
                )

    issues.extend(_build_cross_file_consistency_issues(staged_df, open_statuses, complete_statuses))
    return issues


def _build_cross_file_consistency_issues(
    staged_df: pd.DataFrame,
    open_statuses: set[str],
    complete_statuses: set[str],
) -> list[dict]:
    issues: list[dict] = []
    join_keys = ["provider_npi", "market_name"]

    roster = staged_df[staged_df["source_file_type"] == "provider_roster"].copy()
    onboarding = staged_df[staged_df["source_file_type"] == "onboarding_tracker"].copy()
    audit = staged_df[staged_df["source_file_type"] == "directory_audit"].copy()

    if onboarding.empty or audit.empty:
        return issues

    roster_latest = roster.drop_duplicates(subset=join_keys, keep="last")
    onboarding_latest = onboarding.drop_duplicates(subset=join_keys, keep="last")
    audit_latest = audit.drop_duplicates(subset=join_keys, keep="last")

    onboarding_lookup = {
        (str(row["provider_npi"]), str(row["market_name"])): row
        for _, row in onboarding_latest.iterrows()
        if pd.notna(row.get("provider_npi")) and pd.notna(row.get("market_name"))
    }
    roster_lookup = {
        (str(row["provider_npi"]), str(row["market_name"])): row
        for _, row in roster_latest.iterrows()
        if pd.notna(row.get("provider_npi")) and pd.notna(row.get("market_name"))
    }

    for _, audit_row in audit_latest.iterrows():
        key = (_clean_text(audit_row.get("provider_npi")), _clean_text(audit_row.get("market_name")))
        onboarding_row = onboarding_lookup.get(key)
        audit_status = _clean_text(audit_row.get("workflow_status"))
        audit_result = _clean_text(audit_row.get("audit_result")).lower()

        onboarding_complete = False
        onboarding_status = ""
        if onboarding_row is not None:
            onboarding_status = _clean_text(onboarding_row.get("workflow_status"))
            onboarding_complete = (
                pd.notna(onboarding_row.get("completed_date")) or onboarding_status in complete_statuses
            )

        if audit_status == "published" and not onboarding_complete:
            issues.append(
                _issue_row(
                    audit_row,
                    "audit_onboarding_mismatch",
                    "warning",
                    "Directory audit shows `published` before onboarding is completed.",
                )
            )

        roster_row = roster_lookup.get(key)
        roster_status = _clean_text(roster_row.get("workflow_status")) if roster_row is not None else ""
        if audit_status == "published" and roster_status in open_statuses:
            issues.append(
                _issue_row(
                    audit_row,
                    "unexpected_status_transition",
                    "warning",
                    f"Audit status `published` conflicts with upstream open roster status `{roster_status}`.",
                )
            )

        if audit_result == "pass" and onboarding_row is not None and not onboarding_complete:
            issues.append(
                _issue_row(
                    audit_row,
                    "audit_onboarding_mismatch",
                    "warning",
                    "Passing audit result found while onboarding is still incomplete.",
                )
            )

    return issues
