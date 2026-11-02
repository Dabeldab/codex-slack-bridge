from __future__ import annotations

import json
from pathlib import Path

from codex_slack_bridge.agent_worker import _serialize_response
from codex_slack_bridge.agents import _credential_vault_path


def test_worker_response_envelope_is_ascii_safe_and_round_trips_unicode():
    framed = _serialize_response({"ok": True, "result": "queued → reviewed ✅"})

    framed.encode("cp1252")
    payload = framed.split("__CODEX_AGENT_RESULT__", 1)[1]
    assert json.loads(payload) == {"ok": True, "result": "queued → reviewed ✅"}


def test_credential_vault_path_does_not_create_operator_directory(tmp_path: Path) -> None:
    missing_vault = tmp_path / "missing-vault"

    resolved = _credential_vault_path({"credential_vault_path": str(missing_vault)})

    assert Path(resolved) == missing_vault.resolve()
    assert not missing_vault.exists()
