"""Read-only collection of Zoom support-chat monitoring data.

The collector intentionally has no Zoom mutation primitive.  It uses the OAuth
and environment helpers from :mod:`zoom_kb_sync`, isolates permission failures
by product surface, and stores only a bounded, sanitized local snapshot.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from .memory import redact_secrets
from .zoom_kb_sync import csv_ids, get_zoom_token, load_env_files, zoom_get


DEFAULT_CACHE_PATH = Path("data/command_center/zoom_chat_monitor.json")
TEAM_CHAT_MEMBER_IDS_ENV = "ZOOM_CHAT_MONITOR_TEAM_CHAT_MEMBER_IDS"
TEAM_CHAT_TARGETS_ENV = "ZOOM_CHAT_MONITOR_TEAM_CHAT_TARGETS"
# Backward-compatible aliases for early local configurations.
TEAM_CHAT_USER_IDS_ENV = "ZOOM_CHAT_MONITOR_TEAM_CHAT_USER_IDS"
TEAM_CHAT_SESSION_IDS_ENV = "ZOOM_CHAT_MONITOR_TEAM_CHAT_SESSION_IDS"
LOOKBACK_HOURS_ENV = "ZOOM_CHAT_MONITOR_LOOKBACK_HOURS"
MAX_PAGES = 20
MAX_RECORDS = 1_000
MAX_LIST_ITEMS = 250
MAX_TEXT_CHARS = 2_000

JsonGetter = Callable[[str, str, dict[str, str] | None], dict[str, Any]]


def main() -> None:
    args = parse_args()
    load_env_files([Path("config/ops.env"), Path(".env")])
    try:
        token = get_zoom_token()
        configured_hours = args.since_hours
        if configured_hours is None:
            configured_hours = _safe_int(os.getenv(LOOKBACK_HOURS_ENV, "24"), default=24)
        snapshot = collect_zoom_chat_snapshot(token, since_hours=configured_hours)
        write_snapshot_atomic(Path(args.cache), snapshot)
    except Exception as exc:
        raise SystemExit(f"Zoom chat monitor failed: {safe_error(exc)}") from exc
    # Deliberately emit counts and statuses only. Transcripts, messages, member
    # identifiers, API errors, and credentials stay out of terminal output.
    print(json.dumps(snapshot_summary(snapshot, Path(args.cache)), indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Cache a bounded, read-only Zoom support-chat monitoring snapshot."
    )
    parser.add_argument("--cache", "--output", dest="cache", default=str(DEFAULT_CACHE_PATH))
    parser.add_argument(
        "--since-hours",
        type=int,
        default=None,
        help="Completed ZVA lookback (1-720 hours; default 24).",
    )
    return parser.parse_args()


def collect_zoom_chat_snapshot(
    token: str,
    *,
    since_hours: int = 24,
    now: datetime | None = None,
    environ: Mapping[str, str] | None = None,
    getter: JsonGetter | None = None,
) -> dict[str, Any]:
    """Collect independent read-only snapshots for each supported Zoom surface.

    Team Chat is disabled unless at least one user or report-session identifier
    is explicitly allowlisted. A 401/403 or scope-like failure on one surface is
    represented in that surface's status and does not discard successful data
    from the other surfaces.
    """

    resolved_now = _as_utc(now or datetime.now(timezone.utc))
    hours = max(1, min(int(since_hours), 24 * 30))
    start = resolved_now - timedelta(hours=hours)
    api_get = getter or _default_getter
    env = environ if environ is not None else os.environ

    zva = _collect_zva(token, start=start, end=resolved_now, getter=api_get)
    contact_center = _collect_contact_center(token, getter=api_get)
    team_chat = _collect_team_chat(
        token,
        start=start,
        end=resolved_now,
        user_ids=csv_ids(
            " ".join(
                (
                    str(env.get(TEAM_CHAT_MEMBER_IDS_ENV, "")),
                    str(env.get(TEAM_CHAT_USER_IDS_ENV, "")),
                )
            )
        ),
        session_ids=csv_ids(
            " ".join(
                (
                    str(env.get(TEAM_CHAT_TARGETS_ENV, "")),
                    str(env.get(TEAM_CHAT_SESSION_IDS_ENV, "")),
                )
            )
        ),
        getter=api_get,
    )
    return sanitize_payload(
        {
            "schema_version": 1,
            "collected_at": _iso(resolved_now),
            "window": {"from": _iso(start), "to": _iso(resolved_now)},
            "read_only": True,
            "surfaces": {
                "zva": zva,
                "contact_center": contact_center,
                "team_chat": team_chat,
            },
        }
    )


def _collect_zva(
    token: str,
    *,
    start: datetime,
    end: datetime,
    getter: JsonGetter,
) -> dict[str, Any]:
    base_params = {
        "from": _iso(start),
        "to": _iso(end),
        "timezone": "UTC",
        "page_size": "100",
    }
    result: dict[str, Any] = {
        "status": "ok",
        "engagements_status": "ok",
        "transcripts_status": "ok",
        "engagements": [],
        "transcripts": [],
        "errors": [],
    }
    try:
        rows = _fetch_pages(
            token,
            "/virtual_agent/report/engagements",
            base_params,
            row_keys=("engagements",),
            getter=getter,
        )
        result["engagements"] = [row for row in rows if _is_completed_zva(row)]
    except Exception as exc:
        result["engagements_status"] = _error_status(exc)
        result["errors"].append({"operation": "engagements", "error": safe_error(exc)})

    try:
        result["transcripts"] = _fetch_pages(
            token,
            "/virtual_agent/report/transcripts",
            base_params,
            row_keys=("transcripts",),
            getter=getter,
        )
    except Exception as exc:
        result["transcripts_status"] = _error_status(exc)
        result["errors"].append({"operation": "transcripts", "error": safe_error(exc)})

    result["status"] = _combined_status(
        str(result["engagements_status"]), str(result["transcripts_status"])
    )
    return result


def _collect_contact_center(
    token: str,
    *,
    getter: JsonGetter,
) -> dict[str, Any]:
    try:
        rows = _fetch_pages(
            token,
            "/contact_center/open_engagements",
            {"page_size": "100"},
            row_keys=("engagements",),
            getter=getter,
        )
        messaging = [row for row in rows if _is_messaging_engagement(row)]
        return {"status": "ok", "open_messaging_engagements": messaging, "errors": []}
    except Exception as exc:
        return {
            "status": _error_status(exc),
            "open_messaging_engagements": [],
            "errors": [{"operation": "open_engagements", "error": safe_error(exc)}],
        }


def _collect_team_chat(
    token: str,
    *,
    start: datetime,
    end: datetime,
    user_ids: list[str],
    session_ids: list[str],
    getter: JsonGetter,
) -> dict[str, Any]:
    # This opt-in is a privacy boundary: never enumerate account-wide chat
    # reports to discover identifiers.
    if not user_ids and not session_ids:
        return {
            "status": "disabled",
            "reason": (
                f"Set {TEAM_CHAT_MEMBER_IDS_ENV} or {TEAM_CHAT_TARGETS_ENV} "
                "to an explicit allowlist."
            ),
            "users": [],
            "sessions": [],
            "errors": [],
        }

    result: dict[str, Any] = {"status": "ok", "users": [], "sessions": [], "errors": []}
    user_params = {
        "from": _iso(start),
        "to": _iso(end),
        "page_size": "100",
    }
    report_params = {
        "from": start.date().isoformat(),
        "to": end.date().isoformat(),
        "page_size": "100",
    }

    for user_id in _unique(user_ids)[:MAX_RECORDS]:
        try:
            sessions = _fetch_pages(
                token,
                f"/chat/users/{urllib.parse.quote(user_id, safe='')}/sessions",
                user_params,
                row_keys=("sessions",),
                getter=getter,
            )
            result["users"].append({"user_id": user_id, "sessions": sessions})
        except Exception as exc:
            result["errors"].append(
                {"operation": "user_sessions", "subject": _safe_identifier(user_id), "error": safe_error(exc)}
            )

    for session_id in _unique(session_ids)[:MAX_RECORDS]:
        try:
            payload = getter(
                token,
                f"/report/chat/sessions/{urllib.parse.quote(session_id, safe='')}",
                report_params,
            )
            result["sessions"].append(
                {
                    "session_id": session_id,
                    "messages": _rows(payload, ("messages",)),
                    "deleted_messages": _rows(payload, ("deleted_messages",)),
                }
            )
        except Exception as exc:
            result["errors"].append(
                {"operation": "session_messages", "subject": _safe_identifier(session_id), "error": safe_error(exc)}
            )

    if result["errors"]:
        statuses = [_error_status(RuntimeError(str(row.get("error") or ""))) for row in result["errors"]]
        result["status"] = "scope_error" if all(status == "scope_error" for status in statuses) else "partial"
        if result["users"] or result["sessions"]:
            result["status"] = "partial"
    return result


def _fetch_pages(
    token: str,
    path: str,
    params: dict[str, str],
    *,
    row_keys: tuple[str, ...],
    getter: JsonGetter,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    next_page_token = ""
    for _ in range(MAX_PAGES):
        query = dict(params)
        if next_page_token:
            query["next_page_token"] = next_page_token
        payload = getter(token, path, query)
        records.extend(_rows(payload, row_keys))
        if len(records) >= MAX_RECORDS:
            return records[:MAX_RECORDS]
        next_page_token = str(payload.get("next_page_token") or payload.get("nextPageToken") or "").strip()
        if not next_page_token:
            break
    return records[:MAX_RECORDS]


def _default_getter(token: str, path: str, params: dict[str, str] | None) -> dict[str, Any]:
    # zoom_get only issues GET requests and centralizes the existing base URL,
    # bearer-token handling, timeout, and Zoom HTTP error normalization.
    return zoom_get(token, path, params)


def _rows(payload: Mapping[str, Any], keys: tuple[str, ...]) -> list[dict[str, Any]]:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            return [dict(item) for item in value if isinstance(item, Mapping)]
    return []


def _is_completed_zva(row: Mapping[str, Any]) -> bool:
    if row.get("end_time") or row.get("endTime"):
        return True
    status = str(row.get("status") or row.get("state") or "").strip().casefold()
    return status in {"closed", "complete", "completed", "ended", "resolved"}


def _is_messaging_engagement(row: Mapping[str, Any]) -> bool:
    channels = row.get("channels")
    if not isinstance(channels, list):
        return False
    for item in channels:
        value = item.get("channel") if isinstance(item, Mapping) else item
        if str(value or "").strip().casefold() == "messaging":
            return True
    return False


def sanitize_payload(value: Any, *, key: str = "") -> Any:
    """Recursively redact secrets, strip signed URL queries, and bound payloads."""

    lowered = key.casefold()
    if any(
        marker in lowered
        for marker in (
            "access_token",
            "refresh_token",
            "client_secret",
            "authorization",
            "password",
            "api_key",
            "security_key",
        )
    ):
        return "[redacted]"
    if isinstance(value, Mapping):
        return {str(child_key)[:120]: sanitize_payload(child, key=str(child_key)) for child_key, child in value.items()}
    if isinstance(value, list):
        return [sanitize_payload(item, key=key) for item in value[:MAX_LIST_ITEMS]]
    if isinstance(value, str):
        text = redact_secrets(value)
        text = re.sub(r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]+=*", "Bearer [redacted]", text)
        text = re.sub(
            r"(?i)\b(access_token|refresh_token|client_secret|authorization|password|api[_ -]?key|security[_ -]?key)\s*[:=]\s*[^\s,;&]+",
            lambda match: f"{match.group(1)}=[redacted]",
            text,
        )
        if lowered.endswith("url") or lowered.endswith("_url"):
            text = _strip_url_query(text)
        return text[:MAX_TEXT_CHARS]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return redact_secrets(str(value))[:MAX_TEXT_CHARS]


def write_snapshot_atomic(path: Path, snapshot: Mapping[str, Any]) -> None:
    """Durably replace a local JSON snapshot without exposing a partial file."""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    safe_snapshot = sanitize_payload(dict(snapshot))
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            json.dump(safe_snapshot, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_path, 0o640)
        os.replace(temp_path, path)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink(missing_ok=True)


def snapshot_summary(snapshot: Mapping[str, Any], cache_path: Path | None = None) -> dict[str, Any]:
    surfaces = snapshot.get("surfaces") if isinstance(snapshot.get("surfaces"), Mapping) else {}
    zva = surfaces.get("zva") if isinstance(surfaces.get("zva"), Mapping) else {}
    contact_center = (
        surfaces.get("contact_center") if isinstance(surfaces.get("contact_center"), Mapping) else {}
    )
    team_chat = surfaces.get("team_chat") if isinstance(surfaces.get("team_chat"), Mapping) else {}
    summary: dict[str, Any] = {
        "collected_at": str(snapshot.get("collected_at") or ""),
        "read_only": True,
        "surfaces": {
            "zva": {
                "status": str(zva.get("status") or "unknown"),
                "completed_engagements": len(zva.get("engagements") or []),
                "transcripts": len(zva.get("transcripts") or []),
            },
            "contact_center": {
                "status": str(contact_center.get("status") or "unknown"),
                "open_messaging_engagements": len(
                    contact_center.get("open_messaging_engagements") or []
                ),
            },
            "team_chat": {
                "status": str(team_chat.get("status") or "unknown"),
                "allowlisted_users": len(team_chat.get("users") or []),
                "allowlisted_sessions": len(team_chat.get("sessions") or []),
            },
        },
    }
    if cache_path is not None:
        summary["cache"] = str(Path(cache_path).resolve())
    return summary


def safe_error(exc: Exception) -> str:
    return str(sanitize_payload(str(exc)))[:500]


def _error_status(exc: Exception) -> str:
    detail = str(exc).casefold()
    if any(marker in detail for marker in ("http 401", "http 403", "unauthorized", "forbidden", "permission", "scope")):
        return "scope_error"
    return "error"


def _combined_status(*statuses: str) -> str:
    unique = set(statuses)
    if unique == {"ok"}:
        return "ok"
    if "ok" in unique:
        return "partial"
    if unique == {"scope_error"}:
        return "scope_error"
    return "error"


def _strip_url_query(value: str) -> str:
    try:
        parsed = urllib.parse.urlsplit(value)
        if parsed.scheme not in {"http", "https"}:
            return value
        return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
    except ValueError:
        return value


def _safe_identifier(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.@+-]", "?", value)
    return cleaned[:120]


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value.strip() for value in values if value.strip()))


def _safe_int(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return _as_utc(value).replace(microsecond=0).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    main()
