from __future__ import annotations

# AgentChat/direct_codex 2026-07-16T10:30:00-04:00: acknowledge auth failures and enforce guarded 90-day retirement.

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from importlib import import_module
from pathlib import Path
from typing import Any
from urllib.error import HTTPError

try:
    import fcntl
except ImportError:  # pragma: no cover - production runtime is Linux.
    fcntl = None

APPROVED_ACTIONS = {
    "scope": "command_center_singapore_ftp_only",
    "gmailRead": True,
    "uploadFailureFiles": True,
    "maintainExistingServerList": True,
    "sendZoomMessageToVerifiedJulio": True,
    "sendGmailFallbackToVerifiedJulio": False,
    "gmailMarkReadCompletedSources": True,
    "gmailMarkReadZeroSalesNotices": True,
    "gmailAutoReplyFailedTenants": False,
    # Legacy aliases remain explicit and false so older live-runtime readers
    # cannot interpret a missing key as permission to create an operational
    # ticket, review handoff, or outbound failure notice.
    "gmailMarkReadAutomatedFailures": True,
    "queueTicketAndAlexForIncompleteSources": False,
    "catalogIncompleteSourcesForTaylorStatus": True,
    "suppressOutboundFailureNotifications": True,
    "suppressSharedCustomerAndReviewFailureNotifications": True,
    "queueSalesforceTicketsForOperationalOutcomes": False,
    "queueNeedsReviewForOperationalOutcomes": False,
    "queueTicketOnlyForExplicitNewInterfaceRequest": True,
    "directChatSanitizedOutcomes": True,
    "ignoreVerifiedRetiredInterfaces": True,
}

CONFIG_VERIFIED_SUCCESS_STATUSES = {"updated", "already_current", "already_active"}
MAX_ZOOM_MESSAGE_CHARS = 600
SINGAPORE_REMINDER_MESSAGE = (
    "Hey Julio, just a reminder on this Singapore resubmission. Thanks."
)


def run_singapore_ftp_fast(
    *,
    uploader_root: str,
    state_dir: str | Path,
    server_config_path: str | Path,
    trusted_config_sender_domains: list[str] | None = None,
    output_path: Path,
    recipient_hint: str = "Julio",
    ops_env_path: str | Path = "config/ops.env",
    include_non_submissions: bool = False,
    reactivation_target: str = "",
) -> dict[str, Any]:
    """Run Grab & Upload; optionally perform a separately requested review."""
    root = Path(uploader_root).expanduser().resolve()
    private_state = Path(state_dir).expanduser().resolve()
    canonical_servers = Path(server_config_path).expanduser().resolve()
    output_path = Path(output_path).expanduser().resolve()
    ops_env = Path(ops_env_path).expanduser().resolve()
    requested_reactivation_target = _validated_reactivation_target(reactivation_target)
    preserved_remediation: dict[str, Any] = {}
    run_lock: Any = None
    try:
        preserved_remediation = _preserved_remediation(output_path)
        if not root.exists():
            raise FileNotFoundError(f"Singapore module root not found: {root}")
        _ensure_private_state(root, private_state)
        run_lock = _acquire_runner_lock(private_state / "singapore-run.lock")
        modules = _load_parser_modules(root)
        _configure_private_state(private_state, modules)
        service = _authenticate_gmail_noninteractive(private_state, modules["gmail_client"])
        config_change_results: list[dict[str, Any]] = []
        trusted_domains = sorted(
            {
                str(value or "").strip().lower()
                for value in (trusted_config_sender_domains or [])
                if str(value or "").strip()
            }
        )
        if trusted_domains:
            config_change = import_module("server_config_change_runner")
            for trusted_domain in trusted_domains:
                config_result = config_change.run(
                    max_results=100,
                    state_dir=private_state,
                    server_config_path=canonical_servers,
                    trusted_sender_domain=trusted_domain,
                    journal_path=private_state / f"server-config-change-{_safe_filename_part(trusted_domain)}.json",
                    service=service,
                )
                config_change_results.extend(config_result.get("results") or [])
        _ensure_requested_reactivation_outcome(
            config_change_results,
            requested_reactivation_target,
        )
        headless_upload = import_module("headless_upload_runner")
        upload_result = headless_upload.run(
            max_results=300,
            journal_path=private_state / "headless-upload-journal.json",
            state_dir=private_state,
            server_config_path=canonical_servers,
            service=service,
        )
        auth_mailbox_details = _acknowledge_auth_failure_sources(
            service,
            upload_result,
            modules["gmail_client"],
        )
        retirement_policy = _update_retirement_evidence_and_apply(
            private_state=private_state,
            server_config_path=canonical_servers,
            upload_result=upload_result,
            config_change_results=config_change_results,
            reactivation_target=requested_reactivation_target,
        )
        items: list[dict[str, Any]] = []
        reported_items: list[dict[str, Any]] = []
        deferred_items: list[dict[str, Any]] = []
        unresolved_items: list[dict[str, Any]] = []
        unconfigured_items: list[dict[str, Any]] = []
        source_message_ids: list[str] = []
        zero_sales_message_ids: list[str] = []
        zoom_result = _zoom_not_needed(recipient_hint)
        marked_read_count = 0
        mailbox_details: list[dict[str, Any]] = []
        blockers: list[str] = []
        if include_non_submissions:
            processed_path = private_state / "non-submission-processed.json"
            outbox_path = private_state / "non-submission-outbox.json"
            delivery_history_path = (
                private_state / "non-submission-date-deliveries.json"
            )
            team_chat_journal_path = (
                private_state / "zoom-team-chat-messages.jsonl"
            )
            outbox = _read_non_submission_outbox(outbox_path)
            active_outbox = (
                outbox
                if str(outbox.get("status") or "") in {"pending", "verified"}
                else {}
            )
            claimed_source_ids = {
                str(value).strip()
                for value in (active_outbox.get("sourceMessageIds") or [])
                if str(value or "").strip()
            }
            processed = _read_processed_message_ids(processed_path)
            pending_gmail_reads = _read_pending_gmail_read_ids(processed_path)
            processed.update(pending_gmail_reads)
            delivery_history = _read_date_delivery_history(
                delivery_history_path,
                team_chat_journal_path=team_chat_journal_path,
            )
            processed_updates: set[str] = set()
            processed_journal_dirty = False
            if pending_gmail_reads:
                pending_mailbox_details = _mark_gmail_messages_read_verified(
                    service,
                    sorted(pending_gmail_reads),
                    modules["gmail_client"],
                )
                for detail in pending_mailbox_details:
                    detail["kind"] = "non_submission_retry"
                mailbox_details.extend(pending_mailbox_details)
                verified_pending_ids = {
                    str(item.get("messageId") or "").strip()
                    for item in pending_mailbox_details
                    if item.get("readbackVerified") is True
                    and str(item.get("messageId") or "").strip()
                }
                pending_gmail_reads.difference_update(verified_pending_ids)
                processed_journal_dirty = True
                if pending_gmail_reads:
                    blockers.append(
                        f"{len(pending_gmail_reads)} previously delivered non-submission "
                        "source message(s) remain retryable after Gmail readback."
                    )
            canonical_server_records = modules["server_utils"].load_servers(str(canonical_servers))
            notice_batch = modules["non_submission_service"].fetch_submission_notices(
                service,
                max_results=300,
                # The private interface catalog governs file transfer, not
                # whether a valid customer non-submission notice reaches Julio.
                known_servers_only=False,
                servers=canonical_server_records,
                include_read_since_days=14,
                exclude_message_ids=processed | claimed_source_ids,
            )
            records = list(getattr(notice_batch, "records", []) or [])
            unconfigured_records = list(getattr(notice_batch, "unconfigured_records", []) or [])
            zero_sales_message_ids = sorted(
                {
                    str(message_id).strip()
                    for message_id in (getattr(notice_batch, "zero_sales_only_message_ids", []) or [])
                    if str(message_id or "").strip()
                }
            )
            discovered_items = [_nonsubmission_item(record) for record in records]
            unconfigured_items = [
                {
                    **_nonsubmission_item(record),
                    "status": "unconfigured",
                    "notes": "true non-submission tenant is absent from the canonical interface catalog",
                }
                for record in unconfigured_records
            ]
            new_items, reminder_groups = _partition_date_delivery_items(
                discovered_items,
                delivery_history,
            )
            candidate_items, candidate_deferred, selection_unresolved = (
                _select_zoom_delivery_batch(new_items)
            )
            unresolved_items = list(selection_unresolved)
            if active_outbox:
                items = [dict(item) for item in (active_outbox.get("items") or [])]
                deferred_items = [*candidate_items, *candidate_deferred]
            else:
                items = candidate_items
                deferred_items = candidate_deferred
            reported_items = [
                *discovered_items,
                *(
                    [
                        dict(item)
                        for item in (active_outbox.get("items") or [])
                    ]
                    if active_outbox
                    else []
                ),
            ]
            source_message_ids = sorted(
                {
                    source_id
                    for item in reported_items
                    for source_id in _item_source_message_ids(item)
                }
            )
            delivery_results: list[dict[str, Any]] = []
            if items:
                render_year = (
                    int(active_outbox.get("renderYear"))
                    if active_outbox
                    else datetime.now().year
                )
                zoom_message = (
                    str(active_outbox.get("message") or "")
                    if active_outbox
                    else _build_zoom_message(items, render_year=render_year)
                )
                prior_delivery = _prior_delivery_for_batch(
                    active_outbox=active_outbox,
                    output_path=output_path,
                    message=zoom_message,
                )
                if not active_outbox:
                    _write_non_submission_outbox(
                        outbox_path,
                        items=items,
                        message=zoom_message,
                        status="pending",
                        delivery=prior_delivery or None,
                        render_year=render_year,
                    )
                zoom_result = _send_zoom_message(
                    message=zoom_message,
                    recipient_hint=recipient_hint,
                    ops_env_path=ops_env,
                    team_chat_journal_path=team_chat_journal_path,
                    internal_communication_journal_path=Path(
                        os.getenv("NOVA_INTERNAL_COMMUNICATION_JOURNAL_PATH")
                        or "/tmp/nova/broker/internal-comms/verified-requests.jsonl"
                    ),
                    prior_delivery=prior_delivery
                    if str(prior_delivery.get("channel") or "zoom") == "zoom"
                    else None,
                )
                if (
                    zoom_result.get("sent") is True
                    and zoom_result.get("readbackVerified") is True
                    and zoom_result.get("senderReadbackVerified") is True
                    and zoom_result.get("recipientReadbackVerified") is True
                ):
                    _write_non_submission_outbox(
                        outbox_path,
                        items=items,
                        message=zoom_message,
                        status="verified",
                        delivery=zoom_result,
                        render_year=render_year,
                    )
                    delivery_results.append(dict(zoom_result))
                    _record_date_delivery(
                        delivery_history,
                        items=items,
                        delivery=zoom_result,
                    )
                    _write_date_delivery_history(
                        delivery_history_path,
                        delivery_history,
                    )
                    _write_non_submission_outbox(
                        outbox_path,
                        items=items,
                        message=zoom_message,
                        status="completed",
                        delivery=zoom_result,
                        render_year=render_year,
                    )
                else:
                    blockers.append(str(zoom_result.get("notes") or "Julio Zoom message could not be verified."))

            for reply_to_message_id, reminder_items in sorted(
                reminder_groups.items()
            ):
                reminder_sources = sorted(
                    {
                        source_id
                        for item in reminder_items
                        for source_id in _item_source_message_ids(item)
                    }
                )
                reminder_result = _send_zoom_message(
                    message=SINGAPORE_REMINDER_MESSAGE,
                    recipient_hint=recipient_hint,
                    ops_env_path=ops_env,
                    team_chat_journal_path=team_chat_journal_path,
                    internal_communication_journal_path=Path(
                        os.getenv("NOVA_INTERNAL_COMMUNICATION_JOURNAL_PATH")
                        or "/tmp/nova/broker/internal-comms/verified-requests.jsonl"
                    ),
                    reply_to_message_id=reply_to_message_id,
                    idempotency_context="|".join(
                        [
                            reply_to_message_id,
                            *reminder_sources,
                            *sorted(
                                _delivery_date_key(
                                    str(item.get("machineId") or ""),
                                    str(day or ""),
                                )
                                for item in reminder_items
                                for day in (item.get("dates") or [])
                            ),
                        ]
                    ),
                )
                if _zoom_delivery_verified(reminder_result):
                    delivery_results.append(dict(reminder_result))
                    _record_date_delivery(
                        delivery_history,
                        items=reminder_items,
                        delivery=reminder_result,
                        reply_to_message_id=reply_to_message_id,
                        reminder=True,
                    )
                    _write_date_delivery_history(
                        delivery_history_path,
                        delivery_history,
                    )
                else:
                    blockers.append(
                        str(
                            reminder_result.get("notes")
                            or "Julio Zoom reminder could not be verified."
                        )
                    )

            if delivery_results:
                last_delivery = delivery_results[-1]
                zoom_result = {
                    **last_delivery,
                    "verifiedDeliveryCount": len(delivery_results),
                    "reminderCount": sum(
                        1
                        for result in delivery_results
                        if str(result.get("replyMainMessageId") or "").strip()
                    ),
                }

            completed_source_ids = _completed_source_message_ids(
                reported_items,
                delivery_history,
            )
            if completed_source_ids:
                # Persist source/date coverage before touching Gmail. A failed
                # label readback retries only Gmail and never resends Zoom work.
                processed_updates.update(completed_source_ids)
                pending_gmail_reads.update(completed_source_ids)
                _write_processed_message_ids(
                    processed_path,
                    processed | processed_updates,
                    delivery=zoom_result if zoom_result.get("sent") else None,
                    pending_gmail_read_ids=pending_gmail_reads,
                )
                processed_journal_dirty = True
                non_submission_mailbox_details = _mark_gmail_messages_read_verified(
                    service,
                    sorted(completed_source_ids),
                    modules["gmail_client"],
                )
                for detail in non_submission_mailbox_details:
                    detail["kind"] = "non_submission"
                mailbox_details.extend(non_submission_mailbox_details)
                verified_non_submission_ids = {
                    str(item.get("messageId") or "").strip()
                    for item in non_submission_mailbox_details
                    if item.get("readbackVerified") is True
                    and str(item.get("messageId") or "").strip()
                }
                pending_gmail_reads.difference_update(
                    verified_non_submission_ids
                )
                failed_readbacks = (
                    len(non_submission_mailbox_details)
                    - len(verified_non_submission_ids)
                )
                if failed_readbacks:
                    blockers.append(
                        f"{failed_readbacks} non-submission source message(s) remain retryable after Gmail readback."
                    )

            if zero_sales_message_ids:
                zero_sales_mailbox_details = _mark_gmail_messages_read_verified(
                    service,
                    zero_sales_message_ids,
                    modules["gmail_client"],
                )
                for detail in zero_sales_mailbox_details:
                    detail["kind"] = "zero_sales"
                mailbox_details.extend(zero_sales_mailbox_details)
                verified_zero_sales_ids = {
                    str(item.get("messageId") or "").strip()
                    for item in zero_sales_mailbox_details
                    if item.get("readbackVerified") is True and str(item.get("messageId") or "").strip()
                }
                processed_updates.update(verified_zero_sales_ids)
                zero_sales_readback_failed = len(zero_sales_mailbox_details) - len(verified_zero_sales_ids)
                if zero_sales_readback_failed:
                    blockers.append(
                        f"{zero_sales_readback_failed} zero-sale source message(s) remain retryable after Gmail readback."
                    )

            marked_read_count = sum(1 for item in mailbox_details if item.get("readbackVerified") is True)
            if processed_updates or processed_journal_dirty:
                _write_processed_message_ids(
                    processed_path,
                    processed | processed_updates,
                    delivery=zoom_result if zoom_result.get("sent") else None,
                    pending_gmail_read_ids=pending_gmail_reads,
                )
        result = _build_cache(
            root=root,
            private_state=private_state,
            server_config_path=canonical_servers,
            items=reported_items,
            zoom_result=zoom_result,
            source_message_ids=source_message_ids,
            marked_read_count=marked_read_count,
            blockers=blockers,
            upload_result=upload_result,
            config_change_results=config_change_results,
            non_submission_reviewed=include_non_submissions,
            mailbox_details=mailbox_details,
            retirement_policy=retirement_policy,
            zero_sales_count=len(zero_sales_message_ids),
            unconfigured_items=unconfigured_items,
            deferred_items=deferred_items,
            unresolved_items=unresolved_items,
        )
    except Exception as exc:
        result = _blocked_cache(root, private_state, recipient_hint, exc)
    finally:
        _release_runner_lock(run_lock)

    if preserved_remediation:
        result["remediation"] = preserved_remediation
    _write_json(output_path, result)
    return result


