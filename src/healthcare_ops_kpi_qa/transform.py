from __future__ import annotations

from calendar import monthrange
from datetime import date

import pandas as pd

CANONICAL_DERIVED_FIELDS = [
    "completion_flag",
    "turnaround_days",
    "backlog_flag",
    "backlog_over_sla_flag",
    "qa_issue_flag",
    "required_field_complete_flag",
]


def transform_notes() -> list[str]:
    return [
        "Union normalized rows from all sources into one staged contract.",
        "Derive event-level flags before KPI aggregation.",
        "Keep source lineage on every staged row for tie-outs.",
    ]


def build_event_fact(
    staged_df: pd.DataFrame,
    status_values: dict[str, list[str]],
    period: str,
) -> pd.DataFrame:
    if staged_df.empty:
        return pd.DataFrame()

    roster = staged_df[staged_df["source_file_type"] == "provider_roster"].copy()
    onboarding = staged_df[staged_df["source_file_type"] == "onboarding_tracker"].copy()
    audit = staged_df[staged_df["source_file_type"] == "directory_audit"].copy()

    if roster.empty:
        return pd.DataFrame()

    join_keys = ["provider_npi", "market_name"]
    roster = roster[
        [
            "run_id",
            "provider_name",
            "provider_npi",
            "specialty_name",
            "market_name",
            "team_code",
            "workflow_status",
            "received_date",
            "completed_date",
            "effective_date",
            "owner_name",
        ]
    ].copy()
    roster = roster.drop_duplicates(subset=join_keys, keep="last")
    onboarding = (
        onboarding.sort_values(["provider_npi", "market_name", "received_date", "completed_date"])
        .drop_duplicates(subset=join_keys, keep="last")
        .rename(
            columns={
                "team_code": "onboarding_team_code",
                "workflow_status": "onboarding_workflow_status",
                "received_date": "onboarding_received_date",
                "completed_date": "onboarding_completed_date",
                "owner_name": "onboarding_owner_name",
            }
        )
    )
    audit = (
        audit.sort_values(["provider_npi", "market_name", "audit_date"])
        .drop_duplicates(subset=join_keys, keep="last")
        .rename(
            columns={
                "audit_result": "latest_audit_result",
                "audit_issue_type": "latest_audit_issue_type",
                "workflow_status": "audit_workflow_status",
                "audit_date": "latest_audit_date",
            }
        )
    )

    events = roster.merge(
        onboarding[
            [
                "provider_npi",
                "market_name",
                "onboarding_team_code",
                "onboarding_workflow_status",
                "onboarding_received_date",
                "onboarding_completed_date",
                "onboarding_owner_name",
            ]
        ],
        on=join_keys,
        how="left",
    ).merge(
        audit[
            [
                "provider_npi",
                "market_name",
                "latest_audit_result",
                "latest_audit_issue_type",
                "latest_audit_date",
                "audit_workflow_status",
            ]
        ],
        on=join_keys,
        how="left",
    )

    events["team_code"] = events["onboarding_team_code"].fillna(events["team_code"])
    events["event_status"] = (
        events["onboarding_workflow_status"]
        .fillna(events["workflow_status"])
        .fillna(events["audit_workflow_status"])
    )
    events["received_date"] = events["onboarding_received_date"].fillna(events["received_date"])
    events["completed_date"] = events["onboarding_completed_date"].fillna(events["completed_date"])
    events["owner_name"] = events["onboarding_owner_name"].fillna(events["owner_name"])

    complete_statuses = set(status_values["complete"])
    open_statuses = set(status_values["open"])
    events["completion_flag"] = events["event_status"].isin(complete_statuses) | (
        events["completed_date"].notna() & ~events["event_status"].isin(open_statuses)
    )
    events["backlog_flag"] = ~events["completion_flag"]
    turnaround_days = (
        pd.to_datetime(events["completed_date"]) - pd.to_datetime(events["received_date"])
    ).dt.days
    events["turnaround_days"] = turnaround_days.where(turnaround_days >= 0)

    period_end = _period_end(period)
    received_ts = pd.to_datetime(events["received_date"])
    events["backlog_age_days"] = (pd.Timestamp(period_end) - received_ts).dt.days
    events.loc[~events["backlog_flag"], "backlog_age_days"] = pd.NA
    events["backlog_over_sla_flag"] = events["backlog_flag"] & (events["backlog_age_days"].fillna(0) > 30)

    audit_result = events["latest_audit_result"].fillna("").astype("string").str.lower()
    events["qa_issue_flag"] = (
        audit_result.isin(["fail", "failed", "issue", "error"])
        | events["latest_audit_issue_type"].notna()
    )
    events["required_field_complete_flag"] = (
        events["provider_name"].notna()
        & events["provider_npi"].notna()
        & events["market_name"].notna()
        & events["event_status"].notna()
    )

    event_date = (
        pd.to_datetime(events["completed_date"])
        .fillna(pd.to_datetime(events["effective_date"]))
        .fillna(pd.to_datetime(events["received_date"]))
        .fillna(pd.to_datetime(events["latest_audit_date"]))
    )
    events["event_date"] = event_date.dt.date
    events["event_type"] = "provider_work_item"
    events["source_system"] = "provider_ops_v1"
    events["volume"] = 1

    return events[
        [
            "run_id",
            "event_date",
            "market_name",
            "team_code",
            "provider_npi",
            "provider_name",
            "specialty_name",
            "event_type",
            "event_status",
            "completion_flag",
            "turnaround_days",
            "backlog_flag",
            "backlog_over_sla_flag",
            "qa_issue_flag",
            "required_field_complete_flag",
            "backlog_age_days",
            "source_system",
        ]
    ].copy()


def _period_end(period: str) -> date:
    year_str, month_str = period.split("-")
    year = int(year_str)
    month = int(month_str)
    return date(year, month, monthrange(year, month)[1])
