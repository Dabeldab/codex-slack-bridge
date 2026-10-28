from __future__ import annotations

# AgentChat/direct_codex 2026-07-24T13:45:00Z: verify the weekly Yaron
# operation remains exact-recipient, lane-scoped, idempotent, and read back.

import base64
import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from pathlib import Path
from threading import Barrier, Lock

import pytest

import scoped_operations_mcp.zoom_client as zoom_client_module
from scoped_operations_mcp.zoom_client import ScopedZoomClient, _ZoomTranscriptRedirectBlocker
from scoped_operations_mcp.zoom_server import build_mcp


def _s2s_token(user_id: str = "sender-001") -> str:
    def encode(value: dict[str, object]) -> str:
        return base64.urlsafe_b64encode(
            json.dumps(value, separators=(",", ":")).encode("utf-8")
        ).decode("ascii").rstrip("=")

    return f"{encode({'alg': 'none'})}.{encode({'uid': user_id})}.signature"


def _configure_team_chat_sender(monkeypatch, user_id: str = "sender-001") -> str:
    monkeypatch.setenv("ZOOM_TEAM_CHAT_SENDER_USER_ID", user_id)
    return _s2s_token(user_id)


def _sender_user(user_id: str = "sender-001") -> dict[str, str]:
    return {
        "id": user_id,
        "email": "darius@novapointofsale.com",
        "first_name": "Darius",
        "last_name": "Parlor",
        "status": "active",
    }


