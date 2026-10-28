from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Callable

from codex_slack_bridge.config import load_config

from . import preflight as legacy


CORE_RUNTIME_CHECKS = ("rory_isolation", "reasoning_relay", "agent_file_delivery")
REQUIRED_RELAY_LANES = (
    "direct_codex",
    "coding_agent",
    "tickets_agent",
    "billing_agent",
    "claude_agent",
)


def _probe_reasoning_relay() -> dict[str, Any]:
    config = load_config("/opt/nova/current/config/agents.chatgpt-runtime.yaml")
    providers = {
        lane: str((config.agents.get(lane) or {}).get("provider") or "").strip()
        for lane in REQUIRED_RELAY_LANES
    }
    raw_provider = str((config.agents.get("raw_codex") or {}).get("provider") or "").strip()
    command = [
        "/usr/sbin/runuser",
        "-u",
        "nova-runtime",
        "--",
        "/usr/bin/sudo",
        "-n",
        "-H",
        "-u",
        "nova-cloud-broker",
        "--",
        "/opt/nova/bin/run-reasoning-relay-broker",
    ]
    completed = subprocess.run(
        command,
        input=b'{"action":"health"}\n',
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
        check=False,
    )
    try:
        broker = json.loads(completed.stdout.decode("utf-8", errors="replace").strip() or "{}")
    except json.JSONDecodeError:
        broker = {}
    health = broker.get("health") if isinstance(broker, dict) else {}
    workflow_ready = Path("/opt/nova/current/.github/workflows/chatgpt-reasoning-relay.yml").is_file()
    providers_ready = all(value == "chatgpt_work_relay" for value in providers.values())
    raw_disabled = raw_provider == "disabled"
    broker_ready = bool(completed.returncode == 0 and isinstance(broker, dict) and broker.get("ok") is True)
    return {
        "ok": bool(providers_ready and raw_disabled and broker_ready and workflow_ready),
        "providers": providers,
        "rawCodexDisabled": raw_disabled,
        "brokerReady": broker_ready,
        "repository": str((health or {}).get("repository") or ""),
        "relayBranch": str((health or {}).get("branch") or ""),
        "relayBranchExists": bool((health or {}).get("branchExists")),
        "workflowReady": workflow_ready,
        "credentialsExposedToRuntime": False,
    }


def _readiness(checks: dict[str, dict[str, Any]]) -> dict[str, Any]:
    core_failures = [name for name in CORE_RUNTIME_CHECKS if not bool(checks.get(name, {}).get("ok"))]
    degraded = [name for name, value in checks.items() if name not in CORE_RUNTIME_CHECKS and not bool(value.get("ok"))]
    return {
        "ok": not core_failures,
        "fullyReady": not core_failures and not degraded,
        "degraded": bool(core_failures or degraded),
        "coreRequiredChecks": list(CORE_RUNTIME_CHECKS),
        "coreFailures": core_failures,
        "degradedChecks": degraded,
    }


def main() -> None:
    legacy.ZOOM_PREFLIGHT_MARKER.unlink(missing_ok=True)
    checks: dict[str, Any] = {}
    probes: dict[str, Callable[[], dict[str, Any]]] = {
        "slack": legacy._probe_slack,
        "gmail": legacy._probe_gmail,
        "agent_file_delivery": legacy._probe_agent_file_delivery,
        "google_workspace": legacy._probe_google_workspace,
        "chargify": legacy._probe_chargify,
        "rory_isolation": legacy._probe_rory_isolation,
        "reasoning_relay": _probe_reasoning_relay,
        "scoped_mcp_brokers": legacy._probe_scoped_mcp_brokers,
        "live_scoped_connectors": legacy._probe_live_scoped_connectors,
        "deterministic_ticket_close": legacy._probe_deterministic_ticket_close,
        "deterministic_location_region_update": legacy._probe_deterministic_location_region_update,
        "support_email_ticket_readback": legacy._probe_support_email_ticket_readback,
        "support_quality_ticket_projection": legacy._probe_support_quality_ticket_projection,
        "singapore": legacy._probe_singapore,
        "singapore_shared_access": legacy._probe_singapore_shared_access,
    }
    for name, probe in probes.items():
        try:
            checks[name] = probe()
        except Exception as exc:
            checks[name] = {"ok": False, "errorType": type(exc).__name__}
    try:
        checks["salesforce"], checks["nova_sql"] = legacy._probe_salesforce_and_sql()
    except Exception as exc:
        checks["salesforce"] = {"ok": False, "errorType": type(exc).__name__}
        checks["nova_sql"] = {"ok": False, "blockedBy": "salesforce_or_network"}

    readiness = _readiness(checks)
    zoom_ok = bool(
        checks.get("live_scoped_connectors", {})
        .get("connectors", {})
        .get("zoom", {})
        .get("ok")
    )
    if readiness["ok"] and zoom_ok:
        legacy.ZOOM_PREFLIGHT_MARKER.touch(mode=0o600)
        legacy.ZOOM_PREFLIGHT_MARKER.chmod(0o600)
    print(json.dumps({**readiness, "checks": checks}, sort_keys=True, separators=(",", ":")))
    raise SystemExit(0 if readiness["ok"] else 1)


if __name__ == "__main__":
    main()
