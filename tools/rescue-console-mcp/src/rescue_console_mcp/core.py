from __future__ import annotations

from collections import Counter
from typing import Any

from .config import Settings
from .rescue_api import RescueApi


class RescueConsoleCore:
    def __init__(
        self,
        settings: Settings,
        *,
        api: RescueApi | None = None,
    ) -> None:
        self.settings = settings
        self.api = api or RescueApi(settings.connector_root, settings.env_file)

    def status(self) -> dict[str, Any]:
        return {
            "ok": True,
            "api": self.api.configuration(),
            "accessMode": "read_only",
            "mutationToolsExposed": False,
        }

    def list_sessions(self) -> dict[str, Any]:
        try:
            api_result = self.api.list_sessions()
            return {"ok": True, "api": {"available": True, **api_result}}
        except Exception as exc:
            return {
                "ok": False,
                "api": {"available": False, "sessions": [], "error": _safe_error(exc)},
            }

    def read_chat(self, session_id: str = "") -> dict[str, Any]:
        clean_id = str(session_id or "").strip()
        if not clean_id:
            return {"ok": False, "api": {"available": False, "error": "session_id is required"}}
        try:
            return {"ok": True, "api": {"available": True, **self.api.read_chat(clean_id)}}
        except Exception as exc:
            return {"ok": False, "api": {"available": False, "error": _safe_error(exc)}}

    def read_performance(self) -> dict[str, Any]:
        """Return bounded session counts derived from the read-only sessions API."""

        try:
            payload = self.api.list_sessions()
        except Exception as exc:
            return {"ok": False, "available": False, "error": _safe_error(exc)}
        sessions = [item for item in payload.get("sessions", []) if isinstance(item, dict)]
        by_status = Counter(str(item.get("status") or "unknown")[:100] for item in sessions)
        by_technician = Counter(str(item.get("technician") or "unassigned")[:200] for item in sessions)
        return {
            "ok": True,
            "available": True,
            "sessionCount": len(sessions),
            "byStatus": dict(by_status.most_common(50)),
            "byTechnician": dict(by_technician.most_common(50)),
            "nodeRef": payload.get("nodeRef"),
        }


def _safe_error(exc: Exception) -> str:
    text = str(exc or exc.__class__.__name__)
    for marker in ("password", "passwd", "pwd", "authcode", "token"):
        if marker in text.casefold():
            return f"{exc.__class__.__name__}: Rescue authentication or configuration failed"
    return f"{exc.__class__.__name__}: {text[:500]}"
