from __future__ import annotations

import json

import typer

from .ingest import missing_required_file_types, summarize_discovery
from .kpis import list_kpi_codes
from .pipeline import (
    generate_llm_draft_for_run,
    latest_successful_run_id_for_period,
    review_llm_draft,
    run_refresh,
)
from .sample_data import DEMO_PERIODS, seed_demo_periods, seed_sample_inputs
from .settings import get_app_settings, get_project_paths
from .transform import CANONICAL_DERIVED_FIELDS
from .validate import V1_RULES

app = typer.Typer(help="CLI for the Healthcare Operations KPI & QA Pack.")


@app.command()
def show_config() -> None:
    """Print resolved project paths and core runtime metadata."""
    paths = get_project_paths()
    settings = get_app_settings()
    payload = {
        "root": str(paths.root),
        "config_dir": str(paths.config_dir),
        "sql_dir": str(paths.sql_dir),
        "raw_dir": str(paths.raw_dir),
        "database_backend": settings.database.backend,
        "database_target": settings.database.target_label,
        "database_path": str(paths.database_path),
        "outputs_dir": str(paths.outputs_dir),
        "llm_enabled": settings.llm.enabled,
        "llm_provider": settings.llm.provider,
        "llm_model": settings.llm.model,
        "kpis": list_kpi_codes(),
        "validation_rules": V1_RULES,
    }
    typer.echo(json.dumps(payload, indent=2))


@app.command()
def plan(period: str = typer.Option(..., help="Reporting period in YYYY-MM format.")) -> None:
    """Show the expected files and outputs for a reporting period."""
    typer.echo(f"Planning refresh for {period}")
    for line in summarize_discovery(period):
        typer.echo(f"- {line}")

    missing = missing_required_file_types(period)
    if missing:
        typer.echo("")
        typer.echo("Missing required file types:")
        for item in missing:
            typer.echo(f"- {item}")

    typer.echo("")
    typer.echo("Derived fields:")
    for field_name in CANONICAL_DERIVED_FIELDS:
        typer.echo(f"- {field_name}")


@app.command("seed-sample-data")
def seed_sample_data(period: str = typer.Option(..., help="Reporting period in YYYY-MM format.")) -> None:
    """Create synthetic input files for a sample monthly run."""
    created_paths = seed_sample_inputs(period)
    typer.echo(f"Created sample files for {period}:")
    for path in created_paths:
        typer.echo(f"- {path}")


@app.command("seed-demo-data")
def seed_demo_data() -> None:
    """Create a three-period demo dataset for trend and variance analysis."""
    seeded = seed_demo_periods()
    for period, created_paths in seeded.items():
        typer.echo(f"Created sample files for {period}:")
        for path in created_paths:
            typer.echo(f"- {path}")


@app.command("refresh-demo-data")
def refresh_demo_data() -> None:
    """Refresh the demo periods sequentially so prior-period comparisons are stable."""
    results = []
    for period in DEMO_PERIODS:
        results.append(run_refresh(period))
    typer.echo(json.dumps(results, indent=2))


@app.command()
def refresh(
    period: str = typer.Option(..., help="Reporting period in YYYY-MM format."),
    llm_draft: bool = typer.Option(False, "--llm-draft/--no-llm-draft", help="Generate an optional structured LLM commentary draft after refresh."),
) -> None:
    """Run the end-to-end refresh for a reporting period."""
    result = run_refresh(period, include_llm_draft=llm_draft)
    typer.echo(json.dumps(result, indent=2))


@app.command("generate-llm-draft")
def generate_llm_draft_command(
    period: str = typer.Option(..., help="Reporting period in YYYY-MM format."),
    run_id: int | None = typer.Option(None, help="Optional run_id override. Defaults to latest successful run for the period."),
) -> None:
    """Generate an optional structured LLM commentary draft for a successful run."""
    target_run_id = run_id if run_id is not None else latest_successful_run_id_for_period(period)
    if target_run_id is None:
        raise typer.BadParameter(f"No successful run found for period {period}.")
    result = generate_llm_draft_for_run(target_run_id)
    typer.echo(json.dumps(result, indent=2))


@app.command("review-llm-draft")
def review_llm_draft_command(
    draft_id: int = typer.Option(..., help="Draft identifier to review."),
    reviewer: str = typer.Option(..., help="Reviewer name."),
    status: str = typer.Option(..., help="approved or rejected."),
    notes: str | None = typer.Option(None, help="Optional review notes."),
) -> None:
    """Persist review metadata for an LLM commentary draft."""
    result = review_llm_draft(draft_id, reviewer, status, notes)
    typer.echo(json.dumps(result, indent=2))