def apply_server_patch(*, state_dir: str | Path, patch_path: str | Path) -> dict[str, Any]:
    """Apply one verified add/update/remove operation to Taylor's private server list."""
    private_state = Path(state_dir).expanduser().resolve()
    patch_file = Path(patch_path).expanduser().resolve()
    if private_state not in patch_file.parents:
        raise ValueError("Server patch file must be inside the private Singapore state directory.")
    servers_path = private_state / "servers.json"
    patch = json.loads(patch_file.read_text(encoding="utf-8"))
    action = str(patch.get("action") or "upsert").strip().lower()
    key = str(patch.get("key") or "").strip()
    if not key or any(char in key for char in "\\/\r\n\t"):
        raise ValueError("Server patch requires a safe non-empty key.")

    servers = _read_json_object(servers_path)
    backup_dir = private_state / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(servers_path, backup_dir / f"servers-{datetime.now().strftime('%Y%m%dT%H%M%S%f')}.json")

    changed_fields: list[str] = []
    if action == "remove":
        if key not in servers:
            return {"ok": True, "status": "not_needed", "key": key, "changedFields": []}
        servers.pop(key)
    elif action == "retire":
        existing = servers.get(key)
        if not isinstance(existing, dict):
            return {"ok": True, "status": "not_needed", "key": key, "changedFields": []}
        if existing.get("retired") is True or str(existing.get("status") or "").strip().lower() == "retired":
            return {"ok": True, "status": "already_current", "key": key, "changedFields": []}
        server_type = str(existing.get("type") or "").strip()
        if not server_type:
            raise ValueError("Server entry requires a type before retirement.")
        servers[key] = {
            "type": server_type,
            "status": "retired",
            "retired": True,
            "retiredAtUtc": str(patch.get("retiredAtUtc") or _utc_now()),
            "retirementPolicy": "90_day_no_success_or_customer_resubmission",
        }
        changed_fields.extend(["retired", "retiredAtUtc", "retirementPolicy", "status"])
    elif action == "upsert":
        server = patch.get("server")
        if not isinstance(server, dict) or not server:
            raise ValueError("Upsert patch requires a non-empty server object.")
        merged = dict(servers.get(key) or {})
        for field, value in server.items():
            field_name = str(field or "").strip()
            if not field_name:
                continue
            merged[field_name] = value
            changed_fields.append(field_name)
        if not str(merged.get("type") or "").strip():
            raise ValueError("Server entry requires a type.")
        servers[key] = merged
    else:
        raise ValueError("Server patch action must be upsert, retire, or remove.")

    _write_json(servers_path, servers)
    persisted = _read_json_object(servers_path)
    if action == "remove" and key in persisted:
        raise RuntimeError("Server removal readback failed.")
    if action == "retire":
        verified = persisted.get(key) if isinstance(persisted.get(key), dict) else {}
        if verified.get("retired") is not True or str(verified.get("status") or "").lower() != "retired":
            raise RuntimeError("Server retirement readback failed.")
    if action == "upsert":
        verified = persisted.get(key) if isinstance(persisted.get(key), dict) else {}
        if any(verified.get(field) != servers[key].get(field) for field in changed_fields):
            raise RuntimeError("Server update readback failed.")
    return {"ok": True, "status": "updated", "key": key, "changedFields": sorted(changed_fields)}


def _acquire_runner_lock(path: Path) -> Any:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+", encoding="utf-8")
    if fcntl is None:
        return handle
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        handle.close()
        raise RuntimeError(
            "Another Singapore background cycle is already running; this "
            "cycle did not perform provider work."
        ) from exc
    return handle


def _release_runner_lock(handle: Any) -> None:
    if handle is None:
        return
    try:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


def _ensure_private_state(root: Path, state_dir: Path) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    sources = {
        "servers.json": [root / "servers.json"],
        "credentials.json": [root / "dist" / "credentials.json", Path("C:/Users/redma/Uploader/credentials.json"), root / "credentials.json"],
        "token.json": [root / "dist" / "token.json", Path("C:/Users/redma/Uploader/token.json"), root / "token.json"],
    }
    for name, candidates in sources.items():
        destination = state_dir / name
        if destination.exists():
            continue
        source = next((candidate for candidate in candidates if candidate.exists()), None)
        if source is None:
            raise FileNotFoundError(f"Private Singapore state is missing {name}.")
        shutil.copy2(source, destination)


def _load_parser_modules(root: Path) -> dict[str, Any]:
    root_text = str(root)
    if root_text not in sys.path:
        sys.path.insert(0, root_text)
    names = ("gmail_client", "non_submission_parser", "non_submission_service", "server_utils", "upload_log")
    return {name: import_module(name) for name in names}


