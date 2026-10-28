from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TRANSFORMER = ROOT / "scripts" / "runtime_cutover_transform.py"


def _module():
    spec = importlib.util.spec_from_file_location("runtime_cutover_transform", TRANSFORMER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_bootstrap_transform_removes_codex_runtime_dependencies():
    module = _module()
    source = (ROOT / "deploy" / "gcp" / "agent-runtime" / "bootstrap-private-runtime.sh").read_text(encoding="utf-8")
    result = module.transform_bootstrap(source)
    for forbidden in (
        "@openai/codex",
        "/usr/local/bin/codex",
        "nova-codex-auth.service",
        "bootstrap-codex-auth",
        "CODEX_AUTH_MODE",
        "CODEX_VERSION",
    ):
        assert forbidden not in result
    assert "run-reasoning-relay-broker.sh" in result
    assert "preflight_chatgpt.py" in result
    assert "nova-runtime ALL=(nova-cloud-broker) NOPASSWD: /opt/nova/bin/run-reasoning-relay-broker" in result


def test_provisioner_transform_has_no_codex_or_openai_api_secret_dependency():
    module = _module()
    source = (ROOT / "deploy" / "gcp" / "agent-runtime" / "provision-private-runtime.ps1").read_text(encoding="utf-8")
    result = module.transform_provisioner(source)
    for forbidden in (
        "CodexAuthMode",
        "CodexVersion",
        "nova-agents-codex-access-token",
        "openai-api-key",
        "nova-codex-",
    ):
        assert forbidden not in result
    assert 'reasoningProvider = "chatgpt_work_relay"' in result
    assert 'openAiApiKeyRequired = $false' in result
    assert "startup-script=$(Join-Path $PSScriptRoot 'bootstrap-private-runtime.sh')" in result


def test_production_worker_uses_brokered_reasoning_runtime():
    worker = (ROOT / "src" / "codex_slack_bridge" / "agent_worker.py").read_text(encoding="utf-8")
    assert "reasoning_relay_runtime_secure" in worker
    assert "reasoning_relay_runtime import run_reasoning_relay_agent" not in worker


def test_production_start_scripts_use_broker_without_real_key_paths():
    for name in ("run-command-center.sh", "run-slack-bridge.sh"):
        text = (ROOT / "deploy" / "gcp" / "agent-runtime" / name).read_text(encoding="utf-8")
        assert "REASONING_RELAY_BROKER_COMMAND" in text
        assert "/run/nova-runtime/relay-readiness/private-key" in text
        assert "/run/nova-secrets/github-app-private-key" not in text
