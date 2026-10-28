from __future__ import annotations

from dataclasses import replace
import hashlib
import hmac
import json
from pathlib import Path
from typing import Any, Mapping

from .reasoning_relay_protocol import RelayRequest
from .safety import signing_key_path


CLAIM_VERSION = 1


def _canonical_claim_payload(request: RelayRequest) -> dict[str, Any]:
    payload = dict(request.payload)
    payload.pop("runtime_claim", None)
    payload_bytes = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return {
        "version": CLAIM_VERSION,
        "message_id": request.message_id,
        "lane": request.lane,
        "kind": request.kind,
        "conversation_id": request.conversation_id,
        "job_id": request.job_id,
        "created_at": request.created_at,
        "payload_sha256": hashlib.sha256(payload_bytes).hexdigest(),
    }


def _signing_key(agent: Mapping[str, Any]) -> bytes:
    path = Path(signing_key_path(dict(agent)))
    try:
        key = path.read_bytes()
    except OSError as exc:
        raise RuntimeError("reasoning relay authorization signing key is unavailable") from exc
    if len(key) < 32:
        raise RuntimeError("reasoning relay authorization signing key is invalid")
    return key


def _signature_for(request: RelayRequest, agent: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        _canonical_claim_payload(request),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    digest = hmac.new(_signing_key(agent), canonical, hashlib.sha256).hexdigest()
    return f"v1:{digest}"


def attach_relay_authorization_claim(
    request: RelayRequest,
    *,
    agent: Mapping[str, Any],
) -> RelayRequest:
    payload = dict(request.payload)
    payload["runtime_claim"] = {
        "version": CLAIM_VERSION,
        "signature": _signature_for(request, agent),
    }
    return replace(request, payload=payload)


def verify_relay_authorization_claim(
    request: RelayRequest,
    *,
    agent: Mapping[str, Any],
) -> None:
    claim = request.payload.get("runtime_claim")
    if not isinstance(claim, Mapping) or int(claim.get("version") or 0) != CLAIM_VERSION:
        raise PermissionError("reasoning relay request is missing a valid runtime authorization claim")
    supplied = str(claim.get("signature") or "")
    expected = _signature_for(request, agent)
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise PermissionError("reasoning relay request authorization claim is invalid")
