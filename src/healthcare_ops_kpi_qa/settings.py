from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


@dataclass(frozen=True)
class ProjectPaths:
    root: Path
    config_dir: Path
    docs_dir: Path
    sql_dir: Path
    data_dir: Path
    raw_dir: Path
    processed_dir: Path
    outputs_dir: Path
    database_path: Path


@dataclass(frozen=True)
class DatabaseSettings:
    backend: str
    sqlite_path: Path
    postgres_url: str | None

    @property
    def resolved_url(self) -> str:
        if self.backend == "postgres":
            if not self.postgres_url:
                raise ValueError(
                    "HEALTHCARE_OPS_POSTGRES_URL must be set when HEALTHCARE_OPS_DB_BACKEND=postgres."
                )
            return self.postgres_url
        return f"sqlite+pysqlite:///{self.sqlite_path}"

    @property
    def target_label(self) -> str:
        if self.backend == "postgres":
            if not self.postgres_url:
                return "postgres://<unset>"
            try:
                return make_url(self.postgres_url).render_as_string(hide_password=True)
            except ArgumentError:
                return "postgres://<configured>"
        return f"sqlite:///{self.sqlite_path.name}"


@dataclass(frozen=True)
class LLMSettings:
    enabled: bool
    provider: str
    model: str
    reviewer_default: str


@dataclass(frozen=True)
class AppSettings:
    paths: ProjectPaths
    database: DatabaseSettings
    llm: LLMSettings


def get_project_paths() -> ProjectPaths:
    root = Path(__file__).resolve().parents[2]
    data_dir = Path(os.getenv("HEALTHCARE_OPS_DATA_DIR", str(root / "data"))).expanduser()
    outputs_dir = Path(os.getenv("HEALTHCARE_OPS_OUTPUTS_DIR", str(root / "outputs"))).expanduser()
    return ProjectPaths(
        root=root,
        config_dir=root / "config",
        docs_dir=root / "docs",
        sql_dir=root / "sql",
        data_dir=data_dir,
        raw_dir=data_dir / "raw",
        processed_dir=data_dir / "processed",
        outputs_dir=outputs_dir,
        database_path=data_dir / "processed" / "healthcare_ops_kpi_qa.sqlite3",
    )


def get_app_settings() -> AppSettings:
    paths = get_project_paths()
    backend = os.getenv("HEALTHCARE_OPS_DB_BACKEND", "sqlite").strip().lower()
    if backend not in {"sqlite", "postgres"}:
        raise ValueError("HEALTHCARE_OPS_DB_BACKEND must be `sqlite` or `postgres`.")

    sqlite_path = Path(
        os.getenv("HEALTHCARE_OPS_SQLITE_PATH", str(paths.database_path))
    ).expanduser()
    postgres_url = os.getenv("HEALTHCARE_OPS_POSTGRES_URL")

    return AppSettings(
        paths=paths,
        database=DatabaseSettings(
            backend=backend,
            sqlite_path=sqlite_path,
            postgres_url=postgres_url,
        ),
        llm=LLMSettings(
            enabled=os.getenv("HEALTHCARE_OPS_ENABLE_LLM_DRAFT", "false").strip().lower() in {"1", "true", "yes"},
            provider=os.getenv("HEALTHCARE_OPS_LLM_PROVIDER", "openai").strip().lower(),
            model=os.getenv("HEALTHCARE_OPS_OPENAI_MODEL", "gpt-4o-mini").strip(),
            reviewer_default=os.getenv("HEALTHCARE_OPS_DEFAULT_REVIEWER", "human-review-required").strip(),
        ),
    )
