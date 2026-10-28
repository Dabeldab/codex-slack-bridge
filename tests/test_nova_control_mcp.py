from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_nova_control_mcp_contract_is_bounded_and_streamable_http():
    source = (ROOT / "src/codex_slack_bridge/nova_control_mcp.py").read_text(
        encoding="utf-8"
    )

    assert "verify_relay_authorization_claim" in source
    assert "def nova_relay_get_request(" in source
    assert "def nova_relay_list_tools(" in source
    assert "def nova_relay_execute_read_tool(" in source
    assert "def nova_relay_execute_write_tool(" in source
    assert "signed relay request does not authorize live writes" in source
    assert "def nova_relay_submit_final_response(" in source
    assert "def nova_full_sync(" in source
    assert 'transport="streamable-http"' in source
    assert '"streamable_http_path": "/mcp"' in source


def test_nova_control_full_sync_defaults_to_ticket_refresh_only():
    source = (ROOT / "src/codex_slack_bridge/nova_control_mcp.py").read_text(
        encoding="utf-8"
    )

    assert 'NOVA_CONTROL_FULL_SYNC_COMPONENTS") or "tickets"' in source
    assert '"tickets": "/ops/tickets/refresh"' in source


def test_cloud_run_image_contains_agent_profiles_and_lane_workspaces():
    source = (ROOT / "deploy/gcp/Dockerfile.cloud-run-chatgpt").read_text(
        encoding="utf-8"
    )

    assert "COPY profiles ./profiles" in source
    for lane in ("taylor", "alex", "jamie"):
        assert f"/tmp/nova-cloud-run/workspaces/{lane}" in source
    assert "test -x /usr/local/bin/codex" in source
    assert 'codex_module_root="$(npm root -g)"' in source
    assert 'chmod -R a+rX "$codex_module_root/@openai/codex"' in source



def test_nova_control_oauth_mode_uses_oidc_jwt_verification():
    source = (ROOT / "src/codex_slack_bridge/nova_control_mcp.py").read_text(
        encoding="utf-8"
    )

    assert "class OidcJwtTokenVerifier(TokenVerifier)" in source
    assert 'algorithms=["RS256"]' in source
    assert "audience=self.audience" in source
    assert "issuer=self.issuer" in source
    assert '"nova:control"' in source
    assert "AuthSettings(" in source
    assert "resource_server_url=AnyHttpUrl(resource)" in source
    assert 'mode == "oauth"' in source


def test_nova_control_defaults_to_private_cloud_run_iam_mode():
    source = (ROOT / "src/codex_slack_bridge/nova_control_mcp.py").read_text(
        encoding="utf-8"
    )

    assert 'NOVA_CONTROL_MCP_AUTH_MODE") or "cloudrun_iam"' in source
    assert 'elif mode != "cloudrun_iam"' in source
