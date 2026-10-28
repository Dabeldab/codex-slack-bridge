from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import re
import uuid
from typing import Any, Mapping


PROTOCOL_VERSION = 1
MESSAGE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,199}$")
LANE_RE = re.compile(r"^[a-z][a-z0-9_]{1,79}$")
ALLOWED_REQUEST_KINDS = frozenset({"reasoning_request", "tool_result", "protocol_error"})
ALLOWED_RESPONSE_KINDS = frozenset({"tool_request", "final_response"})
MAX_TEXT_CHARS = 120_000
MAX_TOOL_RESULT_CHARS = 180_000
MAX_ARGUMENT_BYTES = 64_000


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def new_message_id(prefix: str = "relay") -> str:
    clean = re.sub(r"[^A-Za-z0-9._:-]+", "-", str(prefix or "relay").strip()).strip("-")
    clean = clean[:40] or "relay"
    return f"{clean}:{uuid.uuid4().hex}"


def _bounded_text(value: Any, *, field: str, limit: int = MAX_TEXT_CHARS, required: bool = False) -> str:
    text = str(value or "")
    if required and not text.strip():
        raise ValueError(f"{field} is required")
    if len(text) > limit:
        raise ValueError(f"{field} exceeds {limit} characters")
    return text


def _message_id(value: Any, *, field: str = "message_id") -> str:
    clean = str(value or "").strip()
    if not MESSAGE_ID_RE.fullmatch(clean):
        raise ValueError(f"{field} is invalid")
    return clean


def _lane(value: Any) -> str:
    clean = str(value or "").strip()
    if not LANE_RE.fullmatch(clean):
        raise ValueError("lane is invalid")
    return clean


def _json_size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


@dataclass(frozen=True)
class RelayRequest:
    message_id: str
    lane: str
    kind: str
    conversation_id: str
    job_id: int | None
    created_at: str
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol_version": PROTOCOL_VERSION,
            "direction": "to_chatgpt",
            "message_id": self.message_id,
            "lane": self.lane,
            "kind": self.kind,
            "conversation_id": self.conversation_id,
            "job_id": self.job_id,
            "created_at": self.created_at,
            "payload": self.payload,
        }

    @classmethod
    def create(
        cls,
        *,
        lane: str,
        kind: str,
        conversation_id: str,
        job_id: int | None,
        payload: Mapping[str, Any],
        message_id: str | None = None,
    ) -> "RelayRequest":
        clean_kind = str(kind or "").strip()
        if clean_kind not in ALLOWED_REQUEST_KINDS:
            raise ValueError("request kind is invalid")
        clean_payload = dict(payload)
        if _json_size(clean_payload) > 450_000:
            raise ValueError("relay request payload is too large")
        return cls(
            message_id=_message_id(message_id or new_message_id(lane)),
            lane=_lane(lane),
            kind=clean_kind,
            conversation_id=_bounded_text(conversation_id, field="conversation_id", limit=500, required=True),
            job_id=int(job_id) if job_id is not None else None,
            created_at=utc_now(),
            payload=clean_payload,
        )

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "RelayRequest":
        if int(raw.get("protocol_version") or 0) != PROTOCOL_VERSION:
            raise ValueError("unsupported relay protocol version")
        if str(raw.get("direction") or "") != "to_chatgpt":
            raise ValueError("relay request direction is invalid")
        payload = raw.get("payload")
        if not isinstance(payload, Mapping):
            raise ValueError("relay request payload must be an object")
        clean_kind = str(raw.get("kind") or "").strip()
        if clean_kind not in ALLOWED_REQUEST_KINDS:
            raise ValueError("request kind is invalid")
        return cls(
            message_id=_message_id(raw.get("message_id")),
            lane=_lane(raw.get("lane")),
            kind=clean_kind,
            conversation_id=_bounded_text(raw.get("conversation_id"), field="conversation_id", limit=500, required=True),
            job_id=int(raw["job_id"]) if raw.get("job_id") is not None else None,
            created_at=_bounded_text(raw.get("created_at"), field="created_at", limit=80, required=True),
            payload=dict(payload),
        )


@dataclass(frozen=True)
class RelayResponse:
    in_reply_to: str
    lane: str
    kind: str
    created_at: str
    text: str = ""
    tool_call: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any], *, expected_request: RelayRequest) -> "RelayResponse":
        if int(raw.get("protocol_version") or 0) != PROTOCOL_VERSION:
            raise ValueError("unsupported relay response protocol version")
        if str(raw.get("direction") or "") != "to_runtime":
            raise ValueError("relay response direction is invalid")
        reply_to = _message_id(raw.get("in_reply_to"), field="in_reply_to")
        if reply_to != expected_request.message_id:
            raise ValueError("relay response does not match the pending request")
        lane = _lane(raw.get("lane"))
        if lane != expected_request.lane:
            raise ValueError("relay response lane does not match the pending request")
        kind = str(raw.get("kind") or "").strip()
        if kind not in ALLOWED_RESPONSE_KINDS:
            raise ValueError("relay response kind is invalid")
        created_at = _bounded_text(raw.get("created_at") or utc_now(), field="created_at", limit=80, required=True)
        if kind == "final_response":
            return cls(
                in_reply_to=reply_to,
                lane=lane,
                kind=kind,
                created_at=created_at,
                text=_bounded_text(raw.get("text"), field="text", limit=MAX_TEXT_CHARS, required=True),
            )
        call = raw.get("tool_call")
        if not isinstance(call, Mapping):
            raise ValueError("tool_request requires tool_call")
        call_id = _message_id(call.get("call_id"), field="tool_call.call_id")
        server = _bounded_text(call.get("server"), field="tool_call.server", limit=100, required=True).strip()
        tool = _bounded_text(call.get("tool"), field="tool_call.tool", limit=160, required=True).strip()
        arguments = call.get("arguments") or {}
        if not isinstance(arguments, Mapping):
            raise ValueError("tool_call.arguments must be an object")
        if _json_size(arguments) > MAX_ARGUMENT_BYTES:
            raise ValueError("tool_call.arguments is too large")
        return cls(
            in_reply_to=reply_to,
            lane=lane,
            kind=kind,
            created_at=created_at,
            tool_call={
                "call_id": call_id,
                "server": server,
                "tool": tool,
                "arguments": dict(arguments),
            },
        )


def compact_tool_result(value: Any) -> Any:
    """Bound a tool result before it becomes relay data."""
    try:
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        encoded = json.dumps({"text": str(value)}, ensure_ascii=False)
    if len(encoded) <= MAX_TOOL_RESULT_CHARS:
        try:
            return json.loads(encoded)
        except json.JSONDecodeError:
            return {"text": encoded}
    return {
        "truncated": True,
        "text": encoded[:MAX_TOOL_RESULT_CHARS],
    }
