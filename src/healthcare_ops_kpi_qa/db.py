from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime
from functools import lru_cache

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine

from .settings import get_app_settings


@lru_cache(maxsize=2)
def get_engine() -> Engine:
    settings = get_app_settings()
    if settings.database.backend == "sqlite":
        _register_sqlite_adapters()
        settings.database.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(settings.database.resolved_url, future=True)


def _register_sqlite_adapters() -> None:
    sqlite3.register_adapter(date, lambda value: value.isoformat())
    sqlite3.register_adapter(datetime, lambda value: value.isoformat(sep=" "))


@contextmanager
def get_connection() -> Iterator[Connection]:
    engine = get_engine()
    with engine.begin() as connection:
        if get_app_settings().database.backend == "sqlite":
            connection.exec_driver_sql("PRAGMA foreign_keys = ON")
        yield connection


def execute_sql(connection: Connection, sql: str, params: dict | None = None):
    return connection.execute(text(sql), params or {})


def fetch_all(connection: Connection, sql: str, params: dict | None = None) -> list[dict]:
    return [dict(row) for row in execute_sql(connection, sql, params).mappings().all()]


def fetch_one(connection: Connection, sql: str, params: dict | None = None) -> dict | None:
    row = execute_sql(connection, sql, params).mappings().first()
    return dict(row) if row is not None else None


def read_sql_frame(connection: Connection, sql: str, params: dict | None = None) -> pd.DataFrame:
    return pd.read_sql_query(text(sql), connection, params=params or {})


def initialize_database(connection: Connection) -> None:
    settings = get_app_settings()
    paths = settings.paths
    backend = settings.database.backend

    ddl_path = paths.sql_dir / ("ddl_postgres.sql" if backend == "postgres" else "ddl.sql")
    marts_path = paths.sql_dir / ("marts_postgres.sql" if backend == "postgres" else "marts.sql")

    should_run_ddl = True
    if backend == "postgres":
        existing = connection.exec_driver_sql("select to_regclass('public.etl_run')").scalar()
        should_run_ddl = existing is None

    if should_run_ddl:
        for statement in _split_sql_statements(ddl_path.read_text()):
            connection.exec_driver_sql(statement)
    for statement in _split_sql_statements(marts_path.read_text()):
        connection.exec_driver_sql(statement)


def _split_sql_statements(script: str) -> list[str]:
    statements: list[str] = []
    current: list[str] = []
    for line in script.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        current.append(line)
        if stripped.endswith(";"):
            statement = "\n".join(current).strip().rstrip(";")
            if statement:
                statements.append(statement)
            current = []
    if current:
        statement = "\n".join(current).strip().rstrip(";")
        if statement:
            statements.append(statement)
    return statements
