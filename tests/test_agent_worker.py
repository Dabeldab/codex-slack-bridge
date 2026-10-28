from __future__ import annotations

import json

from codex_slack_bridge.agent_worker import _serialize_response


def test_worker_response_envelope_is_ascii_safe_and_round_trips_unicode():
    framed = _serialize_response({"ok": True, "result": "queued → reviewed ✅"})

    framed.encode("cp1252")
    payload = framed.split("__CODEX_AGENT_RESULT__", 1)[1]
    assert json.loads(payload) == {"ok": True, "result": "queued → reviewed ✅"}
