from __future__ import annotations

# AgentChat/coding_agent 2026-08-07T12:14:00Z: verify cross-owner Zoom OAuth state startup.
# AgentChat/direct_codex 2026-08-04T15:35:00Z: include the shift reminder timer in preflight fencing.
# AgentChat/direct_codex 2026-07-24T13:45:00Z: verify the weekly Yaron watcher
# is the only newly enabled private-runtime writer.

import importlib.util
import json
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from codex_slack_bridge.config import load_config


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "deploy" / "gcp" / "agent-runtime" / "materialize_secrets.py"
SPEC = importlib.util.spec_from_file_location("materialize_secrets", MODULE_PATH)
assert SPEC and SPEC.loader
materialize_secrets = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(materialize_secrets)

PREFLIGHT_MODULE_PATH = ROOT / "deploy" / "gcp" / "agent-runtime" / "preflight.py"
PREFLIGHT_SPEC = importlib.util.spec_from_file_location(
    "agent_runtime_preflight",
    PREFLIGHT_MODULE_PATH,
)
assert PREFLIGHT_SPEC and PREFLIGHT_SPEC.loader
agent_runtime_preflight = importlib.util.module_from_spec(PREFLIGHT_SPEC)
PREFLIGHT_SPEC.loader.exec_module(agent_runtime_preflight)