def _configure_private_state(state_dir: Path, modules: dict[str, Any]) -> None:
    get_private_dir = lambda: str(state_dir)
    modules["server_utils"].get_app_dir = get_private_dir
    modules["gmail_client"].get_app_dir = get_private_dir


def _authenticate_gmail_noninteractive(state_dir: Path, gmail_module: Any) -> Any:
    """Use Taylor's private token without ever opening an interactive OAuth flow."""
    token_path = state_dir / "token.json"
    if not token_path.exists():
        raise FileNotFoundError("Taylor's private Gmail token is missing.")
    credentials = gmail_module.Credentials.from_authorized_user_file(
        str(token_path),
        gmail_module.SCOPES,
    )
    refreshed = False
    if not credentials.valid:
        if credentials.expired and credentials.refresh_token:
            credentials.refresh(gmail_module.Request())
            refreshed = True
        else:
            raise RuntimeError(
                "Taylor's Gmail token requires interactive reauthentication; refresh the private token outside the headless watcher."
            )
    if refreshed:
        temp_path = token_path.with_suffix(".json.tmp")
        temp_path.write_text(credentials.to_json(), encoding="utf-8")
        os.replace(temp_path, token_path)
    return gmail_module.build("gmail", "v1", credentials=credentials)


def _nonsubmission_item(record: Any) -> dict[str, Any]:
    message_ids = sorted(
        {
            str(value).strip()
            for value in (getattr(record, "message_ids", None) or [getattr(record, "message_id", "")])
            if str(value or "").strip()
        }
    )
    return {
        "sourceEmailId": str(getattr(record, "message_id", "") or ""),
        "sourceEmailIds": message_ids,
        "subject": str(getattr(record, "subject", "") or ""),
        "receivedAt": str(getattr(record, "email_date", "") or ""),
        "location": " / ".join(
            part for part in (str(getattr(record, "mall", "") or ""), str(getattr(record, "shop", "") or "")) if part
        ),
        "machineId": str(getattr(record, "machine_id", "") or ""),
        "dates": [item.isoformat() for item in getattr(record, "missing_dates", [])],
        "notes": "true non-submission item from a matched Singapore source",
    }


def _prior_zoom_delivery(output_path: Path, message: str) -> dict[str, Any] | None:
    try:
        cache = _read_json_object(output_path)
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    delivery = cache.get("zoomMessage") if isinstance(cache.get("zoomMessage"), dict) else {}
    if (
        str(delivery.get("status") or "") in {"sent", "sent_unverified"}
        and str(delivery.get("messageId") or "").strip()
        and str(delivery.get("messageBody") or "") == message
    ):
        return dict(delivery)
    return None


def _prior_delivery_for_batch(
    *,
    active_outbox: dict[str, Any],
    output_path: Path,
    message: str,
) -> dict[str, Any]:
    """Preserve a legacy or verified receipt across an outbox-phase restart."""

    if active_outbox:
        delivery = active_outbox.get("delivery")
        return dict(delivery) if isinstance(delivery, dict) else {}
    return _prior_zoom_delivery(output_path, message) or {}


def _mark_gmail_messages_read_verified(
    service: Any,
    message_ids: list[str],
    gmail_module: Any,
) -> list[dict[str, Any]]:
    """Mark exact sources read and verify each Gmail label independently."""

    results: list[dict[str, Any]] = []
    for message_id in dict.fromkeys(str(value or "").strip() for value in message_ids if str(value or "").strip()):
        result = {
            "messageId": message_id,
            "status": "readback_failed",
            "markedRead": False,
            "readbackVerified": False,
        }
        try:
            current = gmail_module.get_message(service, message_id)
            if "UNREAD" in set(current.get("labelIds") or []):
                gmail_module.mark_messages_as_read(service, [message_id])
            verified = gmail_module.get_message(service, message_id)
            marked_read = "UNREAD" not in set(verified.get("labelIds") or [])
            result.update(
                status="verified_read" if marked_read else "still_unread",
                markedRead=marked_read,
                readbackVerified=marked_read,
            )
        except Exception:
            # Keep the source retryable and omit provider exception details from the shared cache.
            pass
        results.append(result)
    return results


def _acknowledge_auth_failure_sources(
    service: Any,
    upload_result: dict[str, Any],
    gmail_module: Any,
) -> list[dict[str, Any]]:
    """Mark catalogued authentication failures read and attach exact readback."""

    raw_items = upload_result.get("messageResults")
    if not isinstance(raw_items, list):
        return []
    auth_items = [
        item
        for item in raw_items
        if isinstance(item, dict)
        and str(item.get("failureCategory") or "").strip().lower() == "authentication"
        and str(item.get("sourceMessageId") or "").strip()
    ]
    message_ids = [str(item.get("sourceMessageId") or "").strip() for item in auth_items]
    readback = _mark_gmail_messages_read_verified(service, message_ids, gmail_module)
    by_id = {str(item.get("messageId") or ""): item for item in readback}
    for item in auth_items:
        detail = by_id.get(str(item.get("sourceMessageId") or "")) or {}
        item["markedRead"] = detail.get("markedRead") is True
        item["gmailReadbackVerified"] = detail.get("readbackVerified") is True
    verified = sum(1 for item in readback if item.get("readbackVerified") is True)
    failed = len(readback) - verified
    upload_result["markedReadMessages"] = int(upload_result.get("markedReadMessages") or 0) + verified
    upload_result["gmailReadbackFailedMessages"] = (
        int(upload_result.get("gmailReadbackFailedMessages") or 0) + failed
    )
    return readback


def acknowledge_cached_auth_failures(
    *,
    uploader_root: str | Path,
    state_dir: str | Path,
) -> dict[str, Any]:
    """Apply only the newly authorized Gmail readback to the current catalog."""

    root = Path(uploader_root).expanduser().resolve()
    private_state = Path(state_dir).expanduser().resolve()
    if not root.exists():
        raise FileNotFoundError(f"Singapore module root not found: {root}")
    _ensure_private_state(root, private_state)
    modules = _load_parser_modules(root)
    _configure_private_state(private_state, modules)
    service = _authenticate_gmail_noninteractive(private_state, modules["gmail_client"])
    journal_path = private_state / "headless-upload-journal.json"
    journal = _read_json_object(journal_path)
    readback = _acknowledge_auth_failure_sources(service, journal, modules["gmail_client"])
    _write_json(journal_path, journal)
    acknowledged_ids = {str(item.get("messageId") or "") for item in readback}
    try:
        headless_upload = import_module("headless_upload_runner")
        catalog = _read_json_object(private_state / "integration-status.json")
        tenants = catalog.get("tenants") if isinstance(catalog.get("tenants"), dict) else {}
        servers = modules["server_utils"].load_servers(str(private_state / "servers.json"))
        discovered: list[dict[str, Any]] = []
        for stub in headless_upload._search_unread(service, 300):
            message_id = str(stub.get("id") or "").strip()
            if not message_id or message_id in acknowledged_ids:
                continue
            message = modules["gmail_client"].get_message(service, message_id)
            machine_id = str(headless_upload._machine_id_from_upload_message(message) or "").strip()
            server_key = str(modules["server_utils"].find_server_key(machine_id, servers) or "").strip()
            tenant = tenants.get(server_key) if isinstance(tenants.get(server_key), dict) else {}
            if str(tenant.get("status") or "").strip().lower() != "authorization_failed":
                continue
            discovered.append(
                {
                    "sourceMessageId": message_id,
                    "serverKey": server_key,
                    "result": "server_auth_backoff",
                    "failureCategory": "authentication",
                }
            )
        if discovered:
            discovered_result = {
                "messageResults": discovered,
                "markedReadMessages": 0,
                "gmailReadbackFailedMessages": 0,
            }
            readback.extend(
                _acknowledge_auth_failure_sources(
                    service,
                    discovered_result,
                    modules["gmail_client"],
                )
            )
            _write_json(
                private_state / "auth-failure-ack-journal.json",
                {
                    "version": 1,
                    "updatedAtUtc": _utc_now(),
                    "matchedCount": len(discovered),
                    "verifiedReadCount": sum(
                        1 for item in discovered_result["messageResults"] if item.get("gmailReadbackVerified") is True
                    ),
                    "messageResults": discovered_result["messageResults"],
                },
            )
    except Exception:
        # The cached journal path remains usable even if an older uploader lacks
        # discovery helpers. Provider/raw exception details are intentionally omitted.
        pass
    verified = sum(1 for item in readback if item.get("readbackVerified") is True)
    return {
        "status": "completed" if verified == len(readback) else "completed_with_issues",
        "summary": f"Verified {verified} of {len(readback)} catalogued authentication-failure source message(s) read.",
        "matchedCount": len(readback),
        "verifiedReadCount": verified,
        "readbackFailedCount": len(readback) - verified,
    }


def _eastern_weekday(utc_dt: datetime) -> int:
    """Weekday of the New York calendar date, without the IANA tz database.

    Windows Python installs frequently ship without ``tzdata``, so
    ``zoneinfo`` raises ``ZoneInfoNotFoundError``. US DST since 2007 runs from
    2:00 AM on the second Sunday in March to 2:00 AM on the first Sunday in
    November, so the offset is a fixed -5 (EST) or -4 (EDT). Both transitions
    happen at the same calendar date, so the weekday is unambiguous.
    """
    year = utc_dt.year
    march_first_weekday = datetime(year, 3, 1).weekday()
    second_sunday_march = 1 + ((6 - march_first_weekday) % 7) + 7
    november_first_weekday = datetime(year, 11, 1).weekday()
    first_sunday_november = 1 + ((6 - november_first_weekday) % 7)
    dst_start = datetime(year, 3, second_sunday_march, 7, 0, tzinfo=timezone.utc)
    dst_end = datetime(year, 11, first_sunday_november, 6, 0, tzinfo=timezone.utc)
    offset_hours = -4 if dst_start <= utc_dt < dst_end else -5
    return (utc_dt + timedelta(hours=offset_hours)).weekday()


