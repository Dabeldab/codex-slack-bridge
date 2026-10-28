from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from codex_slack_bridge import zoom_chat_monitor as monitor
from codex_slack_bridge import zoom_kb_sync


NOW = datetime(2026, 7, 11, 15, 0, tzinfo=timezone.utc)


def test_collects_read_only_surfaces_and_disables_unconfigured_team_chat(tmp_path: Path):
    calls: list[tuple[str, str, dict[str, str]]] = []

    def getter(token: str, path: str, params: dict[str, str] | None):
        calls.append((token, path, dict(params or {})))
        if path == "/virtual_agent/report/engagements":
            return {
                "engagements": [
                    {"engagement_id": "done", "end_time": "2026-07-11T14:00:00Z"},
                    {"engagement_id": "still-open"},
                ]
            }
        if path == "/virtual_agent/report/transcripts":
            return {
                "transcripts": [
                    {
                        "engagement_id": "done",
                        "messages": [
                            {
                                "sender": "Consumer",
                                "text": "api_key=live-secret " + ("x" * 3_000),
                            }
                        ],
                    }
                ]
            }
        if path == "/contact_center/open_engagements":
            return {
                "engagements": [
                    {"engagement_id": "msg", "channels": [{"channel": "messaging"}]},
                    {"engagement_id": "voice", "channels": [{"channel": "voice"}]},
                ]
            }
        raise AssertionError(f"unexpected path {path}")

    snapshot = monitor.collect_zoom_chat_snapshot(
        "oauth-secret",
        now=NOW,
        environ={},
        getter=getter,
    )

    assert snapshot["read_only"] is True
    assert [row["engagement_id"] for row in snapshot["surfaces"]["zva"]["engagements"]] == ["done"]
    transcript_text = snapshot["surfaces"]["zva"]["transcripts"][0]["messages"][0]["text"]
    assert "live-secret" not in transcript_text
    assert len(transcript_text) <= monitor.MAX_TEXT_CHARS
    assert [
        row["engagement_id"]
        for row in snapshot["surfaces"]["contact_center"]["open_messaging_engagements"]
    ] == ["msg"]
    assert snapshot["surfaces"]["team_chat"]["status"] == "disabled"
    assert all(method_token == "oauth-secret" for method_token, _, _ in calls)
    assert all(path.startswith(("/virtual_agent/report/", "/contact_center/")) for _, path, _ in calls)

    cache = tmp_path / "nested" / "zoom.json"
    monitor.write_snapshot_atomic(cache, snapshot)
    parsed = json.loads(cache.read_text(encoding="utf-8"))
    assert parsed["surfaces"]["zva"]["engagements"][0]["engagement_id"] == "done"
    assert list(cache.parent.glob(f".{cache.name}.*.tmp")) == []


def test_scope_failure_is_isolated_per_surface():
    def getter(_token: str, path: str, _params: dict[str, str] | None):
        if path.startswith("/virtual_agent/"):
            raise RuntimeError("Zoom API failed with HTTP 403: missing scope zva_report:read")
        if path == "/contact_center/open_engagements":
            return {"engagements": [{"id": "active", "channels": ["messaging"]}]}
        raise AssertionError(path)

    snapshot = monitor.collect_zoom_chat_snapshot(
        "token",
        now=NOW,
        environ={},
        getter=getter,
    )

    assert snapshot["surfaces"]["zva"]["status"] == "scope_error"
    assert snapshot["surfaces"]["contact_center"]["status"] == "ok"
    assert len(snapshot["surfaces"]["contact_center"]["open_messaging_engagements"]) == 1
    assert snapshot["surfaces"]["team_chat"]["status"] == "disabled"


def test_team_chat_reads_only_explicit_user_and_session_allowlists():
    paths: list[str] = []

    def getter(_token: str, path: str, _params: dict[str, str] | None):
        paths.append(path)
        if path == "/virtual_agent/report/engagements":
            return {"engagements": []}
        if path == "/virtual_agent/report/transcripts":
            return {"transcripts": []}
        if path == "/contact_center/open_engagements":
            return {"engagements": []}
        if path == "/chat/users/alex%2Bsupport%40example.com/sessions":
            return {"sessions": [{"type": "1:1", "peer_contact_email": "member@example.com"}]}
        if path == "/report/chat/sessions/session%2Fone":
            return {
                "messages": [
                    {
                        "message": "hello",
                        "download_url": "https://zoom.us/download/file?jwt=do-not-cache",
                    }
                ],
                "deleted_messages": [],
            }
        raise AssertionError(f"unexpected path {path}")

    env = {
        monitor.TEAM_CHAT_MEMBER_IDS_ENV: "alex+support@example.com",
        monitor.TEAM_CHAT_TARGETS_ENV: "session/one",
    }
    snapshot = monitor.collect_zoom_chat_snapshot(
        "token",
        now=NOW,
        environ=env,
        getter=getter,
    )

    team = snapshot["surfaces"]["team_chat"]
    assert team["status"] == "ok"
    # Agent operational context retains explicit contact identifiers for lookup.
    # AgentChat/direct_codex 2026-07-14T15:56:53-04:00.
    assert [row["user_id"] for row in team["users"]] == ["alex+support@example.com"]
    assert [row["session_id"] for row in team["sessions"]] == ["session/one"]
    assert team["sessions"][0]["messages"][0]["download_url"] == "https://zoom.us/download/file"
    assert "/report/chat/sessions" not in paths  # No account-wide discovery call.
    assert all(not path.endswith("/messages") for path in paths)  # No send endpoint.


