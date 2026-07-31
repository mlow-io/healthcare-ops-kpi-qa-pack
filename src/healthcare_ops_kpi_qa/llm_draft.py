from __future__ import annotations

import pandas as pd
from pydantic import BaseModel, Field

from .settings import get_app_settings
from .time_utils import utc_now_naive


class KPIHighlight(BaseModel):
    kpi_name: str
    actual_value: float
    prior_period_value: float | None = None
    variance_value: float | None = None
    variance_pct: float | None = None


class ForecastHighlight(BaseModel):
    kpi_name: str
    forecast_value: float
    lower_bound: float | None = None
    upper_bound: float | None = None
    market_name: str | None = None
    team_code: str | None = None


class ValidationSummary(BaseModel):
    issue_type: str
    issue_count: int


class MarketOutlier(BaseModel):
    market_name: str
    qa_issue_rate: float


class CommentaryDraftPayload(BaseModel):
    reporting_period: str
    deterministic_commentary: str
    overall_kpis: list[KPIHighlight]
    forecast_highlights: list[ForecastHighlight]
    validation_counts: list[ValidationSummary]
    top_market_outliers: list[MarketOutlier]


class CommentaryDraftResponse(BaseModel):
    executive_summary: str
    positive_callouts: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)
    review_cautions: list[str] = Field(default_factory=list)

    def to_text(self) -> str:
        lines = [self.executive_summary]
        if self.positive_callouts:
            lines.append("")
            lines.append("Positive callouts:")
            lines.extend(f"- {item}" for item in self.positive_callouts)
        if self.risks:
            lines.append("")
            lines.append("Risks:")
            lines.extend(f"- {item}" for item in self.risks)
        if self.actions:
            lines.append("")
            lines.append("Actions:")
            lines.extend(f"- {item}" for item in self.actions)
        if self.review_cautions:
            lines.append("")
            lines.append("Review cautions:")
            lines.extend(f"- {item}" for item in self.review_cautions)
        return "\n".join(lines)


def build_llm_payload(
    reporting_period: str,
    deterministic_commentary: str,
    overall_kpis: pd.DataFrame,
    market_kpis: pd.DataFrame,
    validation_issues: pd.DataFrame,
    forecasts: pd.DataFrame,
) -> CommentaryDraftPayload:
    overall_rows = []
    for _, row in overall_kpis.sort_values("kpi_name").iterrows():
        overall_rows.append(
            KPIHighlight(
                kpi_name=str(row["kpi_name"]),
                actual_value=float(row["actual_value"]),
                prior_period_value=_float_or_none(row.get("prior_period_value")),
                variance_value=_float_or_none(row.get("variance_value")),
                variance_pct=_float_or_none(row.get("variance_pct")),
            )
        )

    forecast_rows = []
    for _, row in forecasts.sort_values(["kpi_name", "market_name", "team_code"], na_position="first").head(10).iterrows():
        forecast_rows.append(
            ForecastHighlight(
                kpi_name=str(row["kpi_name"]),
                forecast_value=float(row["forecast_value"]),
                lower_bound=_float_or_none(row.get("lower_bound")),
                upper_bound=_float_or_none(row.get("upper_bound")),
                market_name=_string_or_none(row.get("market_name")),
                team_code=_string_or_none(row.get("team_code")),
            )
        )

    validation_counts = []
    if not validation_issues.empty:
        issue_counts = validation_issues["issue_type"].value_counts().sort_values(ascending=False)
        for issue_type, issue_count in issue_counts.items():
            validation_counts.append(ValidationSummary(issue_type=str(issue_type), issue_count=int(issue_count)))

    market_outliers = []
    qa_rows = market_kpis[market_kpis["kpi_name"] == "QA Issue Rate"].sort_values("actual_value", ascending=False).head(5)
    for _, row in qa_rows.iterrows():
        market_outliers.append(
            MarketOutlier(
                market_name=str(row["market_name"]),
                qa_issue_rate=float(row["actual_value"]),
            )
        )

    return CommentaryDraftPayload(
        reporting_period=reporting_period,
        deterministic_commentary=deterministic_commentary,
        overall_kpis=overall_rows,
        forecast_highlights=forecast_rows,
        validation_counts=validation_counts,
        top_market_outliers=market_outliers,
    )


def generate_llm_draft(payload: CommentaryDraftPayload) -> tuple[CommentaryDraftResponse, dict]:
    settings = get_app_settings()
    if settings.llm.provider != "openai":
        raise ValueError(f"Unsupported LLM provider: {settings.llm.provider}")

    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("The `openai` package is not installed.") from exc

    client = OpenAI()
    response = client.responses.parse(
        model=settings.llm.model,
        input=[
            {
                "role": "system",
                "content": (
                    "You draft concise healthcare operations review commentary from structured analytics payloads. "
                    "Do not invent numbers. Keep the draft executive-facing, cautious, and reviewable."
                ),
            },
            {
                "role": "user",
                "content": payload.model_dump_json(indent=2),
            },
        ],
        text_format=CommentaryDraftResponse,
    )
    parsed = response.output_parsed
    if parsed is None:
        raise RuntimeError("The model did not return a structured commentary draft.")

    metadata = {
        "provider": settings.llm.provider,
        "model": settings.llm.model,
        "request_id": getattr(response, "_request_id", None),
        "created_at": utc_now_naive(),
    }
    return parsed, metadata


def build_draft_record(
    run_id: int,
    reporting_period: str,
    payload: CommentaryDraftPayload,
    draft: CommentaryDraftResponse,
    metadata: dict,
) -> dict:
    return {
        "run_id": run_id,
        "reporting_period": reporting_period,
        "draft_type": "monthly_ops_commentary",
        "model_provider": metadata["provider"],
        "model_name": metadata["model"],
        "prompt_payload_json": payload.model_dump_json(indent=2),
        "response_json": draft.model_dump_json(indent=2),
        "draft_text": draft.to_text(),
        "review_status": "pending_review",
        "reviewer_name": None,
        "review_notes": None,
        "created_at": metadata["created_at"],
        "reviewed_at": None,
    }


def _float_or_none(value) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)


def _string_or_none(value) -> str | None:
    if value is None or pd.isna(value):
        return None
    return str(value)
