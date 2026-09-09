"""
Audit logging — Technical Architecture §3.9: "Logs every query — who asked
what, and when — for auditability." Appends JSON-lines to a flat file so it
needs no extra infra for the demo; swap _append() for a DB write later.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import settings

_LOG_PATH = Path(settings.audit_log_path)


def _append(entry: dict) -> None:
    with _LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def log_request(user: str, method: str, path: str, status_code: int) -> None:
    _append(
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "user": user,
            "method": method,
            "path": path,
            "status_code": status_code,
        }
    )


def log_system_event(event: str, detail: str) -> None:
    _append(
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "user": "system",
            "event": event,
            "detail": detail,
        }
    )


def read_recent(limit: int = 50) -> list[dict]:
    if not _LOG_PATH.exists():
        return []
    lines = _LOG_PATH.read_text(encoding="utf-8").splitlines()
    entries = [json.loads(line) for line in lines[-limit:]]
    entries.reverse()
    return entries
