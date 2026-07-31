from __future__ import annotations

import pandas as pd

from .settings import get_project_paths

DEMO_PERIODS = ["2026-02", "2026-03", "2026-04"]


def _make_valid_npi(first_nine_digits: str) -> str:
    base = f"80840{first_nine_digits}"
    total = 0
    double_digit = True
    for char in reversed(base):
        digit = int(char)
        if double_digit:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
        double_digit = not double_digit
    check_digit = (10 - (total % 10)) % 10
    return f"{first_nine_digits}{check_digit}"


def seed_sample_inputs(period: str) -> list[str]:
    output_dir = get_project_paths().raw_dir / period
    output_dir.mkdir(parents=True, exist_ok=True)

    _year_str, month_str = period.split("-")
    month = int(month_str)

    allied_status = {2: "in_review", 3: "ready_for_directory", 4: "ready_for_directory"}.get(month, "in_review")
    allied_completion = {2: "", 3: f"{period}-07", 4: f"{period}-06"}.get(month, "")
    child_status = {2: "pending", 3: "in_review", 4: "in_review"}.get(month, "in_review")
    chatt_status = {2: "pending", 3: "ready_for_directory", 4: "mystery_status"}.get(month, "in_review")
    chatt_audit_result = {2: "fail", 3: "pass", 4: "fail"}.get(month, "pass")
    chatt_issue_type = {2: "bad_address", 3: "", 4: "bad_address"}.get(month, "")
    child_intake = {2: "2026-01-03", 3: "2026-02-05", 4: "2026-03-01"}.get(month, f"{period}-01")
    allied_npi = _make_valid_npi("123456789")
    child_npi = _make_valid_npi("123456780")
    chatt_invalid_checksum_npi = "1234567890"

    roster = pd.DataFrame(
        [
            {
                "Provider Name": "Allied Cardiology Group",
                "NPI": allied_npi,
                "Specialty": "Cardiology",
                "Market": "Nashville",
                "Team": "TEAM_A",
                "Roster Status": allied_status,
                "Effective Date": f"{period}-05",
                "Phone": "615-555-0101",
                "Address": "100 Market St",
            },
            {
                "Provider Name": "Children's Primary Partners",
                "NPI": child_npi,
                "Specialty": "Pediatrics",
                "Market": "Nashville",
                "Team": "TEAM_A",
                "Roster Status": child_status,
                "Effective Date": f"{period}-08",
                "Phone": "615-555-0102",
                "Address": "200 Oak St",
            },
            {
                "Provider Name": "Children's Primary Partners",
                "NPI": child_npi,
                "Specialty": "Pediatrics",
                "Market": "Nashville",
                "Team": "TEAM_A",
                "Roster Status": child_status,
                "Effective Date": f"{period}-08",
                "Phone": "615-555-0102",
                "Address": "200 Oak St",
            },
            {
                "Provider Name": "Volunteer Orthopedics",
                "NPI": "12345",
                "Specialty": "Orthopedics",
                "Market": "Knoxville",
                "Team": "TEAM_B",
                "Roster Status": "pending",
                "Effective Date": f"{period}-12",
                "Phone": "865-555-0110",
                "Address": "10 Summit Rd",
            },
            {
                "Provider Name": "Memphis Oncology Center",
                "NPI": "",
                "Specialty": "Oncology",
                "Market": "Memphis",
                "Team": "TEAM_B",
                "Roster Status": "onboarding",
                "Effective Date": f"{period}-15",
                "Phone": "901-555-0111",
                "Address": "50 River Ave",
            },
            {
                "Provider Name": "Chattanooga Family Care",
                "NPI": chatt_invalid_checksum_npi,
                "Specialty": "Family Medicine",
                "Market": "Chattanooga",
                "Team": "TEAM_C",
                "Roster Status": chatt_status,
                "Effective Date": f"{period}-18",
                "Phone": "423-555-0112",
                "Address": "75 Walnut St",
            },
        ]
    )

    onboarding = pd.DataFrame(
        [
            {
                "NPI": allied_npi,
                "Market": "Nashville",
                "Team": "TEAM_A",
                "Owner": "Alex Carter",
                "Intake Date": f"{period}-01",
                "Completion Date": allied_completion,
                "Onboarding Stage": "completed" if allied_completion else allied_status,
            },
            {
                "NPI": child_npi,
                "Market": "Nashville",
                "Team": "TEAM_A",
                "Owner": "Alex Carter",
                "Intake Date": child_intake,
                "Completion Date": "",
                "Onboarding Stage": child_status,
            },
            {
                "NPI": "12345",
                "Market": "Knoxville",
                "Team": "TEAM_B",
                "Owner": "Jordan Lee",
                "Intake Date": f"{period}-10",
                "Completion Date": f"{period}-08",
                "Onboarding Stage": "pending",
            },
            {
                "NPI": chatt_invalid_checksum_npi,
                "Market": "Chattanooga",
                "Team": "TEAM_C",
                "Owner": "" if month == 4 else "Riley Morgan",
                "Intake Date": f"{period}-16",
                "Completion Date": f"{period}-20" if month == 3 else "",
                "Onboarding Stage": "completed" if month == 3 else chatt_status,
            },
        ]
    )

    directory_audit = pd.DataFrame(
        [
            {
                "NPI": allied_npi,
                "Market": "Nashville",
                "Audit Date": f"{period}-20",
                "Audit Result": "pass" if month >= 3 else "fail",
                "Issue Type": "",
                "Directory Status": "published",
            },
            {
                "NPI": child_npi,
                "Market": "Nashville",
                "Audit Date": f"{period}-20",
                "Audit Result": "fail",
                "Issue Type": "missing_phone",
                "Directory Status": "in_review",
            },
            {
                "NPI": chatt_invalid_checksum_npi,
                "Market": "Chattanooga",
                "Audit Date": f"{period}-21",
                "Audit Result": "pass" if month == 4 else chatt_audit_result,
                "Issue Type": "" if month == 4 else chatt_issue_type,
                "Directory Status": "published" if month in {3, 4} else "in_review",
            },
        ]
    )

    roster_path = output_dir / f"provider_roster_{period.replace('-', '_')}.csv"
    onboarding_path = output_dir / f"onboarding_tracker_{period.replace('-', '_')}.xlsx"
    audit_path = output_dir / f"directory_audit_{period.replace('-', '_')}.csv"

    roster.to_csv(roster_path, index=False)
    onboarding.to_excel(onboarding_path, index=False)
    directory_audit.to_csv(audit_path, index=False)

    return [str(roster_path), str(onboarding_path), str(audit_path)]


def seed_demo_periods(periods: list[str] | None = None) -> dict[str, list[str]]:
    target_periods = periods or DEMO_PERIODS
    return {period: seed_sample_inputs(period) for period in target_periods}