def _configure_weekly_roster(tmp_path: Path, monkeypatch) -> Path:
    path = tmp_path / "zoom-weekly-support-agents.json"
    path.write_text(
        json.dumps(
            {
                "reportId": "report-001",
                "reportName": "Total Calls",
                "agents": [
                    {"id": "agent-001", "name": "Alex"},
                    {"id": "agent-002", "name": "Jamie"},
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("ZOOM_WEEKLY_SUPPORT_AGENT_ROSTER_FILE", str(path))
    return path


def test_zoom_mcp_exposes_only_lane_scoped_guarded_operations() -> None:
    client = ScopedZoomClient(token_provider=lambda: "test", getter=lambda *_args: {"id": "me"})
    shared = {
        "zoom_capabilities",
        "zoom_operator_team_chat_recipient_resolve",
        "zoom_operator_team_chat_send",
        "zoom_team_chat_channels",
        "zoom_team_chat_history",
        "zoom_docs_archives",
        "zoom_docs_archive_content",
        "zoom_ghostbusters_overview_read",
        "zoom_support_queue_metrics",
    }
    mcp = build_mcp("tickets_agent", client)
    names = set(mcp._tool_manager._tools)
    assert names == shared | {
        "zoom_health",
        "zoom_team_chat_recipient_resolve",
        "zoom_team_chat_send",
        "zoom_support_chat_snapshot",
        "zoom_weekly_support_metrics",
        "zoom_weekly_yaron_report_send",
    }
    direct_send_schema = mcp._tool_manager._tools[
        "zoom_team_chat_send"
    ].fn_metadata.arg_model.model_json_schema()
    assert set(direct_send_schema["properties"]) == {
        "exact_recipient",
        "message",
        "authorization_context",
        "idempotency_key",
    }
    assert "sender_lane" not in direct_send_schema["properties"]
    send_schema = mcp._tool_manager._tools["zoom_weekly_yaron_report_send"].fn_metadata.arg_model.model_json_schema()
    assert "ticket_total" in send_schema["properties"]
    assert "nova_classic" not in send_schema["properties"]
    assert "nova_wave" not in send_schema["properties"]
    coding_names = set(build_mcp("coding_agent", client)._tool_manager._tools)
    assert coding_names == shared | {
        "zoom_health",
        "zoom_team_chat_recipient_resolve",
        "zoom_team_chat_send",
        "zoom_support_chat_snapshot",
        "zoom_ghostbusters_overview_update",
    }
    billing_names = set(build_mcp("billing_agent", client)._tool_manager._tools)
    assert billing_names == shared | {
        "zoom_health",
        "zoom_team_chat_recipient_resolve",
        "zoom_team_chat_send",
    }
    quality_names = set(build_mcp("claude_agent", client)._tool_manager._tools)
    assert quality_names == shared | {
        "zoom_health",
        "zoom_ghostbusters_overview_update",
        "zoom_quality_voice_engagements",
        "zoom_quality_agent_performance",
        "zoom_quality_engagement_recordings",
        "zoom_quality_transcript",
    }
    assert not quality_names & {
        "zoom_team_chat_recipient_resolve",
        "zoom_team_chat_send",
        "zoom_support_chat_snapshot",
        "zoom_weekly_support_metrics",
        "zoom_weekly_yaron_report_send",
    }
    direct_names = set(build_mcp("direct_codex", client)._tool_manager._tools)
    assert direct_names == shared | {
        "zoom_health",
        "zoom_team_chat_recipient_resolve",
        "zoom_team_chat_send",
        "zoom_ghostbusters_overview_update",
    }
    with pytest.raises(RuntimeError, match="fixed operational agent lane"):
        build_mcp("unapproved", client)


def test_zoom_health_never_echoes_external_error_text() -> None:
    def fail(*_args):
        raise RuntimeError("Bearer should-never-appear secret=also-never")

    result = ScopedZoomClient(token_provider=lambda: "test", getter=fail).health()
    assert result["ok"] is False
    assert "should-never-appear" not in result["error"]
    assert "also-never" not in result["error"]


def test_zoom_health_verifies_metrics_and_direct_message_recipient_scope(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths: list[str] = []
    _configure_weekly_roster(tmp_path, monkeypatch)
    sender_token = _configure_team_chat_sender(monkeypatch)
    monkeypatch.setenv("ZOOM_SINGAPORE_JULIO_CONTACT", "julio@example.test")
    monkeypatch.setenv("ZOOM_INTERNAL_REQUEST_WIKO_CONTACT", "wiko@example.test")

    def support_reads(_token, path, _params):
        paths.append(path)
        if path == "/users":
            return {
                "users": [
                    _sender_user(),
                    {
                        "id": "u1",
                        "email": "julio@example.test",
                        "first_name": "Julio",
                        "last_name": "Example",
                    },
                    {
                        "id": "u2",
                        "email": "wiko@example.test",
                        "first_name": "Wiko",
                        "last_name": "Example",
                    },
                ]
            }
        if path == "/contact_center/analytics/log/historical/engagement":
            return {"engagement_logs": []}
        raise AssertionError(f"unexpected Zoom health path: {path}")

    result = ScopedZoomClient(
        token_provider=lambda: sender_token,
        getter=support_reads,
    ).health()

    assert result == {
        "ok": True,
        "authenticated": True,
        "surfaceStatus": {
            "contact_center": "ok",
            "team_chat": "guarded_send_ready",
            "zva": "not_authorized",
        },
        "weeklyMetrics": "ok",
        "directTeamChat": "ready",
        "teamChatSender": "ready",
        "internalRequestRecipients": "ready",
    }
    assert "/users" in paths
    assert "/contact_center/queues" not in paths


def test_zoom_team_chat_uses_support_dashboard_calls_s2s_provider(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls: list[tuple[str, str]] = []
    _configure_weekly_roster(tmp_path, monkeypatch)
    sender_token = _configure_team_chat_sender(monkeypatch)
    monkeypatch.setenv("ZOOM_SINGAPORE_JULIO_CONTACT", "julio@example.com")
    monkeypatch.setenv("ZOOM_INTERNAL_REQUEST_WIKO_CONTACT", "wiko@example.com")

    def support_reads(token, path, _params):
        calls.append((token, path))
        if path == "/users":
            return {
                "users": [
                    _sender_user(),
                    {
                        "id": "u1",
                        "email": "julio@example.com",
                        "first_name": "Julio",
                        "last_name": "Example",
                    },
                    {
                        "id": "u2",
                        "email": "wiko@example.com",
                        "first_name": "Wiko",
                        "last_name": "Example",
                    },
                ]
            }
        if path == "/contact_center/analytics/log/historical/engagement":
            return {"engagement_logs": []}
        if path == "/chat/users/sender-001/messages/m1":
            return {
                "id": "m1",
                "message": "Hey Wiko, provider routing test.",
                "sender": "darius@novapointofsale.com",
            }
        raise AssertionError(f"unexpected Zoom path: {path}")

    def support_post(token, path, payload):
        calls.append((token, path))
        assert path == "/chat/users/sender-001/messages"
        assert payload == {
            "message": "Hey Wiko, provider routing test.",
            "to_contact": "wiko@example.com",
        }
        return {"ids": ["m1"]}

    client = ScopedZoomClient(
        token_provider=lambda: "legacy-general-oauth",
        team_chat_token_provider=lambda: sender_token,
        metrics_token_provider=lambda: sender_token,
        getter=support_reads,
        poster=support_post,
        team_chat_journal_path=tmp_path / "team-chat.jsonl",
        internal_communication_journal_path=tmp_path / "internal-requests.jsonl",
    )

    assert client.health()["ok"] is True
    resolved = client.team_chat_recipient_resolve(exact_recipient="configured:wiko")
    sent = client.team_chat_send(
        exact_recipient="configured:wiko",
        message="Hey Wiko, provider routing test.",
        authorization_context="unit test",
        idempotency_key="zoom-s2s-provider-test",
        sender_lane="coding_agent",
    )

    assert resolved["ok"] is True
    assert sent["status"] == "sent"
    assert sent["readbackVerified"] is True
    assert calls
    assert all(token == sender_token for token, _path in calls)
    assert not any(token == "legacy-general-oauth" for token, _path in calls)
    assert client.capabilities()["teamChatCredential"] == "Support Dashboard Calls"
    assert client.capabilities()["teamChatCredentialType"] == "server_to_server_oauth"


def test_operator_team_chat_allows_unique_custom_domain_and_deduplicates(
    tmp_path: Path,
) -> None:
    posts: list[dict[str, object]] = []

    def getter(_token, path, _params):
        if path == "/chat/users/me/contacts":
            return {
                "contacts": [
                    {
                        "id": "contact-001",
                        "member_id": "member-001",
                        "email": "operator@customer-domain.example",
                        "display_name": "External Operator",
                    }
                ]
            }
        if path == "/chat/users/me/messages/message-001":
            return {
                "id": "message-001",
                "message": "The requested status is ready.",
                "sender": "Authorized User",
            }
        raise AssertionError(f"unexpected Zoom path: {path}")

    def poster(_token, path, payload):
        assert path == "/chat/users/me/messages"
        posts.append(payload)
        return {"ids": ["message-001"]}

    client = ScopedZoomClient(
        token_provider=lambda: "user-oauth",
        getter=getter,
        poster=poster,
        team_chat_journal_path=tmp_path / "operator-chat.jsonl",
    )
    first = client.operator_team_chat_send(
        exact_recipient="operator@customer-domain.example",
        message="The requested status is ready.",
        authorization_context="Operator explicitly requested this exact Zoom message.",
        idempotency_key="operator-custom-domain-001",
        sender_lane="claude_agent",
    )
    second = client.operator_team_chat_send(
        exact_recipient="operator@customer-domain.example",
        message="The requested status is ready.",
        authorization_context="Operator explicitly requested this exact Zoom message.",
        idempotency_key="operator-custom-domain-001",
        sender_lane="claude_agent",
    )

    assert first["ok"] is True
    assert first["readbackVerified"] is True
    assert first["recipient"]["email"] == "operator@customer-domain.example"
    assert second["ok"] is True
    assert second["duplicatePrevented"] is True
    assert len(posts) == 1


def test_operator_team_chat_blocks_ambiguous_full_name() -> None:
    def getter(_token, path, _params):
        assert path == "/chat/users/me/contacts"
        return {
            "contacts": [
                {
                    "id": "contact-001",
                    "email": "one@example.test",
                    "display_name": "Same Name",
                },
                {
                    "id": "contact-002",
                    "email": "two@another-domain.test",
                    "display_name": "Same Name",
                },
            ]
        }

    result = ScopedZoomClient(
        token_provider=lambda: "user-oauth",
        getter=getter,
    ).operator_team_chat_recipient_resolve(exact_recipient="Same Name")

    assert result["ok"] is False
    assert result["status"] == "blocked"


def test_ghostbusters_overview_update_is_fixed_private_safe_and_read_back(
    tmp_path: Path,
) -> None:
    file_id = zoom_client_module.DEFAULT_GHOSTBUSTERS_OVERVIEW_FILE_ID
    markdown = "\n".join(
        [
            "# Ghost Busters Chat Overview",
            "## Public Content Rule",
            "Public operational resources only. Keep private material out.",
            (
                "Never include customer identifiers, ticket identifiers, "
                "one-on-one material, API keys, or access tokens."
            ),
            "## Nova versions",
            "Nova Wave 0.1.5.3 and Nova 7.0.0.67 are verified.",
            "## Support resources",
            (
                "[Printer drivers]"
                "(https://drive.google.com/drive/u/0/folders/"
                "1futCMqrBpsOmpmrfq0btyJaiXl2KpP0r)"
            ),
        ]
    )
    manifest = tmp_path / "NOVA_VERSION_MATRIX.md"
    manifest.write_text(
        (
            "[Printer drivers]"
            "(https://drive.google.com/drive/u/0/folders/"
            "1futCMqrBpsOmpmrfq0btyJaiXl2KpP0r)\n"
        ),
        encoding="utf-8",
    )
    posts: list[tuple[str, dict[str, object]]] = []

    def getter(_token, path, params):
        if path == f"/docs/files/{file_id}":
            return {"file_id": file_id, "file_name": "Chat Overview"}
        if path == f"/docs/files/{file_id}/content" and params == {"format": "xml"}:
            return {
                "file_name": "Chat Overview",
                "file_content": '<text id="23605">Old</text><text id="0197a">Body</text>',
            }
        if path == f"/docs/files/{file_id}/content" and params is None:
            return {"file_name": "Chat Overview", "file_content": markdown}
        raise AssertionError(f"unexpected Zoom path: {path}")

    def poster(_token, path, payload):
        posts.append((path, payload))
        return {}

    client = ScopedZoomClient(
        token_provider=lambda: "user-oauth",
        getter=getter,
        poster=poster,
        ghostbusters_overview_journal_path=tmp_path / "overview.jsonl",
        ghostbusters_link_manifest_path=manifest,
    )
    result = client.ghostbusters_overview_update(
        markdown=markdown,
        source_date="2026-07-30",
        source_summary="Verified public Nova version and operational resource refresh.",
        authorization_context="Operator requested the Ghost Busters overview refresh.",
        idempotency_key="ghostbusters-overview-20260730",
        sender_lane="claude_agent",
    )

    assert result["ok"] is True
    assert result["readbackVerified"] is True
    assert result["verifiedLinkCount"] == 1
    assert result["linkManifestSha256"] == hashlib.sha256(
        manifest.read_text(encoding="utf-8").encode("utf-8")
    ).hexdigest()
    assert posts[0][0] == f"/docs/files/{file_id}/blocks/replace_range"
    assert posts[0][1]["start_block_id"] == "23605"
    assert posts[0][1]["end_block_id"] == "0197a"
    assert isinstance(posts[0][1]["blocks"], str)

    with pytest.raises(ValueError, match="customer or ticket identifiers"):
        client.ghostbusters_overview_update(
            markdown=markdown + "\nCustomer account ID: private-1234",
            source_date="2026-07-30",
            source_summary="Private record attempt.",
            authorization_context="Operator requested the Ghost Busters overview refresh.",
            idempotency_key="ghostbusters-overview-private",
            sender_lane="claude_agent",
        )

    with pytest.raises(ValueError, match="private operational material"):
        client.ghostbusters_overview_update(
            markdown=markdown + "\n## One-on-one notes",
            source_date="2026-07-30",
            source_summary="Private meeting attempt.",
            authorization_context="Operator requested the Ghost Busters overview refresh.",
            idempotency_key="ghostbusters-overview-private-meeting",
            sender_lane="claude_agent",
        )

    with pytest.raises(ValueError, match="credential values"):
        client.ghostbusters_overview_update(
            markdown=markdown + "\nAPI key: private-value",
            source_date="2026-07-30",
            source_summary="Credential value attempt.",
            authorization_context="Operator requested the Ghost Busters overview refresh.",
            idempotency_key="ghostbusters-overview-private-credential",
            sender_lane="claude_agent",
        )

    with pytest.raises(ValueError, match="verified Nova version/link manifest"):
        client.ghostbusters_overview_update(
            markdown=markdown + "\n[Unverified installer](https://downloads.example.test/setup.exe)",
            source_date="2026-07-30",
            source_summary="Unverified route attempt.",
            authorization_context="Operator requested the Ghost Busters overview refresh.",
            idempotency_key="ghostbusters-overview-unverified-link",
            sender_lane="claude_agent",
        )


def test_ghostbusters_overview_update_fails_closed_without_link_manifest(
    tmp_path: Path,
) -> None:
    client = ScopedZoomClient(
        token_provider=lambda: "user-oauth",
        ghostbusters_overview_journal_path=tmp_path / "overview.jsonl",
        ghostbusters_link_manifest_path=tmp_path / "missing.md",
    )

    with pytest.raises(RuntimeError, match="manifest is unavailable"):
        client.ghostbusters_overview_update(
            markdown=(
                "# Ghost Busters Chat Overview\n"
                "## Support team resources\n"
                "Public operational tools, versions, topics, and reminders only. "
                "Exclude private customer, ticket, credential, and one-on-one material."
            ),
            source_date="2026-07-30",
            source_summary="Support team overview refresh.",
            authorization_context="Operator requested the Ghost Busters overview refresh.",
            idempotency_key="ghostbusters-overview-no-manifest",
            sender_lane="claude_agent",
        )


def test_zoom_docs_archive_read_uses_only_validated_zoom_download(
    tmp_path: Path,
) -> None:
    archive = {
        "file_id": "archive-file-001",
        "file_name": "Meeting Summary",
        "product": "meeting_summary",
        "archive_time": "2026-07-29T12:00:00Z",
        "download_url": "https://api.zoom.us/v2/docs/archives/archive-file-001/content",
        "owner_email": "private@example.test",
    }

    def getter(_token, path, _params):
        assert path == "/docs/archives"
        return {"archives": [archive]}

    client = ScopedZoomClient(
        token_provider=lambda: "user-oauth",
        team_chat_token_provider=lambda: "s2s",
        getter=getter,
        text_getter=lambda _token, _url, _limit: json.dumps(
            {
                "product": "meeting_summary",
                "markdown": "Operational initiative summary.",
                "transcript": {"items": []},
            }
        ),
    )
    listing = client.docs_archives(
        start_utc="2026-01-01T00:00:00Z",
        end_utc="2026-07-30T00:00:00Z",
    )
    content = client.docs_archive_content(
        file_id="archive-file-001",
        start_utc="2026-01-01T00:00:00Z",
        end_utc="2026-07-30T00:00:00Z",
    )

    assert listing["ok"] is True
    assert "owner_email" not in listing["archives"][0]
    assert "download_url" not in listing["archives"][0]
    assert content["ok"] is True
    assert content["markdown"] == "Operational initiative summary."


def test_thor_quality_reads_fixed_roster_voice_and_performance_only(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _configure_weekly_roster(tmp_path, monkeypatch)
    paths: list[str] = []

    def reads(token, path, params):
        assert token == "support-dashboard-calls-s2s"
        paths.append(path)
        if path == "/contact_center/analytics/log/historical/engagement":
            assert params["timezone"] == "UTC"
            return {
                "engagement_logs": [
                    {
                        "engagement_id": "engagement-quality-001",
                        "start_time": "2026-07-21T12:00:00Z",
                        "direction": "inbound",
                        "channels": [{"channel": "voice"}],
                        "users": [{"user_id": "agent-001"}],
                        "consumer_number": "+15555550123",
                        "consumer_display_name": "Must Not Leak",
                    },
                    {
                        "engagement_id": "engagement-message-001",
                        "start_time": "2026-07-21T13:00:00Z",
                        "channels": [{"channel": "messaging"}],
                        "users": [{"user_id": "agent-001"}],
                    },
                    {
                        "engagement_id": "engagement-other-001",
                        "start_time": "2026-07-21T14:00:00Z",
                        "channels": [{"channel": "voice"}],
                        "users": [{"user_id": "not-on-roster"}],
                    },
                ]
            }
        if path == "/contact_center/analytics/dataset/historical/agent_performance":
            assert params["from"] == "2026-07-21T00:00:00Z"
            assert params["to"] == "2026-07-22T00:00:00Z"
            return {
                "agent_performance": [
                    {
                        "user_id": "cx-id-does-not-match-profile",
                        "user_name": "Alex",
                        "engagement_id": "engagement-quality-001",
                        "talk_duration": 120,
                        "hold_duration": 15,
                        "consumer_number": "+15555550123",
                    }
                ]
            }
        raise AssertionError(path)

    client = ScopedZoomClient(
        token_provider=lambda: "legacy-general-oauth",
        metrics_token_provider=lambda: "support-dashboard-calls-s2s",
        getter=reads,
    )
    voice = client.quality_voice_engagements(
        start_utc="2026-07-21T00:00:00Z",
        end_utc="2026-07-22T00:00:00Z",
    )
    performance = client.quality_agent_performance(
        start_utc="2026-07-21T00:00:00Z",
        end_utc="2026-07-22T00:00:00Z",
    )

    assert voice["ok"] is True
    assert voice["totalVoiceEngagements"] == 1
    assert voice["engagements"][0]["engagementId"] == "engagement-quality-001"
    assert performance["ok"] is True
    assert performance["matchedRowCount"] == 1
    assert performance["perAgent"][0]["matchBasis"] == ["unique_roster_name"]
    assert performance["perAgent"][0]["metrics"] == {
        "hold_duration": 15,
        "talk_duration": 120,
    }
    serialized = json.dumps({"voice": voice, "performance": performance})
    assert "Must Not Leak" not in serialized
    assert "+15555550123" not in serialized
    assert paths == [
        "/contact_center/analytics/log/historical/engagement",
        "/contact_center/analytics/dataset/historical/agent_performance",
    ]


def test_thor_quality_validates_engagement_and_downloads_only_zoom_returned_transcript(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _configure_weekly_roster(tmp_path, monkeypatch)
    downloads: list[tuple[str, str, int]] = []

    def reads(token, path, params):
        assert token == "support-dashboard-calls-s2s"
        if path == "/contact_center/analytics/log/historical/engagement":
            return {
                "engagement_logs": [
                    {
                        "engagement_id": "engagement-quality-001",
                        "start_time": "2026-07-21T12:00:00Z",
                        "channels": [{"channel": "voice"}],
                        "users": [{"user_id": "agent-001"}],
                    }
                ]
            }
        if path == "/contact_center/engagements/engagement-quality-001/recordings":
            assert params["channel"] == "voice"
            assert params["channel_type"] == "voice"
            return {
                "recordings": [
                    {
                        "recording_id": "recording-quality-001",
                        "engagement_id": "engagement-quality-001",
                        "recording_duration": 180,
                        "channel": "voice",
                        "direction": "inbound",
                        "transcript_url": (
                            "https://api.zoom.us/v2/contact_center/recording/"
                            "transcripts/download/recording-quality-001?type=voice"
                        ),
                        "consumer_number": "+15555550123",
                    }
                ]
            }
        raise AssertionError(path)

    def download(token, url, max_bytes):
        downloads.append((token, url, max_bytes))
        return "WEBVTT\n\n00:00.000 --> 00:02.000\nAgent: Welcome to Nova support."

    client = ScopedZoomClient(
        token_provider=lambda: "legacy-general-oauth",
        metrics_token_provider=lambda: "support-dashboard-calls-s2s",
        getter=reads,
        text_getter=download,
    )
    recordings = client.quality_engagement_recordings(
        engagement_id="engagement-quality-001",
        start_utc="2026-07-21T00:00:00Z",
        end_utc="2026-07-22T00:00:00Z",
    )
    transcript = client.quality_transcript(
        engagement_id="engagement-quality-001",
        recording_id="recording-quality-001",
        start_utc="2026-07-21T00:00:00Z",
        end_utc="2026-07-22T00:00:00Z",
        max_chars=10_000,
    )

    assert recordings["ok"] is True
    assert recordings["transcriptAvailableCount"] == 1
    assert transcript["ok"] is True
    assert transcript["ephemeralEvidence"] is True
    assert "Welcome to Nova support" in transcript["transcript"]
    assert downloads and downloads[0][0] == "support-dashboard-calls-s2s"
    assert downloads[0][1].startswith("https://api.zoom.us/v2/contact_center/")
    assert "transcript_url" not in json.dumps(recordings)
    assert "https://api.zoom.us" not in json.dumps(transcript)
    assert "+15555550123" not in json.dumps(recordings)


def test_thor_quality_rejects_non_zoom_transcript_host(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _configure_weekly_roster(tmp_path, monkeypatch)

    def reads(_token, path, _params):
        if path == "/contact_center/analytics/log/historical/engagement":
            return {
                "engagement_logs": [
                    {
                        "engagement_id": "engagement-quality-001",
                        "start_time": "2026-07-21T12:00:00Z",
                        "channels": [{"channel": "voice"}],
                        "users": [{"user_id": "agent-001"}],
                    }
                ]
            }
        if path == "/contact_center/engagements/engagement-quality-001/recordings":
            return {
                "recordings": [
                    {
                        "recording_id": "recording-quality-001",
                        "transcript_url": "https://attacker.example/transcript/steal",
                    }
                ]
            }
        raise AssertionError(path)

    client = ScopedZoomClient(
        token_provider=lambda: "test",
        metrics_token_provider=lambda: "support-dashboard-calls-s2s",
        getter=reads,
        text_getter=lambda *_args: pytest.fail("an untrusted URL must never be fetched"),
    )
    result = client.quality_transcript(
        engagement_id="engagement-quality-001",
        recording_id="recording-quality-001",
        start_utc="2026-07-21T00:00:00Z",
        end_utc="2026-07-22T00:00:00Z",
    )

    assert result["ok"] is False
    assert result["status"] == "blocked"
    assert result["coverageGaps"] == ["voice_transcript_unavailable"]
    assert "attacker.example" not in json.dumps(result)


def test_thor_quality_blocks_transcript_redirect_before_bearer_can_leave_zoom() -> None:
    handler = _ZoomTranscriptRedirectBlocker()

    with pytest.raises(RuntimeError, match="redirects are not allowed"):
        handler.redirect_request(
            object(),
            None,
            302,
            "Found",
            {},
            "https://attacker.example/transcript",
        )


def test_thor_quality_missing_transcript_is_an_explicit_coverage_gap(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _configure_weekly_roster(tmp_path, monkeypatch)

    def reads(_token, path, _params):
        if path == "/contact_center/analytics/log/historical/engagement":
            return {
                "engagement_logs": [
                    {
                        "engagement_id": "engagement-quality-001",
                        "start_time": "2026-07-21T12:00:00Z",
                        "channels": [{"channel": "voice"}],
                        "users": [{"user_id": "agent-001"}],
                    }
                ]
            }
        if path == "/contact_center/engagements/engagement-quality-001/recordings":
            return {
                "recordings": [
                    {
                        "recording_id": "recording-quality-001",
                        "channel": "voice",
                    }
                ]
            }
        raise AssertionError(path)

    result = ScopedZoomClient(
        token_provider=lambda: "test",
        metrics_token_provider=lambda: "support-dashboard-calls-s2s",
        getter=reads,
    ).quality_transcript(
        engagement_id="engagement-quality-001",
        recording_id="recording-quality-001",
        start_utc="2026-07-21T00:00:00Z",
        end_utc="2026-07-22T00:00:00Z",
    )

    assert result["ok"] is True
    assert result["status"] == "partial"
    assert result["transcriptAvailable"] is False
    assert result["coverageGaps"] == ["voice_transcript_missing_or_processing"]


def test_weekly_metrics_match_fixed_report_agent_sum_across_all_queues(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _configure_weekly_roster(tmp_path, monkeypatch)

    def reads(_token, path, params):
        if path == "/contact_center/analytics/log/historical/engagement":
            assert params["timezone"] == "UTC"
            assert "channel" not in params
            assert "channels" not in params
            return {
                "engagement_logs": [
                    {
                        "engagement_id": "e1",
                        "start_time": "2026-07-17T05:00:00Z",
                        "direction": "inbound",
                        "channels": [{"channel": "voice"}],
                        "queues": [{"queue_id": "any-queue"}],
                        "users": [
                            {"user_id": "agent-001"},
                            {"user_id": "agent-002"},
                        ],
                    },
                    {
                        "engagement_id": "e1",
                        "start_time": "2026-07-17T05:01:00Z",
                        "direction": "inbound",
                        "channels": [{"channel": "voice"}],
                        "queues": [{"queue_id": "different-queue"}],
                        "users": [
                            {"user_id": "agent-001"},
                            {"user_id": "agent-002"},
                        ],
                    },
                    {
                        "engagement_id": "e2",
                        "start_time": "2026-07-18T05:00:00Z",
                        "direction": "outbound",
                        "channels": [{"channel": "voice"}],
                        "users": [{"user_id": "agent-002"}],
                    },
                    {
                        "engagement_id": "e3",
                        "start_time": "2026-07-19T05:00:00Z",
                        "direction": "inbound",
                        "channels": [{"channel": "messaging"}],
                        "users": [{"user_id": "agent-001"}],
                    },
                ]
            }
        raise AssertionError(path)

    result = ScopedZoomClient(token_provider=lambda: "test", getter=reads).weekly_support_metrics(
        start_utc="2026-07-17T04:00:00Z",
        end_utc="2026-07-24T04:00:00Z",
    )

    assert result["ok"] is True
    assert result["inbound"] == 3
    assert result["outbound"] == 1
    assert result["total"] == 4
    assert result["uniqueEngagements"] == 3
    assert result["calls"] == {
        "inbound": 1,
        "outbound": 1,
        "unknown": 0,
        "total": 2,
    }
    assert result["chatSessions"] == {
        "inbound": 1,
        "outbound": 0,
        "unknown": 0,
        "total": 1,
    }
    assert result["unclassifiedSessions"]["total"] == 0
    assert result["doNotUseTotalAsCallCount"] is True
    assert result["supportQueue"] == "All queues"
    assert result["reportId"] == "report-001"
    assert result["countDefinition"] == (
        "sum of distinct engagements per agent across all channels and queues "
        "for the fixed report roster"
    )
    assert result["perAgent"] == [
        {
            "id": "agent-001",
            "name": "Alex",
            "inbound": 2,
            "outbound": 0,
            "unknown": 0,
            "total": 2,
            "calls": {"inbound": 1, "outbound": 0, "unknown": 0, "total": 1},
            "chatSessions": {
                "inbound": 1,
                "outbound": 0,
                "unknown": 0,
                "total": 1,
            },
            "unclassifiedSessions": {
                "inbound": 0,
                "outbound": 0,
                "unknown": 0,
                "total": 0,
            },
        },
        {
            "id": "agent-002",
            "name": "Jamie",
            "inbound": 1,
            "outbound": 1,
            "unknown": 0,
            "total": 2,
            "calls": {"inbound": 1, "outbound": 1, "unknown": 0, "total": 2},
            "chatSessions": {
                "inbound": 0,
                "outbound": 0,
                "unknown": 0,
                "total": 0,
            },
            "unclassifiedSessions": {
                "inbound": 0,
                "outbound": 0,
                "unknown": 0,
                "total": 0,
            },
        },
    ]


def test_weekly_metrics_reproduce_saved_total_calls_report_77(
    tmp_path: Path,
    monkeypatch,
) -> None:
    expected = [
        ("mordi-01", "Mordi Tech Support", 18, 0),
        ("darius-01", "Darius Parlor - Nova Point of Sale", 11, 0),
        ("eddie-01", "Eddie Talal", 13, 1),
        ("oscar-o-01", "Oscar Ocampo", 5, 0),
        ("eduardo-01", "Eduardo Brambila", 18, 8),
        ("oscar-u-01", "Oscar Umana", 3, 0),
    ]
    roster_path = tmp_path / "zoom-weekly-support-agents.json"
    roster_path.write_text(
        json.dumps(
            {
                "reportId": "ASNsvKgkR0man2E-rUZqMA",
                "reportName": "Total Calls",
                "agents": [
                    {"id": user_id, "name": name}
                    for user_id, name, _inbound, _outbound in expected
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("ZOOM_WEEKLY_SUPPORT_AGENT_ROSTER_FILE", str(roster_path))
    rows = []
    for user_id, _name, inbound, outbound in expected:
        for index in range(inbound + outbound):
            rows.append(
                {
                    "engagement_id": f"{user_id}-{index}",
                    "start_time": "2026-07-20T12:00:00Z",
                    "direction": "inbound" if index < inbound else "outbound",
                    "channels": [
                        {
                            "channel": (
                                "messaging"
                                if user_id == "darius-01" and index == inbound - 1
                                else "voice"
                            )
                        }
                    ],
                    "users": [{"user_id": user_id}],
                }
            )
    rows.append(dict(rows[0]))

    def reads(_token, path, _params):
        assert path == "/contact_center/analytics/log/historical/engagement"
        return {"engagement_logs": rows}

    result = ScopedZoomClient(token_provider=lambda: "test", getter=reads).weekly_support_metrics(
        start_utc="2026-07-17T04:00:00Z",
        end_utc="2026-07-24T04:00:00Z",
    )

    assert result["ok"] is True
    assert result["inbound"] == 68
    assert result["outbound"] == 9
    assert result["total"] == 77
    assert result["calls"]["total"] == 76
    assert result["chatSessions"]["total"] == 1
    assert [item["total"] for item in result["perAgent"]] == [18, 11, 14, 5, 26, 3]


def test_weekly_metrics_use_approved_s2s_engagement_log_only(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _configure_weekly_roster(tmp_path, monkeypatch)
    paths: list[str] = []

    def reads(_token, path, _params):
        paths.append(path)
        if path == "/contact_center/analytics/log/historical/engagement":
            return {
                "engagement_logs": [
                    {
                        "engagement_id": "e1",
                        "start_time": "2026-07-18T05:00:00Z",
                        "direction": "inbound",
                        "channels": [{"channel": "voice"}],
                        "users": [{"user_id": "agent-001"}],
                    }
                ]
            }
        raise AssertionError(path)

    result = ScopedZoomClient(
        token_provider=lambda: "general-token",
        metrics_token_provider=lambda: "approved-s2s-token",
        getter=reads,
    ).weekly_support_metrics(
        start_utc="2026-07-17T04:00:00Z",
        end_utc="2026-07-24T04:00:00Z",
    )

    assert result["ok"] is True
    assert result["total"] == 1
    assert paths == ["/contact_center/analytics/log/historical/engagement"]


def test_weekly_metrics_fail_closed_when_fixed_agent_roster_is_missing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    missing = tmp_path / "missing-roster.json"
    monkeypatch.setenv("ZOOM_WEEKLY_SUPPORT_AGENT_ROSTER_FILE", str(missing))
    calls = []

    result = ScopedZoomClient(
        token_provider=lambda: "test",
        getter=lambda *_args: calls.append(_args) or {"engagement_logs": []},
    ).weekly_support_metrics(
        start_utc="2026-07-17T04:00:00Z",
        end_utc="2026-07-24T04:00:00Z",
    )

    assert result["ok"] is False
    assert result["status"] == "blocked"
    assert result["total"] is None
    assert calls == []


def test_weekly_send_posts_once_reads_back_and_journals(tmp_path: Path, monkeypatch) -> None:
    calls = {"posts": 0}
    sent_body = {}
    _configure_weekly_roster(tmp_path, monkeypatch)
    sender_token = _configure_team_chat_sender(monkeypatch)

    def reads(_token, path, params):
        if path == "/contact_center/analytics/log/historical/engagement":
            return {
                "engagement_logs": [
                    {
                        "engagement_id": "e1",
                        "start_time": "2026-07-17T05:00:00Z",
                        "direction": "inbound",
                        "channels": [{"channel": "voice"}],
                        "users": [{"user_id": "agent-001"}],
                    }
                ]
            }
        if path == "/users":
            return {
                "users": [
                    _sender_user(),
                    {
                        "id": "y1",
                        "email": "verified@example.test",
                        "first_name": "Yaron",
                        "last_name": "Bachar",
                    }
                ]
            }
        if path == "/chat/users/sender-001/messages":
            return {"messages": []}
        if path == "/chat/users/sender-001/messages/m1":
            assert params == {"to_contact": "verified@example.test"}
            return {
                "id": "m1",
                "message": sent_body["message"],
                "sender": "darius@novapointofsale.com",
            }
        raise AssertionError(path)

    def post(_token, path, body):
        calls["posts"] += 1
        assert path == "/chat/users/sender-001/messages"
        assert body["to_contact"] == "verified@example.test"
        assert "7/17/2026-7/23/2026" in body["message"]
        assert "Total calls: 1" in body["message"]
        assert "Total tickets: 6" in body["message"]
        assert "Nova Classic" not in body["message"]
        assert "Nova Wave" not in body["message"]
        assert "inbound" not in body["message"].casefold()
        assert "outbound" not in body["message"].casefold()
        assert "Alex" not in body["message"]
        sent_body.update(body)
        return {"ids": ["m1"]}

    monkeypatch.delenv("ZOOM_WEEKLY_YARON_RECIPIENT_EMAIL", raising=False)
    client = ScopedZoomClient(
        token_provider=lambda: sender_token,
        getter=reads,
        poster=post,
        journal_path=tmp_path / "journal.jsonl",
    )
    kwargs = {
        "start_utc": "2026-07-17T04:00:00Z",
        "end_utc": "2026-07-24T04:00:00Z",
        "ticket_total": 6,
        "idempotency_key": "weekly-yaron:2026-07-17:2026-07-24",
    }

    first = client.weekly_yaron_report_send(**kwargs)
    second = client.weekly_yaron_report_send(**kwargs)
    rebound = client.weekly_yaron_report_send(
        **{
            **kwargs,
            "ticket_total": 7,
        }
    )
    entries = [
        json.loads(line)
        for line in (tmp_path / "journal.jsonl").read_text(encoding="utf-8").splitlines()
    ]

    assert first["ok"] is True, first
    assert first["messageId"] == "m1"
    assert first["channel"] == "zoom"
    assert first["readbackVerified"] is True
    assert first["senderReadbackVerified"] is True
    assert first["recipientReadbackVerified"] is True
    assert first["sender"]["id"] == "sender-001"
    assert first["tickets"] == {"total": 6}
    assert second["duplicatePrevented"] is True
    assert rebound["ok"] is False
    assert rebound["status"] == "blocked"
    assert "different weekly Zoom report request" in rebound["reason"]
    assert [entry["status"] for entry in entries] == ["provider_attempt", "sent"]
    assert calls["posts"] == 1


def test_weekly_send_atomic_attempt_claim_prevents_concurrent_duplicate(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _configure_weekly_roster(tmp_path, monkeypatch)
    sender_token = _configure_team_chat_sender(monkeypatch)
    monkeypatch.setenv("ZOOM_WEEKLY_YARON_RECIPIENT_EMAIL", "verified@example.test")
    attempt_started = Event()
    allow_finish = Event()
    sent_body: dict[str, str] = {}
    calls = {"posts": 0}

    def reads(_token, path, _params):
        if path == "/contact_center/analytics/log/historical/engagement":
            return {"engagement_logs": []}
        if path == "/users":
            return {
                "users": [
                    _sender_user(),
                    {
                        "id": "y1",
                        "email": "verified@example.test",
                        "first_name": "Yaron",
                        "last_name": "Bachar",
                        "status": "active",
                    },
                ]
            }
        if path == "/chat/users/sender-001/messages":
            return {"messages": []}
        if path == "/chat/users/sender-001/messages/weekly-concurrent":
            return {
                "id": "weekly-concurrent",
                "message": sent_body["message"],
                "sender": "darius@novapointofsale.com",
            }
        raise AssertionError(path)

    def post(_token, _path, body):
        calls["posts"] += 1
        attempt_started.set()
        assert allow_finish.wait(timeout=5)
        sent_body.update(body)
        return {"id": "weekly-concurrent"}

    client = ScopedZoomClient(
        token_provider=lambda: sender_token,
        getter=reads,
        poster=post,
        journal_path=tmp_path / "journal.jsonl",
    )
    request = {
        "start_utc": "2026-07-17T04:00:00Z",
        "end_utc": "2026-07-24T04:00:00Z",
        "ticket_total": 6,
        "idempotency_key": "weekly-yaron:concurrent:2026-07-24",
    }

    with ThreadPoolExecutor(max_workers=2) as pool:
        first_future = pool.submit(client.weekly_yaron_report_send, **request)
        assert attempt_started.wait(timeout=5)
        second_future = pool.submit(client.weekly_yaron_report_send, **request)
        second = second_future.result(timeout=5)
        allow_finish.set()
        first = first_future.result(timeout=5)

    assert first["ok"] is True
    assert second["ok"] is False
    assert second["status"] == "uncertain"
    assert calls["posts"] == 1
    third = client.weekly_yaron_report_send(**request)
    assert third["ok"] is True
    assert third["duplicatePrevented"] is True
    assert calls["posts"] == 1


def test_direct_team_chat_send_resolves_configured_recipient_posts_once_and_reads_back(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls = {"posts": 0}
    sent_body: dict[str, str] = {}
    sender_token = _configure_team_chat_sender(monkeypatch)
    monkeypatch.setenv("ZOOM_SINGAPORE_JULIO_CONTACT", "julio@example.test")

    def reads(_token, path, params):
        if path == "/users":
            assert params["status"] == "active"
            return {
                "users": [
                    _sender_user(),
                    {
                        "id": "julio-001",
                        "email": "julio@example.test",
                        "first_name": "Julio",
                        "last_name": "Example",
                    }
                ]
            }
        if path == "/chat/users/sender-001/messages/direct-001":
            assert params == {"to_contact": "julio@example.test"}
            return {
                "id": "direct-001",
                "message": sent_body["message"],
                "sender": "darius@novapointofsale.com",
            }
        raise AssertionError(path)

    def post(_token, path, body):
        calls["posts"] += 1
        assert path == "/chat/users/sender-001/messages"
        assert body == {
            "message": "Hey Julio, can you please reset the company password for Example Account?",
            "to_contact": "julio@example.test",
        }
        sent_body.update(body)
        return {"id": "direct-001"}

    journal = tmp_path / "team-chat.jsonl"
    client = ScopedZoomClient(
        token_provider=lambda: sender_token,
        getter=reads,
        poster=post,
        team_chat_journal_path=journal,
        internal_communication_journal_path=tmp_path / "internal-requests.jsonl",
    )
    kwargs = {
        "exact_recipient": "configured:julio",
        "message": "Hey Julio, can you please reset the company password for Example Account?",
        "authorization_context": "Operator request for ticket 347375",
        "idempotency_key": "zoom-ticket-347375-password-reset",
        "sender_lane": "coding_agent",
    }

    resolved = client.team_chat_recipient_resolve(exact_recipient="configured:julio")
    first = client.team_chat_send(**kwargs)
    restored_days: list[str] = []
    monkeypatch.setattr(
        zoom_client_module,
        "restore_verified_internal_request_day",
        lambda _recipient, **kwargs: restored_days.append(
            kwargs["verified_local_date"]
        )
        or True,
    )
    second = client.team_chat_send(
        **{
            **kwargs,
            "message": "can you please reset the company password for Example Account?",
        }
    )
    entries = [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines()]

    assert resolved["ok"] is True
    assert resolved["recipient"]["email"] == "julio@example.test"
    assert first["ok"] is True
    assert first["messageId"] == "direct-001"
    assert first["readbackVerified"] is True
    assert first["senderReadbackVerified"] is True
    assert first["recipientReadbackVerified"] is True
    assert second["ok"] is True
    assert second["duplicatePrevented"] is True
    assert restored_days == [first["internalRequestLocalDate"]]
    assert calls["posts"] == 1
    assert [entry["status"] for entry in entries] == ["provider_attempt", "sent"]


def test_direct_team_chat_send_can_reply_to_one_verified_parent_message(
    tmp_path: Path,
    monkeypatch,
) -> None:
    sender_token = _configure_team_chat_sender(monkeypatch)
    monkeypatch.setenv("ZOOM_SINGAPORE_JULIO_CONTACT", "julio@example.test")
    sent_body: dict[str, str] = {}

    def reads(_token, path, params):
        if path == "/users":
            return {
                "users": [
                    _sender_user(),
                    {
                        "id": "julio-001",
                        "email": "julio@example.test",
                        "first_name": "Julio",
                        "last_name": "Example",
                    },
                ]
            }
        if path == "/chat/users/sender-001/messages/reply-001":
            assert params == {"to_contact": "julio@example.test"}
            return {
                "id": "reply-001",
                "message": sent_body["message"],
                "sender": "darius@novapointofsale.com",
                "reply_main_message_id": "main-001",
            }
        raise AssertionError(path)

    def post(_token, path, body):
        assert path == "/chat/users/sender-001/messages"
        assert body["reply_main_message_id"] == "main-001"
        sent_body.update(body)
        return {"id": "reply-001"}

    client = ScopedZoomClient(
        token_provider=lambda: sender_token,
        getter=reads,
        poster=post,
        team_chat_journal_path=tmp_path / "team-chat.jsonl",
        internal_communication_journal_path=tmp_path / "internal-requests.jsonl",
    )

    result = client.team_chat_send(
        exact_recipient="configured:julio",
        message="Hey Julio, just a reminder on this Singapore resubmission. Thanks.",
        authorization_context="Verified repeated Singapore machine and date",
        idempotency_key="singapore-reminder-main-001",
        sender_lane="coding_agent",
        reply_main_message_id="main-001",
    )

    assert result["ok"] is True
    assert result["replyMainMessageId"] == "main-001"
    assert result["readbackVerified"] is True


def test_existing_team_chat_message_can_be_verified_without_resend(
    tmp_path: Path,
    monkeypatch,
) -> None:
    sender_token = _configure_team_chat_sender(monkeypatch)
    monkeypatch.setenv("ZOOM_SINGAPORE_JULIO_CONTACT", "julio@example.test")
    expected_body = "Hey Julio, can you please resubmit tenant 8000640? Thanks."

    def reads(_token, path, params):
        if path == "/users":
            return {
                "users": [
                    _sender_user(),
                    {
                        "id": "julio-001",
                        "email": "julio@example.test",
                        "first_name": "Julio",
                        "last_name": "Example",
                        "status": "active",
                    },
                ]
            }
        assert path == "/chat/users/sender-001/messages/legacy-message-001"
        assert params == {"to_contact": "julio@example.test"}
        return {
            "id": "legacy-message-001",
            "message": expected_body,
            "sender": "darius@novapointofsale.com",
        }

    client = ScopedZoomClient(
        token_provider=lambda: sender_token,
        getter=reads,
        poster=lambda *_args: (_ for _ in ()).throw(
            AssertionError("verification must not send")
        ),
        team_chat_journal_path=tmp_path / "team-chat.jsonl",
    )

    result = client.team_chat_verify_existing(
        exact_recipient="configured:julio",
        message_id="legacy-message-001",
        message=expected_body,
    )

    assert result["ok"] is True
    assert result["sent"] is True
    assert result["readbackVerified"] is True
    assert result["senderReadbackVerified"] is True
    assert result["recipientReadbackVerified"] is True
    assert result["existingMessageVerified"] is True
    assert not (tmp_path / "team-chat.jsonl").exists()


def test_existing_team_chat_message_requires_current_sender_readback(
    tmp_path: Path,
    monkeypatch,
) -> None:
    sender_token = _configure_team_chat_sender(monkeypatch)
    monkeypatch.setenv("ZOOM_SINGAPORE_JULIO_CONTACT", "julio@example.test")

    def reads(_token, path, _params):
        if path == "/users":
            return {
                "users": [
                    _sender_user(),
                    {
                        "id": "julio-001",
                        "email": "julio@example.test",
                        "first_name": "Julio",
                        "last_name": "Example",
                        "status": "active",
                    },
                ]
            }
        assert path == "/chat/users/sender-001/messages/legacy-message-002"
        return {
            "id": "legacy-message-002",
            "message": "same body",
            "sender": "someone-else@novapointofsale.com",
        }

    client = ScopedZoomClient(
        token_provider=lambda: sender_token,
        getter=reads,
        team_chat_journal_path=tmp_path / "team-chat.jsonl",
    )

    result = client.team_chat_verify_existing(
        exact_recipient="configured:julio",
        message_id="legacy-message-002",
        message="same body",
    )

    assert result["ok"] is False
    assert result["sent"] is False
    assert result["status"] == "sent_unverified"
    assert result["retryAllowed"] is False


def test_direct_team_chat_requires_exact_sender_in_provider_readback(
    tmp_path: Path,
    monkeypatch,
) -> None:
    sender_token = _configure_team_chat_sender(monkeypatch)
    monkeypatch.setenv("ZOOM_SINGAPORE_JULIO_CONTACT", "julio@example.test")
    sent_body: dict[str, str] = {}

    def reads(_token, path, _params):
        if path == "/users":
            return {
                "users": [
                    _sender_user(),
                    {
                        "id": "julio-001",
                        "email": "julio@example.test",
                        "first_name": "Julio",
                        "last_name": "Nova",
                        "status": "active",
                    },
                ]
            }
        if path == "/chat/users/sender-001/messages/direct-missing-sender":
            return {
                "id": "direct-missing-sender",
                "message": sent_body["message"],
            }
        raise AssertionError(path)

    def post(_token, _path, body):
        sent_body["message"] = body["message"]
        return {"id": "direct-missing-sender"}

    client = ScopedZoomClient(
        token_provider=lambda: sender_token,
        getter=reads,
        poster=post,
        team_chat_journal_path=tmp_path / "team-chat.jsonl",
        internal_communication_journal_path=tmp_path / "internal-requests.jsonl",
    )

    result = client.team_chat_send(
        exact_recipient="configured:julio",
        message="can you check this?",
        authorization_context="Operator-requested internal follow-up",
        idempotency_key="julio-missing-sender-readback",
        sender_lane="coding_agent",
    )

    assert result["ok"] is False
    assert result["status"] == "uncertain"
    assert result["sent"] is False
    assert "sender readback" in result["reason"]


def test_direct_team_chat_crash_after_atomic_attempt_marker_never_blind_retries(
    tmp_path: Path,
    monkeypatch,
) -> None:
    sender_token = _configure_team_chat_sender(monkeypatch)
    monkeypatch.setenv("ZOOM_SINGAPORE_JULIO_CONTACT", "julio@example.test")
    journal = tmp_path / "team-chat.jsonl"
    users = {
        "users": [
            _sender_user(),
            {
                "id": "julio-001",
                "email": "julio@example.test",
                "first_name": "Julio",
                "last_name": "Nova",
                "status": "active",
            },
        ]
    }

    def crash_reads(_token, path, _params):
        if path == "/users":
            return users
        raise AssertionError(path)

    first = ScopedZoomClient(
        token_provider=lambda: sender_token,
        getter=crash_reads,
        poster=lambda *_args: (_ for _ in ()).throw(SystemExit("simulated crash")),
        team_chat_journal_path=journal,
        internal_communication_journal_path=tmp_path / "internal-requests.jsonl",
    )
    request = {
        "exact_recipient": "configured:julio",
        "message": "can you check this?",
        "authorization_context": "Operator-requested internal follow-up",
        "idempotency_key": "julio-provider-attempt-crash",
        "sender_lane": "coding_agent",
    }

    with pytest.raises(SystemExit, match="simulated crash"):
        first.team_chat_send(**request)

    entries = [
        json.loads(line)
        for line in journal.read_text(encoding="utf-8").splitlines()
    ]
    assert [entry["status"] for entry in entries] == ["provider_attempt"]
    posts: list[object] = []

    def recovery_reads(_token, path, _params):
        if path == "/users":
            return users
        if path == "/chat/users/sender-001/messages":
            return {"messages": []}
        raise AssertionError(path)

    second = ScopedZoomClient(
        token_provider=lambda: sender_token,
        getter=recovery_reads,
        poster=lambda *_args: posts.append(_args),
        team_chat_journal_path=journal,
        internal_communication_journal_path=tmp_path / "internal-requests.jsonl",
    )
    result = second.team_chat_send(**request)

    assert result["ok"] is False
    assert result["status"] == "uncertain"
    assert posts == []


def test_direct_team_chat_send_requires_explicit_sender_user_id(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("ZOOM_TEAM_CHAT_SENDER_USER_ID", raising=False)
    monkeypatch.setenv("ZOOM_SINGAPORE_JULIO_CONTACT", "julio@example.test")
    posts: list[object] = []

    client = ScopedZoomClient(
        token_provider=lambda: _s2s_token(),
        getter=lambda _token, path, _params: (
            {"users": [_sender_user()]}
            if path == "/users"
            else pytest.fail(f"unexpected read: {path}")
        ),
        poster=lambda *_args: posts.append(_args),
        team_chat_journal_path=tmp_path / "team-chat.jsonl",
        internal_communication_journal_path=tmp_path / "internal-requests.jsonl",
    )

    with pytest.raises(
        RuntimeError,
        match="ZOOM_TEAM_CHAT_SENDER_USER_ID",
    ):
        client.team_chat_send(
            exact_recipient="configured:julio",
            message="can you check this?",
            authorization_context="Operator-requested internal follow-up",
            idempotency_key="julio-missing-explicit-sender",
            sender_lane="coding_agent",
        )

    assert posts == []


def test_direct_team_chat_send_rejects_sender_that_is_not_s2s_token_owner(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("ZOOM_TEAM_CHAT_SENDER_USER_ID", "different-sender")
    monkeypatch.setenv("ZOOM_SINGAPORE_JULIO_CONTACT", "julio@example.test")
    posts: list[object] = []

    client = ScopedZoomClient(
        token_provider=lambda: _s2s_token("token-owner"),
        getter=lambda _token, path, _params: (
            {"users": [_sender_user("different-sender")]}
            if path == "/users"
            else pytest.fail(f"unexpected read: {path}")
        ),
        poster=lambda *_args: posts.append(_args),
        team_chat_journal_path=tmp_path / "team-chat.jsonl",
        internal_communication_journal_path=tmp_path / "internal-requests.jsonl",
    )

    with pytest.raises(RuntimeError, match="does not match"):
        client.team_chat_send(
            exact_recipient="configured:julio",
            message="can you check this?",
            authorization_context="Operator-requested internal follow-up",
            idempotency_key="julio-token-owner-mismatch",
            sender_lane="coding_agent",
        )

    assert posts == []


def test_direct_team_chat_adds_first_daily_greeting_and_removes_it_from_followup(
    tmp_path: Path,
    monkeypatch,
) -> None:
    sender_token = _configure_team_chat_sender(monkeypatch)
    monkeypatch.setenv("ZOOM_INTERNAL_REQUEST_WIKO_CONTACT", "wiko@example.test")
    sent: dict[str, str] = {}
    posts: list[dict[str, str]] = []

    def reads(_token, path, _params):
        if path == "/users":
            return {
                "users": [
                    _sender_user(),
                    {
                        "id": "wiko-001",
                        "email": "wiko@example.test",
                        "first_name": "Wiko",
                        "last_name": "Example",
                    }
                ]
            }
        if path.startswith("/chat/users/sender-001/messages/direct-"):
            message_id = path.rsplit("/", 1)[-1]
            return {
                "id": message_id,
                "message": sent[message_id],
                "sender": "darius@novapointofsale.com",
            }
        raise AssertionError(path)

    def post(_token, _path, body):
        message_id = f"direct-{len(posts) + 1}"
        posts.append(body)
        sent[message_id] = body["message"]
        return {"id": message_id}

    client = ScopedZoomClient(
        token_provider=lambda: sender_token,
        getter=reads,
        poster=post,
        team_chat_journal_path=tmp_path / "team-chat.jsonl",
        internal_communication_journal_path=tmp_path / "internal-requests.jsonl",
    )
    common = {
        "exact_recipient": "configured:wiko",
        "authorization_context": "Operator-requested internal follow-up",
        "sender_lane": "tickets_agent",
    }

    first = client.team_chat_send(
        message="Can you check the device?",
        idempotency_key="wiko-request-first-message",
        **common,
    )
    followup = client.team_chat_send(
        message="Hey Wiko, it is the device at the front desk.",
        idempotency_key="wiko-request-followup-message",
        **common,
    )

    assert first["ok"] is True
    assert followup["ok"] is True
    assert [item["message"] for item in posts] == [
        "Hey Wiko, Can you check the device?",
        "it is the device at the front desk.",
    ]


def test_direct_team_chat_serializes_concurrent_identical_requests(
    tmp_path: Path,
    monkeypatch,
) -> None:
    sender_token = _configure_team_chat_sender(monkeypatch)
    monkeypatch.setenv("ZOOM_INTERNAL_REQUEST_WIKO_CONTACT", "wiko@example.test")
    sent: dict[str, str] = {}
    calls = {"posts": 0}
    calls_lock = Lock()
    start = Barrier(2)

    def reads(_token, path, _params):
        if path == "/users":
            return {
                "users": [
                    _sender_user(),
                    {
                        "id": "wiko-001",
                        "email": "wiko@example.test",
                        "first_name": "Wiko",
                        "last_name": "Example",
                    }
                ]
            }
        if path == "/chat/users/sender-001/messages/direct-concurrent":
            return {
                "id": "direct-concurrent",
                "message": sent["message"],
                "sender": "darius@novapointofsale.com",
            }
        raise AssertionError(path)

    def post(_token, _path, body):
        with calls_lock:
            calls["posts"] += 1
            sent.update(body)
        time.sleep(0.05)
        return {"id": "direct-concurrent"}

    client = ScopedZoomClient(
        token_provider=lambda: sender_token,
        getter=reads,
        poster=post,
        team_chat_journal_path=tmp_path / "team-chat.jsonl",
        internal_communication_journal_path=tmp_path / "internal-requests.jsonl",
    )

    def send():
        start.wait()
        return client.team_chat_send(
            exact_recipient="configured:wiko",
            message="can you check the device?",
            authorization_context="Operator-requested internal follow-up",
            idempotency_key="wiko-request-concurrent-message",
            sender_lane="tickets_agent",
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _index: send(), range(2)))

    assert calls["posts"] == 1
    assert sent["message"] == "Hey Wiko, can you check the device?"
    assert all(result["ok"] is True for result in results)
    assert sorted(result["duplicatePrevented"] for result in results) == [
        False,
        True,
    ]
    assert len(
        (tmp_path / "internal-requests.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ) == 1


def test_direct_team_chat_recipient_resolution_fails_closed_on_ambiguous_name(
    tmp_path: Path,
) -> None:
    calls = []

    def reads(_token, path, _params):
        calls.append(path)
        return {"users": []}

    client = ScopedZoomClient(
        token_provider=lambda: "test",
        getter=reads,
        poster=lambda *_args: pytest.fail("ambiguous recipient must never send"),
        team_chat_journal_path=tmp_path / "team-chat.jsonl",
        internal_communication_journal_path=tmp_path / "internal-requests.jsonl",
    )

    result = client.team_chat_recipient_resolve(exact_recipient="Julio Example")

    assert result["ok"] is False
    assert result["status"] == "blocked"
    assert calls == []


def test_direct_team_chat_uncertain_send_is_reconciled_without_blind_retry(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls = {"posts": 0}
    sender_token = _configure_team_chat_sender(monkeypatch)
    monkeypatch.setenv("ZOOM_SINGAPORE_JULIO_CONTACT", "julio@example.test")

    def reads(_token, path, _params):
        if path == "/users":
            return {
                "users": [
                    _sender_user(),
                    {
                        "id": "u1",
                        "email": "julio@example.test",
                        "first_name": "Julio",
                        "last_name": "Example",
                    }
                ]
            }
        if path == "/chat/users/sender-001/messages":
            return {"messages": []}
        raise AssertionError(path)

    def fail_post(*_args):
        calls["posts"] += 1
        raise RuntimeError("simulated timeout")

    client = ScopedZoomClient(
        token_provider=lambda: sender_token,
        getter=reads,
        poster=fail_post,
        team_chat_journal_path=tmp_path / "team-chat.jsonl",
        internal_communication_journal_path=tmp_path / "internal-requests.jsonl",
    )
    kwargs = {
        "exact_recipient": "configured:julio",
        "message": "Hey Julio, please reset the company password for Example Account.",
        "authorization_context": "Operator request for ticket 347375",
        "idempotency_key": "zoom-ticket-347375-uncertain",
        "sender_lane": "coding_agent",
    }

    first = client.team_chat_send(**kwargs)
    second = client.team_chat_send(**kwargs)

    assert first["status"] == "uncertain"
    assert first["retryAllowed"] is False
    assert second["status"] == "uncertain"
    assert second["retryAllowed"] is False
    assert calls["posts"] == 1


def test_direct_team_chat_idempotency_key_cannot_be_rebound(
    tmp_path: Path,
    monkeypatch,
) -> None:
    sent_body: dict[str, str] = {}
    sender_token = _configure_team_chat_sender(monkeypatch)
    monkeypatch.setenv("ZOOM_SINGAPORE_JULIO_CONTACT", "julio@example.test")

    def reads(_token, path, _params):
        if path == "/users":
            return {
                "users": [
                    _sender_user(),
                    {
                        "id": "u1",
                        "email": "julio@example.test",
                        "first_name": "Julio",
                        "last_name": "Example",
                    }
                ]
            }
        if path == "/chat/users/sender-001/messages/direct-002":
            return {
                "id": "direct-002",
                "message": sent_body["message"],
                "sender": "darius@novapointofsale.com",
            }
        raise AssertionError(path)

    def post(_token, _path, body):
        sent_body.update(body)
        return {"id": "direct-002"}

    client = ScopedZoomClient(
        token_provider=lambda: sender_token,
        getter=reads,
        poster=post,
        team_chat_journal_path=tmp_path / "team-chat.jsonl",
        internal_communication_journal_path=tmp_path / "internal-requests.jsonl",
    )
    common = {
        "exact_recipient": "configured:julio",
        "authorization_context": "Operator request for ticket 347375",
        "idempotency_key": "zoom-ticket-347375-rebound",
        "sender_lane": "coding_agent",
    }
    first = client.team_chat_send(message="Hey Julio, original message.", **common)
    rebound = client.team_chat_send(message="Hey Julio, different message.", **common)

    assert first["ok"] is True
    assert rebound["ok"] is False
    assert rebound["status"] == "blocked"
    assert rebound["duplicatePrevented"] is True


def test_find_exact_messages_falls_back_to_per_day_when_range_is_clamped():
    """The Zoom list endpoint only honors a bounded recent window (~24h) and
    echoes the clamped window. Reconciliation of an older pending send must
    fall back to the per-day endpoint instead of returning uncertain."""
    from datetime import date, datetime, timedelta, timezone

    target_date = date(2026, 9, 14)
    target_id = "c5ed792d-e071-407f-b062-c8e72c4ff696"
    body = "Hey Julio, can you please resubmit these Singapore integrations?"
    seen_params = []

    def fake_getter(token, path, params):
        assert path.endswith("/messages")
        seen_params.append(dict(params))
        if "date" in params:
            if params["date"] == target_date.isoformat():
                return {
                    "date": target_date.isoformat(),
                    "page_size": "100",
                    "next_page_token": "",
                    "messages": [
                        {
                            "id": target_id,
                            "message": body,
                            "reply_main_message_id": "",
                        }
                    ],
                }
            return {"date": params["date"], "page_size": "100", "next_page_token": "", "messages": []}
        # Range query: Zoom clamps the window to the last 24h and echoes it.
        return {
            "from": "2026-10-10T13:48:39Z",
            "to": "2026-10-11T13:48:39Z",
            "page_size": "100",
            "next_page_token": "",
            "messages": [],
        }

    client = ScopedZoomClient(
        token_provider=lambda: "test",
        getter=fake_getter,
    )
    matches = client._find_exact_team_chat_messages(
        "token",
        sender="sender-001",
        recipient_email="julio@example.test",
        body=body,
        from_date=target_date,
        reply_main_message_id="",
    )
    assert matches == [target_id]
    # The per-day fallback must scan forward from the pending date and stop
    # at the first matching day.
    day_queries = [p for p in seen_params if "date" in p]
    assert day_queries
    assert day_queries[0]["date"] == target_date.isoformat()
    assert [p["date"] for p in day_queries] == [target_date.isoformat()]
    assert all(p["to_contact"] == "julio@example.test" for p in day_queries)


def test_find_exact_messages_no_fallback_when_range_honored():
    """When the list endpoint honors the requested span (echoed from date
    matches the request) there is no per-day fallback."""
    from datetime import date, datetime, timedelta, timezone

    target_date = date(2026, 10, 11)
    target_id = "0123abcd-1111-4111-8111-111111111111"
    body = "resubmit tenants"
    seen_params = []

    def fake_getter(token, path, params):
        seen_params.append(dict(params))
        assert "date" not in params
        return {
            "from": target_date.isoformat(),
            "to": datetime.now(timezone.utc).date().isoformat(),
            "page_size": "100",
            "next_page_token": "",
            "messages": [
                {"id": target_id, "message": body, "reply_main_message_id": ""}
            ],
        }

    client = ScopedZoomClient(token_provider=lambda: "test", getter=fake_getter)
    matches = client._find_exact_team_chat_messages(
        "token",
        sender="sender-001",
        recipient_email="julio@example.test",
        body=body,
        from_date=target_date,
        reply_main_message_id="",
    )
    assert matches == [target_id]
    assert all("date" not in p for p in seen_params)
