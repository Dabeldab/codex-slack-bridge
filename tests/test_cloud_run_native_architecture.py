from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_native_dockerfile_uses_one_cloud_run_entrypoint_and_codex_cli() -> None:
    dockerfile = (ROOT / "deploy/gcp/Dockerfile.cloud-run-native").read_text(encoding="utf-8")
    assert 'CMD ["python", "-m", "codex_slack_bridge.cloud_run_entrypoint"]' in dockerfile
    assert "@openai/codex@0.144.4" in dockerfile
    assert "cloud-run-native" not in dockerfile.lower().replace("cloud-run-native", "")


def test_native_entrypoint_runs_command_center_and_slack_in_one_process() -> None:
    entrypoint = (ROOT / "src/codex_slack_bridge/cloud_run_entrypoint.py").read_text(encoding="utf-8")
    assert "command_center_server.main()" in entrypoint
    assert "slack_app.main()" in entrypoint
    assert "10.42.0.2" not in entrypoint
    assert "COMMAND_CENTER_UPSTREAM_URL" not in entrypoint


def test_native_config_is_not_a_private_vm_gateway_contract() -> None:
    config = (ROOT / "config/agents.cloud-native.yaml").read_text(encoding="utf-8")
    assert "extends: agents.gcp-runtime.yaml" in config
    assert "runtime_mode: primary" in config
    assert "state_db: \"/tmp/nova-cloud-run/bridge.sqlite3\"" in config
    assert "codex_command_prefix: []" in config
    assert "10.42.0.2" not in config
    assert "nova-agent-runtime" not in config
    assert "credential_vault_tool: \"\"" in config


def test_native_deploy_uses_cloud_sql_and_has_no_private_gateway_parameters() -> None:
    script = (ROOT / "deploy/gcp/deploy-cloud-run-native.ps1").read_text(encoding="utf-8")
    assert "--add-cloudsql-instances=$CloudSqlInstance" in script
    assert "NOVA_DATABASE_BACKEND=cloudsql" in script
    assert "NOVA_DB_SOCKET=/cloudsql/$CloudSqlInstance" in script
    assert "--no-cpu-throttling" in script
    assert '"--min=1"' in script
    assert '"--max=1"' in script
    assert "-EnablePrivateGateway" not in script
    assert "10.42.0.2" not in script


def test_cloud_sql_state_adapter_translates_sqlite_specific_contract() -> None:
    from codex_slack_bridge.cloud_sql_state import _translate_sql

    assert "BIGSERIAL PRIMARY KEY" in _translate_sql(
        "CREATE TABLE IF NOT EXISTS jobs (id INTEGER PRIMARY KEY AUTOINCREMENT)"
    )
    assert _translate_sql("BEGIN IMMEDIATE") == "BEGIN"
    assert "INSERT INTO desktop_slack_mirrors" in _translate_sql(
        "INSERT OR IGNORE INTO desktop_slack_mirrors(event_id) VALUES (?)"
    )
    assert "%s" in _translate_sql("SELECT * FROM jobs WHERE id = ?")


def test_chatgpt_cloud_build_pushes_and_deploys_new_revision() -> None:
    config = (ROOT / "deploy/gcp/cloudbuild-cloud-run-chatgpt.yaml").read_text(encoding="utf-8")
    assert "push-chatgpt-relay-image" in config
    assert "deploy-chatgpt-relay-cloud-run" in config
    assert "route-chatgpt-relay-traffic" in config
    assert "${_DEPLOY_SERVICE}" in config
    assert "--image=${_IMAGE}" in config or '--image="${_IMAGE}"' in config
    assert "--to-latest" in config
    assert "_DEPLOY_SERVICE: nova-command-center-shadow" in config
    assert "_DEPLOY_REGION: us-central1" in config


def test_chatgpt_cloud_build_trigger_is_pinned_to_main() -> None:
    script = (ROOT / "deploy/gcp/configure-chatgpt-cloud-run-trigger.ps1").read_text(
        encoding="utf-8"
    )
    assert '[string]$BranchPattern = "^main$"' in script
    assert '[string]$BuildConfig = "deploy/gcp/cloudbuild-cloud-run-chatgpt.yaml"' in script
    assert "builds triggers update github" in script
    assert "--branch-pattern=$BranchPattern" in script
    assert "--build-config=$BuildConfig" in script
    assert "builds triggers describe" in script
    assert "--branch=main" in script