def _send_zoom_message(
    *,
    message: str,
    recipient_hint: str,
    ops_env_path: Path,
    team_chat_journal_path: Path | None = None,
    internal_communication_journal_path: Path | None = None,
    prior_delivery: dict[str, Any] | None = None,
    reply_to_message_id: str = "",
    idempotency_context: str = "",
    now: datetime | None = None,
) -> dict[str, Any]:
    if str(recipient_hint or "").strip().casefold() != "julio":
        return _zoom_blocked(
            recipient_hint,
            "The Singapore non-submission recipient must be configured:julio.",
        )
    send_now = now or datetime.now(timezone.utc)
    if send_now.tzinfo is None:
        send_now = send_now.replace(tzinfo=timezone.utc)
    # The weekend is defined by the New York calendar date. The nightly run
    # fires at 23:00 ET, which is already the next weekday in UTC, so a UTC
    # weekday check would wrongly allow a Sunday-night send to Julio. Windows
    # Pythons often lack the IANA tz database, so fall back to a pure-Python
    # US DST rule that yields the identical weekday.
    utc_now = send_now.astimezone(timezone.utc)
    try:
        from zoneinfo import ZoneInfo

        eastern_weekday = utc_now.astimezone(ZoneInfo("America/New_York")).weekday()
    except Exception:
        eastern_weekday = _eastern_weekday(utc_now)
    if eastern_weekday >= 5:
        return _zoom_blocked(
            recipient_hint,
            "Julio is not messaged on weekends; the Singapore resubmission "
            "batch is deferred to the next weekday run.",
        )
    legacy = dict(prior_delivery or {})
    private_root = Path(ops_env_path).expanduser().resolve().parent
    journal_path = (
        Path(team_chat_journal_path).expanduser().resolve()
        if team_chat_journal_path is not None
        else private_root / "zoom-team-chat-messages.jsonl"
    )
    communication_path = (
        Path(internal_communication_journal_path).expanduser().resolve()
        if internal_communication_journal_path is not None
        else Path(
            os.getenv("NOVA_INTERNAL_COMMUNICATION_JOURNAL_PATH")
            or "/tmp/nova/broker/internal-comms/verified-requests.jsonl"
        ).expanduser().resolve()
    )
    parent_message_id = str(reply_to_message_id or "").strip()
    idempotency_material = "\n".join(
        [
            message,
            parent_message_id,
            str(idempotency_context or "").strip(),
        ]
    )
    idempotency_key = (
        (
            "singapore-nonsubmission-reminder:"
            if parent_message_id
            else "singapore-nonsubmission:"
        )
        + hashlib.sha256(idempotency_material.encode("utf-8")).hexdigest()
    )
    try:
        client = _build_singapore_zoom_client(
            team_chat_journal_path=journal_path,
            internal_communication_journal_path=communication_path,
        )
        if (
            str(legacy.get("messageBody") or "") == message
            and str(legacy.get("messageId") or "").strip()
            and str(legacy.get("status") or "") in {"sent", "sent_unverified"}
        ):
            verified_legacy = client.team_chat_verify_existing(
                exact_recipient="configured:julio",
                message_id=str(legacy["messageId"]),
                message=message,
            )
            if (
                verified_legacy.get("ok") is True
                and verified_legacy.get("sent") is True
                and verified_legacy.get("readbackVerified") is True
                and verified_legacy.get("senderReadbackVerified") is True
                and verified_legacy.get("recipientReadbackVerified") is True
            ):
                return {
                    **legacy,
                    **verified_legacy,
                    "duplicatePrevented": True,
                    "legacyReceiptReused": True,
                }
            return {
                **legacy,
                **verified_legacy,
                "ok": False,
                "sent": False,
                "status": "sent_unverified",
                "retryAllowed": False,
                "notes": (
                    "A legacy Zoom receipt exists for this exact message, but "
                    "current provider readback could not verify its message, "
                    "sender, and recipient. The message will not be sent again."
                ),
            }
        result = client.team_chat_send(
            exact_recipient="configured:julio",
            message=message,
            authorization_context=(
                "Deterministic Singapore non-submission reminder reply from a "
                "verified repeated machine and date"
                if parent_message_id
                else "Deterministic Singapore non-submission batch from verified "
                "Gmail source messages"
            ),
            idempotency_key=idempotency_key,
            sender_lane="coding_agent",
            reply_main_message_id=parent_message_id,
        )
        if (
            result.get("ok") is True
            and result.get("sent") is True
            and result.get("readbackVerified") is True
            and result.get("senderReadbackVerified") is True
            and result.get("recipientReadbackVerified") is True
        ):
            return result
        return {
            **result,
            "sent": False,
            "status": str(result.get("status") or "blocked"),
            "notes": str(
                result.get("reason")
                or "Julio Zoom message did not pass typed message, sender, and recipient readback."
            ),
        }
    except (HTTPError, RuntimeError, ValueError) as exc:
        return _zoom_blocked(recipient_hint, f"Zoom Team Chat send failed: {_safe_error(exc)}")


def _build_singapore_zoom_client(
    *,
    team_chat_journal_path: Path,
    internal_communication_journal_path: Path,
) -> Any:
    from scoped_operations_mcp.zoom_client import ScopedZoomClient

    return ScopedZoomClient(
        team_chat_journal_path=team_chat_journal_path,
        internal_communication_journal_path=internal_communication_journal_path,
    )