def test_paginates_zva_without_leaking_page_tokens_to_snapshot():
    calls = 0

    def getter(_token: str, path: str, params: dict[str, str] | None):
        nonlocal calls
        if path == "/virtual_agent/report/engagements":
            calls += 1
            if calls == 1:
                return {
                    "engagements": [{"engagement_id": "a", "end_time": "2026-07-11T10:00:00Z"}],
                    "next_page_token": "private-page-token",
                }
            assert params and params["next_page_token"] == "private-page-token"
            return {"engagements": [{"engagement_id": "b", "end_time": "2026-07-11T11:00:00Z"}]}
        if path == "/virtual_agent/report/transcripts":
            return {"transcripts": []}
        if path == "/contact_center/open_engagements":
            return {"engagements": []}
        raise AssertionError(path)

    snapshot = monitor.collect_zoom_chat_snapshot("token", now=NOW, environ={}, getter=getter)

    assert [row["engagement_id"] for row in snapshot["surfaces"]["zva"]["engagements"]] == ["a", "b"]
    assert "private-page-token" not in json.dumps(snapshot)


def test_summary_never_contains_messages_errors_or_member_identifiers(tmp_path: Path):
    snapshot = {
        "collected_at": "2026-07-11T15:00:00Z",
        "surfaces": {
            "zva": {
                "status": "partial",
                "engagements": [{"consumer": "private-person"}],
                "transcripts": [{"messages": [{"text": "private transcript"}]}],
                "errors": [{"error": "Bearer private-token"}],
            },
            "contact_center": {
                "status": "ok",
                "open_messaging_engagements": [{"consumer": "private-person"}],
            },
            "team_chat": {
                "status": "ok",
                "users": [{"user_id": "member@example.com"}],
                "sessions": [{"session_id": "private-session"}],
            },
        },
    }

    summary = monitor.snapshot_summary(snapshot, tmp_path / "cache.json")
    rendered = json.dumps(summary)

    assert summary["surfaces"]["zva"]["transcripts"] == 1
    assert summary["surfaces"]["team_chat"]["allowlisted_users"] == 1
    for private_value in (
        "private transcript",
        "private-token",
        "member@example.com",
        "private-session",
        "private-person",
    ):
        assert private_value not in rendered


def test_sanitize_payload_redacts_credential_fields_and_signed_urls():
    result = monitor.sanitize_payload(
        {
            "access_token": "do-not-store",
            "authorization": "Bearer do-not-store-either",
            "launch_url": "https://zoom.us/transcript?id=secret",
            "text": "client_secret=very-secret",
        }
    )

    rendered = json.dumps(result)
    assert "do-not-store" not in rendered
    assert "very-secret" not in rendered
    assert result["launch_url"] == "https://zoom.us/transcript"


def test_output_is_cli_alias_for_command_center_cache(monkeypatch):
    monkeypatch.setattr("sys.argv", ["zoom-chat-monitor", "--output", "custom.json"])
    args = monitor.parse_args()

    assert args.cache == "custom.json"
    assert args.since_hours is None
    assert monitor.DEFAULT_CACHE_PATH == Path("data/command_center/zoom_chat_monitor.json")


def test_zoom_refresh_token_rotation_persists_to_private_state(tmp_path, monkeypatch):
    state = tmp_path / "oauth.env"
    monkeypatch.setenv("ZOOM_OAUTH_STATE_PATH", str(state))
    monkeypatch.setenv("ZOOM_OAUTH_REFRESH_TOKEN", "initial-refresh")
    monkeypatch.setattr(
        zoom_kb_sync,
        "zoom_oauth_client_credentials",
        lambda: ("client", "secret"),
    )
    monkeypatch.setattr(
        zoom_kb_sync,
        "zoom_token_request",
        lambda *_args, **_kwargs: {"access_token": "access", "refresh_token": "rotated-refresh"},
    )

    assert zoom_kb_sync.get_zoom_token() == "access"
    assert "ZOOM_OAUTH_REFRESH_TOKEN=rotated-refresh" in state.read_text(encoding="utf-8")
    assert state.with_suffix(".env.lock").exists()