def test_chatgpt_cloud_build_reasserts_relay_runtime_configuration() -> None:
    config = (ROOT / "deploy/gcp/cloudbuild-cloud-run-chatgpt.yaml").read_text(encoding="utf-8")
    assert "REASONING_RELAY_ENABLED=1" in config
    assert "REASONING_RELAY_BROKER_COMMAND=/usr/local/bin/python -m codex_slack_bridge.reasoning_relay_broker" in config
    assert "GITHUB_APP_ID_PATH=/run/nova-secrets/github-app-id/value" in config
    assert "nova-agents-github-app-id:latest" in config
    assert "COMMAND_CENTER_TRUSTED_BEARER_PATH=/run/nova-relay-secrets/command-center-upstream-token" in config
    assert "/run/nova-relay-secrets/command-center-upstream-token=nova-command-center-upstream-token:4" in config
    assert "verify-chatgpt-relay-cloud-run" in config
    assert "Cloud Run relay configuration verified" in config


def test_cloud_run_entrypoint_fails_closed_on_broken_reasoning_relay() -> None:
    source = (ROOT / "src/codex_slack_bridge/cloud_run_entrypoint.py").read_text(encoding="utf-8")
    assert "def _validate_reasoning_relay_startup()" in source
    assert "BrokeredGitHubReasoningRelayTransport.from_environment()" in source
    assert "transport.health()" in source
    assert "_validate_reasoning_relay_startup()" in source



def test_nova_control_cloud_build_stays_private_with_no_oauth_issuer() -> None:
    config = (ROOT / "deploy/gcp/cloudbuild-cloud-run-chatgpt.yaml").read_text(
        encoding="utf-8"
    )
    # Nova Control has no real external caller today (ChatGPT Work uses the
    # GitHub PR relay, not this MCP endpoint) and no OAuth issuer exists for
    # it, so it must stay on Cloud Run's native IAM auth and never go public.
    assert "NOVA_CONTROL_MCP_AUTH_MODE=${_CONTROL_AUTH_MODE}" in config
    assert "_CONTROL_AUTH_MODE: cloudrun_iam" in config
    assert "verify-nova-control-mcp-private" in config
    assert "Nova Control verified private (cloudrun_iam, no public IAM binding)" in config
    assert "if \"allUsers\" in members:" in config

    # The abandoned Auth0-shaped OAuth cutover must not be active. Cleanup
    # directives are intentionally allowed because Cloud Run revisions retain old
    # env/secrets unless a later deploy explicitly removes them.
    assert "_CONTROL_AUTH_MODE: oauth" not in config
    assert "nova-control-auth-issuer-url" not in config

    deploy_step = config.split("- id: deploy-nova-control-mcp", 1)[1].split(
        "- id: verify-nova-control-mcp-private", 1
    )[0]
    update_env = next(line for line in deploy_step.splitlines() if "--update-env-vars=" in line)
    update_secrets = next(line for line in deploy_step.splitlines() if "--update-secrets=" in line)
    for legacy_name in (
        "NOVA_CONTROL_AUTH_ISSUER_URL",
        "NOVA_CONTROL_MCP_RESOURCE_URL",
        "NOVA_CONTROL_AUTH_AUDIENCE",
        "NOVA_CONTROL_AUTH_REQUIRED_SCOPES",
    ):
        assert legacy_name not in update_env
        assert legacy_name not in update_secrets

    assert (
        "--remove-env-vars=NOVA_CONTROL_MCP_RESOURCE_URL,"
        "NOVA_CONTROL_AUTH_AUDIENCE,NOVA_CONTROL_AUTH_REQUIRED_SCOPES"
    ) in deploy_step
    assert "--remove-secrets=NOVA_CONTROL_AUTH_ISSUER_URL" in deploy_step
    assert "nova:control" not in config
    assert "services add-iam-policy-binding" not in config
    assert "services remove-iam-policy-binding" not in config
