from __future__ import annotations

# AgentChat/direct_codex 2026-07-27T18:30:00Z: use the existing Support
# Dashboard Calls S2S app for every typed Team Chat operation.

import base64
import hashlib
import html
import json
import os
import re
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import defaultdict
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from codex_slack_bridge.zoom_chat_monitor import collect_zoom_chat_snapshot, snapshot_summary
from codex_slack_bridge.zoom_kb_sync import get_zoom_s2s_token, get_zoom_token, zoom_get

from .internal_communications import (
    internal_request_day,
    restore_verified_internal_request_day,
)

try:
    import fcntl
except ImportError:  # pragma: no cover - production runtime is Linux.
    fcntl = None


IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,239}$")
DEFAULT_WEEKLY_JOURNAL = "/var/lib/nova/broker/zoom-shared/weekly_yaron_messages.jsonl"
DEFAULT_TEAM_CHAT_JOURNAL = "/var/lib/nova/broker/zoom-shared/team_chat_messages.jsonl"
DEFAULT_GHOSTBUSTERS_OVERVIEW_JOURNAL = (
    "/var/lib/nova/broker/zoom-shared/ghostbusters_overview.jsonl"
)
DEFAULT_GHOSTBUSTERS_LINK_MANIFEST = (
    "/opt/nova/current/docs/NOVA_VERSION_MATRIX.md"
)
DEFAULT_WEEKLY_AGENT_ROSTER = "/opt/nova/current/config/zoom-weekly-support-agents.json"
DEFAULT_GHOSTBUSTERS_OVERVIEW_FILE_ID = "QG9gZSdFQRuXnRAka_07KA"
ZOOM_ID = re.compile(r"^[A-Za-z0-9_-]{8,160}$")
ZOOM_DOC_BLOCK_ID = re.compile(r"^[A-Za-z0-9_-]{1,160}$")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
EMAIL_IN_TEXT = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
PHONE_IN_TEXT = re.compile(
    r"(?<![\d.])(?:\+?1[ .()-]*)?(?:\(?\d{3}\)?[ .-]*)\d{3}[ .-]\d{4}"
    r"(?![\d.])"
)
PRIVATE_IDENTIFIER_IN_TEXT = re.compile(
    r"(?i)\b(?:account|customer|location|subscription|ticket|case)"
    r"\s*(?:(?:id|number|no\.?)\b|#)\s*[:#-]?\s*"
    r"[A-Za-z0-9][A-Za-z0-9_-]{3,}\b"
)
PRIVATE_OVERVIEW_TERMS = re.compile(
    r"(?i)\b(?:password|api[_ -]?key|access[_ -]?token|"
    r"performance review|disciplinary|one[- ]on[- ]one)\b"
)
PRIVATE_OVERVIEW_POLICY_PREFIX = re.compile(
    r"(?i)\b(?:never|do not|must not|cannot|exclude|excluding|"
    r"keep\s+(?:private|personal)|reserved(?:\s+only)?(?:\s+for)?)\b"
)
PRIVATE_CREDENTIAL_VALUE_IN_TEXT = re.compile(
    r"(?i)\b(?:password|api[_ -]?key|access[_ -]?token)\s*[:=]\s*\S+"
)
QUALITY_MAX_WINDOW_DAYS = 31
QUALITY_MAX_ENGAGEMENTS = 500
QUALITY_MAX_TRANSCRIPT_CHARS = 200_000
KNOWLEDGE_MAX_WINDOW_DAYS = 730
KNOWLEDGE_MAX_MESSAGES = 500
OVERVIEW_MAX_CHARS = 30_000
QUALITY_TRANSCRIPT_HOST = re.compile(r"(^|\.)zoom\.us$", re.IGNORECASE)
_JOURNAL_THREAD_LOCK = threading.RLock()


