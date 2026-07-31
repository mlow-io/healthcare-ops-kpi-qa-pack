from __future__ import annotations

import json
from datetime import UTC, date, datetime


def utc_now_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def json_default(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def json_dumps(value) -> str:
    return json.dumps(value, indent=2, default=json_default)