def test_secret_manifest_requires_numeric_version_and_runtime_path(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps(
            {
                "project_id": "gen-lang-client-0051653266",
                "secrets": [
                    {
                        "id": "nova-agents-slack-bot-token",
                        "version": "latest",
                        "path": "/run/nova-secrets/slack-bot-token",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(materialize_secrets.SecretManifestError, match="numeric version pin"):
        materialize_secrets.load_manifest(path)

    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["secrets"][0]["version"] = "7"
    raw["secrets"][0]["path"] = "/tmp/escaped"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(materialize_secrets.SecretManifestError, match="under /run/nova-secrets"):
        materialize_secrets.load_manifest(path)


def test_secret_manifest_accepts_a_utf8_bom_without_exposing_values(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    path.write_bytes(
        b"\xef\xbb\xbf"
        + json.dumps(
            {
                "project_id": "gen-lang-client-0051653266",
                "secrets": [
                    {
                        "id": "nova-agents-slack-bot-token",
                        "version": "1",
                        "path": "/run/nova-secrets/slack-bot-token",
                    }
                ],
            }
        ).encode("utf-8")
    )

    manifest = materialize_secrets.load_manifest(path)

    assert manifest["project_id"] == "gen-lang-client-0051653266"
    assert manifest["secrets"][0]["version"] == "1"


def test_materializer_never_returns_secret_payload(monkeypatch, tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps(
            {
                "project_id": "gen-lang-client-0051653266",
                "secrets": [
                    {
                        "id": "nova-agents-slack-bot-token",
                        "version": "3",
                        "path": "/run/nova-secrets/slack-bot-token",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    manifest = materialize_secrets.load_manifest(path)
    payload = b"do-not-return-this-secret"
    written: dict[str, bytes] = {}

    class FakeClient:
        def access_secret_version(self, request):
            assert request["name"].endswith("/versions/3")
            return SimpleNamespace(payload=SimpleNamespace(data=payload, data_crc32c=123))

    monkeypatch.setattr(materialize_secrets, "_verify_crc32c", lambda value, expected: None)
    monkeypatch.setattr(
        materialize_secrets,
        "_write_secret",
        lambda target, value, **kwargs: written.update({str(target): value}),
    )

    result = materialize_secrets.materialize(manifest, client=FakeClient())

    assert list(written.values()) == [payload]
    assert payload.decode() not in json.dumps(result)
    assert result == [
        {"id": "nova-agents-slack-bot-token", "version": "3", "status": "materialized"}
    ]


def test_cloud_runtime_templates_force_chatgpt_and_keep_rory_on_codex_cli() -> None:
    codex_home = ROOT / "deploy" / "gcp" / "agent-runtime" / "codex-home"
    rory = (codex_home / "rory.toml").read_text(encoding="utf-8")
    taylor = (codex_home / "taylor.toml").read_text(encoding="utf-8")
    overlay = (ROOT / "config" / "agents.gcp-runtime.yaml").read_text(encoding="utf-8")

    assert 'forced_login_method = "chatgpt"' in rory
    assert "GEMINI_API_KEY" not in rory
    assert "nova-rory" in overlay
    assert 'provider: openai' not in overlay
    assert "gcp_github_ops" in rory
    assert "rory_operator_ops" in rory
    assert "salesforce_operator_ops" in rory
    assert '"/opt/nova/bin/run-cloud-ops-broker", "coding_agent"' in taylor


def test_cloud_runtime_approval_policies_match_each_lane() -> None:
    codex_home = ROOT / "deploy" / "gcp" / "agent-runtime" / "codex-home"
    workspaces = {
        "rory": "/srv/nova/workspaces/rory",
        "taylor": "/srv/nova/workspaces/taylor",
        "alex": "/srv/nova/workspaces/alex",
        "jamie": "/srv/nova/workspaces/jamie",
        "raw": "/srv/nova/workspaces/raw",
        "claude": "/srv/nova/workspaces/claude",
    }
    for name, workspace in workspaces.items():
        config = tomllib.loads((codex_home / f"{name}.toml").read_text(encoding="utf-8"))
        assert config["approval_policy"] == "never"
        assert config["approvals_reviewer"] == "user"
        assert config["analytics"] == {"enabled": False}
        assert config["feedback"] == {"enabled": False}
        assert config["otel"] == {
            "exporter": "none",
            "metrics_exporter": "none",
            "trace_exporter": "none",
            "log_user_prompt": False,
        }
        assert "auto_review" not in config
        assert config["projects"] == {workspace: {"trust_level": "trusted"}}
        if name in {"rory", "claude", "taylor", "alex", "jamie"}:
            assert config["mcp_servers"]
            assert all(
                server["default_tools_approval_mode"] == "approve"
                for server in config["mcp_servers"].values()
            )


def test_cloud_runtime_disables_telemetry_in_every_agent_process() -> None:
    bootstrap = (
        ROOT / "deploy" / "gcp" / "agent-runtime" / "bootstrap-private-runtime.sh"
    ).read_text(encoding="utf-8")
    preflight = (
        ROOT / "deploy" / "gcp" / "agent-runtime" / "preflight.py"
    ).read_text(encoding="utf-8")

    assert bootstrap.count("Environment=DO_NOT_TRACK=1") == 4
    assert bootstrap.count("Environment=OTEL_SDK_DISABLED=true") == 4
    assert '"telemetryDisabled": telemetry_disabled' in preflight


def test_deterministic_close_and_singapore_shared_state_are_least_privilege() -> None:
    runtime = ROOT / "deploy" / "gcp" / "agent-runtime"
    bootstrap = (runtime / "bootstrap-private-runtime.sh").read_text(encoding="utf-8")
    close_launcher = (runtime / "run-salesforce-ticket-close.sh").read_text(encoding="utf-8")
    location_region_launcher = (
        runtime / "run-nova-location-region.sh"
    ).read_text(encoding="utf-8")
    support_readback_launcher = (
        runtime / "run-salesforce-support-email-readback.sh"
    ).read_text(encoding="utf-8")
    support_quality_launcher = (
        runtime / "run-salesforce-support-quality-projection.sh"
    ).read_text(encoding="utf-8")
    singapore_launcher = (runtime / "run-singapore-background.sh").read_text(encoding="utf-8")
    approval_probe = (runtime / "verify-codex-mcp-approval.py").read_text(encoding="utf-8")

    assert "nova-singapore-shared" in bootstrap
    assert "usermod -a -G nova-singapore-shared nova-runtime" in bootstrap
    assert "usermod -a -G nova-singapore-shared nova-singapore-broker" in bootstrap
    assert "-g nova-singapore-shared /var/lib/nova/broker/singapore-shared" in bootstrap
    assert "nova-internal-comms" in bootstrap
    assert "usermod -a -G nova-internal-comms nova-salesforce-broker" in bootstrap
    assert "usermod -a -G nova-internal-comms nova-zoom-broker" in bootstrap
    assert "usermod -a -G nova-internal-comms nova-singapore-broker" in bootstrap
    assert "-g nova-internal-comms /var/lib/nova/broker/internal-comms" in bootstrap
    assert "for internal_comms_file in" in bootstrap
    assert 'chgrp nova-internal-comms "$internal_comms_file"' in bootstrap
    assert 'chmod 0660 "$internal_comms_file"' in bootstrap
    assert "usermod -a -G nova-zoom-credentials nova-cloud-broker" in bootstrap
    assert "-g nova-zoom-credentials /var/lib/nova/broker/zoom" in bootstrap
    assert "for zoom_state_file in /var/lib/nova/broker/zoom/oauth.env /var/lib/nova/broker/zoom/oauth.env.lock" in bootstrap
    assert 'chgrp nova-zoom-credentials "$zoom_state_file"' in bootstrap
    assert 'chmod 0660 "$zoom_state_file"' in bootstrap
    assert "ZOOM_OAUTH_STATE_PATH" not in singapore_launcher
    assert "ZOOM_OAUTH_SHARED_STATE" not in singapore_launcher
    assert 'export ZOOM_ACCOUNT_ID="$(cat "$secret_root/zoom-s2s-account-id")"' in singapore_launcher
    assert 'export ZOOM_CLIENT_ID="$(cat "$secret_root/zoom-s2s-client-id")"' in singapore_launcher
    assert 'export ZOOM_CLIENT_SECRET="$(cat "$secret_root/zoom-s2s-client-secret")"' in singapore_launcher
    assert (
        'export ZOOM_TEAM_CHAT_SENDER_USER_ID="$(cat '
        '"$secret_root/zoom-team-chat-sender-user-id")"'
    ) in singapore_launcher
    assert (
        "NOVA_INTERNAL_COMMUNICATION_JOURNAL_PATH="
        "/var/lib/nova/broker/internal-comms/verified-requests.jsonl"
    ) in singapore_launcher
    assert "NOVA_SINGAPORE_JULIO_EMAIL" not in singapore_launcher
    assert "umask 0007" in singapore_launcher
    assert (
        "nova-runtime ALL=(nova-salesforce-broker) NOPASSWD: "
        "/opt/nova/bin/run-salesforce-ticket-close"
    ) in bootstrap
    assert (
        "nova-runtime ALL=(nova-salesforce-broker) NOPASSWD: "
        "/opt/nova/bin/run-nova-location-region"
    ) in bootstrap
    assert (
        "nova-runtime ALL=(nova-salesforce-broker) NOPASSWD: "
        "/opt/nova/bin/run-salesforce-support-email-readback"
    ) in bootstrap
    assert (
        "nova-runtime ALL=(nova-salesforce-broker) NOPASSWD: "
        "/opt/nova/bin/run-salesforce-support-quality-projection"
    ) in bootstrap
    for user in ("nova-rory", "nova-raw", "nova-claude", "nova-taylor", "nova-alex", "nova-jamie"):
        assert f"{user} ALL=(nova-salesforce-broker) NOPASSWD: /opt/nova/bin/run-salesforce-ticket-close" not in bootstrap
        assert (
            f"{user} ALL=(nova-salesforce-broker) NOPASSWD: "
            "/opt/nova/bin/run-nova-location-region"
        ) not in bootstrap
        assert (
            f"{user} ALL=(nova-salesforce-broker) NOPASSWD: "
            "/opt/nova/bin/run-salesforce-support-email-readback"
        ) not in bootstrap
        assert (
            f"{user} ALL=(nova-salesforce-broker) NOPASSWD: "
            "/opt/nova/bin/run-salesforce-support-quality-projection"
        ) not in bootstrap
    assert "JSON on stdin only" in close_launcher
    assert "JSON on stdin only" in location_region_launcher
    assert (
        "scoped_operations_mcp.nova_sql_location_region_cli"
        in location_region_launcher
    )
    assert "JSON on stdin only" in support_readback_launcher
    assert "JSON on stdin only" in support_quality_launcher
    assert (
        "scoped_operations_mcp.salesforce_support_quality_projection_cli"
        in support_quality_launcher
    )
    assert "salesforce_support_email_readback_cli" in support_readback_launcher
    assert "Description__c" not in support_readback_launcher
    assert '("thread_id", "session_id")' in approval_probe
    assert "event.get(key)" in approval_probe
    assert '"freshSessionApproved"' in approval_probe
    assert '"resumedSessionApproved"' in approval_probe
    assert 'default_tools_approval_mode="approve"' in approval_probe
    assert '"rory": ("nova-rory", "/home/nova-rory")' in approval_probe
    assert "config_before = config_path.read_bytes()" in approval_probe
    assert "_restore_config(" in approval_probe


def test_cloud_brokers_keep_provider_secrets_out_of_codex_users() -> None:
    runtime = ROOT / "deploy" / "gcp" / "agent-runtime"
    bootstrap = (runtime / "bootstrap-private-runtime.sh").read_text(encoding="utf-8")
    taylor = (runtime / "codex-home" / "taylor.toml").read_text(encoding="utf-8")
    jamie = (runtime / "codex-home" / "jamie.toml").read_text(encoding="utf-8")
    provision = (runtime / "provision-private-runtime.ps1").read_text(encoding="utf-8")

    assert "nova-maxio-broker" in bootstrap
    assert "/var/lib/nova/broker/salesforce" in bootstrap
    for broker in ("nova-cloud-broker", "nova-rescue-broker", "nova-zoom-broker", "nova-singapore-broker"):
        assert broker in bootstrap
    assert '"/opt/nova/bin/run-maxio-broker", "coding_agent"' in taylor
    assert '"/opt/nova/bin/run-maxio-broker", "billing_agent"' in jamie
    assert "nova-maxio-broker" in provision
    assert "CHARGIFY_API_KEY" not in taylor
    assert "CHARGIFY_API_KEY" not in jamie
    assert "auto-delete=no" in provision
    assert "install -d -m 0711 -o root -g root /var/lib/nova/broker" in bootstrap
    assert "\ncd /\n" in (runtime / "run-salesforce-broker.sh").read_text(encoding="utf-8")
    assert "\ncd /\n" in (runtime / "run-maxio-broker.sh").read_text(encoding="utf-8")
    assert (
        "SALESFORCE_OPERATION_JOURNAL_PATH=/var/lib/nova/broker/salesforce/operations.jsonl"
        in (runtime / "run-salesforce-broker.sh").read_text(encoding="utf-8")
    )
    assert (
        'SALESFORCE_SUPPORT_EMAIL_TICKET_CREATED_BY="Darius Parlor"'
        in (runtime / "run-salesforce-broker.sh").read_text(encoding="utf-8")
    )

    config = load_config(ROOT / "config" / "agents.gcp-runtime.yaml")
    assert "maxio_coding_ops" in config.agents["coding_agent"]["mcp_allowlist"]
    assert "maxio_billing_ops" in config.agents["billing_agent"]["mcp_allowlist"]
    assert config.defaults["command_center_data_root"] == "/var/lib/nova/state/command_center"
    assert config.defaults["ops_support_email_intake_enabled"] is True
    assert (
        config.defaults["ops_support_email_salesforce_readback_executor"]
        == "/opt/nova/bin/run-salesforce-support-email-readback"
    )
    assert (
        config.defaults[
            "ops_weekly_support_quality_salesforce_projection_executor"
        ]
        == "/opt/nova/bin/run-salesforce-support-quality-projection"
    )
    assert "gcp_github_ops" in config.agents["direct_codex"]["mcp_allowlist"]
    assert "rory_operator_ops" in config.agents["direct_codex"]["mcp_allowlist"]
    assert "salesforce_operator_ops" in config.agents["direct_codex"]["mcp_allowlist"]
    assert "gcp_github_ops" in config.agents["coding_agent"]["mcp_allowlist"]
    assert (
        "nova-taylor ALL=(nova-cloud-broker) NOPASSWD: "
        "/opt/nova/bin/run-cloud-ops-broker coding_agent"
    ) in bootstrap
    assert "rescue_console" in config.agents["tickets_agent"]["mcp_allowlist"]
    assert "zoom_support_ops" in config.agents["tickets_agent"]["mcp_allowlist"]
    assert "zoom_coding_ops" in config.agents["coding_agent"]["mcp_allowlist"]
    assert "zoom_billing_ops" in config.agents["billing_agent"]["mcp_allowlist"]
    assert config.agents["claude_agent"]["mcp_allowlist"] == [
        "rescue_console",
        "zoom_quality_ops",
        "salesforce_ticket_reads",
        "google_drive_support_reads",
    ]
    assert '"/opt/nova/bin/run-zoom-broker", "billing_agent"' in jamie
    assert (
        "nova-jamie ALL=(nova-zoom-broker) NOPASSWD: "
        "/opt/nova/bin/run-zoom-broker billing_agent"
    ) in bootstrap


def test_private_command_center_gateway_is_secret_backed_and_network_scoped() -> None:
    runtime = ROOT / "deploy" / "gcp" / "agent-runtime"
    bootstrap = (runtime / "bootstrap-private-runtime.sh").read_text(encoding="utf-8")
    command = (runtime / "run-command-center.sh").read_text(encoding="utf-8")
    provision = (runtime / "provision-private-runtime.ps1").read_text(encoding="utf-8")
    deploy = (ROOT / "deploy" / "gcp" / "deploy-cloud-run-shadow.ps1").read_text(
        encoding="utf-8"
    )

    assert "LoadCredential=command-center-proxy-token:" in bootstrap
    assert "RuntimeDirectory=nova-runtime" in bootstrap
    assert "COMMAND_CENTER_TRUSTED_BEARER_PATH=/run/nova-runtime/command-center-proxy.token" in command
    assert 'install -m 0600 "$CREDENTIALS_DIRECTORY/command-center-proxy-token" /run/nova-runtime/command-center-proxy.token' in bootstrap
    assert 'COMMAND_CENTER_HOST="${COMMAND_CENTER_HOST:-127.0.0.1}"' in command
    assert "nova-command-center-upstream-token" in provision
    assert "--vpc-egress=private-ranges-only" in deploy
    assert "--network-tags=$VPCNetworkTag" in deploy
    assert "/run/secrets/command-center-upstream-token" in deploy
    assert "[int]$UpstreamTokenVersion = 0" in deploy
    assert '"--sort-by=~createTime"' in deploy
    assert "Pinned private gateway token version: $UpstreamTokenVersion" in deploy
    assert "secrets versions describe $UpstreamTokenVersion" in deploy
    assert "requested private gateway token version is not enabled" in deploy
    assert "$upstreamVolumeVersions.Count -lt 1" in deploy
    assert "deployed private gateway token version is not enabled" in deploy
    assert "--concurrency=16" in deploy
    assert "COMMAND_CENTER_UPSTREAM_TIMEOUT_SECONDS=15" in deploy
    assert "$readbackConcurrency -ne 16" in deploy


def test_private_command_center_has_local_process_and_health_recovery() -> None:
    runtime = ROOT / "deploy" / "gcp" / "agent-runtime"
    bootstrap = (runtime / "bootstrap-private-runtime.sh").read_text(encoding="utf-8")
    provision = (runtime / "provision-private-runtime.ps1").read_text(encoding="utf-8")

    assert "Restart=always" in bootstrap
    assert "StartLimitIntervalSec=300" in bootstrap
    assert "nova-command-center-healthcheck.timer" in bootstrap
    assert "OnUnitActiveSec=60s" in bootstrap
    assert "http://127.0.0.1:17866/healthz" in bootstrap
    assert "nova-runtime-recovery.timer" in bootstrap
    assert "OnUnitActiveSec=2m" in bootstrap
    assert "systemctl enable --now nova-runtime-recovery.timer" in bootstrap
    assert "[ -f \"$runtime_marker\" ] && exit 0" in bootstrap
    assert "systemctl start nova-agent-preflight.service" in bootstrap
    assert "Production preflight is still blocked; core services remain stopped." in bootstrap
    assert "Production preflight recovered; core services were restored once." in bootstrap
    assert "disable --now nova-runtime-recovery.timer" in provision
    assert "systemctl restart nova-command-center.service" in bootstrap
    assert "nova-command-center-healthcheck.timer" in provision


def test_support_reminder_timer_obeys_shared_automation_window() -> None:
    runner = (
        ROOT / "deploy" / "gcp" / "agent-runtime" / "run-support-shift-reminders.sh"
    ).read_text(encoding="utf-8")

    gate = "python -m codex_slack_bridge.automation_window"
    reminder = "python -m codex_slack_bridge.support_shift_reminders"
    assert gate in runner
    assert runner.index(gate) < runner.index("secret_root=/run/nova-secrets")
    assert runner.index(gate) < runner.index(reminder)
    assert 'if [ "$automation_window_status" -eq 3 ]' in runner
    assert "deferred until the daily window opens" in runner
    assert 'test -r "$state_path" && test -w "$state_path"' in runner
    assert 'chgrp nova-zoom-credentials "$state_path"' not in runner
    assert 'chmod 0660 "$state_path"' not in runner


def test_cloud_scheduler_automation_window_script_preserves_watchdog() -> None:
    script = (ROOT / "deploy" / "gcp" / "set-automation-window.ps1").read_text(
        encoding="utf-8"
    )

    assert '[string]$TimeZone = "America/New_York"' in script
    assert '[string]$LogMeInSchedule = "*/15 8-18 * * *"' in script
    assert '[string]$QualitySchedule = "30 8 * * *"' in script
    assert 'name = "logmein-connector-scheduler-trigger"' in script
    assert 'name = "quality-emailer-logmein-connector-scheduler-trigger"' in script
    assert '$watchdogName = "nova-command-center-runtime-watchdog"' in script
    assert "The always-on runtime watchdog changed unexpectedly." in script
    assert "PLAN ONLY" in script


def test_cloud_runtime_provisions_lane_scoped_agent_sandboxes() -> None:
    bootstrap = (
        ROOT / "deploy" / "gcp" / "agent-runtime" / "bootstrap-private-runtime.sh"
    ).read_text(encoding="utf-8")

    assert "install -d -m 0711 -o root -g root /srv/nova/workspaces /srv/nova/sandboxes" in bootstrap
    for mapping in (
        "direct_codex:nova-rory",
        "raw_codex:nova-raw",
        "coding_agent:nova-taylor",
        "tickets_agent:nova-alex",
        "billing_agent:nova-jamie",
        "claude_agent:nova-claude",
    ):
        assert mapping in bootstrap
    assert 'install -d -m 2770 -o "$owner" -g "$owner" "/srv/nova/sandboxes/$sandbox"' in bootstrap
    assert "awk -v target=\"$auth_home\" '$2 != target { print }' /etc/fstab" in bootstrap
    assert 'umount "$auth_home"' in bootstrap
    assert 'mount --bind "$auth_root" "$auth_home"' in bootstrap


def test_rory_operator_broker_is_exclusive_while_taylor_gets_only_guarded_cloud_broker() -> None:
    runtime = ROOT / "deploy" / "gcp" / "agent-runtime"
    bootstrap = (runtime / "bootstrap-private-runtime.sh").read_text(encoding="utf-8")
    provision = (runtime / "provision-private-runtime.ps1").read_text(encoding="utf-8")
    rory = (runtime / "codex-home" / "rory.toml").read_text(encoding="utf-8")
    config = load_config(ROOT / "config" / "agents.gcp-runtime.yaml")

    assert '"/opt/nova/bin/run-operator-broker", "direct_codex"' in rory
    assert '"/opt/nova/bin/run-salesforce-broker", "direct_codex"' in rory
    assert "nova-rory ALL=(nova-cloud-broker) NOPASSWD: /opt/nova/bin/run-operator-broker direct_codex" in bootstrap
    assert "nova-rory ALL=(nova-salesforce-broker) NOPASSWD: /opt/nova/bin/run-salesforce-broker direct_codex" in bootstrap
    for other in ("nova-runtime", "nova-raw", "nova-claude", "nova-taylor", "nova-alex", "nova-jamie"):
        assert f"{other} ALL=(nova-cloud-broker) NOPASSWD: /opt/nova/bin/run-operator-broker" not in bootstrap
    assert "ExecStartPost=/opt/nova/bin/apply-rory-operator-secret-acls" in bootstrap
    assert "/run/nova-secrets/command-center-proxy-token" in bootstrap
    assert 'RORY_COMMAND_CENTER_TOKEN_PATH="$secret_root/command-center-proxy-token"' in (
        runtime / "run-operator-broker.sh"
    ).read_text(encoding="utf-8")
    assert "nova-agents-github-user-token" in provision
    assert "nova-agents-google-workspace-adc" in provision
    assert '"roles/owner"' in provision
    assert '"roles/secretmanager.secretAccessor"' in provision

    assert config.agents["coding_agent"]["mcp_allowlist"] == [
        "openaiDeveloperDocs",
        "gcp_github_ops",
        "salesforce_coding_ops",
        "maxio_coding_ops",
        "zoom_coding_ops",
    ]
    assert config.agents["tickets_agent"]["mcp_allowlist"] == [
        "openaiDeveloperDocs", "rescue_console", "salesforce_support_ops", "zoom_support_ops"
    ]
    assert config.agents["billing_agent"]["mcp_allowlist"] == [
        "openaiDeveloperDocs", "salesforce_billing_ops", "maxio_billing_ops", "zoom_billing_ops"
    ]
    assert config.agents["claude_agent"]["mcp_allowlist"] == [
        "rescue_console",
        "zoom_quality_ops",
        "salesforce_ticket_reads",
        "google_drive_support_reads",
    ]


def test_runtime_validates_non_secret_mcp_policy_without_auth_home_access() -> None:
    runtime = ROOT / "deploy" / "gcp" / "agent-runtime"
    bootstrap = (runtime / "bootstrap-private-runtime.sh").read_text(encoding="utf-8")
    auth_bootstrap = (
        runtime / "bootstrap-codex-auth.sh"
    ).read_text(encoding="utf-8")
    overlay = (ROOT / "config" / "agents.gcp-runtime.yaml").read_text(encoding="utf-8")

    assert "install -d -m 0750 -o root -g nova-runtime /etc/nova/codex-mcp-policy" in bootstrap
    assert '"/etc/nova/codex-mcp-policy/$template.toml"' in bootstrap
    for template in ("rory", "raw", "claude", "taylor", "alex", "jamie"):
        assert f'/etc/nova/codex-mcp-policy/{template}.toml' in overlay
    assert 'install -d -m 0700 -o "$user" -g "$user" "$home/.codex"' in auth_bootstrap
    assert 'chmod 0750 "$home/.codex"' not in auth_bootstrap
    assert 'install -m 0640 -o "$user" -g "$user"' in auth_bootstrap
    assert 'chmod 0600 "$home/.codex/auth.json"' in auth_bootstrap

    config = load_config(ROOT / "config" / "agents.gcp-runtime.yaml")
    claude = config.agents["claude_agent"]
    assert claude["provider"] == "codex_cli"
    assert claude["workspace_root"] == "/srv/nova/workspaces/claude"
    assert claude["codex_command_prefix"][-2:] == ["nova-claude", "--"]
    assert claude["mcp_allowlist"] == [
        "rescue_console",
        "zoom_quality_ops",
        "salesforce_ticket_reads",
        "google_drive_support_reads",
    ]
    assert claude["sandbox"] == "read-only"
    assert claude["model"] == "gpt-5.6-terra"
    assert claude["effort"] == "medium"
    assert claude["extra_args"] == []
    assert "claude:nova-claude" in bootstrap
    assert "raw:nova-raw" in bootstrap
    assert "nova-rory ALL=(nova-cloud-broker) NOPASSWD: /opt/nova/bin/run-cloud-ops-broker raw_codex" not in bootstrap


def test_thor_runtime_has_bounded_zoom_rescue_and_salesforce_evidence_brokers() -> None:
    runtime = ROOT / "deploy" / "gcp" / "agent-runtime"
    bootstrap = (runtime / "bootstrap-private-runtime.sh").read_text(encoding="utf-8")
    rescue_launcher = (runtime / "run-rescue-broker.sh").read_text(encoding="utf-8")
    zoom_launcher = (runtime / "run-zoom-broker.sh").read_text(encoding="utf-8")
    preflight = (runtime / "preflight.py").read_text(encoding="utf-8")
    thor_home = tomllib.loads(
        (runtime / "codex-home" / "claude.toml").read_text(encoding="utf-8")
    )

    assert set(thor_home["mcp_servers"]) == {
        "rescue_console",
        "zoom_quality_ops",
        "salesforce_ticket_reads",
        "google_drive_support_reads",
    }
    assert thor_home["mcp_servers"]["rescue_console"]["args"][-1] == "claude_agent"
    assert thor_home["mcp_servers"]["zoom_quality_ops"]["args"][-1] == "claude_agent"
    assert thor_home["mcp_servers"]["salesforce_ticket_reads"]["args"][-1] == "claude_agent"
    assert thor_home["mcp_servers"]["google_drive_support_reads"]["args"][-1] == "claude_agent"
    assert all(
        server["default_tools_approval_mode"] == "approve"
        for server in thor_home["mcp_servers"].values()
    )
    assert (
        "nova-claude ALL=(nova-rescue-broker) NOPASSWD: "
        "/opt/nova/bin/run-rescue-broker claude_agent"
    ) in bootstrap
    assert (
        "nova-claude ALL=(nova-zoom-broker) NOPASSWD: "
        "/opt/nova/bin/run-zoom-broker claude_agent"
    ) in bootstrap
    assert (
        "nova-claude ALL=(nova-salesforce-broker) NOPASSWD: "
        "/opt/nova/bin/run-salesforce-broker claude_agent"
    ) in bootstrap
    assert (
        "nova-claude ALL=(nova-cloud-broker) NOPASSWD: "
        "/opt/nova/bin/run-thor-drive-broker claude_agent"
    ) in bootstrap
    assert "tickets_agent|claude_agent" in rescue_launcher
    assert "direct_codex|billing_agent|coding_agent|tickets_agent|claude_agent" in zoom_launcher
    assert 'if [ "$lane" != claude_agent ]; then' in zoom_launcher
    assert '"launcher": "/opt/nova/bin/run-thor-drive-broker"' in preflight
    assert '"google_support_drive_files_list"' in preflight
    assert '"google_workspace_api_request"' in preflight

    rescue_quality = preflight.split('"rescue_quality": {', 1)[1].split(
        '"zoom_coding": {', 1
    )[0]
    zoom_quality = preflight.split('"zoom_quality": {', 1)[1].split(
        '"rory_cloud": {', 1
    )[0]
    assert '"model_user": "nova-claude"' in rescue_quality
    assert '"lane": "claude_agent"' in rescue_quality
    for tool in (
        "rescue_console_status",
        "rescue_list_sessions",
        "rescue_read_chat",
        "rescue_read_performance",
    ):
        assert f'"{tool}"' in rescue_quality
    assert '"model_user": "nova-claude"' in zoom_quality
    assert '"lane": "claude_agent"' in zoom_quality
    for tool in (
        "zoom_capabilities",
        "zoom_health",
        "zoom_quality_voice_engagements",
        "zoom_quality_agent_performance",
        "zoom_quality_engagement_recordings",
        "zoom_quality_transcript",
        "zoom_operator_team_chat_recipient_resolve",
        "zoom_operator_team_chat_send",
        "zoom_team_chat_channels",
        "zoom_team_chat_history",
        "zoom_docs_archives",
        "zoom_docs_archive_content",
        "zoom_ghostbusters_overview_read",
        "zoom_ghostbusters_overview_update",
    ):
        assert f'"{tool}"' in preflight
    for tool in (
        "zoom_health",
        "zoom_quality_voice_engagements",
        "zoom_quality_agent_performance",
        "zoom_quality_engagement_recordings",
        "zoom_quality_transcript",
        "zoom_ghostbusters_overview_update",
    ):
        assert f'"{tool}"' in zoom_quality
    for forbidden in (
        "zoom_team_chat_recipient_resolve",
        "zoom_team_chat_send",
        "zoom_update",
        "zoom_delete",
        "zoom_transfer",
    ):
        assert f'"{forbidden}"' in zoom_quality
    assert (
        '"support_quality_ticket_projection": '
        "_probe_support_quality_ticket_projection"
    ) in preflight
    assert '"/opt/nova/bin/run-salesforce-support-quality-projection"' in preflight
    assert '"typed_support_quality_ticket_projection_only"' in preflight


def test_runtime_preflight_starts_exact_lane_brokers_from_agent_workspaces() -> None:
    runtime = ROOT / "deploy" / "gcp" / "agent-runtime"
    preflight = (runtime / "preflight.py").read_text(encoding="utf-8")
    salesforce_server = (
        ROOT
        / "tools"
        / "scoped-operations-mcp"
        / "src"
        / "scoped_operations_mcp"
        / "salesforce_server.py"
    ).read_text(encoding="utf-8")

    assert "StdioServerParameters" in preflight
    assert 'command="/usr/sbin/runuser"' in preflight
    assert '"launcher": "/opt/nova/bin/run-salesforce-broker"' in preflight
    assert '"salesforce_operator": {' in preflight
    salesforce_operator = preflight.split('"salesforce_operator": {', 1)[1].split(
        '"salesforce_coding": {', 1
    )[0]
    salesforce_coding = preflight.split('"salesforce_coding": {', 1)[1].split(
        '"salesforce_support": {', 1
    )[0]
    salesforce_support = preflight.split('"salesforce_support": {', 1)[1].split(
        '"salesforce_billing": {', 1
    )[0]
    salesforce_billing = preflight.split('"salesforce_billing": {', 1)[1].split(
        '"maxio_coding": {', 1
    )[0]
    salesforce_thor = preflight.split('"salesforce_thor": {', 1)[1].split(
        '"maxio_coding": {', 1
    )[0]
    thor_salesforce_reads = preflight.split("thor_salesforce_reads = {", 1)[1].split(
        "ticket_writes = {", 1
    )[0]
    assert '"salesforce_weekly_ticket_totals"' not in salesforce_operator
    assert '"salesforce_weekly_ticket_totals"' in salesforce_support
    assert '"required": thor_salesforce_reads' in salesforce_thor
    assert '"salesforce_weekly_ticket_totals"' in thor_salesforce_reads
    assert '"launcher": "/opt/nova/bin/run-maxio-broker"' in preflight
    assert '"launcher": "/opt/nova/bin/run-rescue-broker"' in preflight
    assert '"launcher": "/opt/nova/bin/run-zoom-broker"' in preflight
    assert '"launcher": "/opt/nova/bin/run-cloud-ops-broker"' in preflight
    assert '"launcher": "/opt/nova/bin/run-operator-broker"' in preflight
    assert '"taylor_cloud": {' in preflight
    assert '"taylor_github": {' in preflight
    assert 'and payload.get("mergeToolsExposed")' in preflight
    assert 'and not payload.get("directProtectedBranchWrites")' in preflight
    assert 'and payload.get("inlineFilePayloadsAccepted")' in preflight
    assert 'and not payload.get("brokerWorkspaceTraversalRequired")' in preflight
    for workspace in ("rory", "taylor", "alex", "jamie"):
        assert f'"workspace": "/srv/nova/workspaces/{workspace}"' in preflight
    assert '"nova_sql_execute_guarded"' in preflight
    assert '"nova_sql_location_region_update"' in salesforce_coding
    assert '"nova_sql_location_layaway_enable"' in salesforce_coding
    assert '"nova_sql_instyle_demo_sync_preview"' in preflight
    assert '"nova_sql_instyle_demo_sync_execute"' in preflight
    assert '"nova_sql_table_restore_preview"' in salesforce_coding
    assert '"nova_sql_table_restore_execute"' in salesforce_coding
    assert '"salesforce_support_email_ticket_create"' in salesforce_coding
    assert '"salesforce_location_lifecycle_order_preview"' in salesforce_coding
    assert '"salesforce_location_lifecycle_order_apply"' in salesforce_coding
    assert '"salesforce_reactivation_order_approval_preview"' not in salesforce_coding.split(
        '"forbidden": {', 1
    )[0]
    for forbidden in (
        '"salesforce_ticket_create"',
        '"salesforce_order_create"',
        '"salesforce_location_update"',
    ):
        assert forbidden in salesforce_coding
    for non_taylor_lane in (salesforce_operator, salesforce_support, salesforce_billing):
        assert '"nova_sql_location_region_update"' in non_taylor_lane
        assert '"nova_sql_location_layaway_enable"' in non_taylor_lane
        assert '"nova_sql_table_restore_preview"' in non_taylor_lane
        assert '"nova_sql_table_restore_execute"' in non_taylor_lane
    assert "TargetScopedProtectedDemoRestoreGateway" in salesforce_server
    assert 'sql_capabilities.get("instyleDemoRebuildConfigured")' in preflight
    assert 'sql_capabilities.get("tableRestore", {}).get("configured")' in preflight
    assert '"operationDependenciesReady": operation_ready' in preflight
    assert '"nova_billing_locations_read"' in preflight
    assert '"maxio_subscription_creation_preview"' in preflight
    assert '"maxio_subscription_creation_apply"' in preflight
    assert '"maxio_billing_cycle_recovery_preview"' in preflight
    assert '"maxio_billing_cycle_recovery_apply"' in preflight
    assert '"maxio_nova_integrated_products"' in preflight
    assert '"maxio_nova_integrated_promo_credit_preview"' in preflight
    assert '"maxio_nova_integrated_promo_credit_apply"' in preflight
    assert "required_preapproved_servers = configured_servers" in preflight
    assert '"requiredPreapprovedServers": sorted(required_preapproved_servers)' in preflight
    assert '"scoped_mcp_brokers": _probe_scoped_mcp_brokers' in preflight
    assert '"rory_isolation": _probe_rory_isolation' in preflight
    assert (
        '"deterministic_location_region_update": '
        "_probe_deterministic_location_region_update"
    ) in preflight
    assert "fixed_location_region_update_only" in preflight


def test_zoom_and_thor_connectors_are_required_by_production_preflight() -> None:
    runtime = ROOT / "deploy" / "gcp" / "agent-runtime"
    preflight = (runtime / "preflight.py").read_text(encoding="utf-8")
    bootstrap = (runtime / "bootstrap-private-runtime.sh").read_text(encoding="utf-8")

    assert "OPTIONAL_LIVE_CONNECTORS: tuple[str, ...] = ()" in preflight
    assert "OPTIONAL_SCOPED_MCP_LANES: tuple[str, ...] = ()" in preflight
    assert '"mutationExposed": bool(payload.get("mutationExposed"))' in preflight
    assert 'not payload.get("permissionAdministrationExposed")' in preflight
    assert "optional_names=OPTIONAL_LIVE_CONNECTORS" in preflight
    assert '"optionalFailures": readiness["optionalFailures"]' in preflight
    assert 'ZOOM_PREFLIGHT_MARKER = Path("/run/nova-preflight/zoom-passed")' in preflight
    assert 'if ok and zoom_ok:' in preflight
    assert 'ZOOM_PREFLIGHT_MARKER=/run/nova-preflight/zoom-passed' in bootstrap
    assert 'ConditionPathExists=/run/nova-preflight/zoom-passed' in bootstrap
    assert 'systemctl disable --now nova-zoom-monitor.timer' in bootstrap
    assert 'systemctl enable nova-command-center.service nova-slack-bridge.service' in bootstrap
    assert 'systemctl enable nova-command-center.service nova-slack-bridge.service nova-zoom-monitor.timer' not in bootstrap


def test_activated_runtime_restarts_only_after_preflight() -> None:
    bootstrap = (
        ROOT / "deploy" / "gcp" / "agent-runtime" / "bootstrap-private-runtime.sh"
    ).read_text(encoding="utf-8")

    assert "install -d -m 0700 -o root -g root /var/lib/nova/activation" in bootstrap
    assert "PRODUCTION_CUTOVER_MARKER=/var/lib/nova/activation/production-cutover.enabled" in bootstrap
    assert bootstrap.index('if ! systemctl start nova-agent-preflight.service; then') < bootstrap.index(
        'systemctl restart nova-command-center.service'
    )
    assert "systemctl disable --now nova-command-center.service nova-slack-bridge.service" in bootstrap
    assert "RUNTIME_PREFLIGHT_MARKER=/run/nova-runtime/production-preflight-passed" in bootstrap
    assert bootstrap.count("ConditionPathExists=/run/nova-runtime/production-preflight-passed") == 5
    assert bootstrap.rindex('install -m 0600 -o root -g root /dev/null "$RUNTIME_PREFLIGHT_MARKER"') < bootstrap.rindex(
        'systemctl restart nova-command-center.service'
    )
    assert bootstrap.index('install -m 0600 -o root -g root /dev/null "$runtime_marker"') < bootstrap.index(
        'systemctl restart nova-command-center.service'
    )


def test_existing_runtime_promotion_is_explicit_quiesced_and_never_reset() -> None:
    runtime = ROOT / "deploy" / "gcp" / "agent-runtime"
    provision = (runtime / "provision-private-runtime.ps1").read_text(encoding="utf-8")
    readme = (runtime / "README.md").read_text(encoding="utf-8")

    assert "[switch]$UpdateExisting" in provision
    assert "UpdateExisting requires the private runtime instance to already exist" in provision
    assert "use -UpdateExisting for a guarded immutable promotion" in provision
    assert "existingRuntimeInvariantReady" in provision
    assert "Get-PrivateRuntimeInvariantFailures" in provision
    assert "compute instances add-metadata" in provision
    assert "compute ssh" in provision
    assert "--tunnel-through-iap" in provision
    assert "disable --now nova-command-center.service nova-slack-bridge.service" in provision
    assert "disable --now nova-zoom-monitor.timer" in provision
    promotion_start = provision.index(
        'if ($UpdateExisting) {\n            Invoke-Gcloud compute instances add-metadata'
    )
    promotion = provision[promotion_start:].split("\n        else {", 1)[0]
    assert promotion.index("compute instances add-metadata") < promotion.index("compute ssh")
    assert promotion.index("compute ssh") < promotion.index("Set-PrivateRuntimeWatchdogHold")
    assert promotion.index("Set-PrivateRuntimeWatchdogHold") < promotion.index(
        "compute instances stop"
    )
    assert promotion.index("compute instances stop") < promotion.index(
        "Start-PrivateRuntimeInstanceWithRetry"
    )
    assert "finally {" in promotion
    assert "if (-not $promotionRestartVerified)" in promotion
    assert "Clear-PrivateRuntimeWatchdogHold" in promotion
    assert "compute instances reset" not in provision
    assert "only_after_bootstrap_preflight" in provision
    assert "-CodexAuthMode device -UpdateExisting" in readme


def test_runtime_watchdog_is_external_exact_target_and_maintenance_safe() -> None:
    watchdog = ROOT / "deploy" / "gcp" / "runtime-watchdog"
    workflow_path = watchdog / "command-center-runtime-watchdog.yaml"
    installer = (watchdog / "install-runtime-watchdog.ps1").read_text(encoding="utf-8")
    provision = (
        ROOT / "deploy" / "gcp" / "agent-runtime" / "provision-private-runtime.ps1"
    ).read_text(encoding="utf-8")
    workflow_text = workflow_path.read_text(encoding="utf-8")
    workflow = yaml.safe_load(workflow_text)
    steps = {
        name: body
        for step in workflow["main"]["steps"]
        for name, body in step.items()
    }

    assert steps["read_instance"]["call"] == "googleapis.compute.v1.instances.get"
    assert steps["start_instance"]["call"] == "http.post"
    start_url = steps["start_instance"]["args"]["url"]
    assert "/instances/\" + instanceName + \"/start?requestId=" in start_url
    assert "GOOGLE_CLOUD_WORKFLOW_EXECUTION_ID" in workflow_text
    assert 'instance.status != "TERMINATED"' in workflow_text
    assert "holdUntil > sys.now()" in workflow_text
    assert 'action: "maintenance_hold"' in workflow_text
    assert "compute.v1.instances.stop" not in workflow_text
    assert "/stop" not in workflow_text
    assert "/delete" not in workflow_text

    assert '"compute.instances.get"' in installer
    assert '"compute.instances.start"' in installer
    assert "compute.instances.stop" not in installer
    assert "compute instances add-iam-policy-binding $Instance" in installer
    assert "--role=$CustomRole" in installer
    assert "roles/workflows.invoker" in installer
    assert "nova-runtime-watchdog-trigger" in installer
    assert '"*/2 * * * *"' in installer
    assert "--message-body-from-file=$schedulerMessagePath" in installer
    assert "--headers=Content-Type=application/json" in installer
    assert "--update-headers=Content-Type=application/json" in installer
    assert '"workflows",\n        "run",' in installer
    assert "Invoke-GcloudWithRetry -Attempts 12 -DelaySeconds 10" in installer
    assert "testExecutionState" in installer

    assert "[int]$PromotionWatchdogHoldSeconds = 900" in provision
    assert "--labels=nova-watchdog-hold-until=$holdUntil" in provision
    assert "remove-labels $Instance" in provision
    assert "external_workflow_after_expiring_maintenance_hold" in provision


def test_runtime_watchdog_repairs_only_the_exact_enabled_gateway_secret_pin() -> None:
    watchdog = ROOT / "deploy" / "gcp" / "runtime-watchdog"
    workflow_path = watchdog / "command-center-runtime-watchdog.yaml"
    installer_path = watchdog / "install-runtime-watchdog.ps1"
    workflow_text = workflow_path.read_text(encoding="utf-8")
    installer = installer_path.read_text(encoding="utf-8")
    workflow = yaml.safe_load(workflow_text)
    steps = {
        name: body
        for step in workflow["main"]["steps"]
        for name, body in step.items()
    }

    first_vm_condition = steps["choose_vm_action"]["switch"][0]
    assert first_vm_condition["condition"] == "${holdUntil > sys.now()}"
    assert first_vm_condition["next"] == "maintenance_hold"
    assert steps["choose_vm_action"]["switch"][1]["next"] == "read_manifest_metadata"

    assert "nova-secret-manifest" in workflow_text
    assert steps["read_target_secret_metadata"]["call"] == (
        "googleapis.secretmanager.v1.projects.secrets.versions.get"
    )
    assert (
        steps["read_target_secret_metadata"]["args"]["name"]
        == '${"projects/" + project + "/secrets/" + upstreamSecretName + '
        '"/versions/" + targetVersion}'
    )
    assert '!= "ENABLED"' in workflow_text
    assert "/versions/latest" not in workflow_text
    assert "secretmanager.v1.projects.secrets.versions.access" not in workflow_text
    assert "secretmanager.v1.projects.secrets.versions.enable" not in workflow_text

    assert steps["read_gateway_service"]["call"] == (
        "googleapis.run.v2.projects.locations.services.get"
    )
    patch = steps["patch_gateway_secret_pin"]
    assert patch["call"] == "googleapis.run.v2.projects.locations.services.patch"
    assert patch["args"]["allowMissing"] is False
    assert patch["args"]["updateMask"] == "template.volumes"
    assert patch["args"]["body"]["name"] == "${gatewayService.name}"
    assert patch["args"]["body"]["etag"] == "${gatewayService.etag}"
    assert patch["args"]["body"]["template"] == {
        "volumes": "${gatewayInspection.patchedVolumes}"
    }
    assert patch["args"]["connector_params"]["timeout"] == 300
    assert patch["args"]["connector_params"]["polling_policy"]["max_delay"] == 10
    assert "matchingItemCount < 1 or gatewayInspection.pinDiffers" in workflow_text

    inspect_text = yaml.safe_dump(workflow["inspectGatewayService"], sort_keys=False)
    assert "template" in inspect_text
    assert "volumes" in inspect_text
    assert "patchedVolumes" in inspect_text
    assert "map.merge" in inspect_text
    assert "matchingItemCount" in inspect_text
    assert "latestTrafficPercent == 100" in inspect_text
    assert "otherTrafficPercent == 0" in inspect_text
    assert "latestReadyRevision" in inspect_text
    assert "latestCreatedRevision" in inspect_text

    assert ":signJwt" in workflow_text
    assert 'aud: ${gatewayService.uri + "/healthz"}' in workflow_text
    assert 'url: ${healthUrl}' in workflow_text
    assert "timeout: 20" in workflow_text
    assert steps["call_end_to_end_health"]["try"]["call"] == "http.get"
    assert workflow["reportFailure"]["steps"][0]["log_failure"]["args"]["severity"] == "ALERT"
    assert "NOVA_COMMAND_CENTER_WATCHDOG_FAILURE" in workflow_text
    assert "zoom" not in workflow_text.lower()

    assert "compute.v1.instances.stop" not in workflow_text
    assert "/stop" not in workflow_text
    assert "/delete" not in workflow_text
    assert "run.v2.projects.locations.services.delete" not in workflow_text
    assert 'updateMask: "traffic"' not in workflow_text

    for permission in (
        "compute.instances.get",
        "compute.instances.start",
        "run.operations.get",
        "run.services.get",
        "run.services.update",
        "secretmanager.versions.get",
    ):
        assert f'"{permission}"' in installer
    assert "roles/iam.serviceAccountTokenCreator" in installer
    assert "roles/iam.serviceAccountUser" in installer
    assert "roles/iap.httpsResourceAccessor" in installer
    assert "roles/secretmanager.secretAccessor" not in installer
    assert "roles/run.admin" not in installer
    assert "roles/editor" not in installer.lower()
    assert "roles/owner" not in installer.lower()
    assert "iamcredentials.googleapis.com" in installer
    assert "iap.googleapis.com" in installer
    assert "secretmanager.googleapis.com" in installer
    assert "NOVA_WATCHDOG_GATEWAY_SERVICE=$GatewayService" in installer
    assert "NOVA_WATCHDOG_UPSTREAM_SECRET=$UpstreamTokenSecret" in installer
    assert "NOVA_WATCHDOG_SERVICE_ACCOUNT=$RuntimeServiceAccount" in installer
    assert "VM-manifest exact upstream-token version is not ENABLED" in installer
    assert "gatewayImageAfter -eq $GatewayImageBefore" in installer
    assert "gatewayServiceAccountAfter -eq $GatewayRuntimeServiceAccount" in installer
    assert "[int]$latestTrafficPercent -eq 100" in installer
    assert "[int]$otherTrafficPercent -eq 0" in installer
    assert installer.count('"*/2 * * * *"') == 1


def test_cloud_runtime_enables_only_guarded_portable_background_ingress_after_cutover() -> None:
    config = load_config(ROOT / "config" / "agents.gcp-runtime.yaml")

    assert config.defaults["command_center_provider_readiness_enabled"] is True
    assert config.defaults["command_center_provider_readiness_success_ttl_seconds"] == 300
    assert config.defaults["command_center_provider_readiness_failure_ttl_seconds"] == 30
    assert config.defaults["command_center_provider_readiness_probe_timeout_seconds"] == 10
    assert config.defaults["ops_inbox_ledger_enabled"] is True
    assert config.defaults["ops_inbox_ledger_fail_open_to_legacy"] is False
    assert config.defaults["ops_ticket_refresh_enabled"] is True
    assert config.defaults["ops_ticket_refresh_interval_seconds"] == 900
    assert config.defaults["capability_state_path"] == (
        "/var/lib/nova/state/agent_runtime/capabilities.json"
    )
    assert config.defaults["agent_runtime_restart_request_path"] == (
        "/var/lib/nova/state/agent_runtime/restart_request.json"
    )
    assert config.defaults["command_center_pause_manifest_path"] == (
        "/var/lib/nova/state/command_center/restart_manifest.json"
    )
    assert config.defaults["ops_ticket_refresh_output_root"] == (
        "/srv/nova/workspaces/alex/command-center-output/ticket-refresh"
    )
    assert config.defaults["ops_support_email_intake_enabled"] is True
    for key in (
        "ops_email_watch_enabled",
        "ops_schedule_watch_enabled",
        "ops_salesforce_delta_enabled",
        "ops_kpi_dashboard_enabled",
        "ops_propelr_nmi_enabled",
        "ops_weekly_yaron_report_enabled",
        "ops_zoom_chat_monitor_enabled",
        "drawing_board_digest_enabled",
        "prospective_enabled",
    ):
        if key in {"ops_weekly_yaron_report_enabled", "prospective_enabled"}:
            assert config.defaults[key] is True
        else:
            assert config.defaults[key] is False
    assert config.defaults["ops_singapore_ftp_enabled"] is True
    assert config.defaults["ops_singapore_ftp_include_non_submissions"] is True
    assert config.defaults["ops_singapore_ftp_executor"] == "/opt/nova/bin/run-singapore-background"
    assert config.defaults["ops_singapore_ftp_result_path"].startswith(
        "/var/lib/nova/broker/singapore-shared/"
    )
    assert config.defaults["ops_weekly_yaron_report_interval_seconds"] == 900
    assert config.defaults["ops_weekly_yaron_report_weekday"] == "friday"
    assert config.defaults["ops_weekly_yaron_report_local_time"] == "08:00"
    assert config.defaults["ops_weekly_yaron_report_timezone"] == "America/New_York"
    assert config.defaults["ops_weekly_yaron_report_recipient_hint"] == "Yaron"
    assert "ops_weekly_yaron_report_recipient_email" not in config.defaults
    assert config.defaults["ops_weekly_yaron_report_queue_hint"] == (
        "All queues / fixed Total Calls report roster"
    )
    assert config.defaults["ops_weekly_yaron_report_output_path"] == (
        "/srv/nova/workspaces/alex/command-center-output/weekly-report/"
        "ops_weekly_yaron_report.json"
    )
    assert config.defaults["ops_weekly_yaron_report_idempotency_seconds"] == 604800
    assert config.defaults["ops_weekly_support_quality_enabled"] is True
    assert config.defaults["ops_weekly_support_quality_weekday"] == "Wednesday"
    assert config.defaults["ops_weekly_support_quality_local_time"] == "09:00"
    assert config.defaults["ops_weekly_support_quality_timezone"] == "America/New_York"
    assert config.defaults["ops_weekly_support_quality_output_path"] == (
        "/var/lib/nova/state/command_center/ops_weekly_support_quality.json"
    )
    assert config.defaults["ops_weekly_support_quality_prior_weeks"] == 8
    assert config.defaults["ops_weekly_support_quality_idempotency_seconds"] == 604800


def test_cloud_runtime_explicitly_includes_singapore_non_submission_categories() -> None:
    overlay = yaml.safe_load(
        (ROOT / "config" / "agents.gcp-runtime.yaml").read_text(encoding="utf-8")
    )

    assert overlay["defaults"]["ops_singapore_ftp_include_non_submissions"] is True


def test_codex_preflight_treats_only_thor_login_failure_as_degraded(monkeypatch) -> None:
    def fake_run(command, **_kwargs):
        logged_in = command[2] != "nova-claude"
        return SimpleNamespace(
            returncode=0 if logged_in else 1,
            stdout="Logged in using ChatGPT" if logged_in else "",
            stderr="",
        )

    monkeypatch.setattr(agent_runtime_preflight.subprocess, "run", fake_run)

    result = agent_runtime_preflight._probe_codex()

    assert result["ok"] is True
    assert result["degraded"] is True
    assert result["missingRequiredIdentities"] == []
    assert result["optionalFailures"] == ["thor"]
    assert result["identities"]["thor"] is False


def test_codex_preflight_blocks_when_required_identity_login_fails(monkeypatch) -> None:
    def fake_run(command, **_kwargs):
        logged_in = command[2] != "nova-taylor"
        return SimpleNamespace(
            returncode=0 if logged_in else 1,
            stdout="Logged in using ChatGPT" if logged_in else "",
            stderr="",
        )

    monkeypatch.setattr(agent_runtime_preflight.subprocess, "run", fake_run)

    result = agent_runtime_preflight._probe_codex()

    assert result["ok"] is False
    assert result["degraded"] is False
    assert result["missingRequiredIdentities"] == ["taylor"]
    assert result["optionalFailures"] == []
    assert result["identities"]["taylor"] is False


def test_thor_connector_failures_block_production_readiness() -> None:
    results = {
        "core": {"ok": True},
        "rescue_quality": {"ok": False},
        "zoom_quality": {"ok": False},
    }

    readiness = agent_runtime_preflight._required_optional_readiness(
        results,
        optional_names=agent_runtime_preflight.OPTIONAL_SCOPED_MCP_LANES,
    )

    assert readiness["ok"] is False
    assert readiness["degraded"] is False
    assert readiness["required"] == ["core", "rescue_quality", "zoom_quality"]
    assert readiness["optional"] == []
    assert readiness["optionalFailures"] == []
    assert agent_runtime_preflight.OPTIONAL_LIVE_CONNECTORS == ()


def test_provider_and_lane_failures_degrade_without_taking_down_command_center() -> None:
    readiness = agent_runtime_preflight._runtime_readiness(
        {
            "rory_isolation": {"ok": True},
            "codex_runtime_approval_policy": {"ok": True},
            "agent_file_delivery": {"ok": True},
            "gmail": {"ok": False},
            "codex_cli": {"ok": False},
            "scoped_mcp_brokers": {"ok": False},
        }
    )

    assert readiness["ok"] is True
    assert readiness["fullyReady"] is False
    assert readiness["degraded"] is True
    assert readiness["coreFailures"] == []
    assert readiness["degradedChecks"] == [
        "gmail",
        "codex_cli",
        "scoped_mcp_brokers",
    ]


def test_core_isolation_or_runtime_policy_failure_still_blocks_startup() -> None:
    readiness = agent_runtime_preflight._runtime_readiness(
        {
            "rory_isolation": {"ok": False},
            "codex_runtime_approval_policy": {"ok": True},
            "agent_file_delivery": {"ok": True},
            "gmail": {"ok": True},
        }
    )

    assert readiness["ok"] is False
    assert readiness["fullyReady"] is False
    assert readiness["degraded"] is True
    assert readiness["coreFailures"] == ["rory_isolation"]


def test_singapore_preflight_does_not_require_zoom_send_credentials() -> None:
    launcher = (
        ROOT
        / "deploy"
        / "gcp"
        / "agent-runtime"
        / "run-singapore-background.sh"
    ).read_text(encoding="utf-8")

    preflight_branch = launcher.index('if [ "$preflight" -eq 1 ]; then')
    zoom_requirements = launcher.index("zoom-s2s-account-id")
    assert preflight_branch < zoom_requirements


def test_required_connector_failure_still_blocks_core_runtime() -> None:
    readiness = agent_runtime_preflight._required_optional_readiness(
        {
            "core": {"ok": False},
            "thor_zoom": {"ok": True},
        },
        optional_names=("thor_zoom",),
    )

    assert readiness["ok"] is False
    assert readiness["degraded"] is False
    assert readiness["required"] == ["core"]
    assert readiness["optionalFailures"] == []


def test_weekly_zoom_metrics_reuse_s2s_credentials_and_fixed_agent_roster() -> None:
    runtime = ROOT / "deploy" / "gcp" / "agent-runtime"
    provision = (runtime / "provision-private-runtime.ps1").read_text(encoding="utf-8")
    bootstrap = (runtime / "bootstrap-private-runtime.sh").read_text(encoding="utf-8")
    launcher = (runtime / "run-zoom-broker.sh").read_text(encoding="utf-8")
    preflight = (runtime / "preflight.py").read_text(encoding="utf-8")
    roster = json.loads(
        (ROOT / "config" / "zoom-weekly-support-agents.json").read_text(encoding="utf-8")
    )

    for secret in (
        "zoom-singapore-julio-contact",
        "zoom-internal-wiko-contact",
        "zoom-s2s-account-id",
        "zoom-s2s-client-id",
        "zoom-s2s-client-secret",
    ):
        assert f"/run/nova-secrets/{secret}" in provision
        assert secret in launcher
        assert f"/run/nova-secrets/{secret}" in preflight
    assert 'export ZOOM_ACCOUNT_ID="$(cat "$secret_root/zoom-s2s-account-id")"' in launcher
    assert 'export ZOOM_CLIENT_ID="$(cat "$secret_root/zoom-s2s-client-id")"' in launcher
    assert 'export ZOOM_CLIENT_SECRET="$(cat "$secret_root/zoom-s2s-client-secret")"' in launcher
    assert (
        'export ZOOM_SINGAPORE_JULIO_CONTACT='
        '"$(cat "$secret_root/zoom-singapore-julio-contact")"'
    ) in launcher
    assert (
        'export ZOOM_INTERNAL_REQUEST_WIKO_CONTACT='
        '"$(cat "$secret_root/zoom-internal-wiko-contact")"'
    ) in launcher
    assert "required Zoom user OAuth secret is unavailable" in launcher
    assert 'for name in \\\n  zoom-oauth-client-id' in launcher
    assert (
        "NOVA_INTERNAL_COMMUNICATION_JOURNAL_PATH="
        "/var/lib/nova/broker/internal-comms/verified-requests.jsonl"
    ) in launcher
    assert '"salesforce_ticket_internal_request_post"' in preflight
    assert "ZOOM_TEAM_CHAT_JOURNAL_PATH" in (
        ROOT
        / "tools"
        / "scoped-operations-mcp"
        / "src"
        / "scoped_operations_mcp"
        / "zoom_client.py"
    ).read_text(encoding="utf-8")
    assert (
        "export ZOOM_WEEKLY_SUPPORT_AGENT_ROSTER_FILE="
        "/opt/nova/current/config/zoom-weekly-support-agents.json"
    ) in launcher
    assert "zoom-support-queue-id" not in launcher
    assert "zoom-support-queue-id" not in provision
    assert "zoom-support-queue-id" not in preflight
    assert roster["reportId"] == "ASNsvKgkR0man2E-rUZqMA"
    assert [agent["name"] for agent in roster["agents"]] == [
        "Mordi Tech Support",
        "Darius Parlor - Nova Point of Sale",
        "Eddie Talal",
        "Oscar Ocampo",
        "Eduardo Brambila",
        "Oscar Umana",
    ]
    assert "install -d -m 2770 -o nova-alex -g nova-alex" in bootstrap
    assert "/srv/nova/workspaces/alex/command-center-output/weekly-report" in bootstrap


def test_zoom_broker_accepts_group_writable_rotated_oauth_state() -> None:
    launcher = (
        ROOT / "deploy" / "gcp" / "agent-runtime" / "run-zoom-broker.sh"
    ).read_text(encoding="utf-8")

    existing_state_branch = launcher.split('if [ ! -s "$state_path" ]; then', 1)[1].split(
        "fi", 1
    )[1]
    assert 'chgrp nova-zoom-credentials "$state_path"' not in existing_state_branch
    assert 'chmod 0660 "$state_path"' not in existing_state_branch
    assert 'test -r "$state_path" && test -w "$state_path"' in existing_state_branch


def test_cloud_build_publishes_tested_immutable_runtime_without_promoting() -> None:
    config_path = ROOT / "deploy" / "gcp" / "cloudbuild-agent-runtime.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    steps = {step["id"]: step for step in config["steps"]}

    assert set(steps) == {
        "bridge-tests",
        "scoped-provider-tests",
        "package-immutable-runtime",
        "publish-private-runtime",
    }
    assert steps["package-immutable-runtime"]["waitFor"] == [
        "bridge-tests",
        "scoped-provider-tests",
    ]
    bridge_install_script = steps["bridge-tests"]["args"][-1]
    provider_install_script = steps["scoped-provider-tests"]["args"][-1]
    assert 'install_root=/tmp/codex-slack-bridge-install' in bridge_install_script
    assert 'scoped_root=/tmp/scoped-operations-mcp-install' in bridge_install_script
    assert 'cp tools/scoped-operations-mcp/pyproject.toml "$scoped_root/"' in bridge_install_script
    assert '"$install_root"' in bridge_install_script
    assert '"$scoped_root"' in bridge_install_script
    assert (
        "PYTHONPATH=/workspace/src:/workspace/tools/scoped-operations-mcp/src"
        in bridge_install_script
    )
    assert 'bridge_root=/tmp/codex-slack-bridge-install' in provider_install_script
    assert '"$bridge_root"' in provider_install_script
    assert '"$scoped_root[test]"' in provider_install_script
    assert '"$rescue_root[test]"' in provider_install_script
    assert "python -m pip install --disable-pip-version-check ." not in bridge_install_script
    assert "python -m pip install --disable-pip-version-check ." not in provider_install_script
    publish_script = steps["publish-private-runtime"]["args"][-1]
    assert "$COMMIT_SHA.tar.gz" in publish_script
    assert "gcloud storage cp" in publish_script

    rendered = config_path.read_text(encoding="utf-8")
    assert "gcloud run" not in rendered
    assert "compute instances reset" not in rendered
    assert "nova-slack-bridge.service" not in rendered


def test_provisioner_accepts_only_github_main_cloud_build_artifact() -> None:
    provision = (
        ROOT / "deploy" / "gcp" / "agent-runtime" / "provision-private-runtime.ps1"
    ).read_text(encoding="utf-8")

    assert "ls-remote --exit-code origin refs/heads/main" in provision
    assert "$remoteMainExitCode = $LASTEXITCODE" in provision
    assert "$Commit -ne $GitHubMainCommit" in provision
    assert "SourceArtifactReady" in provision
    assert "the tested Cloud Build artifact does not exist" in provision
    assert "git -C $RepoRoot archive" not in provision
    assert "storage cp $archive" not in provision


def test_device_auth_mode_is_explicit_persistent_and_does_not_weaken_cutover() -> None:
    runtime = ROOT / "deploy" / "gcp" / "agent-runtime"
    provision = (runtime / "provision-private-runtime.ps1").read_text(encoding="utf-8")
    bootstrap = (runtime / "bootstrap-private-runtime.sh").read_text(encoding="utf-8")
    codex_auth = (runtime / "bootstrap-codex-auth.sh").read_text(encoding="utf-8")
    device_auth = (runtime / "begin-codex-device-auth.sh").read_text(encoding="utf-8")
    preflight = (runtime / "preflight.py").read_text(encoding="utf-8")

    assert 'ValidateSet("access-token", "device")' in provision
    assert '$CodexAuthMode -eq "access-token"' in provision
    assert "nova-codex-auth-mode=$CodexAuthMode" in provision
    assert "interactiveCodexAuthRequired" in provision
    assert '"--labels=application=nova-agent-runtime,environment=staging,data=state"' in provision
    assert '"--labels=application=nova-agent-runtime,environment=staging"' in provision
    assert '"oslogin.googleapis.com"' in provision
    assert "[Text.UTF8Encoding]::new($false)" in provision
    assert '$interface.PSObject.Properties["accessConfigs"]' in provision
    assert "/var/lib/nova/codex/$identity" in bootstrap
    assert 'mount --bind "$auth_root" "$auth_home"' in bootstrap
    assert 'umask 022' in bootstrap
    assert 'chmod a+rx /usr/local/lib/node_modules /usr/local/lib/node_modules/@openai' in bootstrap
    assert 'chmod -R a+rX /usr/local/lib/node_modules/@openai/codex' in bootstrap
    assert 'chmod -R a+rX /opt/nova/venv' in bootstrap
    assert 'iptables -A NOVA_METADATA -p udp --dport 53 -j RETURN' in bootstrap
    assert 'iptables -A NOVA_METADATA -p tcp --dport 53 -j RETURN' in bootstrap
    assert 'ip6tables -A NOVA_METADATA_V6 -p udp --dport 53 -j RETURN' in bootstrap
    assert 'ip6tables -A NOVA_METADATA_V6 -p tcp --dport 53 -j RETURN' in bootstrap
    assert 'uid-owner "$(id -u nova-cloud-broker)"' not in bootstrap
    assert "mint_cloud_identity_token.py" in bootstrap
    assert "nova-cloud-token.timer" in bootstrap
    assert bootstrap.index('iptables -A NOVA_METADATA -p tcp --dport 53 -j RETURN') < bootstrap.index(
        'iptables -A NOVA_METADATA -j REJECT'
    )
    assert 'systemctl restart nova-metadata-firewall.service' in bootstrap
    assert bootstrap.index('systemctl restart nova-metadata-firewall.service') < bootstrap.index(
        'systemctl restart nova-secrets.service'
    )
    assert 'systemctl restart nova-secrets.service' in bootstrap
    assert bootstrap.index('systemctl restart nova-secrets.service') < bootstrap.index(
        'systemctl start nova-codex-auth.service'
    )
    assert "nova-command-center.service nova-slack-bridge.service" in bootstrap
    assert "codex_device_auth_pending" in codex_auth
    assert "Device-auth mode must not materialize a Codex access token" in codex_auth
    assert "codex login --device-auth" in device_auth
    for identity in ("rory", "taylor", "alex", "jamie"):
        assert f"{identity}) user=nova-{identity}" in device_auth
    assert "thor|claude) user=nova-claude; identity=thor" in device_auth
    assert '("thor", "nova-claude")' in preflight
    assert '"users":5' in codex_auth
    assert 'apps_connections_open(app_token=_secret("slack-app-token"))' in preflight


def test_cloud_build_trigger_uses_dedicated_non_deploying_service_account() -> None:
    setup = (ROOT / "deploy" / "gcp" / "configure-agent-runtime-cloud-build.ps1").read_text(
        encoding="utf-8"
    )

    assert 'ServiceAccountId = "nova-agent-build"' in setup
    assert '"--build-config=$buildConfig"' in setup
    assert "builds triggers create github" in setup
    assert "builds triggers delete" in setup
    assert "legacyTriggerRemoved" in setup
    assert "-Attempts 10" in setup
    assert "roles/storage.objectCreator" in setup
    assert "roles/storage.objectViewer" in setup
    assert "roles/logging.logWriter" in setup
    assert "cloudbuild.builds.create" in setup
    assert "roles/cloudbuild.builds.builder" not in setup
    assert '"--billing-project=$ProjectId"' in setup
    assert "automaticProductionPromotion = $false" in setup