def _build_cache(
    *,
    root: Path,
    private_state: Path,
    server_config_path: Path,
    items: list[dict[str, Any]],
    zoom_result: dict[str, Any],
    source_message_ids: list[str],
    marked_read_count: int,
    blockers: list[str],
    upload_result: dict[str, Any],
    config_change_results: list[dict[str, Any]],
    non_submission_reviewed: bool,
    mailbox_details: list[dict[str, Any]] | None = None,
    retirement_policy: dict[str, Any] | None = None,
    zero_sales_count: int = 0,
    unconfigured_items: list[dict[str, Any]] | None = None,
    deferred_items: list[dict[str, Any]] | None = None,
    unresolved_items: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    sent = bool(zoom_result.get("sent"))
    status = "ok" if not blockers else "partial"
    upload_status = str(upload_result.get("status") or "blocked")
    upload_marked = int(upload_result.get("markedReadMessages") or 0)
    upload_failed = int(upload_result.get("failedMessages") or 0)
    upload_unmatched = int(upload_result.get("unmatchedMessages") or 0)
    # authBlockedServers counts credentials rejected during this invocation,
    # while authBackoffServers includes those failures plus credentials whose
    # existing circuit prevented another unsafe login attempt.  The operator
    # cache must report every currently active authentication circuit.
    upload_auth_blocked = max(
        int(upload_result.get("authBlockedServers") or 0),
        int(upload_result.get("authBackoffServers") or 0),
    )
    gmail_readback_failed = int(upload_result.get("gmailReadbackFailedMessages") or 0)
    catalog_counts = upload_result.get("catalogStatusCounts") if isinstance(upload_result.get("catalogStatusCounts"), dict) else {}
    auto_reply = upload_result.get("autoReply") if isinstance(upload_result.get("autoReply"), dict) else {}
    safe_mailbox_details = [
        {
            "messageId": _safe_detail_text(item.get("messageId")),
            "kind": "zero_sales" if str(item.get("kind") or "") == "zero_sales" else "non_submission",
            "status": str(item.get("status") or "readback_failed")
            if str(item.get("status") or "") in {"verified_read", "still_unread", "readback_failed"}
            else "readback_failed",
            "markedRead": bool(item.get("markedRead")),
            "readbackVerified": item.get("readbackVerified") is True,
        }
        for item in (mailbox_details or [])[:500]
        if isinstance(item, dict) and str(item.get("messageId") or "").strip()
    ]
    non_submission_readback_failed = sum(
        1
        for item in safe_mailbox_details
        if item.get("kind") == "non_submission" and item.get("readbackVerified") is not True
    )
    zero_sales_readback_failed = sum(
        1
        for item in safe_mailbox_details
        if item.get("kind") == "zero_sales" and item.get("readbackVerified") is not True
    )
    zero_sales_marked_read = sum(
        1
        for item in safe_mailbox_details
        if item.get("kind") == "zero_sales" and item.get("readbackVerified") is True
    )
    safe_unconfigured_items = [
        {
            "sourceEmailId": _safe_detail_text(item.get("sourceEmailId")),
            "sourceEmailIds": _safe_detail_list(item.get("sourceEmailIds")),
            "machineId": _safe_detail_text(item.get("machineId")),
            "dates": _safe_detail_list(item.get("dates")),
            "status": "unconfigured",
            "notes": "true non-submission tenant is absent from the canonical interface catalog",
        }
        for item in (unconfigured_items or [])[:100]
        if isinstance(item, dict) and str(item.get("machineId") or "").strip()
    ]
    deferred_count = len(deferred_items or [])
    deferred_source_ids = sorted(
        {
            source_id
            for item in (deferred_items or [])
            if isinstance(item, dict)
            for source_id in _item_source_message_ids(item)
        }
    )
    safe_unresolved_items = [
        {
            "sourceEmailId": _safe_detail_text(item.get("sourceEmailId")),
            "sourceEmailIds": _safe_detail_list(item.get("sourceEmailIds")),
            "machineId": _safe_detail_text(item.get("machineId")),
            "dates": _safe_detail_list(item.get("dates")),
            "status": (
                str(item.get("status") or "")
                if str(item.get("status") or "")
                in {
                    "missing_source_message_id",
                    "mixed_configured_unconfigured_source",
                    "oversized_source_group",
                }
                else "unresolved"
            ),
        }
        for item in (unresolved_items or [])[:100]
        if isinstance(item, dict)
    ]
    issues: list[str] = []
    if gmail_readback_failed:
        issues.append(
            f"{gmail_readback_failed} automated Singapore source message(s) could not be verified read and remain retryable."
        )
    if non_submission_readback_failed:
        issues.append(
            f"{non_submission_readback_failed} non-submission source message(s) could not be verified read and remain retryable."
        )
    if zero_sales_readback_failed:
        issues.append(
            f"{zero_sales_readback_failed} zero-sale source message(s) could not be verified read and remain retryable."
        )
    if safe_unconfigured_items:
        issues.append(
            f"{len(safe_unconfigured_items)} true non-submission tenant(s) are absent from the canonical interface catalog; "
            "they require parser review."
        )
    if safe_unresolved_items:
        issues.append(
            f"{len(safe_unresolved_items)} non-submission row(s) "
            "were left unread because their source batch could not be delivered "
            "without losing or partially acknowledging source work."
        )
    if upload_status != "complete" or upload_failed or upload_unmatched or upload_auth_blocked:
        issues.append(
            f"{upload_failed + upload_unmatched} upload source message(s) remain incomplete; "
            f"{upload_auth_blocked} server authentication circuit(s) are active."
        )
    auto_reply_failed = int(auto_reply.get("failed") or 0)
    if auto_reply_failed:
        issues.append(
            f"{auto_reply_failed} customer Singapore integration reply attempt(s) failed verification and remain unread."
        )
    safe_config_change_results = _safe_config_change_results(config_change_results)
    config_blocked = sum(1 for item in safe_config_change_results if str(item.get("status") or "") == "blocked")
    config_verified = sum(
        1
        for item in safe_config_change_results
        if str(item.get("status") or "") in CONFIG_VERIFIED_SUCCESS_STATUSES
        and item.get("configVerified") is True
    )
    config_updated = sum(
        1
        for item in safe_config_change_results
        if str(item.get("status") or "") == "updated" and item.get("configVerified") is True
    )
    config_already_current = sum(
        1
        for item in safe_config_change_results
        if str(item.get("status") or "") in {"already_current", "already_active"}
        and item.get("configVerified") is True
    )
    new_interface_requests = sum(
        1 for item in safe_config_change_results if str(item.get("status") or "") == "new_interface_request"
    )
    retired_ignored = sum(
        1 for item in safe_config_change_results if str(item.get("status") or "") == "retired_interface_ignored"
    )
    config_marked_read = sum(1 for item in safe_config_change_results if bool(item.get("gmailReadbackVerified")))
    config_readback_failed = sum(
        1
        for item in safe_config_change_results
        if str(item.get("gmailReadbackStatus") or "") in {"readback_failed", "still_unread"}
    )
    if config_readback_failed:
        issues.append(
            f"{config_readback_failed} Singapore configuration source message(s) remain retryable after Gmail readback."
        )
    config_verification_pending = sum(
        1 for item in safe_config_change_results if item.get("retryable") is True
    )
    if config_verification_pending:
        issues.append(
            f"{config_verification_pending} Singapore configuration result(s) could not be verified and remain retryable."
        )
    other_config_blocked = max(0, config_blocked - config_verification_pending)
    if other_config_blocked:
        issues.append(f"{other_config_blocked} trusted server-change message(s) could not be applied safely.")
    status = "partial" if blockers or issues else "ok"
    upload_summary = (
        f"Uploaded {int(upload_result.get('uploadedFiles') or 0)} file(s), verified "
        f"{int(upload_result.get('alreadyPresentFiles') or 0)} already-present file(s), "
        f"and marked {upload_marked} upload-source message(s) read."
    )
    if upload_failed or upload_unmatched:
        upload_summary += (
            f" Catalogued {upload_failed + upload_unmatched} incomplete background-service outcome(s); "
            "no Salesforce ticket or Needs Review packet was created. Authentication-failure "
            "sources are marked read with per-message Gmail readback after cataloging. Outbound "
            "failure notifications are suppressed."
        )
    if non_submission_reviewed:
        summary = upload_summary + " " + (
            f"Non-submission review found {len(items)} machine item(s); "
            + (
                (
                    f"completed {int(zoom_result.get('verifiedDeliveryCount') or 1)} "
                    f"verified Zoom delivery action(s), including "
                    f"{int(zoom_result.get('reminderCount') or 0)} reminder reply/replies."
                )
                if sent
                else "Julio message was not needed."
                if not items
                else "Julio message is blocked."
            )
        )
        if zero_sales_count:
            summary += f" Auto-read {zero_sales_marked_read} pure zero-sale notice(s) with Gmail readback."
        if deferred_count:
            summary += (
                f" Queued {deferred_count} additional machine item(s) "
                "for the next bounded cycle."
            )
    else:
        summary = upload_summary + " Non-submission review was not run; it remains a separate manual step."
    return {
        "ok": True,
        "status": status,
        "updatedAtUtc": _utc_now(),
        "summary": summary,
        "approvedActions": dict(APPROVED_ACTIONS),
        "configChanges": {
            "status": "completed_with_issues" if config_blocked else "completed",
            "verifiedCount": config_verified,
            "updatedCount": config_updated,
            "alreadyCurrentCount": config_already_current,
            "newInterfaceRequestCount": new_interface_requests,
            "retiredIgnoredCount": retired_ignored,
            "markedReadCount": config_marked_read,
            "gmailReadbackFailedCount": config_readback_failed,
            "retryableCount": config_verification_pending,
            "blockedCount": config_blocked,
            "results": safe_config_change_results,
        },
        "nonsubmissions": items,
        "deferredNonsubmissionCount": deferred_count,
        "deferredSourceMessageIds": deferred_source_ids,
        "unresolvedNonsubmissions": safe_unresolved_items,
        "unconfiguredNonsubmissions": safe_unconfigured_items,
        "ignored": {"zeroSales": int(zero_sales_count), "salesVerification": 0, "other": 0},
        "zoomMessage": zoom_result,
        "julioDelivery": zoom_result,
        "upload": {
            "status": "completed" if upload_status == "complete" else "completed_with_issues",
            "uploadedCount": int(upload_result.get("uploadedFiles") or 0),
            "skippedCount": int(upload_result.get("alreadyPresentFiles") or 0),
            "failedMessageCount": upload_failed,
            "unmatchedMessageCount": upload_unmatched,
            "authBlockedServerCount": upload_auth_blocked,
            "details": _safe_upload_details(upload_result),
        },
        "integrationCatalog": {
            "status": "completed",
            "statusCounts": catalog_counts,
        },
        "retirementPolicy": dict(retirement_policy or {
            "status": "not_evaluated",
            "inactivityDays": 90,
            "authenticationFailureServerCount": 0,
            "eligibleCount": 0,
            "retiredCount": 0,
            "blockedCount": 0,
        }),
        "automaticReplies": {
            "status": "completed_with_issues" if auto_reply_failed else "completed",
            "matchedCount": int(auto_reply.get("matched") or 0),
            "sentCount": int(auto_reply.get("replied") or 0),
            "failedCount": int(auto_reply.get("failed") or 0),
            "markedReadCount": int(auto_reply.get("markedRead") or 0),
        },
        "mailbox": {
            "status": "completed_with_issues"
            if gmail_readback_failed or auto_reply_failed or non_submission_readback_failed or zero_sales_readback_failed
            else "completed",
            "markedReadCount": marked_read_count + upload_marked,
            "details": safe_mailbox_details,
        },
        "blockers": blockers,
        "issues": issues,
    }


def _blocked_cache(root: Path, state_dir: Path, recipient_hint: str, exc: Exception) -> dict[str, Any]:
    del root, state_dir, exc
    message = "Singapore background service did not complete."
    return {
        "ok": True,
        "status": "blocked",
        "updatedAtUtc": _utc_now(),
        "summary": message,
        "approvedActions": dict(APPROVED_ACTIONS),
        "nonsubmissions": [],
        "ignored": {"zeroSales": 0, "salesVerification": 0, "other": 0},
        "zoomMessage": _zoom_blocked(recipient_hint, message),
        "upload": {"status": "not_applicable", "uploadedCount": 0, "skippedCount": 0, "details": []},
        "mailbox": {"status": "blocked", "markedReadCount": 0, "details": []},
        "blockers": ["background_service_blocked"],
    }


def _safe_upload_details(upload_result: dict[str, Any]) -> list[dict[str, Any]]:
    raw_items = upload_result.get("messageResults")
    if not isinstance(raw_items, list):
        raw_items = upload_result.get("processedMessages")
    if not isinstance(raw_items, list):
        return []
    allowed_results = {
        "complete",
        "gmail_readback_failed",
        "no_attachment",
        "retired_machine_pending_handoff",
        "retired_ignored",
        "server_auth_backoff",
        "server_auth_blocked",
        "unknown_machine",
        "upload_or_verification_failed",
    }
    allowed_failures = {
        "",
        "authentication",
        "gmail_readback",
        "no_attachment",
        "retired_server",
        "transfer_or_verification",
        "unknown_machine",
    }
    allowed_circuits = {"", "closed", "open"}
    details: list[dict[str, Any]] = []
    for raw in raw_items[:500]:
        if not isinstance(raw, dict):
            continue
        result = str(raw.get("result") or raw.get("status") or "").strip().lower()
        failure_category = str(raw.get("failureCategory") or "").strip().lower()
        circuit_state = str(raw.get("circuitState") or "").strip().lower()
        detail = {
            "sourceMessageId": _safe_detail_text(raw.get("sourceMessageId")),
            "sourceThreadId": _safe_detail_text(raw.get("sourceThreadId")),
            "machineId": _safe_detail_text(raw.get("machineId")),
            "machineIds": _safe_detail_list(raw.get("machineIds")),
            "serverKey": _safe_detail_text(raw.get("serverKey")),
            "serverKeys": _safe_detail_list(raw.get("serverKeys")),
            "result": result if result in allowed_results else "unknown",
            "status": result if result in allowed_results else "unknown",
            "failureCategory": failure_category if failure_category in allowed_failures else "unknown",
            "markedRead": bool(raw.get("markedRead")),
            "retryAfterUtc": _safe_detail_text(raw.get("retryAfterUtc")),
            "circuitState": circuit_state if circuit_state in allowed_circuits else "",
            "configuredServer": bool(raw.get("configuredServer")),
            "retiredServer": bool(raw.get("retiredServer")),
            "retirementVerified": bool(raw.get("retirementVerified")),
        }
        if detail["sourceMessageId"] or detail["sourceThreadId"]:
            details.append(detail)
    return details


def _safe_config_change_results(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    safe: list[dict[str, Any]] = []
    for raw in items[:500]:
        if not isinstance(raw, dict):
            continue
        reported_status = str(raw.get("status") or "").strip().lower()
        config_verified = raw.get("configVerified") is True
        unverified_success_claim = (
            reported_status in CONFIG_VERIFIED_SUCCESS_STATUSES and not config_verified
        )
        status = (
            reported_status
            if reported_status
            in CONFIG_VERIFIED_SUCCESS_STATUSES
            | {
                "blocked",
                "new_interface_request",
                "retired_interface_ignored",
            }
            else "blocked"
        )
        if unverified_success_claim:
            status = "blocked"
        safe.append(
            {
                "sourceMessageId": _safe_detail_text(raw.get("sourceMessageId")),
                "sourceThreadId": _safe_detail_text(raw.get("sourceThreadId")),
                "machineId": _safe_detail_text(raw.get("machineId")),
                "status": status,
                "requestKind": (
                    str(raw.get("requestKind") or "").strip().lower()
                    if str(raw.get("requestKind") or "").strip().lower()
                    in {"existing_config", "new_interface", "reactivation"}
                    else ""
                ),
                # External runner reasons are arbitrary text and can contain
                # credentials or connection details. Outcome routing needs only
                # the allowlisted status/request kind, so do not expose reasons
                # through the agent-readable cache.
                "reason": "",
                "changedFields": _safe_detail_list(raw.get("changedFields"), limit=40),
                "configVerified": config_verified,
                "retryable": unverified_success_claim or (
                    status == "blocked" and raw.get("retryable") is True
                ),
                "createdServer": bool(raw.get("createdServer")),
                "authBackoffCleared": bool(raw.get("authBackoffCleared")),
                "markedRead": bool(raw.get("markedRead")),
                "gmailReadbackVerified": bool(raw.get("gmailReadbackVerified")),
                "gmailReadbackStatus": (
                    str(raw.get("gmailReadbackStatus") or "").strip().lower()
                    if str(raw.get("gmailReadbackStatus") or "").strip().lower()
                    in {"not_attempted", "verified_read", "still_unread", "readback_failed"}
                    else "not_attempted"
                ),
            }
        )
    return safe


def _validated_reactivation_target(value: Any) -> str:
    target = str(value or "").strip()
    if not target:
        return ""
    if re.fullmatch(r"\d{5,10}", target) is None:
        raise ValueError("Singapore reactivation target is invalid.")
    return target


def _ensure_requested_reactivation_outcome(
    results: list[dict[str, Any]],
    machine_id: str,
) -> None:
    """Keep a direct reactivation request targeted and visibly retryable."""

    if not machine_id:
        return
    for result in results:
        if not isinstance(result, dict):
            continue
        if (
            str(result.get("machineId") or "").strip() == machine_id
            and str(result.get("requestKind") or "").strip().lower() == "reactivation"
        ):
            return
    # A direct instruction authorizes only a matching trusted reactivation
    # source; it never supplies connection values itself. If no such source was
    # found, retain a metadata-only blocker so the request cannot be reported as
    # successful or silently lost.
    results.append(
        {
            "sourceMessageId": "",
            "sourceThreadId": "",
            "machineId": machine_id,
            "status": "blocked",
            "requestKind": "reactivation",
            "reason": "",
            "changedFields": [],
            "configVerified": False,
            "retryable": True,
            "createdServer": False,
            "authBackoffCleared": False,
            "markedRead": False,
            "gmailReadbackVerified": False,
            "gmailReadbackStatus": "not_attempted",
        }
    )


def _safe_detail_text(value: Any, *, limit: int = 200) -> str:
    return str(value or "").replace("\r", " ").replace("\n", " ").strip()[:limit]


def _safe_detail_list(value: Any, *, limit: int = 100) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value[:limit]:
        text = _safe_detail_text(item)
        if text and text not in result:
            result.append(text)
    return result


def _preserved_remediation(output_path: Path) -> dict[str, Any]:
    try:
        previous = json.loads(output_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    remediation = previous.get("remediation") if isinstance(previous, dict) else None
    return remediation if isinstance(remediation, dict) else {}


def _zoom_not_needed(recipient_hint: str) -> dict[str, Any]:
    return {"recipient": recipient_hint, "sent": False, "messageBody": "", "sentAtUtc": "", "messageId": "", "status": "not_needed"}


def _zoom_blocked(recipient_hint: str, notes: str) -> dict[str, Any]:
    return {"recipient": recipient_hint, "sent": False, "messageBody": "", "sentAtUtc": "", "messageId": "", "status": "blocked", "notes": notes}


def _item_source_message_ids(item: dict[str, Any]) -> set[str]:
    return {
        str(value).strip()
        for value in (item.get("sourceEmailIds") or [item.get("sourceEmailId")])
        if str(value or "").strip()
    }


def _zoom_delivery_verified(result: dict[str, Any]) -> bool:
    return (
        result.get("sent") is True
        and result.get("readbackVerified") is True
        and result.get("senderReadbackVerified") is True
        and result.get("recipientReadbackVerified") is True
    )


def _delivery_date_key(machine_id: str, day: str) -> str:
    machine = str(machine_id or "").strip()
    value = str(day or "").strip()
    if not re.fullmatch(r"\d{5,10}", machine):
        raise ValueError("Singapore delivery machine id is invalid.")
    if _parse_date(value) is None:
        raise ValueError("Singapore delivery date is invalid.")
    return f"{machine}|{value}"


def _parse_short_zoom_dates(value: str, *, default_year: int) -> list[str]:
    parsed: list[str] = []
    for token in str(value or "").split(","):
        match = re.fullmatch(
            r"\s*(\d{1,2})/(\d{1,2})(?:/(\d{2}|\d{4}))?(?:-(\d{1,2}))?\s*",
            token,
        )
        if not match:
            continue
        month = int(match.group(1))
        start_day = int(match.group(2))
        year_text = str(match.group(3) or "")
        year = (
            int(year_text)
            if len(year_text) == 4
            else 2000 + int(year_text)
            if year_text
            else int(default_year)
        )
        end_day = int(match.group(4) or start_day)
        if end_day < start_day or end_day - start_day > 31:
            continue
        for day_number in range(start_day, end_day + 1):
            try:
                parsed.append(date(year, month, day_number).isoformat())
            except ValueError:
                continue
    return sorted(set(parsed))


def _parse_zoom_delivery_items(
    message: str,
    *,
    sent_at_utc: str,
) -> list[dict[str, Any]]:
    body = str(message or "").strip()
    if not re.match(
        r"^(?:Hey\s+Julio,\s*)?(?:can\s+you\s+please\s+)?resubmit\s+these\s+"
        r"Singapore\s+integrations\?",
        body,
        re.IGNORECASE,
    ):
        return []
    try:
        sent_at = datetime.fromisoformat(
            str(sent_at_utc or "").replace("Z", "+00:00")
        )
        default_year = sent_at.year
    except ValueError:
        default_year = datetime.now(timezone.utc).year
    items: list[dict[str, Any]] = []
    pattern = re.compile(
        r"(?P<machine>\d{5,10}):\s*(?P<dates>.*?)"
        r"(?=;\s*\d{5,10}:|\.?\s*Thanks\.|$)",
        re.IGNORECASE,
    )
    for match in pattern.finditer(body):
        dates = _parse_short_zoom_dates(
            match.group("dates"),
            default_year=default_year,
        )
        if dates:
            items.append(
                {
                    "machineId": match.group("machine"),
                    "dates": dates,
                }
            )
    return items


def _read_date_delivery_history(
    path: Path,
    *,
    team_chat_journal_path: Path,
) -> dict[str, Any]:
    if path.exists():
        try:
            data = _read_json_object(path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                "The Singapore date-delivery journal is unreadable; refusing "
                "to resend or acknowledge non-submission dates."
            ) from exc
    else:
        data = {}
    entries = data.get("dates") if isinstance(data.get("dates"), dict) else {}
    safe_entries: dict[str, dict[str, Any]] = {}
    for key, raw in entries.items():
        if not isinstance(raw, dict):
            continue
        try:
            expected_key = _delivery_date_key(
                str(raw.get("machineId") or ""),
                str(raw.get("date") or ""),
            )
        except ValueError:
            continue
        if str(key) != expected_key:
            continue
        root_message_id = str(raw.get("threadRootMessageId") or "").strip()
        if not root_message_id:
            continue
        safe_entries[expected_key] = {
            "machineId": str(raw.get("machineId") or ""),
            "date": str(raw.get("date") or ""),
            "threadRootMessageId": root_message_id,
            "lastDeliveryMessageId": str(
                raw.get("lastDeliveryMessageId") or root_message_id
            ),
            "lastDeliveredAtUtc": str(raw.get("lastDeliveredAtUtc") or ""),
            "acknowledgedSourceMessageIds": sorted(
                {
                    str(value).strip()
                    for value in (
                        raw.get("acknowledgedSourceMessageIds") or []
                    )
                    if str(value or "").strip()
                }
            ),
        }

    try:
        journal_lines = team_chat_journal_path.read_text(
            encoding="utf-8"
        ).splitlines()
    except OSError:
        journal_lines = []
    for line in journal_lines[-10000:]:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if (
            not isinstance(row, dict)
            or str(row.get("status") or "") != "sent"
            or not str(row.get("messageId") or "").strip()
        ):
            continue
        message_id = str(row.get("messageId") or "").strip()
        sent_at = str(row.get("sentAtUtc") or "")
        root_message_id = str(
            row.get("replyMainMessageId") or message_id
        ).strip()
        for item in _parse_zoom_delivery_items(
            str(row.get("messageBody") or ""),
            sent_at_utc=sent_at,
        ):
            for day in item["dates"]:
                key = _delivery_date_key(item["machineId"], day)
                existing = safe_entries.get(key) or {}
                if str(existing.get("lastDeliveredAtUtc") or "") > sent_at:
                    continue
                safe_entries[key] = {
                    "machineId": item["machineId"],
                    "date": day,
                    "threadRootMessageId": root_message_id,
                    "lastDeliveryMessageId": message_id,
                    "lastDeliveredAtUtc": sent_at,
                    "acknowledgedSourceMessageIds": list(
                        existing.get("acknowledgedSourceMessageIds") or []
                    ),
                }
    return {
        "version": 1,
        "updatedAtUtc": str(data.get("updatedAtUtc") or ""),
        "dates": safe_entries,
    }


def _write_date_delivery_history(path: Path, history: dict[str, Any]) -> None:
    _write_json(
        path,
        {
            "version": 1,
            "updatedAtUtc": _utc_now(),
            "dates": dict(history.get("dates") or {}),
        },
    )


def _partition_date_delivery_items(
    items: list[dict[str, Any]],
    history: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    new_items: list[dict[str, Any]] = []
    reminders: dict[str, list[dict[str, Any]]] = {}
    entries = history.get("dates") if isinstance(history.get("dates"), dict) else {}
    for item in items:
        sources = _item_source_message_ids(item)
        new_dates: list[str] = []
        reminder_dates: dict[str, list[str]] = {}
        for day in sorted(
            {
                str(value).strip()
                for value in (item.get("dates") or [])
                if str(value or "").strip()
            }
        ):
            try:
                entry = entries.get(
                    _delivery_date_key(
                        str(item.get("machineId") or ""),
                        day,
                    )
                )
            except ValueError:
                continue
            if not isinstance(entry, dict):
                new_dates.append(day)
                continue
            acknowledged = {
                str(value).strip()
                for value in (
                    entry.get("acknowledgedSourceMessageIds") or []
                )
                if str(value or "").strip()
            }
            if sources and sources.issubset(acknowledged):
                continue
            root_message_id = str(
                entry.get("threadRootMessageId") or ""
            ).strip()
            if root_message_id:
                reminder_dates.setdefault(root_message_id, []).append(day)
            else:
                new_dates.append(day)
        if new_dates:
            new_items.append({**item, "dates": new_dates})
        for root_message_id, dates in reminder_dates.items():
            reminders.setdefault(root_message_id, []).append(
                {**item, "dates": sorted(set(dates))}
            )
    return new_items, reminders


def _record_date_delivery(
    history: dict[str, Any],
    *,
    items: list[dict[str, Any]],
    delivery: dict[str, Any],
    reply_to_message_id: str = "",
    reminder: bool = False,
) -> None:
    message_id = str(delivery.get("messageId") or "").strip()
    if not message_id:
        raise ValueError("Verified Singapore delivery has no Zoom message id.")
    entries = history.setdefault("dates", {})
    for item in items:
        sources = _item_source_message_ids(item)
        machine_id = str(item.get("machineId") or "")
        for day in item.get("dates") or []:
            key = _delivery_date_key(machine_id, str(day or ""))
            existing = entries.get(key) if isinstance(entries.get(key), dict) else {}
            acknowledged = {
                str(value).strip()
                for value in (
                    existing.get("acknowledgedSourceMessageIds") or []
                )
                if str(value or "").strip()
            }
            acknowledged.update(sources)
            root_message_id = (
                str(reply_to_message_id or "").strip()
                if reminder
                else message_id
            )
            entries[key] = {
                "machineId": machine_id,
                "date": str(day),
                "threadRootMessageId": root_message_id
                or str(existing.get("threadRootMessageId") or message_id),
                "lastDeliveryMessageId": message_id,
                "lastDeliveredAtUtc": str(
                    delivery.get("sentAtUtc") or _utc_now()
                ),
                "acknowledgedSourceMessageIds": sorted(acknowledged),
            }


def _completed_source_message_ids(
    items: list[dict[str, Any]],
    history: dict[str, Any],
) -> set[str]:
    entries = history.get("dates") if isinstance(history.get("dates"), dict) else {}
    all_sources = {
        source_id
        for item in items
        for source_id in _item_source_message_ids(item)
    }
    complete: set[str] = set()
    for source_id in all_sources:
        covered = True
        for item in items:
            if source_id not in _item_source_message_ids(item):
                continue
            for day in item.get("dates") or []:
                try:
                    entry = entries.get(
                        _delivery_date_key(
                            str(item.get("machineId") or ""),
                            str(day or ""),
                        )
                    )
                except ValueError:
                    covered = False
                    break
                acknowledged = (
                    {
                        str(value).strip()
                        for value in (
                            entry.get("acknowledgedSourceMessageIds") or []
                        )
                        if str(value or "").strip()
                    }
                    if isinstance(entry, dict)
                    else set()
                )
                if source_id not in acknowledged:
                    covered = False
                    break
            if not covered:
                break
        if covered:
            complete.add(source_id)
    return complete


def _partition_mixed_source_items(
    configured_items: list[dict[str, Any]],
    unconfigured_items: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Withhold a whole Gmail source when any row in it is unconfigured."""

    unconfigured_source_ids = {
        source_id
        for item in unconfigured_items
        for source_id in _item_source_message_ids(item)
    }
    eligible: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    for item in configured_items:
        if _item_source_message_ids(item).intersection(unconfigured_source_ids):
            unresolved.append(
                {
                    **item,
                    "status": "mixed_configured_unconfigured_source",
                }
            )
        else:
            eligible.append(item)
    return eligible, unresolved


def _select_zoom_delivery_batch(
    items: list[dict[str, Any]],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    """Select one source-safe message; the five-minute cycle drains the rest."""

    unresolved = [
        {**item, "status": "missing_source_message_id"}
        for item in items
        if not _item_source_message_ids(item)
    ]
    remaining = sorted(
        (
            item
            for item in items
            if _item_source_message_ids(item)
        ),
        key=lambda row: str(row.get("machineId") or ""),
    )
    groups: list[list[dict[str, Any]]] = []
    while remaining:
        group = [remaining.pop(0)]
        source_ids = set(_item_source_message_ids(group[0]))
        changed = True
        while changed:
            changed = False
            kept: list[dict[str, Any]] = []
            for item in remaining:
                item_sources = _item_source_message_ids(item)
                if source_ids.intersection(item_sources):
                    group.append(item)
                    source_ids.update(item_sources)
                    changed = True
                else:
                    kept.append(item)
            remaining = kept
        if len(_render_zoom_message(group)) > MAX_ZOOM_MESSAGE_CHARS:
            unresolved.extend(
                {**item, "status": "oversized_source_group"}
                for item in group
            )
            continue
        groups.append(group)

    selected: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    for group in groups:
        candidate = selected + group
        if len(_render_zoom_message(candidate)) <= MAX_ZOOM_MESSAGE_CHARS:
            selected = candidate
        else:
            deferred.extend(group)
    return selected, deferred, unresolved


def _safe_outbox_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    safe_items = [
        {
            "sourceEmailId": str(item.get("sourceEmailId") or ""),
            "sourceEmailIds": sorted(_item_source_message_ids(item)),
            "machineId": str(item.get("machineId") or ""),
            "dates": sorted(
                {
                    str(value).strip()
                    for value in (item.get("dates") or [])
                    if str(value or "").strip()
                }
            ),
        }
        for item in items
    ]
    if any(not _item_source_message_ids(item) for item in safe_items):
        raise ValueError(
            "Every Singapore Zoom outbox item requires an exact Gmail source id."
        )
    return safe_items


def _read_non_submission_outbox(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = _read_json_object(path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            "The Singapore Zoom outbox is unreadable; refusing to create a "
            "second delivery batch."
        ) from exc
    status = str(data.get("status") or "")
    if status not in {"pending", "verified", "completed"}:
        raise RuntimeError("The Singapore Zoom outbox has an invalid status.")
    if status == "completed":
        return data
    items = data.get("items")
    if not isinstance(items, list) or not items or not all(
        isinstance(item, dict) for item in items
    ):
        raise RuntimeError("The Singapore Zoom outbox has no valid batch items.")
    message = str(data.get("message") or "")
    try:
        render_year = int(data.get("renderYear"))
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            "The Singapore Zoom outbox has no valid render year."
        ) from exc
    if not 2000 <= render_year <= 2100:
        raise RuntimeError("The Singapore Zoom outbox render year is invalid.")
    source_ids = {
        str(value).strip()
        for value in (data.get("sourceMessageIds") or [])
        if str(value or "").strip()
    }
    expected_source_ids = {
        value for item in items for value in _item_source_message_ids(item)
    }
    if (
        not source_ids
        or source_ids != expected_source_ids
        or message != _build_zoom_message(items, render_year=render_year)
    ):
        raise RuntimeError(
            "The Singapore Zoom outbox batch binding is inconsistent; "
            "refusing to send or acknowledge it."
        )
    return data


def _write_non_submission_outbox(
    path: Path,
    *,
    items: list[dict[str, Any]],
    message: str,
    status: str,
    delivery: dict[str, Any] | None = None,
    render_year: int | None = None,
) -> dict[str, Any]:
    if status not in {"pending", "verified", "completed"}:
        raise ValueError("Singapore Zoom outbox status is invalid.")
    existing = _read_non_submission_outbox(path)
    existing_status = str(existing.get("status") or "")
    bound_render_year = int(
        (
            existing.get("renderYear")
            if existing_status in {"pending", "verified"}
            else None
        )
        or render_year
        or datetime.now().year
    )
    if not 2000 <= bound_render_year <= 2100:
        raise ValueError("Singapore Zoom outbox render year is invalid.")
    safe_items = _safe_outbox_items(items)
    if (
        not safe_items
        or message
        != _build_zoom_message(
            safe_items,
            render_year=bound_render_year,
        )
    ):
        raise ValueError("Singapore Zoom outbox message does not match its items.")
    if (
        existing_status in {"pending", "verified"}
        and str(existing.get("message") or "") != message
    ):
        raise RuntimeError(
            "An unfinished Singapore Zoom outbox batch must be reconciled "
            "before another batch can be created."
        )
    created_at = (
        str(existing.get("createdAtUtc") or _utc_now())
        if existing_status in {"pending", "verified"}
        else _utc_now()
    )
    safe_delivery = {}
    if isinstance(delivery, dict):
        safe_delivery = {
            "ok": delivery.get("ok") is True,
            "sent": delivery.get("sent") is True,
            "status": str(delivery.get("status") or ""),
            "channel": str(delivery.get("channel") or "zoom"),
            "messageId": str(delivery.get("messageId") or ""),
            "messageBody": str(delivery.get("messageBody") or message),
            "sentAtUtc": str(delivery.get("sentAtUtc") or ""),
            "readbackVerified": delivery.get("readbackVerified") is True,
            "senderReadbackVerified": delivery.get("senderReadbackVerified") is True,
            "recipientReadbackVerified": delivery.get("recipientReadbackVerified") is True,
        }
    payload = {
        "version": 1,
        "status": status,
        "createdAtUtc": created_at,
        "updatedAtUtc": _utc_now(),
        "renderYear": bound_render_year,
        "sourceMessageIds": sorted(
            {value for item in safe_items for value in _item_source_message_ids(item)}
        ),
        "items": safe_items,
        "message": message,
        "messageSha256": hashlib.sha256(message.encode("utf-8")).hexdigest(),
        "delivery": safe_delivery,
    }
    _write_json(path, payload)
    return payload


def _render_zoom_message(
    items: list[dict[str, Any]],
    *,
    render_year: int | None = None,
) -> str:
    entries: list[str] = []
    for item in sorted(items, key=lambda row: str(row.get("machineId") or "")):
        days = [_parse_date(value) for value in item.get("dates", [])]
        entries.append(
            f"{item.get('machineId')}: "
            f"{_format_short_dates([day for day in days if day], current_year=render_year)}"
        )
    return (
        "Hey Julio, can you please resubmit these Singapore integrations? "
        + "; ".join(entries)
        + ". Thanks."
    )


def _build_zoom_message(
    items: list[dict[str, Any]],
    *,
    render_year: int | None = None,
) -> str:
    message = _render_zoom_message(items, render_year=render_year)
    if len(message) > MAX_ZOOM_MESSAGE_CHARS:
        raise ValueError(
            f"Singapore Zoom message exceeds {MAX_ZOOM_MESSAGE_CHARS} characters."
        )
    return message


def _format_short_dates(
    days: list[date],
    *,
    current_year: int | None = None,
) -> str:
    if not days:
        return "(dates not parsed)"
    unique = sorted(set(days))
    workflow_year = int(current_year or datetime.now().year)
    parts: list[str] = []
    start = previous = unique[0]
    for day in unique[1:] + [None]:
        if day is not None and day.year == previous.year and day.month == previous.month and day.day == previous.day + 1:
            previous = day
            continue
        prefix = f"{start.month}/{start.day}"
        if start.year != workflow_year:
            prefix += f"/{str(start.year)[-2:]}"
        if previous != start:
            prefix += f"-{previous.day}"
        parts.append(prefix)
        if day is not None:
            start = previous = day
    return ", ".join(parts)


def _parse_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _read_json_object(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object in {path.name}.")
    return data


def _result_server_keys(item: dict[str, Any]) -> list[str]:
    values = item.get("serverKeys")
    if not isinstance(values, list):
        values = [item.get("serverKey")]
    return sorted(
        {
            str(value or "").strip()
            for value in values
            if re.fullmatch(r"\d{5,10}", str(value or "").strip()) is not None
        }
    )


def _parse_evidence_time(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _latest_success_by_server(log_path: Path) -> dict[str, datetime]:
    """Read only strict success records from the established local upload log."""

    if not log_path.exists():
        return {}
    pattern = re.compile(
        r"^(?P<when>[^|]+)\|\s*(?:SUCCESS|UPLOAD_PRESENT)\s*\|\s*[^|]+\|\s*server=(?P<server>\d{5,10})(?:;|$)"
    )
    latest: dict[str, datetime] = {}
    for raw_line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = pattern.match(raw_line.strip())
        if not match:
            continue
        observed = _parse_evidence_time(match.group("when"))
        if observed is None:
            continue
        key = match.group("server")
        if key not in latest or observed > latest[key]:
            latest[key] = observed
    return latest


def _update_retirement_evidence_and_apply(
    *,
    private_state: Path,
    server_config_path: Path,
    upload_result: dict[str, Any],
    config_change_results: list[dict[str, Any]],
    reactivation_target: str = "",
    now: datetime | None = None,
    inactivity_days: int = 90,
) -> dict[str, Any]:
    """Retire only after 90 observed days without success or customer contact."""

    observed_now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    now_text = observed_now.isoformat().replace("+00:00", "Z")
    cutoff = observed_now - timedelta(days=max(1, int(inactivity_days)))
    evidence_path = private_state / "singapore-retirement-evidence.json"
    try:
        state = _read_json_object(evidence_path)
    except (OSError, ValueError, json.JSONDecodeError):
        state = {}
    entries = state.get("entries") if isinstance(state.get("entries"), dict) else {}
    historical_success = _latest_success_by_server(private_state / "upload_log.txt")

    raw_items = upload_result.get("messageResults")
    if not isinstance(raw_items, list):
        raw_items = []
    auth_keys: set[str] = set()
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        keys = _result_server_keys(raw)
        result = str(raw.get("result") or "").strip().lower()
        category = str(raw.get("failureCategory") or "").strip().lower()
        for key in keys:
            entry = entries.get(key) if isinstance(entries.get(key), dict) else {}
            entry.setdefault("observationStartedAtUtc", now_text)
            historical = historical_success.get(key)
            if result == "complete":
                entry["lastVerifiedSuccessAtUtc"] = now_text
            elif historical is not None:
                prior = _parse_evidence_time(entry.get("lastVerifiedSuccessAtUtc"))
                if prior is None or historical > prior:
                    entry["lastVerifiedSuccessAtUtc"] = historical.isoformat().replace("+00:00", "Z")
            if category == "authentication":
                auth_keys.add(key)
                entry["lastAuthenticationFailureAtUtc"] = now_text
            entries[key] = entry

    for raw in config_change_results:
        if not isinstance(raw, dict):
            continue
        request_kind = str(raw.get("requestKind") or "").strip().lower()
        key = str(raw.get("machineId") or "").strip()
        if request_kind not in {"existing_config", "reactivation"} or re.fullmatch(r"\d{5,10}", key) is None:
            continue
        entry = entries.get(key) if isinstance(entries.get(key), dict) else {}
        entry.setdefault("observationStartedAtUtc", now_text)
        entry["lastCustomerContactAtUtc"] = now_text
        entries[key] = entry
    if reactivation_target:
        entry = entries.get(reactivation_target) if isinstance(entries.get(reactivation_target), dict) else {}
        entry.setdefault("observationStartedAtUtc", now_text)
        entry["lastCustomerContactAtUtc"] = now_text
        entries[reactivation_target] = entry

    eligible: list[str] = []
    for key in sorted(auth_keys):
        entry = entries.get(key) if isinstance(entries.get(key), dict) else {}
        evidence_times = [
            _parse_evidence_time(entry.get("observationStartedAtUtc")),
            _parse_evidence_time(entry.get("lastVerifiedSuccessAtUtc")),
            _parse_evidence_time(entry.get("lastCustomerContactAtUtc")),
        ]
        boundary = max((value for value in evidence_times if value is not None), default=observed_now)
        if boundary <= cutoff:
            eligible.append(key)

    retired = 0
    blocked = 0
    canonical_private_path = (private_state / "servers.json").resolve()
    if server_config_path.resolve() != canonical_private_path:
        blocked = len(eligible)
    else:
        for key in eligible:
            patch_path = private_state / f"retirement-policy-{_safe_filename_part(key)}.json"
            try:
                _write_json(
                    patch_path,
                    {"action": "retire", "key": key, "retiredAtUtc": now_text},
                )
                result = apply_server_patch(state_dir=private_state, patch_path=patch_path)
                if str(result.get("status") or "") in {"updated", "already_current"}:
                    retired += 1
                    entries[key]["retiredAtUtc"] = now_text
                else:
                    blocked += 1
            except Exception:
                blocked += 1
            finally:
                try:
                    patch_path.unlink(missing_ok=True)
                except OSError:
                    pass

    _write_json(
        evidence_path,
        {
            "version": 1,
            "updatedAtUtc": now_text,
            "inactivityDays": max(1, int(inactivity_days)),
            "entries": entries,
        },
    )
    return {
        "status": "completed_with_issues" if blocked else "completed",
        "inactivityDays": max(1, int(inactivity_days)),
        "authenticationFailureServerCount": len(auth_keys),
        "eligibleCount": len(eligible),
        "retiredCount": retired,
        "blockedCount": blocked,
    }


def _read_processed_message_ids(path: Path) -> set[str]:
    data = _read_processed_journal(path)
    return {
        str(value).strip()
        for value in (data.get("messageIds") or [])
        if str(value or "").strip()
    }


def _read_pending_gmail_read_ids(path: Path) -> set[str]:
    data = _read_processed_journal(path)
    return {
        str(value).strip()
        for value in (data.get("gmailReadPendingMessageIds") or [])
        if str(value or "").strip()
    }


def _read_processed_journal(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return _read_json_object(path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            "The non-submission delivery journal is unreadable; refusing to "
            "rediscover or resend previously handled source messages."
        ) from exc


def _write_processed_message_ids(
    path: Path,
    message_ids: set[str],
    *,
    delivery: dict[str, Any] | None = None,
    pending_gmail_read_ids: set[str] | None = None,
) -> None:
    safe_delivery = {}
    if isinstance(delivery, dict):
        safe_delivery = {
            "recipient": str(delivery.get("recipient") or ""),
            "status": str(delivery.get("status") or ""),
            "sent": delivery.get("sent") is True,
            "messageId": str(delivery.get("messageId") or ""),
            "sentAtUtc": str(delivery.get("sentAtUtc") or ""),
        }
    else:
        existing = _read_processed_journal(path)
        prior_delivery = existing.get("lastVerifiedDelivery")
        if isinstance(prior_delivery, dict):
            safe_delivery = dict(prior_delivery)
    if pending_gmail_read_ids is None:
        pending_gmail_read_ids = _read_pending_gmail_read_ids(path)
    _write_json(
        path,
        {
            "version": 2,
            "updatedAtUtc": _utc_now(),
            "messageIds": sorted(message_ids),
            "gmailReadPendingMessageIds": sorted(pending_gmail_read_ids),
            "lastVerifiedDelivery": safe_delivery,
        },
    )


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.parent / f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    try:
        temp_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def _safe_error(exc: Exception) -> str:
    if isinstance(exc, HTTPError):
        return f"HTTP {exc.code}"
    # Exception text from OAuth, FTP, and config libraries can echo secrets.
    # Keep the diagnostic category while withholding arbitrary external text.
    return type(exc).__name__


def _safe_filename_part(value: str) -> str:
    return "".join(char if char.isalnum() or char in "-_." else "_" for char in value).strip("._") or "sender"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def preflight_singapore_runtime(
    *,
    uploader_root: str | Path,
    state_dir: str | Path,
    server_config_path: str | Path,
) -> dict[str, Any]:
    """Verify portable modules, Gmail OAuth, and the private catalog without uploading."""

    root = Path(uploader_root).expanduser().resolve()
    private_state = Path(state_dir).expanduser().resolve()
    catalog_path = Path(server_config_path).expanduser().resolve()
    if not root.exists() or not catalog_path.is_file():
        raise FileNotFoundError("Singapore component or private server catalog is unavailable")
    _ensure_private_state(root, private_state)
    modules = _load_parser_modules(root)
    _configure_private_state(private_state, modules)
    service = _authenticate_gmail_noninteractive(private_state, modules["gmail_client"])
    profile = service.users().getProfile(userId="me").execute()
    servers = modules["server_utils"].load_servers(str(catalog_path))
    if not isinstance(servers, dict) or not servers:
        raise RuntimeError("Singapore private server catalog is empty")
    active = sum(1 for value in servers.values() if not modules["server_utils"].is_retired_server(value))
    return {
        "status": "ready",
        "gmailAuthenticated": bool(profile.get("emailAddress")),
        "configuredServerCount": len(servers),
        "activeServerCount": active,
        "uploadAttempted": False,
        "messageSent": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Taylor's Singapore Grab & Upload runner.")
    parser.add_argument("--uploader-root", default="")
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("--server-config-path", default="")
    parser.add_argument("--trusted-config-sender-domain", action="append", default=[])
    parser.add_argument("--output-path", default="")
    parser.add_argument("--ops-env-path", default="config/ops.env")
    parser.add_argument("--recipient-hint", default="Julio")
    parser.add_argument("--server-patch-path", default="")
    parser.add_argument("--acknowledge-cached-auth-failures", action="store_true")
    parser.add_argument("--include-non-submissions", action="store_true")
    parser.add_argument("--reactivation-target", default="")
    parser.add_argument("--preflight", action="store_true")
    args = parser.parse_args()
    if args.preflight:
        if not args.uploader_root or not args.server_config_path:
            parser.error("--uploader-root and --server-config-path are required for preflight")
        result = preflight_singapore_runtime(
            uploader_root=args.uploader_root,
            state_dir=args.state_dir,
            server_config_path=args.server_config_path,
        )
    elif args.acknowledge_cached_auth_failures:
        if not args.uploader_root:
            parser.error("--uploader-root is required for cached authentication-failure acknowledgement")
        result = acknowledge_cached_auth_failures(
            uploader_root=args.uploader_root,
            state_dir=args.state_dir,
        )
    elif args.server_patch_path:
        result = apply_server_patch(state_dir=args.state_dir, patch_path=args.server_patch_path)
    else:
        if not args.uploader_root or not args.output_path or not args.server_config_path:
            parser.error("--uploader-root, --server-config-path, and --output-path are required for a scan")
        result = run_singapore_ftp_fast(
            uploader_root=args.uploader_root,
            state_dir=args.state_dir,
            server_config_path=args.server_config_path,
            trusted_config_sender_domains=args.trusted_config_sender_domain,
            output_path=Path(args.output_path),
            recipient_hint=args.recipient_hint,
            ops_env_path=args.ops_env_path,
            include_non_submissions=args.include_non_submissions,
            reactivation_target=args.reactivation_target,
        )
    response = {"ok": True, "status": result.get("status"), "summary": result.get("summary", "")}
    if args.preflight:
        response.update(
            {
                "gmailAuthenticated": bool(result.get("gmailAuthenticated")),
                "configuredServerCount": int(result.get("configuredServerCount") or 0),
                "activeServerCount": int(result.get("activeServerCount") or 0),
                "uploadAttempted": False,
                "messageSent": False,
            }
        )
    print(json.dumps(response))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