def test_zoom_refresh_payload_uses_shared_state_and_preserves_scopes(tmp_path, monkeypatch):
    state = tmp_path / "oauth.env"
    state.write_text("ZOOM_OAUTH_REFRESH_TOKEN=shared-refresh\n", encoding="utf-8")
    monkeypatch.setenv("ZOOM_OAUTH_STATE_PATH", str(state))
    monkeypatch.setenv("ZOOM_OAUTH_SHARED_STATE", "true")
    monkeypatch.setattr(
        zoom_kb_sync,
        "zoom_oauth_client_credentials",
        lambda: ("client", "secret"),
    )
    monkeypatch.setattr(
        zoom_kb_sync,
        "zoom_token_request",
        lambda *_args, **_kwargs: {
            "access_token": "access",
            "refresh_token": "next-shared-refresh",
            "scope": "team_chat:write:user_message team_chat:read:list_user_messages",
        },
    )

    payload = zoom_kb_sync.get_zoom_oauth_payload()

    assert payload["access_token"] == "access"
    assert "team_chat:write:user_message" in payload["scope"]
    assert "ZOOM_OAUTH_REFRESH_TOKEN=next-shared-refresh" in state.read_text(encoding="utf-8")


def test_zoom_refresh_recovers_from_stale_shared_state_with_new_pinned_token(
    tmp_path,
    monkeypatch,
):
    state = tmp_path / "oauth.env"
    state.write_text("ZOOM_OAUTH_REFRESH_TOKEN=stale-refresh\n", encoding="utf-8")
    monkeypatch.setenv("ZOOM_OAUTH_STATE_PATH", str(state))
    monkeypatch.setenv("ZOOM_OAUTH_SHARED_STATE", "true")
    monkeypatch.setenv("ZOOM_OAUTH_REFRESH_TOKEN", "new-pinned-refresh")
    monkeypatch.setattr(
        zoom_kb_sync,
        "zoom_oauth_client_credentials",
        lambda: ("client", "secret"),
    )
    attempted_tokens = []

    def token_request(form, **_kwargs):
        attempted_tokens.append(form["refresh_token"])
        if form["refresh_token"] == "stale-refresh":
            raise RuntimeError("Zoom OAuth token request failed with HTTP 400")
        return {
            "access_token": "access",
            "refresh_token": "rotated-from-new-pin",
        }

    monkeypatch.setattr(zoom_kb_sync, "zoom_token_request", token_request)

    payload = zoom_kb_sync.get_zoom_oauth_payload()

    assert payload["access_token"] == "access"
    assert attempted_tokens == ["stale-refresh", "new-pinned-refresh"]
    assert (
        "ZOOM_OAUTH_REFRESH_TOKEN=rotated-from-new-pin"
        in state.read_text(encoding="utf-8")
    )


def test_zoom_refresh_does_not_fallback_for_non_invalid_refresh_error(
    tmp_path,
    monkeypatch,
):
    state = tmp_path / "oauth.env"
    state.write_text("ZOOM_OAUTH_REFRESH_TOKEN=current-refresh\n", encoding="utf-8")
    monkeypatch.setenv("ZOOM_OAUTH_STATE_PATH", str(state))
    monkeypatch.setenv("ZOOM_OAUTH_REFRESH_TOKEN", "different-pinned-refresh")
    monkeypatch.setattr(
        zoom_kb_sync,
        "zoom_oauth_client_credentials",
        lambda: ("client", "secret"),
    )
    attempted_tokens = []

    def token_request(form, **_kwargs):
        attempted_tokens.append(form["refresh_token"])
        raise RuntimeError("Zoom OAuth token request failed with HTTP 503")

    monkeypatch.setattr(zoom_kb_sync, "zoom_token_request", token_request)

    with pytest.raises(
        RuntimeError,
        match="Zoom OAuth token request failed with HTTP 503",
    ):
        zoom_kb_sync.get_zoom_oauth_payload()

    assert attempted_tokens == ["current-refresh"]
    assert (
        "ZOOM_OAUTH_REFRESH_TOKEN=current-refresh"
        in state.read_text(encoding="utf-8")
    )


def test_shared_zoom_lock_accepts_group_writable_non_owner_file(tmp_path, monkeypatch):
    state = tmp_path / "oauth.env"
    lock_path = state.with_suffix(".env.lock")
    lock_path.write_text("", encoding="utf-8")
    monkeypatch.setenv("ZOOM_OAUTH_SHARED_STATE", "true")
    real_chmod = zoom_kb_sync.os.chmod

    def reject_non_owner_chmod(path, mode):
        if Path(path) == lock_path:
            raise PermissionError("not owner")
        return real_chmod(path, mode)

    monkeypatch.setattr(zoom_kb_sync.os, "chmod", reject_non_owner_chmod)

    with zoom_kb_sync._zoom_oauth_refresh_lock(state):
        assert lock_path.exists()