class ScopedZoomClient:
    """Authenticated Zoom operations with guarded, typed mutations."""

    def __init__(
        self,
        *,
        token_provider: Callable[[], str] = get_zoom_token,
        team_chat_token_provider: Callable[[], str] | None = None,
        metrics_token_provider: Callable[[], str] | None = None,
        getter: Callable[[str, str, dict[str, str] | None], dict[str, Any]] = zoom_get,
        poster: Callable[[str, str, dict[str, Any]], dict[str, Any]] | None = None,
        text_getter: Callable[[str, str, int], str] | None = None,
        journal_path: str | Path | None = None,
        team_chat_journal_path: str | Path | None = None,
        ghostbusters_overview_journal_path: str | Path | None = None,
        ghostbusters_link_manifest_path: str | Path | None = None,
        internal_communication_journal_path: str | Path | None = None,
    ) -> None:
        self._token_provider = token_provider
        default_s2s_provider = (
            get_zoom_s2s_token if token_provider is get_zoom_token else token_provider
        )
        self._team_chat_token_provider = team_chat_token_provider or default_s2s_provider
        self._metrics_token_provider = metrics_token_provider or default_s2s_provider
        self._getter = getter
        self._poster = poster or _zoom_post_json
        self._text_getter = text_getter or _zoom_get_text
        self._journal_path = Path(
            journal_path or os.getenv("ZOOM_WEEKLY_YARON_JOURNAL_PATH") or DEFAULT_WEEKLY_JOURNAL
        )
        self._team_chat_journal_path = Path(
            team_chat_journal_path
            or os.getenv("ZOOM_TEAM_CHAT_JOURNAL_PATH")
            or DEFAULT_TEAM_CHAT_JOURNAL
        )
        self._ghostbusters_overview_journal_path = Path(
            ghostbusters_overview_journal_path
            or os.getenv("ZOOM_GHOSTBUSTERS_OVERVIEW_JOURNAL_PATH")
            or DEFAULT_GHOSTBUSTERS_OVERVIEW_JOURNAL
        )
        self._ghostbusters_link_manifest_path = Path(
            ghostbusters_link_manifest_path
            or os.getenv("ZOOM_GHOSTBUSTERS_LINK_MANIFEST_PATH")
            or _default_ghostbusters_link_manifest_path()
        )
        self._internal_communication_journal_path = internal_communication_journal_path

    def capabilities(self) -> dict[str, Any]:
        return {
            "ok": True,
            "accessMode": "typed_operations_only",
            "mutationToolsExposed": True,
            "weeklyYaronSendOnly": True,
            "directTeamChatSend": True,
            "recipientResolution": "configured_julio_or_wiko_only",
            "internalRequestRecipients": ["Julio", "Wiko"],
            "salesforceFirstForOtherEmployees": True,
            "messageReadbackRequired": True,
            "idempotencyJournalRequired": True,
            "teamChatEnumerationAllowed": False,
            "teamChatCredential": "Support Dashboard Calls",
            "teamChatCredentialType": "server_to_server_oauth",
            "explicitTeamChatSenderRequired": True,
        }

    def quality_capabilities(self) -> dict[str, Any]:
        return {
            "ok": True,
            "accessMode": "support_quality_with_explicit_operator_communications",
            "credential": "Support Dashboard Calls",
            "credentialType": "server_to_server_oauth",
            "fixedRosterRequired": True,
            "voiceOnly": True,
            "callerSuppliedUrlsAllowed": False,
            "transcriptUrlsExposed": False,
            "rawTranscriptPersistenceAllowed": False,
            "mutationToolsExposed": [
                "explicit_operator_team_chat_send",
                "fixed_ghostbusters_overview_update",
            ],
            "recipientResolutionExposed": True,
            "teamChatSendExposed": "explicit_operator_request_only",
            "ticketToolsExposed": "separate_read_only_salesforce_broker",
            "zoomChatHistoryExposed": True,
            "zoomDocsArchiveReadExposed": True,
            "ghostbustersOverviewFileIdFixed": True,
        }

    def quality_health(self) -> dict[str, Any]:
        now = datetime.now(timezone.utc).replace(microsecond=0)
        start = now - timedelta(hours=1)
        start_text = start.strftime("%Y-%m-%dT%H:%M:%SZ")
        end_text = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        voice = self.quality_voice_engagements(
            start_utc=start_text,
            end_utc=end_text,
            max_engagements=1,
        )
        performance = self.quality_agent_performance(
            start_utc=start_text,
            end_utc=end_text,
        )
        ok = bool(voice.get("ok") and performance.get("ok"))
        return {
            "ok": ok,
            "authenticated": ok,
            "surfaceStatus": {
                "voiceEngagements": "ok" if voice.get("ok") else "blocked",
                "agentPerformance": "ok" if performance.get("ok") else "blocked",
                "recordings": "validated_on_demand",
                "transcripts": "validated_on_demand",
                "teamChat": "not_exposed",
            },
            "fixedRosterReady": bool(voice.get("fixedRosterCount")),
            **({} if ok else {"error": _safe_error(RuntimeError("quality reads unavailable"))}),
        }

    def health(self) -> dict[str, Any]:
        try:
            token = self._team_chat_token_provider()
            active_users = self._active_users(token)
            user_directory_ready = isinstance(active_users, list)
            sender_ready = False
            try:
                self._resolve_team_chat_sender(
                    token,
                    active_users=active_users,
                )
                sender_ready = True
            except Exception:
                sender_ready = False
            internal_recipients_ready = True
            for alias in ("configured:julio", "configured:wiko"):
                try:
                    label, address = _configured_internal_request_contact(alias)
                    _match_configured_internal_request_user(active_users, label, address)
                except Exception:
                    internal_recipients_ready = False
                    break
            now = datetime.now(timezone.utc)
            metrics = self.weekly_support_metrics(
                start_utc=(now - timedelta(hours=1)).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
                end_utc=now.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            )
            metrics_ready = metrics.get("ok") is True
            verified = (
                metrics_ready
                and user_directory_ready
                and sender_ready
                and internal_recipients_ready
            )
            result = {
                "ok": bool(verified),
                "authenticated": True,
                "surfaceStatus": {
                    "contact_center": "ok" if metrics_ready else "blocked",
                    "team_chat": (
                        "guarded_send_ready"
                        if user_directory_ready
                        and sender_ready
                        and internal_recipients_ready
                        else "blocked"
                    ),
                    "zva": "not_authorized",
                },
                "weeklyMetrics": "ok" if metrics_ready else "blocked",
                "directTeamChat": (
                    "ready"
                    if user_directory_ready
                    and sender_ready
                    and internal_recipients_ready
                    else "blocked"
                ),
                "teamChatSender": "ready" if sender_ready else "blocked",
                "internalRequestRecipients": (
                    "ready" if internal_recipients_ready else "blocked"
                ),
            }
            if not verified:
                result["error"] = _safe_error(RuntimeError("bounded Zoom reads unavailable"))
            return result
        except Exception as exc:
            return {"ok": False, "authenticated": False, "error": _safe_error(exc)}

    def team_chat_recipient_resolve(self, *, exact_recipient: str) -> dict[str, Any]:
        """Resolve one configured Julio or Wiko Zoom user without directory exposure."""

        try:
            recipient = self._resolve_team_chat_recipient(
                self._team_chat_token_provider(),
                exact_recipient=exact_recipient,
            )
            return {
                "ok": True,
                "recipient": recipient,
                "resolution": "configured_julio_or_wiko_only",
            }
        except Exception as exc:
            return {
                "ok": False,
                "status": "blocked",
                "reason": (
                    "direct employee requests are Zoom-only for configured Julio or Wiko; "
                    "use the relevant Salesforce ticket and tagged Chatter request for everyone else"
                ),
                "error": _safe_error(exc),
            }

    def operator_team_chat_recipient_resolve(
        self,
        *,
        exact_recipient: str,
    ) -> dict[str, Any]:
        """Resolve one exact Zoom contact without restricting its email domain."""

        try:
            recipient = self._resolve_operator_team_chat_recipient(
                self._token_provider(),
                exact_recipient=exact_recipient,
            )
            return {
                "ok": True,
                "recipient": recipient,
                "resolution": "unique_exact_zoom_contact",
                "customEmailDomainsAllowed": True,
            }
        except Exception as exc:
            return {
                "ok": False,
                "status": "blocked",
                "reason": (
                    "The exact Zoom contact was not uniquely resolved. Use one exact "
                    "Zoom email address or unique full name."
                ),
                "error": _safe_error(exc),
            }

    def operator_team_chat_send(
        self,
        *,
        exact_recipient: str,
        message: str,
        authorization_context: str,
        idempotency_key: str,
        sender_lane: str,
    ) -> dict[str, Any]:
        """Send one explicitly authorized Zoom message and verify its provider readback."""

        key = str(idempotency_key or "").strip()
        if not IDEMPOTENCY_KEY.fullmatch(key):
            raise ValueError("idempotency_key must be 8-240 safe characters")
        lane = str(sender_lane or "").strip()
        if lane not in {
            "direct_codex",
            "coding_agent",
            "tickets_agent",
            "billing_agent",
            "claude_agent",
        }:
            raise ValueError("sender_lane is outside the operator-authorized Zoom lanes")
        body = _team_chat_message(message)
        authorization = " ".join(str(authorization_context or "").split())
        if not 12 <= len(authorization) <= 500:
            raise ValueError("authorization_context must preserve the explicit operator request")

        token = self._token_provider()
        recipient = self._resolve_operator_team_chat_recipient(
            token,
            exact_recipient=exact_recipient,
        )
        request_hash = _operator_team_chat_request_hash(recipient, body)
        prior = self._team_chat_journal_entry(key)
        if prior:
            return self._resume_operator_team_chat_send(
                token,
                prior=prior,
                recipient=recipient,
                body=body,
                request_hash=request_hash,
            )

        attempted_at = datetime.now(timezone.utc)
        pending = {
            "operation": "operator_team_chat_send",
            "status": "provider_attempt",
            "sent": False,
            "channel": "zoom",
            "sender": {"id": "me", "name": "Authorized Zoom user"},
            "recipient": recipient,
            "requestedByLane": lane,
            "authorizationContext": authorization,
            "idempotencyKey": key,
            "messageBody": body,
            "messageSha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
            "requestSha256": request_hash,
            "providerAttemptAtUtc": attempted_at.isoformat(),
            "retryAllowed": False,
        }
        claimed_prior = _claim_journal(
            self._team_chat_journal_path,
            pending,
            prefix=".team-chat-",
        )
        if claimed_prior:
            return self._resume_operator_team_chat_send(
                token,
                prior=claimed_prior,
                recipient=recipient,
                body=body,
                request_hash=request_hash,
            )

        reconciled = False
        try:
            created = self._poster(
                token,
                "/chat/users/me/messages",
                {"message": body, "to_contact": recipient["email"]},
            )
        except Exception as exc:
            matches = self._find_operator_team_chat_messages(
                token,
                recipient_email=recipient["email"],
                body=body,
                from_date=attempted_at.date(),
            )
            if len(matches) != 1:
                return {
                    **pending,
                    "ok": False,
                    "status": "uncertain",
                    "reason": "Zoom send outcome could not be uniquely reconciled",
                    "error": _safe_error(exc),
                }
            created = {"ids": [matches[0]]}
            reconciled = True

        message_ids = created.get("ids") if isinstance(created.get("ids"), list) else []
        message_id = str(
            message_ids[0] if message_ids else created.get("id") or ""
        ).strip()
        if not message_id:
            return {
                **pending,
                "ok": False,
                "status": "uncertain",
                "reason": "Zoom did not return a message id",
            }
        return self._verify_operator_team_chat_message(
            token,
            pending=pending,
            message_id=message_id,
            reconciled=reconciled,
        )

    def team_chat_channels(self, *, max_channels: int = 100) -> dict[str, Any]:
        """List bounded channels visible to the authorized Zoom user."""

        clean_max = max(1, min(int(max_channels), 500))
        try:
            channels = self._operator_team_chat_channels(
                self._token_provider(),
                max_channels=clean_max,
            )
            return {
                "ok": True,
                "channels": channels,
                "count": len(channels),
                "rowCeiling": clean_max,
                "ephemeralEvidence": True,
            }
        except Exception as exc:
            return {"ok": False, "status": "blocked", "error": _safe_error(exc)}

    def team_chat_history(
        self,
        *,
        channel_id: str,
        start_utc: str,
        end_utc: str,
        max_messages: int = 200,
    ) -> dict[str, Any]:
        """Read one bounded channel after proving it belongs to the authorized user."""

        clean_channel = str(channel_id or "").strip()
        if not ZOOM_ID.fullmatch(clean_channel):
            raise ValueError("channel_id must be one exact Zoom channel id")
        start_text, end_text, start_value, end_value = _knowledge_window(
            start_utc,
            end_utc,
        )
        clean_max = max(1, min(int(max_messages), KNOWLEDGE_MAX_MESSAGES))
        try:
            token = self._token_provider()
            channels = self._operator_team_chat_channels(token, max_channels=500)
            matches = [row for row in channels if row["id"] == clean_channel]
            if len(matches) != 1:
                raise RuntimeError("the exact channel is not visible to the authorized Zoom user")
            messages: list[dict[str, Any]] = []
            next_token = ""
            for _ in range(20):
                params = {
                    "to_channel": clean_channel,
                    "from": start_value.date().isoformat(),
                    "to": end_value.date().isoformat(),
                    "page_size": str(min(100, clean_max - len(messages))),
                }
                if next_token:
                    params["next_page_token"] = next_token
                payload = self._getter(token, "/chat/users/me/messages", params)
                for row in _rows(payload, "messages"):
                    if len(messages) >= clean_max:
                        break
                    message_id = str(
                        row.get("id") or row.get("message_id") or ""
                    ).strip()
                    body = str(row.get("message") or "")
                    if not message_id or not body:
                        continue
                    messages.append(
                        {
                            "messageId": message_id,
                            "message": body,
                            "sender": str(
                                row.get("sender")
                                or row.get("sender_name")
                                or row.get("sender_email")
                                or ""
                            )[:300],
                            "dateTime": str(
                                row.get("date_time")
                                or row.get("timestamp")
                                or row.get("time")
                                or ""
                            )[:80],
                            "replyMainMessageId": str(
                                row.get("reply_main_message_id") or ""
                            )[:160],
                        }
                    )
                if len(messages) >= clean_max:
                    break
                next_token = str(payload.get("next_page_token") or "").strip()
                if not next_token:
                    break
            return {
                "ok": True,
                "channel": matches[0],
                "window": {"startUtc": start_text, "endUtc": end_text},
                "messages": messages,
                "count": len(messages),
                "rowCeiling": clean_max,
                "ephemeralEvidence": True,
                "rawPersistenceAllowed": False,
            }
        except Exception as exc:
            return {"ok": False, "status": "blocked", "error": _safe_error(exc)}

    def docs_archives(
        self,
        *,
        start_utc: str,
        end_utc: str,
        product: str = "",
        max_records: int = 200,
    ) -> dict[str, Any]:
        """List bounded Zoom Docs, My Notes, and Meeting Summary archive metadata."""

        start_text, end_text, _start_value, _end_value = _knowledge_window(
            start_utc,
            end_utc,
        )
        clean_product = str(product or "").strip().casefold()
        if clean_product and clean_product not in {"docs", "my_notes", "meeting_summary"}:
            raise ValueError("product must be docs, my_notes, meeting_summary, or blank")
        clean_max = max(1, min(int(max_records), 500))
        try:
            rows = self._docs_archive_rows(
                self._team_chat_token_provider(),
                start_utc=start_text,
                end_utc=end_text,
                product=clean_product,
                max_records=clean_max,
            )
            return {
                "ok": True,
                "window": {"startUtc": start_text, "endUtc": end_text},
                "product": clean_product or "all",
                "archives": [_docs_archive_summary(row) for row in rows],
                "count": len(rows),
                "rowCeiling": clean_max,
                "ephemeralEvidence": True,
            }
        except Exception as exc:
            return {"ok": False, "status": "blocked", "error": _safe_error(exc)}

    def docs_archive_content(
        self,
        *,
        file_id: str,
        start_utc: str,
        end_utc: str,
        max_chars: int = 120_000,
    ) -> dict[str, Any]:
        """Read one validated archived Doc, My Notes transcript, or meeting summary."""

        clean_file_id = str(file_id or "").strip()
        if not ZOOM_ID.fullmatch(clean_file_id):
            raise ValueError("file_id must be one exact Zoom Docs file id")
        start_text, end_text, _start_value, _end_value = _knowledge_window(
            start_utc,
            end_utc,
        )
        clean_max = max(1_000, min(int(max_chars), QUALITY_MAX_TRANSCRIPT_CHARS))
        try:
            token = self._team_chat_token_provider()
            rows = self._docs_archive_rows(
                token,
                start_utc=start_text,
                end_utc=end_text,
                product="",
                max_records=500,
            )
            matches = [
                row
                for row in rows
                if str(row.get("file_id") or row.get("fileId") or "").strip()
                == clean_file_id
            ]
            if not matches:
                raise RuntimeError("the exact Zoom Docs archive was not found in the bounded window")
            selected = sorted(
                matches,
                key=lambda row: str(row.get("archive_time") or ""),
            )[-1]
            download_url = str(selected.get("download_url") or "").strip()
            _validate_zoom_download_url(download_url)
            raw = self._text_getter(token, download_url, clean_max * 4)
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise RuntimeError("Zoom Docs archive content was not a JSON object")
            markdown = str(payload.get("markdown") or "")
            transcript = payload.get("transcript")
            transcript_rows = (
                transcript.get("items")
                if isinstance(transcript, dict)
                and isinstance(transcript.get("items"), list)
                else []
            )
            items = []
            used = len(markdown)
            for row in transcript_rows:
                if not isinstance(row, dict):
                    continue
                text = str(row.get("text") or "")
                if not text or used + len(text) > clean_max:
                    break
                used += len(text)
                items.append(
                    {
                        "text": text,
                        "startTime": str(row.get("start_time") or "")[:40],
                        "endTime": str(row.get("end_time") or "")[:40],
                        "speakerRef": str(row.get("user_id") or "")[:80],
                    }
                )
            return {
                "ok": True,
                "fileId": clean_file_id,
                "product": str(
                    payload.get("product") or selected.get("product") or ""
                )[:80],
                "archiveTime": str(
                    payload.get("archive_time")
                    or selected.get("archive_time")
                    or ""
                )[:80],
                "markdown": markdown[:clean_max],
                "transcriptItems": items,
                "truncated": len(markdown) > clean_max
                or len(items) < len(transcript_rows),
                "ephemeralEvidence": True,
                "rawPersistenceAllowed": False,
            }
        except Exception as exc:
            return {"ok": False, "status": "blocked", "error": _safe_error(exc)}

    def ghostbusters_overview_read(self) -> dict[str, Any]:
        """Read the one configured public operational Chat Overview document."""

        try:
            token = self._token_provider()
            file_id = _ghostbusters_overview_file_id()
            metadata = self._getter(token, f"/docs/files/{file_id}", None)
            content = self._getter(token, f"/docs/files/{file_id}/content", None)
            _validate_ghostbusters_overview(metadata, file_id)
            return {
                "ok": True,
                "fileId": file_id,
                "fileName": str(content.get("file_name") or "")[:200],
                "markdown": str(content.get("file_content") or ""),
                "modifiedTime": str(metadata.get("modified_time") or "")[:80],
                "publicOperationalContentOnly": True,
            }
        except Exception as exc:
            return {"ok": False, "status": "blocked", "error": _safe_error(exc)}

    def ghostbusters_overview_update(
        self,
        *,
        markdown: str,
        source_date: str,
        source_summary: str,
        authorization_context: str,
        idempotency_key: str,
        sender_lane: str,
    ) -> dict[str, Any]:
        """Replace only the fixed public Chat Overview after privacy and readback checks."""

        key = str(idempotency_key or "").strip()
        if not IDEMPOTENCY_KEY.fullmatch(key):
            raise ValueError("idempotency_key must be 8-240 safe characters")
        lane = str(sender_lane or "").strip()
        if lane not in {"direct_codex", "coding_agent", "claude_agent"}:
            raise ValueError("sender_lane cannot maintain the Ghost Busters overview")
        authorization = " ".join(str(authorization_context or "").split())
        if not 12 <= len(authorization) <= 500:
            raise ValueError("authorization_context must preserve the operator-approved purpose")
        clean_source_date = _overview_source_date(source_date)
        clean_source_summary = _public_overview_text(
            source_summary,
            field_name="source_summary",
            min_chars=8,
            max_chars=500,
        )
        clean_markdown = _public_overview_text(
            markdown,
            field_name="markdown",
            min_chars=100,
            max_chars=OVERVIEW_MAX_CHARS,
        )
        link_evidence = _validate_overview_links(
            clean_markdown,
            self._ghostbusters_link_manifest_path,
        )
        requested_hash = hashlib.sha256(clean_markdown.encode("utf-8")).hexdigest()
        file_id = _ghostbusters_overview_file_id()
        token = self._token_provider()
        prior = _journal_entry(self._ghostbusters_overview_journal_path, key)
        if prior:
            same_request = (
                str(prior.get("operation") or "") == "ghostbusters_overview_update"
                and str(prior.get("fileId") or "") == file_id
                and str(prior.get("requestedSha256") or "") == requested_hash
            )
            if not same_request:
                return {
                    **prior,
                    "ok": False,
                    "status": "blocked",
                    "reason": "idempotency key is already bound to a different overview update",
                    "retryAllowed": False,
                }
            if prior.get("status") == "verified":
                return {**prior, "ok": True, "duplicatePrevented": True}
            return {
                **prior,
                "ok": False,
                "status": "uncertain",
                "reason": "a prior overview write is pending verification",
                "retryAllowed": False,
            }

        metadata = self._getter(token, f"/docs/files/{file_id}", None)
        before = self._getter(
            token,
            f"/docs/files/{file_id}/content",
            {"format": "xml"},
        )
        _validate_ghostbusters_overview(metadata, file_id)
        before_xml = str(before.get("file_content") or "")
        block_ids = _top_level_doc_block_ids(before_xml)
        if not block_ids:
            raise RuntimeError("the fixed Chat Overview did not return replaceable blocks")
        before_hash = hashlib.sha256(before_xml.encode("utf-8")).hexdigest()
        pending = {
            "operation": "ghostbusters_overview_update",
            "status": "provider_attempt",
            "fileId": file_id,
            "fileName": str(metadata.get("file_name") or "")[:200],
            "requestedByLane": lane,
            "authorizationContext": authorization,
            "idempotencyKey": key,
            "sourceDate": clean_source_date,
            "sourceSummary": clean_source_summary,
            "linkManifestSha256": link_evidence["manifestSha256"],
            "verifiedLinkCount": link_evidence["verifiedLinkCount"],
            "beforeSha256": before_hash,
            "requestedSha256": requested_hash,
            "providerAttemptAtUtc": datetime.now(timezone.utc).isoformat(),
            "retryAllowed": False,
        }
        claimed_prior = _claim_journal(
            self._ghostbusters_overview_journal_path,
            pending,
            prefix=".ghostbusters-overview-",
        )
        if claimed_prior:
            return {
                **claimed_prior,
                "ok": False,
                "status": "uncertain",
                "reason": "another worker already claimed this overview update",
                "retryAllowed": False,
            }

        self._poster(
            token,
            f"/docs/files/{file_id}/blocks/replace_range",
            {
                "start_block_id": block_ids[0],
                "end_block_id": block_ids[-1],
                "blocks": _overview_xml_blocks(clean_markdown),
            },
        )
        readback = self._getter(token, f"/docs/files/{file_id}/content", None)
        readback_markdown = str(readback.get("file_content") or "")
        if _normalize_doc_text(readback_markdown) != _normalize_doc_text(clean_markdown):
            return {
                **pending,
                "ok": False,
                "status": "uncertain",
                "reason": "Zoom Docs readback did not match the requested overview content",
                "retryAllowed": False,
            }
        receipt = {
            **pending,
            "status": "verified",
            "verified": True,
            "readbackVerified": True,
            "afterSha256": hashlib.sha256(
                readback_markdown.encode("utf-8")
            ).hexdigest(),
            "verifiedAtUtc": datetime.now(timezone.utc).isoformat(),
        }
        _append_journal(
            self._ghostbusters_overview_journal_path,
            receipt,
            prefix=".ghostbusters-overview-",
        )
        return {**receipt, "ok": True, "duplicatePrevented": False}

    def team_chat_verify_existing(
        self,
        *,
        exact_recipient: str,
        message_id: str,
        message: str,
    ) -> dict[str, Any]:
        """Read back one known Team Chat message without creating a new send."""

        known_message_id = str(message_id or "").strip()
        if not ZOOM_ID.fullmatch(known_message_id):
            raise ValueError("message_id must be one exact Zoom message id")
        body = _team_chat_message(message)
        try:
            token = self._team_chat_token_provider()
            active_users = self._active_users(token)
            sender_identity = self._resolve_team_chat_sender(
                token,
                active_users=active_users,
            )
            sender = sender_identity["id"]
            label, address = _configured_internal_request_contact(exact_recipient)
            recipient = _match_configured_internal_request_user(
                active_users,
                label,
                address,
            )
            readback = self._getter(
                token,
                f"/chat/users/{urllib.parse.quote(sender, safe='')}/messages/"
                f"{urllib.parse.quote(known_message_id, safe='')}",
                {"to_contact": recipient["email"]},
            )
            readback_id = str(
                readback.get("id") or readback.get("message_id") or ""
            ).strip()
            sender_email = str(readback.get("sender") or "").strip()
            verified = (
                readback_id == known_message_id
                and str(readback.get("message") or "") == body
                and bool(sender_email)
                and sender_email.casefold()
                == str(sender_identity.get("email") or "").casefold()
            )
            if not verified:
                return {
                    "ok": False,
                    "sent": False,
                    "status": "sent_unverified",
                    "channel": "zoom",
                    "messageId": known_message_id,
                    "messageBody": body,
                    "sender": sender_identity,
                    "recipient": recipient,
                    "readbackVerified": False,
                    "senderReadbackVerified": False,
                    "recipientReadbackVerified": True,
                    "retryAllowed": False,
                    "reason": "Zoom message id, body, or sender readback did not match",
                }
            return {
                "ok": True,
                "sent": True,
                "status": "sent",
                "channel": "zoom",
                "messageId": known_message_id,
                "messageBody": body,
                "sender": sender_identity,
                "recipient": recipient,
                "readbackVerified": True,
                "senderReadbackVerified": True,
                "recipientReadbackVerified": True,
                "retryAllowed": False,
                "duplicatePrevented": True,
                "existingMessageVerified": True,
            }
        except Exception as exc:
            return {
                "ok": False,
                "sent": False,
                "status": "sent_unverified",
                "channel": "zoom",
                "messageId": known_message_id,
                "messageBody": body,
                "readbackVerified": False,
                "senderReadbackVerified": False,
                "recipientReadbackVerified": False,
                "retryAllowed": False,
                "reason": "Existing Zoom message could not be verified",
                "error": _safe_error(exc),
            }

    def team_chat_send(
        self,
        *,
        exact_recipient: str,
        message: str,
        authorization_context: str,
        idempotency_key: str,
        sender_lane: str,
        reply_main_message_id: str = "",
    ) -> dict[str, Any]:
        """Send one exact direct Team Chat message and verify the provider readback."""

        key = str(idempotency_key or "").strip()
        if not IDEMPOTENCY_KEY.fullmatch(key):
            raise ValueError("idempotency_key must be 8-240 safe characters")
        lane = str(sender_lane or "").strip()
        if lane not in {"coding_agent", "tickets_agent", "billing_agent"}:
            raise ValueError("sender_lane is outside the fixed Zoom messaging lanes")
        reply_parent = str(reply_main_message_id or "").strip()
        if reply_parent and not ZOOM_ID.fullmatch(reply_parent):
            raise ValueError(
                "reply_main_message_id must be one exact Zoom message id"
            )
        requested_body = _team_chat_message(message)
        authorization = " ".join(str(authorization_context or "").split())
        if not 4 <= len(authorization) <= 500:
            raise ValueError("authorization_context must be 4-500 characters")

        token = self._team_chat_token_provider()
        active_users = self._active_users(token)
        sender_identity = self._resolve_team_chat_sender(
            token,
            active_users=active_users,
        )
        sender = sender_identity["id"]
        label, address = _configured_internal_request_contact(exact_recipient)
        recipient = _match_configured_internal_request_user(
            active_users,
            label,
            address,
        )
        prior = self._team_chat_journal_entry(key)
        request_body = _team_chat_request_content(requested_body, recipient)

        if prior and prior.get("status") == "sent":
            result = _completed_team_chat_result(
                prior,
                exact_recipient=exact_recipient,
                body=request_body,
                sender_id=sender,
                reply_main_message_id=reply_parent,
            )
            if result.get("ok") is True:
                restore_verified_internal_request_day(
                    recipient["email"],
                    verified_local_date=str(
                        result.get("internalRequestLocalDate") or ""
                    ),
                    channel="zoom",
                    provider_id=str(result.get("messageId") or ""),
                    journal_path=self._internal_communication_journal_path,
                )
            return result
        if prior and prior.get("status") in {"pending", "provider_attempt"}:
            result = self._reconcile_pending_team_chat(
                token,
                prior=prior,
                sender=sender,
                sender_identity=sender_identity,
                recipient=recipient,
                request_body=request_body,
                reply_main_message_id=reply_parent,
            )
            if result.get("ok") is True and result.get("readbackVerified") is True:
                restore_verified_internal_request_day(
                    recipient["email"],
                    verified_local_date=str(
                        result.get("internalRequestLocalDate") or ""
                    ),
                    channel="zoom",
                    provider_id=str(result.get("messageId") or ""),
                    journal_path=self._internal_communication_journal_path,
                )
            return result

        with internal_request_day(
            recipient["email"],
            journal_path=self._internal_communication_journal_path,
        ) as communication:
            body = _render_internal_request_message(
                request_body,
                recipient,
                include_greeting=communication.greeting_required,
            )
            pending_at = datetime.now(timezone.utc)
            pending = {
                "status": "provider_attempt",
                "sent": False,
                "channel": "zoom",
                "sender": sender_identity,
                "recipient": recipient,
                "requestedByLane": lane,
                "authorizationContext": authorization,
                "idempotencyKey": key,
                "messageBody": body,
                "messageSha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
                "requestSha256": hashlib.sha256(
                    request_body.encode("utf-8")
                ).hexdigest(),
                "replyMainMessageId": reply_parent,
                "internalRequestLocalDate": communication.local_date,
                "firstMessageGreetingIncluded": bool(
                    communication.greeting_required
                ),
                "pendingAtUtc": pending_at.isoformat(),
                "providerAttemptAtUtc": pending_at.isoformat(),
                "retryAllowed": False,
            }
            claimed_prior = _claim_journal(
                self._team_chat_journal_path,
                pending,
                prefix=".team-chat-",
            )
            if claimed_prior and claimed_prior.get("status") == "sent":
                result = _completed_team_chat_result(
                    claimed_prior,
                    exact_recipient=exact_recipient,
                    body=request_body,
                    sender_id=sender,
                    reply_main_message_id=reply_parent,
                )
                if (
                    result.get("ok") is True
                    and result.get("internalRequestLocalDate")
                    == communication.local_date
                ):
                    communication.record_verified(
                        channel="zoom",
                        provider_id=str(result.get("messageId") or ""),
                    )
                return result
            if claimed_prior:
                result = self._reconcile_pending_team_chat(
                    token,
                    prior=claimed_prior,
                    sender=sender,
                    sender_identity=sender_identity,
                    recipient=recipient,
                    request_body=request_body,
                    reply_main_message_id=reply_parent,
                )
                if (
                    result.get("ok") is True
                    and result.get("readbackVerified") is True
                    and result.get("internalRequestLocalDate")
                    == communication.local_date
                ):
                    communication.record_verified(
                        channel="zoom",
                        provider_id=str(result.get("messageId") or ""),
                    )
                return result

            reconciled = False
            try:
                provider_body = {
                    "message": body,
                    "to_contact": recipient["email"],
                }
                if reply_parent:
                    provider_body["reply_main_message_id"] = reply_parent
                created = self._poster(
                    token,
                    f"/chat/users/{urllib.parse.quote(sender, safe='')}/messages",
                    provider_body,
                )
            except Exception as exc:
                matches = self._find_exact_team_chat_messages(
                    token,
                    sender=sender,
                    recipient_email=recipient["email"],
                    body=body,
                    from_date=pending_at.date(),
                    reply_main_message_id=reply_parent,
                )
                if len(matches) != 1:
                    return {
                        **pending,
                        "ok": False,
                        "status": "uncertain",
                        "error": _safe_error(exc),
                        "reason": "Zoom send outcome could not be uniquely reconciled",
                    }
                created = {"ids": [matches[0]]}
                reconciled = True

            message_ids = (
                created.get("ids") if isinstance(created.get("ids"), list) else []
            )
            message_id = str(
                message_ids[0] if message_ids else created.get("id") or ""
            ).strip()
            if not message_id:
                return {
                    **pending,
                    "ok": False,
                    "status": "uncertain",
                    "reason": "Zoom did not return a message id",
                }
            result = self._verify_team_chat_message(
                token,
                key=key,
                lane=lane,
                authorization=authorization,
                sender=sender,
                sender_identity=sender_identity,
                recipient=recipient,
                body=body,
                message_id=message_id,
                reconciled=reconciled,
                internal_request_local_date=communication.local_date,
                first_message_greeting_included=bool(
                    communication.greeting_required
                ),
                reply_main_message_id=reply_parent,
            )
            if result.get("ok") is True and result.get("readbackVerified") is True:
                communication.record_verified(
                    channel="zoom",
                    provider_id=str(result.get("messageId") or ""),
                )
            return result

    def support_chat_snapshot(self, *, since_hours: int = 24) -> dict[str, Any]:
        hours = max(1, min(int(since_hours), 24 * 30))
        try:
            snapshot = collect_zoom_chat_snapshot(
                self._token_provider(),
                since_hours=hours,
                getter=self._getter,
            )
            return {
                "ok": True,
                "summary": snapshot_summary(snapshot),
                "snapshot": snapshot,
            }
        except Exception as exc:
            return {"ok": False, "error": _safe_error(exc)}

    def quality_voice_engagements(
        self,
        *,
        start_utc: str,
        end_utc: str,
        max_engagements: int = 200,
    ) -> dict[str, Any]:
        start_text, end_text, start_value, end_value = _quality_window(start_utc, end_utc)
        limit = max(1, min(int(max_engagements), QUALITY_MAX_ENGAGEMENTS))
        try:
            roster = self._weekly_support_agent_roster()
            rows = self._historical_engagements(
                self._metrics_token_provider(),
                start_text=start_text,
                end_text=end_text,
            )
            return _summarize_quality_voice_engagements(
                rows,
                start_value=start_value,
                end_value=end_value,
                roster=roster,
                limit=limit,
            )
        except Exception as exc:
            return {
                "ok": False,
                "status": "blocked",
                "startUtc": start_text,
                "endUtc": end_text,
                "fixedRosterCount": 0,
                "totalVoiceEngagements": 0,
                "engagements": [],
                "coverageGaps": ["voice_engagement_inventory_unavailable"],
                "error": _safe_error(exc),
            }

    def quality_agent_performance(
        self,
        *,
        start_utc: str,
        end_utc: str,
    ) -> dict[str, Any]:
        start_text, end_text, start_value, end_value = _quality_window(start_utc, end_utc)
        try:
            roster = self._weekly_support_agent_roster()
            rows = self._historical_agent_performance(
                self._metrics_token_provider(),
                start_text=start_text,
                end_text=end_text,
            )
            return _summarize_quality_agent_performance(
                rows,
                start_value=start_value,
                end_value=end_value,
                roster=roster,
            )
        except Exception as exc:
            return {
                "ok": False,
                "status": "blocked",
                "startUtc": start_text,
                "endUtc": end_text,
                "fixedRosterCount": 0,
                "perAgent": [],
                "coverageGaps": ["agent_performance_unavailable"],
                "error": _safe_error(exc),
            }

    def quality_engagement_recordings(
        self,
        *,
        engagement_id: str,
        start_utc: str,
        end_utc: str,
    ) -> dict[str, Any]:
        engagement = _zoom_id(engagement_id, "engagement_id")
        start_text, end_text, _start_value, _end_value = _quality_window(start_utc, end_utc)
        try:
            inventory = self.quality_voice_engagements(
                start_utc=start_text,
                end_utc=end_text,
                max_engagements=QUALITY_MAX_ENGAGEMENTS,
            )
            if not inventory.get("ok"):
                raise RuntimeError("the fixed-roster voice inventory is unavailable")
            allowed = {
                str(item.get("engagementId") or "")
                for item in inventory.get("engagements") or []
                if isinstance(item, dict)
            }
            if engagement not in allowed:
                raise ValueError("engagement_id is not a fixed-roster voice engagement in this window")
            token = self._metrics_token_provider()
            rows = self._engagement_recordings(
                token,
                engagement_id=engagement,
                start_text=start_text,
                end_text=end_text,
            )
            recordings = [_quality_recording_summary(row) for row in rows]
            recordings = [item for item in recordings if item.get("recordingId")]
            transcript_count = sum(1 for item in recordings if item.get("transcriptAvailable"))
            gaps = [] if transcript_count else ["voice_transcript_missing_or_processing"]
            return {
                "ok": True,
                "status": "ok" if transcript_count else "partial",
                "engagementId": engagement,
                "startUtc": start_text,
                "endUtc": end_text,
                "recordingCount": len(recordings),
                "transcriptAvailableCount": transcript_count,
                "recordings": recordings,
                "coverageGaps": gaps,
                "source": "Zoom Contact Center fixed-roster voice recording metadata",
            }
        except Exception as exc:
            return {
                "ok": False,
                "status": "blocked",
                "engagementId": engagement,
                "startUtc": start_text,
                "endUtc": end_text,
                "recordingCount": 0,
                "transcriptAvailableCount": 0,
                "recordings": [],
                "coverageGaps": ["recording_metadata_unavailable"],
                "error": _safe_error(exc),
            }

    def quality_transcript(
        self,
        *,
        engagement_id: str,
        recording_id: str,
        start_utc: str,
        end_utc: str,
        max_chars: int = 120_000,
    ) -> dict[str, Any]:
        engagement = _zoom_id(engagement_id, "engagement_id")
        recording = _zoom_id(recording_id, "recording_id")
        limit = max(1_000, min(int(max_chars), QUALITY_MAX_TRANSCRIPT_CHARS))
        start_text, end_text, _start_value, _end_value = _quality_window(start_utc, end_utc)
        try:
            metadata = self.quality_engagement_recordings(
                engagement_id=engagement,
                start_utc=start_text,
                end_utc=end_text,
            )
            if not metadata.get("ok"):
                raise RuntimeError("recording metadata is unavailable")
            selected = next(
                (
                    item
                    for item in metadata.get("recordings") or []
                    if isinstance(item, dict)
                    and str(item.get("recordingId") or "") == recording
                ),
                None,
            )
            if not selected:
                raise ValueError("recording_id is not part of the validated engagement")
            token = self._metrics_token_provider()
            rows = self._engagement_recordings(
                token,
                engagement_id=engagement,
                start_text=start_text,
                end_text=end_text,
            )
            raw = next(
                (
                    row
                    for row in rows
                    if str(
                        row.get("recording_id")
                        or row.get("recordingId")
                        or row.get("id")
                        or ""
                    ).strip()
                    == recording
                ),
                None,
            )
            transcript_url = _quality_transcript_url(raw or {})
            if not transcript_url:
                return {
                    "ok": True,
                    "status": "partial",
                    "engagementId": engagement,
                    "recordingId": recording,
                    "transcriptAvailable": False,
                    "transcript": "",
                    "truncated": False,
                    "coverageGaps": ["voice_transcript_missing_or_processing"],
                    "source": "Zoom Contact Center recording transcript",
                }
            _validate_zoom_transcript_url(transcript_url)
            transcript = self._text_getter(token, transcript_url, limit + 1)
            clean = _quality_transcript_text(transcript)
            truncated = len(clean) > limit
            if truncated:
                clean = clean[:limit].rstrip()
            return {
                "ok": True,
                "status": "ok",
                "engagementId": engagement,
                "recordingId": recording,
                "transcriptAvailable": True,
                "transcript": clean,
                "transcriptChars": len(clean),
                "truncated": truncated,
                "ephemeralEvidence": True,
                "coverageGaps": ["transcript_truncated"] if truncated else [],
                "source": "Zoom Contact Center recording transcript",
            }
        except Exception as exc:
            return {
                "ok": False,
                "status": "blocked",
                "engagementId": engagement,
                "recordingId": recording,
                "transcriptAvailable": False,
                "transcript": "",
                "truncated": False,
                "coverageGaps": ["voice_transcript_unavailable"],
                "error": _safe_error(exc),
            }

    def weekly_support_metrics(
        self,
        *,
        start_utc: str,
        end_utc: str,
        queue_hint: str = "All queues / fixed Total Calls report roster",
    ) -> dict[str, Any]:
        start_text, start_value = _utc_timestamp(start_utc, "start_utc")
        end_text, end_value = _utc_timestamp(end_utc, "end_utc")
        if end_value <= start_value:
            raise ValueError("end_utc must be after start_utc")
        if (end_value - start_value).total_seconds() > 31 * 86400:
            raise ValueError("weekly support metrics are limited to 31 days")
        try:
            roster = self._weekly_support_agent_roster()
            token = self._metrics_token_provider()
            rows = self._historical_engagements(
                token,
                start_text=start_text,
                end_text=end_text,
            )
            return _summarize_report_engagements(
                rows,
                start_value=start_value,
                end_value=end_value,
                roster=roster,
                report_id=str(roster.get("reportId") or ""),
                report_name=str(roster.get("reportName") or "Total Calls"),
            )
        except Exception as exc:
            return {
                "ok": False,
                "status": "blocked",
                "startUtc": start_text,
                "endUtc": end_text,
                "inbound": None,
                "outbound": None,
                "total": None,
                "calls": {"inbound": None, "outbound": None, "unknown": None, "total": None},
                "chatSessions": {
                    "inbound": None,
                    "outbound": None,
                    "unknown": None,
                    "total": None,
                },
                "perAgent": [],
                "error": _safe_error(exc),
            }

    def _weekly_support_agent_roster(self) -> dict[str, Any]:
        configured_path = str(
            os.getenv("ZOOM_WEEKLY_SUPPORT_AGENT_ROSTER_FILE")
            or DEFAULT_WEEKLY_AGENT_ROSTER
        ).strip()
        path = Path(configured_path).expanduser()
        if not path.is_file():
            raise RuntimeError("the fixed weekly Zoom support-agent roster is unavailable")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError("the fixed weekly Zoom support-agent roster is invalid") from exc
        if not isinstance(payload, dict):
            raise RuntimeError("the fixed weekly Zoom support-agent roster is invalid")
        raw_agents = payload.get("agents")
        if not isinstance(raw_agents, list) or not 1 <= len(raw_agents) <= 50:
            raise RuntimeError("the fixed weekly Zoom support-agent roster is invalid")
        agents: list[dict[str, str]] = []
        seen: set[str] = set()
        for item in raw_agents:
            if not isinstance(item, dict):
                raise RuntimeError("the fixed weekly Zoom support-agent roster is invalid")
            user_id = str(item.get("id") or "").strip()
            name = " ".join(str(item.get("name") or "").split())[:160]
            if not ZOOM_ID.fullmatch(user_id) or not name or user_id in seen:
                raise RuntimeError("the fixed weekly Zoom support-agent roster is invalid")
            seen.add(user_id)
            agents.append({"id": user_id, "name": name})
        report_id = str(payload.get("reportId") or "").strip()
        if report_id and not ZOOM_ID.fullmatch(report_id):
            raise RuntimeError("the fixed weekly Zoom support-agent roster is invalid")
        return {
            "reportId": report_id,
            "reportName": " ".join(str(payload.get("reportName") or "Total Calls").split())[:160],
            "agents": agents,
        }

    def weekly_yaron_report_send(
        self,
        *,
        start_utc: str,
        end_utc: str,
        ticket_total: int,
        idempotency_key: str,
        queue_hint: str = "All queues / fixed Total Calls report roster",
    ) -> dict[str, Any]:
        key = str(idempotency_key or "").strip()
        if not IDEMPOTENCY_KEY.fullmatch(key):
            raise ValueError("idempotency_key must be 8-240 safe characters")
        tickets = _bounded_count(ticket_total, "ticket_total")
        start_text, start_value = _utc_timestamp(start_utc, "start_utc")
        end_text, end_value = _utc_timestamp(end_utc, "end_utc")
        if end_value <= start_value:
            raise ValueError("end_utc must be after start_utc")
        queue = " ".join(str(queue_hint or "").split())
        request_sha256 = _weekly_request_sha256(
            start_text=start_text,
            end_text=end_text,
            ticket_total=tickets,
            queue_hint=queue,
        )
        prior = self._journal_entry(key)
        if prior:
            if not _weekly_request_matches(
                prior,
                request_sha256=request_sha256,
                start_text=start_text,
                end_text=end_text,
                ticket_total=tickets,
            ):
                return {
                    **prior,
                    "ok": False,
                    "status": "blocked",
                    "reason": (
                        "idempotency key is already bound to a different weekly "
                        "Zoom report request"
                    ),
                    "duplicatePrevented": True,
                    "retryAllowed": False,
                }
            if prior.get("status") == "sent":
                return {**prior, "ok": True, "duplicatePrevented": True}

        metrics = self.weekly_support_metrics(
            start_utc=start_text,
            end_utc=end_text,
            queue_hint=queue,
        )
        if not metrics.get("ok"):
            return {
                "ok": False,
                "status": "blocked",
                "sent": False,
                "reason": "verified Zoom support metrics were unavailable",
                "metrics": metrics,
            }
        token = self._team_chat_token_provider()
        active_users = self._active_users(token)
        sender_identity = self._resolve_team_chat_sender(
            token,
            active_users=active_users,
        )
        sender = sender_identity["id"]
        recipient = self._resolve_yaron(token, active_users=active_users)
        body = _weekly_message(
            start_value=start_value,
            end_value=end_value,
            metrics=metrics,
            ticket_total=tickets,
        )
        attempt = {
            "status": "provider_attempt",
            "sent": False,
            "channel": "zoom",
            "readbackVerified": False,
            "senderReadbackVerified": False,
            "recipientReadbackVerified": False,
            "sender": sender_identity,
            "recipient": recipient,
            "idempotencyKey": key,
            "requestSha256": request_sha256,
            "startUtc": start_text,
            "endUtc": end_text,
            "queueHint": queue,
            "tickets": {"total": tickets},
            "metrics": metrics,
            "messageBody": body,
            "messageSha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
            "providerAttemptAtUtc": datetime.now(timezone.utc).isoformat(),
            "retryAllowed": False,
        }
        claimed_prior = _claim_journal(
            self._journal_path,
            attempt,
            prefix=".zoom-weekly-",
        )
        if claimed_prior:
            if not _weekly_request_matches(
                claimed_prior,
                request_sha256=request_sha256,
                start_text=start_text,
                end_text=end_text,
                ticket_total=tickets,
            ):
                return {
                    **claimed_prior,
                    "ok": False,
                    "status": "blocked",
                    "reason": (
                        "idempotency key is already bound to a different weekly "
                        "Zoom report request"
                    ),
                    "duplicatePrevented": True,
                    "retryAllowed": False,
                }
            if claimed_prior.get("status") == "sent":
                return {
                    **claimed_prior,
                    "ok": True,
                    "duplicatePrevented": True,
                }
            prior_sender = (
                claimed_prior.get("sender")
                if isinstance(claimed_prior.get("sender"), dict)
                else {}
            )
            prior_recipient = (
                claimed_prior.get("recipient")
                if isinstance(claimed_prior.get("recipient"), dict)
                else {}
            )
            if (
                str(prior_sender.get("id") or "").strip() != sender
                or str(prior_recipient.get("email") or "").strip().casefold()
                != recipient["email"].casefold()
            ):
                return {
                    **claimed_prior,
                    "ok": False,
                    "status": "blocked",
                    "reason": (
                        "idempotency key is already bound to a different weekly "
                        "Zoom sender or recipient"
                    ),
                    "duplicatePrevented": True,
                    "retryAllowed": False,
                }
            prior_body = str(claimed_prior.get("messageBody") or "")
            if (
                not prior_body
                or claimed_prior.get("messageSha256")
                != hashlib.sha256(prior_body.encode("utf-8")).hexdigest()
            ):
                return {
                    **claimed_prior,
                    "ok": False,
                    "status": "uncertain",
                    "reason": "weekly Zoom attempt journal did not match its message body",
                    "retryAllowed": False,
                }
            existing = self._find_existing_message(
                token,
                sender=sender,
                recipient_email=recipient["email"],
                body=prior_body,
                end_value=end_value,
            )
            if not existing:
                return {
                    **claimed_prior,
                    "ok": False,
                    "status": "uncertain",
                    "sent": False,
                    "reason": "weekly Zoom provider attempt could not be reconciled",
                    "retryAllowed": False,
                }
            prior_metrics = (
                claimed_prior.get("metrics")
                if isinstance(claimed_prior.get("metrics"), dict)
                else metrics
            )
            entry = self._receipt(
                key=key,
                start_text=start_text,
                end_text=end_text,
                message_id=existing,
                message_body=prior_body,
                metrics=prior_metrics,
                ticket_total=tickets,
                reconciled=True,
                sender=sender_identity,
                recipient=recipient,
                request_sha256=request_sha256,
                queue_hint=queue,
            )
            self._append_journal(entry)
            return {**entry, "ok": True, "duplicatePrevented": True}

        existing = self._find_existing_message(
            token,
            sender=sender,
            recipient_email=recipient["email"],
            body=body,
            end_value=end_value,
        )
        if existing:
            entry = self._receipt(
                key=key,
                start_text=start_text,
                end_text=end_text,
                message_id=existing,
                message_body=body,
                metrics=metrics,
                ticket_total=tickets,
                reconciled=True,
                sender=sender_identity,
                recipient=recipient,
                request_sha256=request_sha256,
                queue_hint=queue,
            )
            self._append_journal(entry)
            return {**entry, "ok": True, "duplicatePrevented": True}

        try:
            created = self._poster(
                token,
                f"/chat/users/{urllib.parse.quote(sender, safe='')}/messages",
                {"message": body, "to_contact": recipient["email"]},
            )
        except Exception as exc:
            reconciled_id = self._find_existing_message(
                token,
                sender=sender,
                recipient_email=recipient["email"],
                body=body,
                end_value=end_value,
            )
            if not reconciled_id:
                return {
                    "ok": False,
                    "status": "uncertain",
                    "sent": False,
                    "error": _safe_error(exc),
                    "retryAllowed": False,
                }
            created = {"ids": [reconciled_id]}

        message_ids = created.get("ids") if isinstance(created.get("ids"), list) else []
        message_id = str(message_ids[0] if message_ids else created.get("id") or "").strip()
        if not message_id:
            return {
                "ok": False,
                "status": "uncertain",
                "sent": False,
                "reason": "Zoom did not return a message id",
                "retryAllowed": False,
            }
        readback = self._getter(
            token,
            f"/chat/users/{urllib.parse.quote(sender, safe='')}/messages/"
            f"{urllib.parse.quote(message_id, safe='')}",
            {"to_contact": recipient["email"]},
        )
        if str(readback.get("id") or readback.get("message_id") or "") != message_id:
            return {
                "ok": False,
                "status": "uncertain",
                "sent": False,
                "messageId": message_id,
                "reason": "Zoom message readback did not match",
                "retryAllowed": False,
            }
        if str(readback.get("message") or "") != body:
            return {
                "ok": False,
                "status": "uncertain",
                "sent": False,
                "messageId": message_id,
                "reason": "Zoom message readback body did not match",
                "retryAllowed": False,
            }
        if (
            str(readback.get("sender") or "").strip().casefold()
            != sender_identity["email"].casefold()
        ):
            return {
                "ok": False,
                "status": "uncertain",
                "sent": False,
                "messageId": message_id,
                "reason": "Zoom message sender readback did not match",
                "retryAllowed": False,
            }
        entry = self._receipt(
            key=key,
            start_text=start_text,
            end_text=end_text,
            message_id=message_id,
            message_body=body,
            metrics=metrics,
            ticket_total=tickets,
            reconciled=False,
            sender=sender_identity,
            recipient=recipient,
            request_sha256=request_sha256,
            queue_hint=queue,
        )
        self._append_journal(entry)
        return {**entry, "ok": True, "duplicatePrevented": False}

    def _historical_engagements(
        self,
        token: str,
        *,
        start_text: str,
        end_text: str,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        next_token = ""
        for _ in range(50):
            params = {
                "timezone": "UTC",
                "start_time_from": start_text,
                "start_time_to": end_text,
                "page_size": "100",
                "sort_order": "asc",
            }
            if next_token:
                params["next_page_token"] = next_token
            payload = self._getter(
                token,
                "/contact_center/analytics/log/historical/engagement",
                params,
            )
            rows.extend(_rows(payload, "engagement_logs", "engagements"))
            next_token = str(payload.get("next_page_token") or "").strip()
            if not next_token:
                break
        return rows

    def _historical_agent_performance(
        self,
        token: str,
        *,
        start_text: str,
        end_text: str,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        next_token = ""
        for _ in range(50):
            params = {
                "from": start_text,
                "to": end_text,
                "timezone": "UTC",
                "page_size": "100",
            }
            if next_token:
                params["next_page_token"] = next_token
            payload = self._getter(
                token,
                "/contact_center/analytics/dataset/historical/agent_performance",
                params,
            )
            rows.extend(
                _rows(
                    payload,
                    "agent_performance",
                    "agent_performance_data",
                    "agent_performance_dataset",
                )
            )
            next_token = str(payload.get("next_page_token") or "").strip()
            if not next_token:
                break
        return rows

    def _engagement_recordings(
        self,
        token: str,
        *,
        engagement_id: str,
        start_text: str,
        end_text: str,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        next_token = ""
        path = (
            "/contact_center/engagements/"
            f"{urllib.parse.quote(engagement_id, safe='')}/recordings"
        )
        for _ in range(20):
            params = {
                "channel_type": "voice",
                "channel": "voice",
                "from": start_text,
                "to": end_text,
                "page_size": "30",
            }
            if next_token:
                params["next_page_token"] = next_token
            payload = self._getter(token, path, params)
            rows.extend(_rows(payload, "recordings"))
            next_token = str(payload.get("next_page_token") or "").strip()
            if not next_token:
                break
        return rows

    def _resolve_yaron(
        self,
        token: str,
        *,
        active_users: list[dict[str, Any]] | None = None,
    ) -> dict[str, str]:
        configured_email = str(os.getenv("ZOOM_WEEKLY_YARON_RECIPIENT_EMAIL") or "").strip()
        candidates = active_users if active_users is not None else self._active_users(token)
        matches = []
        for row in candidates:
            email = str(row.get("email") or "").strip()
            name = " ".join(
                str(part or "").strip()
                for part in (row.get("first_name"), row.get("last_name"))
                if str(part or "").strip()
            )
            display = str(row.get("display_name") or name).strip()
            if configured_email:
                matched = email.casefold() == configured_email.casefold()
            else:
                matched = _norm(name) == "yaron bachar" or _norm(display) == "yaron bachar"
            if matched and email:
                matches.append({"id": str(row.get("id") or ""), "email": email, "name": display or name})
        if len(matches) != 1:
            raise RuntimeError("the exact Yaron Bachar Zoom recipient was not uniquely verified")
        return matches[0]

    def _resolve_team_chat_recipient(
        self,
        token: str,
        *,
        exact_recipient: str,
    ) -> dict[str, str]:
        label, address = _configured_internal_request_contact(exact_recipient)
        return _match_configured_internal_request_user(
            self._active_users(token),
            label,
            address,
        )

    def _resolve_operator_team_chat_recipient(
        self,
        token: str,
        *,
        exact_recipient: str,
    ) -> dict[str, str]:
        requested = " ".join(str(exact_recipient or "").split())
        if not requested or len(requested) > 320:
            raise ValueError("exact_recipient must be one Zoom email address or full name")
        requested_email = requested.casefold() if EMAIL.fullmatch(requested) else ""
        requested_name = _norm(requested) if not requested_email else ""
        contacts: list[dict[str, Any]] = []
        next_token = ""
        for _ in range(20):
            params = {"page_size": "100"}
            if next_token:
                params["next_page_token"] = next_token
            payload = self._getter(token, "/chat/users/me/contacts", params)
            contacts.extend(_rows(payload, "contacts"))
            next_token = str(payload.get("next_page_token") or "").strip()
            if not next_token:
                break

        matches: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for row in contacts:
            email_address = str(
                row.get("email")
                or row.get("email_address")
                or row.get("contact_email")
                or ""
            ).strip()
            joined_name = " ".join(
                str(part or "").strip()
                for part in (row.get("first_name"), row.get("last_name"))
                if str(part or "").strip()
            )
            name = " ".join(
                str(row.get("display_name") or row.get("name") or joined_name).split()
            )
            matched = (
                bool(requested_email)
                and email_address.casefold() == requested_email
            ) or (
                bool(requested_name)
                and name
                and _norm(name) == requested_name
            )
            if not matched or not email_address or not EMAIL.fullmatch(email_address):
                continue
            contact_id = str(
                row.get("id")
                or row.get("contact_id")
                or row.get("member_id")
                or ""
            ).strip()
            member_id = str(row.get("member_id") or row.get("memberId") or "").strip()
            key = (contact_id, email_address.casefold())
            if key in seen:
                continue
            seen.add(key)
            matches.append(
                {
                    "id": contact_id,
                    "memberId": member_id,
                    "email": email_address,
                    "name": name or email_address,
                }
            )
        if len(matches) != 1:
            raise RuntimeError("the exact Zoom contact was not uniquely resolved")
        return matches[0]

    def _operator_team_chat_channels(
        self,
        token: str,
        *,
        max_channels: int,
    ) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        next_token = ""
        for _ in range(20):
            remaining = max_channels - len(rows)
            if remaining <= 0:
                break
            params = {"page_size": str(min(100, remaining))}
            if next_token:
                params["next_page_token"] = next_token
            payload = self._getter(token, "/chat/users/me/channels", params)
            for raw in _rows(payload, "channels"):
                channel_id = str(raw.get("id") or raw.get("channel_id") or "").strip()
                if not ZOOM_ID.fullmatch(channel_id):
                    continue
                rows.append(
                    {
                        "id": channel_id,
                        "name": str(raw.get("name") or "")[:300],
                        "type": str(raw.get("type") or "")[:80],
                    }
                )
                if len(rows) >= max_channels:
                    break
            next_token = str(payload.get("next_page_token") or "").strip()
            if not next_token:
                break
        return rows

    def _find_operator_team_chat_messages(
        self,
        token: str,
        *,
        recipient_email: str,
        body: str,
        from_date: date,
    ) -> list[str]:
        matches: list[str] = []
        next_token = ""
        for _ in range(20):
            params = {
                "to_contact": recipient_email,
                "from": from_date.isoformat(),
                "to": datetime.now(timezone.utc).date().isoformat(),
                "page_size": "100",
            }
            if next_token:
                params["next_page_token"] = next_token
            payload = self._getter(token, "/chat/users/me/messages", params)
            for row in _rows(payload, "messages"):
                if str(row.get("message") or "") != body:
                    continue
                message_id = str(row.get("id") or row.get("message_id") or "").strip()
                if message_id:
                    matches.append(message_id)
            next_token = str(payload.get("next_page_token") or "").strip()
            if not next_token:
                break
        return matches

    def _resume_operator_team_chat_send(
        self,
        token: str,
        *,
        prior: dict[str, Any],
        recipient: dict[str, str],
        body: str,
        request_hash: str,
    ) -> dict[str, Any]:
        prior_recipient = (
            prior.get("recipient")
            if isinstance(prior.get("recipient"), dict)
            else {}
        )
        same_request = (
            str(prior.get("operation") or "") == "operator_team_chat_send"
            and str(prior.get("requestSha256") or "") == request_hash
            and str(prior_recipient.get("email") or "").casefold()
            == recipient["email"].casefold()
            and str(prior.get("messageBody") or "") == body
        )
        if not same_request:
            return {
                **prior,
                "ok": False,
                "status": "blocked",
                "reason": "idempotency key is already bound to a different Zoom request",
                "retryAllowed": False,
            }
        if prior.get("status") == "sent" and prior.get("readbackVerified") is True:
            return {**prior, "ok": True, "duplicatePrevented": True}
        attempted_at = _utc_datetime(
            prior.get("providerAttemptAtUtc"),
            "providerAttemptAtUtc",
        )
        matches = self._find_operator_team_chat_messages(
            token,
            recipient_email=recipient["email"],
            body=body,
            from_date=attempted_at.date(),
        )
        if len(matches) != 1:
            return {
                **prior,
                "ok": False,
                "status": "uncertain",
                "reason": "pending Zoom send could not be uniquely reconciled",
                "retryAllowed": False,
            }
        return self._verify_operator_team_chat_message(
            token,
            pending=prior,
            message_id=matches[0],
            reconciled=True,
        )

    def _verify_operator_team_chat_message(
        self,
        token: str,
        *,
        pending: dict[str, Any],
        message_id: str,
        reconciled: bool,
    ) -> dict[str, Any]:
        recipient = (
            pending.get("recipient")
            if isinstance(pending.get("recipient"), dict)
            else {}
        )
        readback = self._getter(
            token,
            f"/chat/users/me/messages/{urllib.parse.quote(message_id, safe='')}",
            {"to_contact": str(recipient.get("email") or "")},
        )
        readback_id = str(
            readback.get("id") or readback.get("message_id") or ""
        ).strip()
        readback_sender = str(
            readback.get("sender")
            or readback.get("sender_email")
            or readback.get("sender_name")
            or ""
        ).strip()
        if (
            readback_id != message_id
            or str(readback.get("message") or "")
            != str(pending.get("messageBody") or "")
            or not readback_sender
        ):
            return {
                **pending,
                "ok": False,
                "status": "uncertain",
                "reason": "Zoom message id/body/sender readback did not match",
                "retryAllowed": False,
            }
        receipt = {
            **pending,
            "status": "sent",
            "sent": True,
            "messageId": message_id,
            "readbackVerified": True,
            "senderReadbackVerified": True,
            "recipientReadbackVerified": True,
            "sentAtUtc": datetime.now(timezone.utc).isoformat(),
            "reconciled": reconciled,
            "retryAllowed": False,
        }
        self._append_team_chat_journal(receipt)
        return {**receipt, "ok": True, "duplicatePrevented": reconciled}

    def _docs_archive_rows(
        self,
        token: str,
        *,
        start_utc: str,
        end_utc: str,
        product: str,
        max_records: int,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        next_token = ""
        for _ in range(40):
            remaining = max_records - len(rows)
            if remaining <= 0:
                break
            params = {
                "from": start_utc,
                "to": end_utc,
                "page_size": str(min(100, remaining)),
            }
            if next_token:
                params["next_page_token"] = next_token
            payload = self._getter(token, "/docs/archives", params)
            for row in _rows(payload, "archives", "data"):
                row_product = str(row.get("product") or "").strip().casefold()
                if product and row_product != product:
                    continue
                rows.append(row)
                if len(rows) >= max_records:
                    break
            next_token = str(payload.get("next_page_token") or "").strip()
            if not next_token:
                break
        return rows

    def _resolve_team_chat_sender(
        self,
        token: str,
        *,
        active_users: list[dict[str, Any]] | None = None,
    ) -> dict[str, str]:
        sender_id = str(os.getenv("ZOOM_TEAM_CHAT_SENDER_USER_ID") or "").strip()
        if not sender_id or not ZOOM_ID.fullmatch(sender_id):
            raise RuntimeError(
                "ZOOM_TEAM_CHAT_SENDER_USER_ID must contain the exact active S2S owner user id"
            )
        if _s2s_token_owner_id(token) != sender_id:
            raise RuntimeError(
                "the configured Team Chat sender does not match the Support Dashboard Calls token owner"
            )
        candidates = active_users if active_users is not None else self._active_users(token)
        matches = [
            row
            for row in candidates
            if str(row.get("id") or "").strip() == sender_id
            and str(row.get("email") or "").strip().casefold().endswith(
                "@novapointofsale.com"
            )
            and str(row.get("status") or "active").strip().casefold() == "active"
        ]
        if len(matches) != 1:
            raise RuntimeError(
                "the configured Team Chat sender was not uniquely verified as an active Nova user"
            )
        row = matches[0]
        email = str(row.get("email") or "").strip()
        name = " ".join(
            str(part or "").strip()
            for part in (row.get("first_name"), row.get("last_name"))
            if str(part or "").strip()
        )
        display = str(row.get("display_name") or name).strip()
        return {
            "id": sender_id,
            "email": email,
            "name": display or name,
        }

    def _active_users(self, token: str) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        next_token = ""
        for _ in range(20):
            params = {"status": "active", "page_size": "300"}
            if next_token:
                params["next_page_token"] = next_token
            payload = self._getter(token, "/users", params)
            candidates.extend(_rows(payload, "users"))
            next_token = str(payload.get("next_page_token") or "").strip()
            if not next_token:
                break
        return candidates

    def _reconcile_pending_team_chat(
        self,
        token: str,
        *,
        prior: dict[str, Any],
        sender: str,
        sender_identity: dict[str, str],
        recipient: dict[str, str],
        request_body: str,
        reply_main_message_id: str = "",
    ) -> dict[str, Any]:
        if _prior_team_chat_request_sha256(prior, recipient) != hashlib.sha256(
            request_body.encode("utf-8")
        ).hexdigest():
            return {
                **prior,
                "ok": False,
                "status": "blocked",
                "reason": "idempotency key is already bound to a different Zoom request",
                "retryAllowed": False,
            }
        prior_sender = (
            prior.get("sender") if isinstance(prior.get("sender"), dict) else {}
        )
        prior_sender_id = str(prior_sender.get("id") or "").strip()
        if prior_sender_id and prior_sender_id != sender:
            return {
                **prior,
                "ok": False,
                "status": "blocked",
                "reason": "idempotency key is already bound to a different Zoom sender",
                "retryAllowed": False,
            }
        prior_email = str((prior.get("recipient") or {}).get("email") or "").casefold()
        if prior_email != recipient["email"].casefold():
            return {
                **prior,
                "ok": False,
                "status": "blocked",
                "reason": "idempotency key is already bound to a different Zoom recipient",
                "retryAllowed": False,
            }
        if (
            str(prior.get("replyMainMessageId") or "").strip()
            != str(reply_main_message_id or "").strip()
        ):
            return {
                **prior,
                "ok": False,
                "status": "blocked",
                "reason": (
                    "idempotency key is already bound to a different Zoom "
                    "reply parent"
                ),
                "retryAllowed": False,
            }
        body = str(prior.get("messageBody") or "")
        if (
            not body
            or prior.get("messageSha256")
            != hashlib.sha256(body.encode("utf-8")).hexdigest()
        ):
            return {
                **prior,
                "ok": False,
                "status": "uncertain",
                "reason": "pending Zoom request journal did not match its message body",
                "retryAllowed": False,
            }
        pending_at = _utc_datetime(prior.get("pendingAtUtc"), "pendingAtUtc")
        matches = self._find_exact_team_chat_messages(
            token,
            sender=sender,
            recipient_email=recipient["email"],
            body=body,
            from_date=pending_at.date(),
            reply_main_message_id=str(reply_main_message_id or "").strip(),
        )
        if len(matches) != 1:
            return {
                **prior,
                "ok": False,
                "status": "uncertain",
                "reason": "pending Zoom send could not be uniquely reconciled",
                "retryAllowed": False,
            }
        return self._verify_team_chat_message(
            token,
            key=str(prior["idempotencyKey"]),
            lane=str(prior["requestedByLane"]),
            authorization=str(prior["authorizationContext"]),
            sender=sender,
            sender_identity=sender_identity,
            recipient=recipient,
            body=body,
            message_id=matches[0],
            reconciled=True,
            internal_request_local_date=str(
                prior.get("internalRequestLocalDate") or ""
            ),
            first_message_greeting_included=bool(
                prior.get("firstMessageGreetingIncluded")
            ),
            reply_main_message_id=str(reply_main_message_id or "").strip(),
        )

    def _find_exact_team_chat_messages(
        self,
        token: str,
        *,
        sender: str,
        recipient_email: str,
        body: str,
        from_date: date,
        reply_main_message_id: str = "",
    ) -> list[str]:
        def _collect(payload: Any) -> list[str]:
            found: list[str] = []
            for row in _rows(payload, "messages"):
                if (
                    str(row.get("message") or "") == body
                    and str(row.get("reply_main_message_id") or "").strip()
                    == str(reply_main_message_id or "").strip()
                ):
                    message_id = str(row.get("id") or row.get("message_id") or "").strip()
                    if message_id:
                        found.append(message_id)
            return found

        today = datetime.now(timezone.utc).date()
        matches = []
        next_token = ""
        echo_untrusted = False
        for _ in range(20):
            params = {
                "to_contact": recipient_email,
                "from": from_date.isoformat(),
                "to": today.isoformat(),
                "page_size": "100",
            }
            if next_token:
                params["next_page_token"] = next_token
            payload = self._getter(
                token,
                f"/chat/users/{urllib.parse.quote(sender, safe='')}/messages",
                params,
            )
            matches.extend(_collect(payload))
            if not echo_untrusted:
                # Zoom may clamp the range and echo the window it actually
                # served. A clamped window cannot prove the requested span
                # was covered, so the range is untrusted.
                try:
                    echoed_from = datetime.fromisoformat(
                        str(payload.get("from") or "").strip()
                    ).date()
                except (TypeError, ValueError):
                    echoed_from = None
                if echoed_from is not None and echoed_from > from_date:
                    echo_untrusted = True
            next_token = str(payload.get("next_page_token") or "").strip()
            if not next_token:
                break
        if echo_untrusted and not matches:
            # The documented list endpoint only honors a bounded recent
            # window (observed 24h), which permanently strands reconciliation
            # of older pending sends. The per-day endpoint honors the exact
            # date, so fall back to a bounded day-by-day scan.
            span_days = (today - from_date).days
            if 0 <= span_days <= 92:
                day = from_date
                while day <= today:
                    day_payload = self._getter(
                        token,
                        f"/chat/users/{urllib.parse.quote(sender, safe='')}/messages",
                        {
                            "to_contact": recipient_email,
                            "date": day.isoformat(),
                            "page_size": "100",
                        },
                    )
                    day_matches = _collect(day_payload)
                    matches.extend(day_matches)
                    if day_matches:
                        break
                    day += timedelta(days=1)
        return matches

    def _verify_team_chat_message(
        self,
        token: str,
        *,
        key: str,
        lane: str,
        authorization: str,
        sender: str,
        sender_identity: dict[str, str],
        recipient: dict[str, str],
        body: str,
        message_id: str,
        reconciled: bool,
        internal_request_local_date: str,
        first_message_greeting_included: bool,
        reply_main_message_id: str = "",
    ) -> dict[str, Any]:
        readback = self._getter(
            token,
            f"/chat/users/{urllib.parse.quote(sender, safe='')}/messages/"
            f"{urllib.parse.quote(message_id, safe='')}",
            {"to_contact": recipient["email"]},
        )
        readback_id = str(readback.get("id") or readback.get("message_id") or "").strip()
        readback_sender = str(readback.get("sender") or "").strip()
        sender_matches = (
            bool(readback_sender)
            and readback_sender.casefold()
            == str(sender_identity.get("email") or "").casefold()
        )
        reply_parent_matches = (
            str(readback.get("reply_main_message_id") or "").strip()
            == str(reply_main_message_id or "").strip()
        )
        if (
            readback_id != message_id
            or str(readback.get("message") or "") != body
            or not sender_matches
            or not reply_parent_matches
        ):
            return {
                "ok": False,
                "status": "uncertain",
                "sent": False,
                "channel": "zoom",
                "sender": sender_identity,
                "recipient": recipient,
                "messageId": message_id,
                "reason": (
                    "Zoom message id/body/sender readback/reply-parent did not match"
                ),
                "retryAllowed": False,
            }
        receipt = {
            "sent": True,
            "status": "sent",
            "channel": "zoom",
            "readbackVerified": True,
            "senderReadbackVerified": True,
            "recipientReadbackVerified": True,
            "sender": sender_identity,
            "recipient": recipient,
            "requestedByLane": lane,
            "authorizationContext": authorization,
            "idempotencyKey": key,
            "messageId": message_id,
            "messageBody": body,
            "messageSha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
            "requestSha256": hashlib.sha256(
                _team_chat_request_content(body, recipient).encode("utf-8")
            ).hexdigest(),
            "replyMainMessageId": str(reply_main_message_id or "").strip(),
            "internalRequestLocalDate": internal_request_local_date,
            "firstMessageGreetingIncluded": bool(
                first_message_greeting_included
            ),
            "sentAtUtc": datetime.now(timezone.utc).isoformat(),
            "reconciled": reconciled,
            "retryAllowed": False,
        }
        self._append_team_chat_journal(receipt)
        return {**receipt, "ok": True, "duplicatePrevented": reconciled}

    def _team_chat_journal_entry(self, key: str) -> dict[str, Any]:
        return _journal_entry(self._team_chat_journal_path, key)

    def _append_team_chat_journal(self, entry: dict[str, Any]) -> None:
        _append_journal(self._team_chat_journal_path, entry, prefix=".team-chat-")

    def _find_existing_message(
        self,
        token: str,
        *,
        sender: str,
        recipient_email: str,
        body: str,
        end_value: datetime,
    ) -> str:
        payload = self._getter(
            token,
            f"/chat/users/{urllib.parse.quote(sender, safe='')}/messages",
            {
                "to_contact": recipient_email,
                "from": end_value.date().isoformat(),
                "to": datetime.now(timezone.utc).date().isoformat(),
                "page_size": "100",
            },
        )
        for row in _rows(payload, "messages"):
            if str(row.get("message") or "") == body:
                return str(row.get("id") or row.get("message_id") or "").strip()
        return ""

    def _journal_entry(self, key: str) -> dict[str, Any]:
        try:
            lines = self._journal_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return {}
        for line in reversed(lines[-500:]):
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(entry, dict) and entry.get("idempotencyKey") == key:
                return entry
        return {}

    def _append_journal(self, entry: dict[str, Any]) -> None:
        self._journal_path.parent.mkdir(parents=True, exist_ok=True)
        existing = ""
        try:
            existing = self._journal_path.read_text(encoding="utf-8")
        except OSError:
            pass
        descriptor, temporary = tempfile.mkstemp(
            prefix=".weekly-yaron-",
            dir=self._journal_path.parent,
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(existing)
                handle.write(json.dumps(entry, sort_keys=True) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o660)
            os.replace(temporary, self._journal_path)
            temporary = ""
        finally:
            if temporary:
                Path(temporary).unlink(missing_ok=True)

    @staticmethod
    def _receipt(
        *,
        key: str,
        start_text: str,
        end_text: str,
        message_id: str,
        message_body: str,
        metrics: dict[str, Any],
        ticket_total: int,
        reconciled: bool,
        sender: dict[str, str],
        recipient: dict[str, str],
        request_sha256: str,
        queue_hint: str,
    ) -> dict[str, Any]:
        return {
            "sent": True,
            "status": "sent",
            "channel": "zoom",
            "readbackVerified": True,
            "senderReadbackVerified": True,
            "recipientReadbackVerified": True,
            "sender": sender,
            "recipient": recipient,
            "idempotencyKey": key,
            "requestSha256": request_sha256,
            "startUtc": start_text,
            "endUtc": end_text,
            "queueHint": queue_hint,
            "messageId": message_id,
            "messageBody": message_body,
            "sentAtUtc": datetime.now(timezone.utc).isoformat(),
            "reconciled": reconciled,
            "phoneCalls": metrics,
            "tickets": {"total": ticket_total},
        }


def _safe_error(exc: Exception) -> str:
    return f"{exc.__class__.__name__}: Zoom authentication, scope, or read verification failed"


def _operator_team_chat_request_hash(
    recipient: dict[str, str],
    body: str,
) -> str:
    payload = {
        "recipientEmail": str(recipient.get("email") or "").strip().casefold(),
        "message": body,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _zoom_get_text(token: str, url: str, max_bytes: int) -> str:
    _validate_zoom_download_url(url)
    limit = max(1_001, min(int(max_bytes), QUALITY_MAX_TRANSCRIPT_CHARS + 1))
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "text/plain,text/vtt,application/json",
        },
    )
    try:
        opener = urllib.request.build_opener(_ZoomTranscriptRedirectBlocker())
        with opener.open(request, timeout=45) as response:
            data = response.read(limit)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Zoom transcript read failed with HTTP {exc.code}") from exc
    return data.decode("utf-8", errors="replace")


class _ZoomTranscriptRedirectBlocker(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        raise RuntimeError("Zoom transcript redirects are not allowed")


def _zoom_post_json(token: str, path: str, body: dict[str, Any]) -> dict[str, Any]:
    base = os.getenv("ZOOM_BASE_URL", "https://api.zoom.us/v2").rstrip("/")
    request = urllib.request.Request(
        base + path,
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            data = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Zoom API write failed with HTTP {exc.code}") from exc
    payload = json.loads(data) if data.strip() else {}
    return payload if isinstance(payload, dict) else {}


def _team_chat_message(value: str) -> str:
    body = str(value or "").strip()
    if not 1 <= len(body) <= 600 or body.count("\n") > 1:
        raise ValueError("message must be one brief conversational request of 1-600 characters")
    if any(ord(character) < 32 and character not in {"\n", "\r", "\t"} for character in body):
        raise ValueError("message contains unsupported control characters")
    return body


def _internal_request_label(recipient: dict[str, str]) -> str:
    alias = str(recipient.get("policyAlias") or "").strip()
    label = alias.partition(":")[2].title() if ":" in alias else ""
    if not label:
        label = str(recipient.get("name") or "").split(" ", 1)[0]
    if not re.fullmatch(r"[A-Za-z][A-Za-z'-]{0,39}", label):
        raise ValueError("the configured internal request recipient name is invalid")
    return label


def _team_chat_request_content(
    value: str,
    recipient: dict[str, str],
) -> str:
    """Return greeting-free request content so retries remain day-independent."""

    body = _team_chat_message(value)
    label = _internal_request_label(recipient)
    body = re.sub(
        rf"(?is)^\s*(?:hey|hi)\s+{re.escape(label)}\s*[,!:.-]+\s*",
        "",
        body,
        count=1,
    ).strip()
    if not body:
        raise ValueError("message must include a request after the greeting")
    return _team_chat_message(body)


def _render_internal_request_message(
    request_body: str,
    recipient: dict[str, str],
    *,
    include_greeting: bool,
) -> str:
    body = _team_chat_request_content(request_body, recipient)
    if include_greeting:
        body = f"Hey {_internal_request_label(recipient)}, {body}"
    return _team_chat_message(body)


def _prior_team_chat_request_sha256(
    prior: dict[str, Any],
    recipient: dict[str, str],
) -> str:
    stored = str(prior.get("requestSha256") or "").strip().casefold()
    if re.fullmatch(r"[0-9a-f]{64}", stored):
        return stored
    message = str(prior.get("messageBody") or "")
    if not message:
        return ""
    try:
        content = _team_chat_request_content(message, recipient)
    except ValueError:
        return ""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _configured_internal_request_contact(exact_recipient: str) -> tuple[str, str]:
    alias = " ".join(str(exact_recipient or "").split()).casefold()
    if alias == "configured:julio":
        label = "Julio"
        address = str(
            os.getenv("ZOOM_INTERNAL_REQUEST_JULIO_CONTACT")
            or os.getenv("ZOOM_SINGAPORE_JULIO_CONTACT")
            or ""
        ).strip()
    elif alias == "configured:wiko":
        label = "Wiko"
        address = str(os.getenv("ZOOM_INTERNAL_REQUEST_WIKO_CONTACT") or "").strip()
    else:
        raise ValueError(
            "exact_recipient must be configured:julio or configured:wiko; "
            "use a tagged Salesforce ticket request for every other employee"
        )
    if not address or not EMAIL.fullmatch(address):
        raise RuntimeError(f"the configured {label} Zoom contact is unavailable")
    return label, address


def _match_configured_internal_request_user(
    rows: list[dict[str, Any]],
    label: str,
    address: str,
) -> dict[str, str]:
    matches: list[dict[str, str]] = []
    expected_name = _norm(label)
    for row in rows:
        email = str(row.get("email") or "").strip()
        first_name = " ".join(str(row.get("first_name") or "").split())
        name = " ".join(
            str(part or "").strip()
            for part in (row.get("first_name"), row.get("last_name"))
            if str(part or "").strip()
        )
        display = " ".join(str(row.get("display_name") or name).split())
        name_verified = (
            _norm(first_name) == expected_name
            or _norm(display) == expected_name
            or _norm(display).startswith(f"{expected_name} ")
        )
        if email.casefold() == address.casefold() and name_verified:
            matches.append(
                {
                    "id": str(row.get("id") or ""),
                    "email": email,
                    "name": display or name,
                    "policyAlias": f"configured:{expected_name}",
                }
            )
    if len(matches) != 1:
        raise RuntimeError(
            f"the configured {label} Zoom recipient was not uniquely verified as an active user"
        )
    return matches[0]


def _completed_team_chat_result(
    prior: dict[str, Any],
    *,
    exact_recipient: str,
    body: str,
    sender_id: str,
    reply_main_message_id: str = "",
) -> dict[str, Any]:
    try:
        _label, requested = _configured_internal_request_contact(exact_recipient)
    except (RuntimeError, ValueError):
        requested = ""
    prior_recipient = prior.get("recipient") if isinstance(prior.get("recipient"), dict) else {}
    prior_email = str(prior_recipient.get("email") or "").strip()
    same_recipient = bool(requested) and prior_email.casefold() == requested.casefold()
    same_message = _prior_team_chat_request_sha256(
        prior,
        prior_recipient,
    ) == hashlib.sha256(body.encode("utf-8")).hexdigest()
    prior_sender = (
        prior.get("sender") if isinstance(prior.get("sender"), dict) else {}
    )
    prior_sender_id = str(prior_sender.get("id") or "").strip()
    same_sender = not prior_sender_id or prior_sender_id == sender_id
    same_reply_parent = (
        str(prior.get("replyMainMessageId") or "").strip()
        == str(reply_main_message_id or "").strip()
    )
    if (
        not same_recipient
        or not same_message
        or not same_sender
        or not same_reply_parent
    ):
        return {
            **prior,
            "ok": False,
            "status": "blocked",
            "reason": (
                "idempotency key is already bound to a different Zoom sender, "
                "recipient, message, or reply parent"
            ),
            "duplicatePrevented": True,
            "retryAllowed": False,
        }
    return {**prior, "ok": True, "duplicatePrevented": True}


def _s2s_token_owner_id(token: str) -> str:
    """Return the signed token's owner id without exposing any token material."""

    parts = str(token or "").strip().split(".")
    if len(parts) != 3:
        raise RuntimeError("the Support Dashboard Calls token owner could not be verified")
    encoded = parts[1]
    encoded += "=" * (-len(encoded) % 4)
    try:
        payload = json.loads(
            base64.urlsafe_b64decode(encoded.encode("ascii")).decode("utf-8")
        )
    except (ValueError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            "the Support Dashboard Calls token owner could not be verified"
        ) from exc
    owner_id = str(payload.get("uid") or "").strip() if isinstance(payload, dict) else ""
    if not ZOOM_ID.fullmatch(owner_id):
        raise RuntimeError("the Support Dashboard Calls token owner could not be verified")
    return owner_id


def _utc_datetime(value: Any, label: str) -> datetime:
    clean = str(value or "").strip()
    try:
        parsed = datetime.fromisoformat(clean.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{label} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _journal_entry(path: Path, key: str) -> dict[str, Any]:
    with _journal_lock(path):
        return _journal_entry_unlocked(path, key)


def _journal_entry_unlocked(path: Path, key: str) -> dict[str, Any]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    for line in reversed(lines[-1000:]):
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(entry, dict) and entry.get("idempotencyKey") == key:
            return entry
    return {}


def _append_journal(path: Path, entry: dict[str, Any], *, prefix: str) -> None:
    with _journal_lock(path):
        _append_journal_unlocked(path, entry, prefix=prefix)


def _append_journal_unlocked(path: Path, entry: dict[str, Any], *, prefix: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = ""
    try:
        existing = path.read_text(encoding="utf-8")
    except OSError:
        pass
    descriptor, temporary = tempfile.mkstemp(prefix=prefix, dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(existing)
            handle.write(json.dumps(entry, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o660)
        os.replace(temporary, path)
        temporary = ""
    finally:
        if temporary:
            Path(temporary).unlink(missing_ok=True)


def _claim_journal(path: Path, pending: dict[str, Any], *, prefix: str) -> dict[str, Any]:
    key = str(pending.get("idempotencyKey") or "")
    with _journal_lock(path):
        prior = _journal_entry_unlocked(path, key)
        if prior:
            return prior
        _append_journal_unlocked(path, pending, prefix=prefix)
        return {}


@contextmanager
def _journal_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(path.name + ".lock")
    with _JOURNAL_THREAD_LOCK:
        with lock_path.open("a+", encoding="utf-8") as handle:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                if fcntl is not None:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _utc_timestamp(value: str, label: str) -> tuple[str, datetime]:
    clean = str(value or "").strip()
    try:
        parsed = datetime.fromisoformat(clean.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{label} must include a timezone")
    normalized = parsed.astimezone(timezone.utc).replace(microsecond=0)
    return normalized.strftime("%Y-%m-%dT%H:%M:%SZ"), normalized


def _quality_window(start_utc: str, end_utc: str) -> tuple[str, str, datetime, datetime]:
    start_text, start_value = _utc_timestamp(start_utc, "start_utc")
    end_text, end_value = _utc_timestamp(end_utc, "end_utc")
    if end_value <= start_value:
        raise ValueError("end_utc must be after start_utc")
    if (end_value - start_value).total_seconds() > QUALITY_MAX_WINDOW_DAYS * 86400:
        raise ValueError(f"support quality reads are limited to {QUALITY_MAX_WINDOW_DAYS} days")
    return start_text, end_text, start_value, end_value


def _knowledge_window(
    start_utc: str,
    end_utc: str,
) -> tuple[str, str, datetime, datetime]:
    start_text, start_value = _utc_timestamp(start_utc, "start_utc")
    end_text, end_value = _utc_timestamp(end_utc, "end_utc")
    if end_value <= start_value:
        raise ValueError("end_utc must be after start_utc")
    if (end_value - start_value).total_seconds() > KNOWLEDGE_MAX_WINDOW_DAYS * 86400:
        raise ValueError(
            f"knowledge reads are limited to {KNOWLEDGE_MAX_WINDOW_DAYS} days"
        )
    if end_value > datetime.now(timezone.utc) + timedelta(days=1):
        raise ValueError("end_utc cannot be more than one day in the future")
    return start_text, end_text, start_value, end_value


def _docs_archive_summary(row: dict[str, Any]) -> dict[str, str]:
    return {
        "fileId": str(row.get("file_id") or row.get("fileId") or "")[:160],
        "fileName": str(row.get("file_name") or row.get("fileName") or "")[:300],
        "product": str(row.get("product") or "")[:80],
        "archiveTime": str(
            row.get("archive_time") or row.get("archiveTime") or ""
        )[:80],
        "triggerType": str(
            row.get("trigger_type") or row.get("triggerType") or ""
        )[:80],
    }


def _validate_zoom_download_url(value: str) -> None:
    parsed = urllib.parse.urlsplit(str(value or "").strip())
    hostname = str(parsed.hostname or "").rstrip(".")
    if (
        parsed.scheme != "https"
        or not hostname
        or not QUALITY_TRANSCRIPT_HOST.search(hostname)
        or parsed.username
        or parsed.password
        or parsed.fragment
    ):
        raise ValueError("Zoom returned an invalid download URL")


def _ghostbusters_overview_file_id() -> str:
    value = str(
        os.getenv("ZOOM_GHOSTBUSTERS_OVERVIEW_FILE_ID")
        or DEFAULT_GHOSTBUSTERS_OVERVIEW_FILE_ID
    ).strip()
    if value != DEFAULT_GHOSTBUSTERS_OVERVIEW_FILE_ID or not ZOOM_ID.fullmatch(value):
        raise RuntimeError("Ghost Busters Chat Overview is not the fixed approved document")
    return value


def _validate_ghostbusters_overview(
    metadata: dict[str, Any],
    file_id: str,
) -> None:
    metadata_id = str(metadata.get("file_id") or metadata.get("id") or file_id).strip()
    file_name = str(metadata.get("file_name") or metadata.get("name") or "").strip()
    if metadata_id != DEFAULT_GHOSTBUSTERS_OVERVIEW_FILE_ID:
        raise RuntimeError("Zoom returned a different Docs file")
    if _norm(file_name) != "chat overview":
        raise RuntimeError("the fixed Zoom Docs file is not named Chat Overview")


def _overview_source_date(value: str) -> str:
    try:
        parsed = date.fromisoformat(str(value or "").strip())
    except ValueError as exc:
        raise ValueError("source_date must be YYYY-MM-DD") from exc
    if parsed < date(2025, 1, 1):
        raise ValueError("source_date must be 2025 or newer")
    if parsed > datetime.now(timezone.utc).date() + timedelta(days=1):
        raise ValueError("source_date cannot be more than one day in the future")
    return parsed.isoformat()


def _public_overview_text(
    value: str,
    *,
    field_name: str,
    min_chars: int,
    max_chars: int,
) -> str:
    text = str(value or "").replace("\x00", "").strip()
    if not min_chars <= len(text) <= max_chars:
        raise ValueError(
            f"{field_name} must be {min_chars}-{max_chars} characters"
        )
    if any(
        ord(character) < 32 and character not in {"\n", "\r", "\t"}
        for character in text
    ):
        raise ValueError(f"{field_name} contains unsupported control characters")
    if EMAIL_IN_TEXT.search(text):
        raise ValueError(f"{field_name} cannot contain email addresses")
    if PHONE_IN_TEXT.search(text):
        raise ValueError(f"{field_name} cannot contain phone numbers")
    if PRIVATE_IDENTIFIER_IN_TEXT.search(text):
        raise ValueError(f"{field_name} cannot contain customer or ticket identifiers")
    if PRIVATE_CREDENTIAL_VALUE_IN_TEXT.search(text):
        raise ValueError(f"{field_name} cannot contain credential values")
    if not _private_overview_terms_are_policy(text):
        raise ValueError(f"{field_name} cannot contain private operational material")
    if re.search(r"(?<!\w)@[A-Za-z0-9._-]{2,}", text):
        raise ValueError(f"{field_name} cannot contain person mentions")
    return text


def _default_ghostbusters_link_manifest_path() -> str:
    production = Path(DEFAULT_GHOSTBUSTERS_LINK_MANIFEST)
    if production.is_file():
        return str(production)
    repository = Path(__file__).resolve().parents[4] / "docs" / "NOVA_VERSION_MATRIX.md"
    return str(repository)


def _validate_overview_links(
    markdown: str,
    manifest_path: Path,
) -> dict[str, Any]:
    try:
        manifest = manifest_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(
            "the verified Nova version/link manifest is unavailable; "
            "the overview was not changed"
        ) from exc
    allowed = _overview_https_links(manifest)
    requested = _overview_https_links(markdown)
    unsupported = sorted(requested - allowed)
    if unsupported:
        raise ValueError(
            "overview links must already exist in the verified Nova version/link "
            f"manifest; unsupported link count: {len(unsupported)}"
        )
    return {
        "manifestSha256": hashlib.sha256(manifest.encode("utf-8")).hexdigest(),
        "verifiedLinkCount": len(requested),
    }


def _overview_https_links(text: str) -> set[str]:
    candidates = re.findall(
        r"https?://[^\s<>\]\[\"']+",
        str(text or ""),
        flags=re.IGNORECASE,
    )
    links: set[str] = set()
    for candidate in candidates:
        clean = candidate.rstrip("`.,;:!?)]}")
        parsed = urllib.parse.urlsplit(clean)
        if (
            parsed.scheme.casefold() != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.fragment
        ):
            raise ValueError("overview links must be credential-free HTTPS URLs")
        normalized = urllib.parse.urlunsplit(
            (
                "https",
                str(parsed.hostname).casefold()
                + (f":{parsed.port}" if parsed.port else ""),
                parsed.path or "/",
                parsed.query,
                "",
            )
        )
        links.add(normalized)
    return links


def _private_overview_terms_are_policy(text: str) -> bool:
    for match in PRIVATE_OVERVIEW_TERMS.finditer(text):
        line_start = text.rfind("\n", 0, match.start()) + 1
        prefix = text[line_start : match.start()]
        if not PRIVATE_OVERVIEW_POLICY_PREFIX.search(prefix):
            return False
    return True


def _overview_xml_blocks(markdown: str) -> str:
    blocks: list[str] = []
    for line in markdown.splitlines():
        value = line.strip()
        if value:
            blocks.append(f"<text>{html.escape(value, quote=False)}</text>")
    if not blocks:
        raise ValueError("markdown must contain at least one nonblank line")
    return "".join(blocks)


def _top_level_doc_block_ids(value: str) -> list[str]:
    source = str(value or "").strip()
    if not source:
        return []
    try:
        root = ET.fromstring(source)
    except ET.ParseError:
        try:
            root = ET.fromstring(f"<root>{source}</root>")
        except ET.ParseError as exc:
            raise RuntimeError("the fixed Chat Overview returned invalid XML") from exc
    candidates: list[list[str]] = []
    for element in root.iter():
        ids = [
            str(child.attrib.get("id") or "").strip()
            for child in list(element)
            if ZOOM_DOC_BLOCK_ID.fullmatch(
                str(child.attrib.get("id") or "").strip()
            )
        ]
        if ids:
            candidates.append(ids)
    return max(candidates, key=len) if candidates else []


def _normalize_doc_text(value: str) -> str:
    lines = []
    for raw in str(value or "").replace("\r\n", "\n").split("\n"):
        line = " ".join(raw.strip().split())
        line = re.sub(r"^(?:[-*•]\s+|#{1,6}\s*)", "", line)
        if line:
            lines.append(line.casefold())
    return "\n".join(lines)


def _zoom_id(value: str, label: str) -> str:
    clean = str(value or "").strip()
    if not ZOOM_ID.fullmatch(clean):
        raise ValueError(f"{label} is not a valid Zoom identifier")
    return clean


def _bounded_count(value: int, label: str) -> int:
    clean = int(value)
    if clean < 0 or clean > 100000:
        raise ValueError(f"{label} is outside the weekly report range")
    return clean


def _rows(payload: dict[str, Any], *preferred: str) -> list[dict[str, Any]]:
    for key in (*preferred, "data", "records", "items"):
        value = payload.get(key)
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]
        if isinstance(value, dict):
            nested = _rows(value, *preferred)
            if nested:
                return nested
    return []


def _norm(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(value or "").casefold()))


def _is_voice_engagement(row: dict[str, Any]) -> bool:
    return _engagement_channel(row) == "voice"


def _engagement_channel(row: dict[str, Any]) -> str:
    values: list[str] = []
    for key in ("channel", "channel_type", "channelType", "media_type"):
        values.append(str(row.get(key) or ""))
    channels = row.get("channels")
    if isinstance(channels, list):
        for item in channels:
            if isinstance(item, dict):
                values.extend(
                    str(item.get(key) or "")
                    for key in ("channel", "channel_type", "channelType", "type")
                )
            else:
                values.append(str(item or ""))
    normalized = {_norm(value) for value in values if str(value).strip()}
    voice = bool(normalized & {"voice", "phone", "call", "voice call"})
    chat = bool(
        normalized
        & {
            "chat",
            "messaging",
            "message",
            "web chat",
            "webchat",
            "sms",
        }
    )
    if voice == chat:
        return "unknown"
    return "voice" if voice else "chat"


def _quality_row_agents(row: dict[str, Any]) -> list[dict[str, str]]:
    raw: list[Any] = []
    for key in ("users", "agents"):
        value = row.get(key)
        if isinstance(value, list):
            raw.extend(value)
    result: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        user_id = str(
            item.get("user_id")
            or item.get("userId")
            or item.get("agent_id")
            or item.get("agentId")
            or item.get("id")
            or ""
        ).strip()
        name = " ".join(
            str(
                item.get("user_name")
                or item.get("display_name")
                or item.get("agent_name")
                or item.get("name")
                or ""
            ).split()
        )[:160]
        if user_id or name:
            result.append({"id": user_id, "name": name})
    return result


def _summarize_quality_voice_engagements(
    rows: list[dict[str, Any]],
    *,
    start_value: datetime,
    end_value: datetime,
    roster: dict[str, Any],
    limit: int,
) -> dict[str, Any]:
    agents = roster.get("agents") if isinstance(roster.get("agents"), list) else []
    roster_by_id = {
        str(item.get("id") or ""): str(item.get("name") or "")
        for item in agents
        if isinstance(item, dict)
    }
    roster_names = {
        _norm(str(item.get("name") or "")): str(item.get("id") or "")
        for item in agents
        if isinstance(item, dict)
    }
    engagements: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(rows):
        if not _is_voice_engagement(row):
            continue
        start = _row_time(row)
        if start and not (start_value <= start < end_value):
            continue
        engagement_id = str(row.get("engagement_id") or row.get("engagementId") or "").strip()
        if not engagement_id:
            raise RuntimeError(f"Zoom voice engagement row {index} has no engagement_id")
        if not ZOOM_ID.fullmatch(engagement_id):
            raise RuntimeError(f"Zoom voice engagement row {index} has an invalid engagement_id")
        matched_ids: set[str] = set()
        for participant in _quality_row_agents(row):
            user_id = participant["id"]
            if user_id in roster_by_id:
                matched_ids.add(user_id)
                continue
            matched = roster_names.get(_norm(participant["name"]))
            if matched:
                matched_ids.add(matched)
        if not matched_ids:
            continue
        item = engagements.setdefault(
            engagement_id,
            {
                "engagementId": engagement_id,
                "startUtc": start.strftime("%Y-%m-%dT%H:%M:%SZ") if start else "",
                "direction": _direction(row),
                "agentIds": set(),
            },
        )
        item["agentIds"].update(matched_ids)

    ordered = sorted(
        engagements.values(),
        key=lambda item: (str(item.get("startUtc") or ""), str(item.get("engagementId") or "")),
    )
    truncated = len(ordered) > limit
    per_agent = []
    for raw in agents:
        user_id = str(raw.get("id") or "")
        count = sum(
            1
            for item in engagements.values()
            if user_id in item.get("agentIds", set())
        )
        per_agent.append({"id": user_id, "name": str(raw.get("name") or ""), "voiceEngagements": count})
    selected = [
        {
            "engagementId": str(item.get("engagementId") or ""),
            "startUtc": str(item.get("startUtc") or ""),
            "direction": str(item.get("direction") or "unknown"),
            "agents": [
                {"id": user_id, "name": roster_by_id[user_id]}
                for user_id in sorted(item.get("agentIds", set()))
            ],
        }
        for item in ordered[:limit]
    ]
    return {
        "ok": True,
        "status": "partial" if truncated else "ok",
        "startUtc": start_value.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "endUtc": end_value.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "fixedRosterCount": len(agents),
        "totalVoiceEngagements": len(ordered),
        "returnedVoiceEngagements": len(selected),
        "truncated": truncated,
        "engagements": selected,
        "perAgent": per_agent,
        "coverageGaps": ["truncated_voice_engagement_inventory"] if truncated else [],
        "source": "Zoom Contact Center historical engagement log, fixed roster, voice only",
    }


QUALITY_PERFORMANCE_METRICS = (
    "engagement_count",
    "inbound_engagement_count",
    "outbound_engagement_count",
    "talk_duration",
    "hold_duration",
    "wrap_up_duration",
    "handling_duration",
    "total_duration",
    "transfer_count",
    "conference_count",
    "parked_count",
    "channel_switch_count",
)


def _summarize_quality_agent_performance(
    rows: list[dict[str, Any]],
    *,
    start_value: datetime,
    end_value: datetime,
    roster: dict[str, Any],
) -> dict[str, Any]:
    agents = roster.get("agents") if isinstance(roster.get("agents"), list) else []
    roster_by_id = {
        str(item.get("id") or ""): str(item.get("name") or "")
        for item in agents
        if isinstance(item, dict)
    }
    names_to_ids: dict[str, list[str]] = defaultdict(list)
    for user_id, name in roster_by_id.items():
        names_to_ids[_norm(name)].append(user_id)
    summaries = {
        user_id: {
            "id": user_id,
            "name": name,
            "rowCount": 0,
            "evidenceIds": [],
            "matchBasis": set(),
            "metrics": defaultdict(float),
        }
        for user_id, name in roster_by_id.items()
    }
    unmatched = 0
    for row in rows:
        user_id = str(
            row.get("user_id")
            or row.get("agent_id")
            or row.get("cc_user_id")
            or ""
        ).strip()
        user_name = " ".join(
            str(
                row.get("user_name")
                or row.get("agent_name")
                or row.get("display_name")
                or ""
            ).split()
        )
        match_basis = ""
        matched_id = user_id if user_id in roster_by_id else ""
        if matched_id:
            match_basis = "roster_id"
        elif user_name:
            candidates = names_to_ids.get(_norm(user_name), [])
            if len(candidates) == 1:
                matched_id = candidates[0]
                match_basis = "unique_roster_name"
        if not matched_id:
            unmatched += 1
            continue
        summary = summaries[matched_id]
        summary["rowCount"] += 1
        summary["matchBasis"].add(match_basis)
        evidence_id = str(
            row.get("agent_leg_id")
            or row.get("engagement_id")
            or row.get("session_id")
            or ""
        ).strip()
        if evidence_id and evidence_id not in summary["evidenceIds"] and len(summary["evidenceIds"]) < 100:
            summary["evidenceIds"].append(evidence_id)
        metric_source = row.get("metrics") if isinstance(row.get("metrics"), dict) else row
        for key in QUALITY_PERFORMANCE_METRICS:
            value = metric_source.get(key)
            if isinstance(value, bool) or value in (None, ""):
                continue
            try:
                summary["metrics"][key] += float(value)
            except (TypeError, ValueError):
                continue

    result = []
    for raw in agents:
        summary = summaries[str(raw.get("id") or "")]
        metrics = {
            key: int(value) if float(value).is_integer() else round(float(value), 3)
            for key, value in sorted(summary["metrics"].items())
        }
        result.append(
            {
                "id": summary["id"],
                "name": summary["name"],
                "rowCount": summary["rowCount"],
                "evidenceIds": summary["evidenceIds"],
                "matchBasis": sorted(summary["matchBasis"]),
                "metrics": metrics,
            }
        )
    gaps = ["unmatched_agent_performance_rows"] if unmatched else []
    return {
        "ok": True,
        "status": "partial" if gaps else "ok",
        "startUtc": start_value.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "endUtc": end_value.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "fixedRosterCount": len(agents),
        "matchedRowCount": sum(item["rowCount"] for item in result),
        "unmatchedRowCount": unmatched,
        "perAgent": result,
        "coverageGaps": gaps,
        "source": "Zoom Contact Center historical agent performance dataset, fixed roster",
    }


def _quality_recording_summary(row: dict[str, Any]) -> dict[str, Any]:
    recording_id = str(
        row.get("recording_id")
        or row.get("recordingId")
        or row.get("id")
        or ""
    ).strip()
    duration = row.get("recording_duration")
    try:
        duration_value = max(0, int(duration)) if duration not in (None, "") else None
    except (TypeError, ValueError):
        duration_value = None
    return {
        "recordingId": recording_id if ZOOM_ID.fullmatch(recording_id) else "",
        "recordingStartUtc": str(row.get("recording_start_time") or "")[:40],
        "recordingEndUtc": str(row.get("recording_end_time") or "")[:40],
        "durationSeconds": duration_value,
        "direction": _direction(row),
        "recordingType": _norm(str(row.get("recording_type") or ""))[:80],
        "transcriptAvailable": bool(_quality_transcript_url(row)),
    }


def _quality_transcript_url(row: dict[str, Any]) -> str:
    for key in ("transcript_url", "transcriptUrl", "transcript_download_url"):
        value = str(row.get(key) or "").strip()
        if value:
            return value
    files = row.get("recording_files")
    if isinstance(files, list):
        for item in files:
            if not isinstance(item, dict):
                continue
            file_type = _norm(
                str(item.get("file_type") or item.get("recording_type") or item.get("type") or "")
            )
            if "transcript" not in file_type:
                continue
            for key in ("transcript_url", "download_url", "downloadUrl"):
                value = str(item.get(key) or "").strip()
                if value:
                    return value
    return ""


def _validate_zoom_transcript_url(value: str) -> None:
    parsed = urllib.parse.urlsplit(str(value or "").strip())
    hostname = str(parsed.hostname or "").rstrip(".")
    if parsed.scheme != "https" or not hostname or not QUALITY_TRANSCRIPT_HOST.search(hostname):
        raise ValueError("Zoom returned an invalid transcript download host")
    path = urllib.parse.unquote(parsed.path or "")
    if not path.startswith("/v2/contact_center/") or "/transcript" not in path.casefold():
        raise ValueError("Zoom returned an invalid transcript download path")
    if parsed.username or parsed.password or parsed.fragment:
        raise ValueError("Zoom returned an invalid transcript download URL")


def _quality_transcript_text(value: str) -> str:
    text = str(value or "").replace("\x00", "")
    return "".join(
        character
        for character in text
        if ord(character) >= 32 or character in {"\n", "\r", "\t"}
    ).strip()


def _summarize_report_engagements(
    rows: list[dict[str, Any]],
    *,
    start_value: datetime,
    end_value: datetime,
    roster: dict[str, Any],
    report_id: str,
    report_name: str,
) -> dict[str, Any]:
    agents = roster.get("agents") if isinstance(roster.get("agents"), list) else []
    roster_by_id = {
        str(item.get("id") or ""): str(item.get("name") or "")
        for item in agents
        if isinstance(item, dict)
    }
    def empty_direction_totals() -> dict[str, int]:
        return {"inbound": 0, "outbound": 0, "unknown": 0, "total": 0}

    per_agent = {
        user_id: {
            "id": user_id,
            "name": name,
            **empty_direction_totals(),
            "calls": empty_direction_totals(),
            "chatSessions": empty_direction_totals(),
            "unclassifiedSessions": empty_direction_totals(),
        }
        for user_id, name in roster_by_id.items()
    }
    engagement_agents: dict[str, set[str]] = defaultdict(set)
    engagement_directions: dict[str, set[str]] = defaultdict(set)
    engagement_channels: dict[str, set[str]] = defaultdict(set)
    team = defaultdict(int)
    for index, row in enumerate(rows):
        start = _row_time(row)
        if start and not (start_value <= start < end_value):
            continue
        direction = _direction(row)
        if direction not in {"inbound", "outbound"}:
            direction = "unknown"
        engagement_id = str(row.get("engagement_id") or "").strip()
        if not engagement_id:
            raise RuntimeError(f"Zoom engagement row {index} has no engagement_id")
        participants = row.get("users") if isinstance(row.get("users"), list) else []
        matched_user_ids = {
            str(participant.get("user_id") or "").strip()
            for participant in participants
            if isinstance(participant, dict)
            and str(participant.get("user_id") or "").strip() in roster_by_id
        }
        if not matched_user_ids:
            continue
        engagement_agents[engagement_id].update(matched_user_ids)
        engagement_directions[engagement_id].add(direction)
        engagement_channels[engagement_id].add(_engagement_channel(row))

    channel_totals = {
        "voice": empty_direction_totals(),
        "chat": empty_direction_totals(),
        "unknown": empty_direction_totals(),
    }
    for engagement_id, matched_user_ids in engagement_agents.items():
        directions = engagement_directions[engagement_id]
        direction = next(iter(directions)) if len(directions) == 1 else "unknown"
        channels = engagement_channels[engagement_id] - {"unknown"}
        channel = next(iter(channels)) if len(channels) == 1 else "unknown"
        channel_totals[channel][direction] += 1
        channel_totals[channel]["total"] += 1
        detail_key = {
            "voice": "calls",
            "chat": "chatSessions",
            "unknown": "unclassifiedSessions",
        }[channel]
        for user_id in matched_user_ids:
            item = per_agent[user_id]
            item[direction] += 1
            item["total"] += 1
            item[detail_key][direction] += 1
            item[detail_key]["total"] += 1
            team[direction] += 1

    ordered_agents = [per_agent[str(item["id"])] for item in agents]
    source = (
        "Zoom Contact Center historical engagement log, all channels and queues, "
        "exact fixed report-agent roster"
    )
    if report_id:
        source += f", custom report {report_id}"
    return {
        "ok": True,
        "status": (
            "ok"
            if not team["unknown"] and not channel_totals["unknown"]["total"]
            else "partial"
        ),
        "supportQueue": "All queues",
        "reportName": report_name or "Total Calls",
        "reportId": report_id,
        "startUtc": start_value.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "endUtc": end_value.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "inbound": team["inbound"],
        "outbound": team["outbound"],
        "unknown": team["unknown"],
        "total": sum(team.values()),
        "uniqueEngagements": len(engagement_agents),
        "calls": channel_totals["voice"],
        "chatSessions": channel_totals["chat"],
        "unclassifiedSessions": channel_totals["unknown"],
        "agentEngagementTotals": {
            "inbound": team["inbound"],
            "outbound": team["outbound"],
            "unknown": team["unknown"],
            "total": sum(team.values()),
        },
        "doNotUseTotalAsCallCount": True,
        "countDefinition": (
            "sum of distinct engagements per agent across all channels and queues "
            "for the fixed report roster"
        ),
        "callCountDefinition": (
            "unique voice engagements across the fixed report roster; transfers and "
            "multi-agent handling count once in the team call total"
        ),
        "chatSessionCountDefinition": (
            "unique chat or messaging engagements across the fixed report roster; "
            "transfers and multi-agent handling count once in the team chat total"
        ),
        "coverageGaps": (
            ["unclassified_engagement_channels"]
            if channel_totals["unknown"]["total"]
            else []
        ),
        "perAgent": ordered_agents,
        "source": source,
    }


def _row_time(row: dict[str, Any]) -> datetime | None:
    for key in ("start_time", "startTime", "engagement_start_time", "created_at"):
        value = str(row.get(key) or "").strip()
        if not value:
            continue
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            continue
        if parsed.tzinfo:
            return parsed.astimezone(timezone.utc)
    return None


def _direction(row: dict[str, Any]) -> str:
    for key in ("direction", "engagement_direction", "call_direction", "channel_direction"):
        value = _norm(str(row.get(key) or ""))
        if "outbound" in value or value == "out":
            return "outbound"
        if "inbound" in value or value == "in":
            return "inbound"
    return "unknown"


def _weekly_request_sha256(
    *,
    start_text: str,
    end_text: str,
    ticket_total: int,
    queue_hint: str,
) -> str:
    payload = {
        "startUtc": start_text,
        "endUtc": end_text,
        "ticketTotal": int(ticket_total),
        "queueHint": " ".join(str(queue_hint or "").split()),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _weekly_request_matches(
    prior: dict[str, Any],
    *,
    request_sha256: str,
    start_text: str,
    end_text: str,
    ticket_total: int,
) -> bool:
    stored = str(prior.get("requestSha256") or "").strip().casefold()
    if re.fullmatch(r"[0-9a-f]{64}", stored):
        return stored == request_sha256
    try:
        prior_total = int((prior.get("tickets") or {}).get("total"))
    except (AttributeError, TypeError, ValueError):
        return False
    return (
        str(prior.get("startUtc") or "") == start_text
        and str(prior.get("endUtc") or "") == end_text
        and prior_total == int(ticket_total)
    )


def _weekly_message(
    *,
    start_value: datetime,
    end_value: datetime,
    metrics: dict[str, Any],
    ticket_total: int,
) -> str:
    start_label = f"{start_value.month}/{start_value.day}/{start_value.year}"
    inclusive_end = end_value - timedelta(days=1)
    end_label = f"{inclusive_end.month}/{inclusive_end.day}/{inclusive_end.year}"
    return "\n".join(
        [
            f"Good morning Yaron, hope you're doing well. Here are the support totals for {start_label}-{end_label}:",
            f"- Total calls: {metrics['calls']['total']}",
            f"- Total tickets: {ticket_total}",
            "Thanks.",
        ]
    )
