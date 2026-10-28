"""Both reasoning providers remain independent and explicit."""
from codex_slack_bridge.agent_worker import _select_execution_backend
from codex_slack_bridge.agent_readiness import _effective_provider
import pytest


def test_codex_stays_default_with_relay_enabled():
    assert _effective_provider("tickets_agent", {"provider": "codex_cli"}) == "codex_cli"
    assert _select_execution_backend("codex_cli", "", relay_enabled=True) == "codex"
    assert _select_execution_backend("codex_cli_direct", "", relay_enabled=True) == "codex"


def test_relay_is_explicitly_selectable_without_disabling_codex():
    assert _select_execution_backend("codex_cli", "chatgpt_relay", relay_enabled=True) == "relay"
    assert _select_execution_backend("codex_cli", "codex_cli", relay_enabled=True) == "codex"
    with pytest.raises(RuntimeError, match="not enabled"):
        _select_execution_backend("codex_cli", "chatgpt_relay", relay_enabled=False)


def test_unsupported_override_cannot_expand_provider_scope():
    with pytest.raises(PermissionError):
        _select_execution_backend("chatgpt_work_relay", "codex_cli", relay_enabled=True)
    with pytest.raises(ValueError):
        _select_execution_backend("codex_cli", "arbitrary", relay_enabled=True)
