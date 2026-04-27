from datetime import datetime, timezone
from typing import Any, Optional


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ok(data: Any) -> dict:
    return {"status": "ok", "updated_at": _now(), "data": data, "error": None}


def err(code: str, message: str) -> dict:
    return {
        "status": "error",
        "updated_at": _now(),
        "data": None,
        "error": {"code": code, "message": message},
    }
