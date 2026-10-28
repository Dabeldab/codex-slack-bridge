from __future__ import annotations

from typing import Any

ALLOWED_VOICES: tuple[str, ...] = ()
MAX_SDP_BYTES = 256 * 1024


class VoiceRoomError(RuntimeError):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


class VoiceRoomGateway:
    """Fail-closed voice surface for the Codex-only runtime."""

    def __init__(self, *, enabled: bool = False, **_: Any) -> None:
        self.enabled = False

    def status(self) -> dict[str, Any]:
        return {
            "ok": True,
            "enabled": False,
            "ready": False,
            "provider": None,
            "transport": None,
            "sessionEndpoint": "/voice/realtime/session",
            "model": None,
            "defaultVoice": None,
            "allowedVoices": [],
            "apiKeyConfigured": False,
            "externalWritesAllowed": False,
            "actionRoute": "command-center-text-dispatch",
            "reason": "Codex-only runtime",
        }

    def create_session(self, sdp_offer: bytes, *, voice: str | None = None) -> bytes:
        raise VoiceRoomError(503, "Voice Room is unavailable in the Codex-only runtime.")
