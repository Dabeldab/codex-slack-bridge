# AgentChat/coding_agent 2026-07-09T00:52:46Z
# AgentChat/coding_agent 2026-07-11T14:04:00-04:00
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from codex_slack_bridge import app
from codex_slack_bridge.config import BridgeConfig, ChannelRoute
from codex_slack_bridge.state import BridgeState


class FakeSlackClient:
    def __init__(self) -> None:
        self.posts: list[dict[str, object]] = []
        self.updates: list[dict[str, object]] = []

    def chat_postMessage(self, *, channel: str, text: str, **kwargs: object) -> dict[str, str]:
        ts = f"1.{len(self.posts) + 1:06d}"
        self.posts.append({"channel": channel, "text": text, "ts": ts, **kwargs})
        return {"ts": ts}

    def chat_update(self, *, channel: str, ts: str, text: str) -> dict[str, str]:
        self.updates.append({"channel": channel, "text": text, "ts": ts})
        return {"ts": ts}


class DesktopSlackMirrorTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_state = app.STATE
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.events_path = self.root / "events.jsonl"
        app.STATE = BridgeState(str(self.root / "bridge.sqlite3"))

    def tearDown(self) -> None:
        app.STATE = self._old_state
        self._tmp.cleanup()

    def _config(self, **defaults: object) -> BridgeConfig:
        base_defaults: dict[str, object] = {
            "shared_chat_log_path": str(self.events_path),
            "max_slack_message_chars": 3900,
            "desktop_slack_mirror_roles": ["user", "assistant"],
            "desktop_slack_mirror_max_events_per_pass": 25,
            "desktop_slack_mirror_scan_lines": 1000,
        }
        base_defaults.update(defaults)
        return BridgeConfig(
            defaults=base_defaults,
            channels={
                "C123": ChannelRoute(
                    channel_id="C123",
                    agent_name="coding_agent",
                    listen="all_messages",
                )
            },
            agents={"coding_agent": {}},
        )

    def _append_event(self, **fields: object) -> None:
        self.events_path.parent.mkdir(parents=True, exist_ok=True)
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(fields, separators=(",", ":")) + "\n")

    def test_mirrors_desktop_events_once(self) -> None:
        self._append_event(
            id="event-1",
            atUtc="2026-07-09T00:55:00+00:00",
            source="desktop",
            agentName="coding_agent",
            role="assistant",
            text="Done from desktop.",
        )
        client = FakeSlackClient()
        config = self._config()

        first_count = app._mirror_desktop_chat_once(client, config, oldest_allowed_at=0)
        second_count = app._mirror_desktop_chat_once(client, config, oldest_allowed_at=0)

        self.assertEqual(first_count, 1)
        self.assertEqual(second_count, 0)
        self.assertEqual(len(client.posts), 1)
        self.assertEqual(client.posts[0]["channel"], "C123")
        self.assertIn("Agent Chat desktop assistant", client.posts[0]["text"])
        self.assertIn("Done from desktop.", client.posts[0]["text"])

    def test_mirrors_command_center_events_once(self) -> None:
        self._append_event(
            id="event-1",
            atUtc="2026-07-09T00:55:00+00:00",
            source="command_center",
            agentName="coding_agent",
            role="assistant",
            text="Done from command center.",
        )
        client = FakeSlackClient()
        config = self._config()

        first_count = app._mirror_desktop_chat_once(client, config, oldest_allowed_at=0)
        second_count = app._mirror_desktop_chat_once(client, config, oldest_allowed_at=0)

        self.assertEqual(first_count, 1)
        self.assertEqual(second_count, 0)
        self.assertEqual(len(client.posts), 1)
        self.assertEqual(client.posts[0]["channel"], "C123")
        self.assertIn("Command Center assistant", client.posts[0]["text"])
        self.assertIn("Done from command center.", client.posts[0]["text"])

    def test_internal_failure_events_are_consumed_without_slack_broadcast(self) -> None:
        self._append_event(
            id="failure-event",
            atUtc="2026-07-13T19:30:00+00:00",
            source="command_center",
            agentName="coding_agent",
            role="assistant",
            text="BLOCKED\nInternal credential path is unavailable.",
        )
        client = FakeSlackClient()
        config = self._config()

        self.assertEqual(app._mirror_desktop_chat_once(client, config, oldest_allowed_at=0), 0)
        self.assertEqual(app._mirror_desktop_chat_once(client, config, oldest_allowed_at=0), 0)
        self.assertEqual(client.posts, [])
        self.assertTrue(app.STATE.has_desktop_slack_mirror("failure-event"))

    def test_skips_slack_source_and_disallowed_role(self) -> None:
        self._append_event(
            id="event-1",
            atUtc="2026-07-09T00:55:00+00:00",
            source="slack",
            agentName="coding_agent",
            role="assistant",
            text="Already in Slack.",
        )
        self._append_event(
            id="event-2",
            atUtc="2026-07-09T00:55:01+00:00",
            source="desktop",
            agentName="coding_agent",
            role="system",
            text="Do not mirror this role.",
        )
        client = FakeSlackClient()
        config = self._config(desktop_slack_mirror_roles=["assistant"])

        count = app._mirror_desktop_chat_once(client, config, oldest_allowed_at=0)

        self.assertEqual(count, 0)
        self.assertEqual(client.posts, [])

    def test_startup_cutoff_prevents_historical_replay(self) -> None:
        self._append_event(
            id="event-1",
            atUtc="2026-07-09T00:55:00+00:00",
            source="desktop",
            agentName="coding_agent",
            role="user",
            text="Old desktop prompt.",
        )
        client = FakeSlackClient()
        config = self._config()

        count = app._mirror_desktop_chat_once(client, config, oldest_allowed_at=9999999999)

        self.assertEqual(count, 0)
        self.assertEqual(client.posts, [])

    def test_restart_lookback_replays_unmirrored_gap_once(self) -> None:
        self._append_event(
            id="event-during-restart",
            atUtc="2026-07-11T17:59:00+00:00",
            source="command_center",
            agentName="coding_agent",
            role="user",
            text="Message written while Slack bridge was restarting.",
        )
        client = FakeSlackClient()
        config = self._config(desktop_slack_mirror_startup_lookback_seconds=86400)
        restarted_at = 1783792800.0  # 2026-07-11T20:00:00Z
        cutoff = restarted_at - float(config.defaults["desktop_slack_mirror_startup_lookback_seconds"])

        self.assertEqual(app._mirror_desktop_chat_once(client, config, oldest_allowed_at=cutoff), 1)
        self.assertEqual(app._mirror_desktop_chat_once(client, config, oldest_allowed_at=cutoff), 0)
        self.assertEqual(len(client.posts), 1)

    def test_thor_mirror_uses_only_public_name(self) -> None:
        formatted = app._format_desktop_slack_mirror_text(
            {
                "source": "desktop",
                "agentName": "claude_agent",
                "role": "assistant",
                "text": "Claude Agent completed the claude_agent run.",
            }
        )

        self.assertIn("Thor", formatted)
        self.assertNotIn("Claude Agent", formatted)
        self.assertNotIn("claude_agent", formatted)

    def test_thor_progress_and_final_feedback_use_only_public_name(self) -> None:
        client = FakeSlackClient()
        config = self._config(reply_in_thread=False)
        memories = [
            {
                "id": "memory-1",
                "source": "Claude Agent",
                "text": "claude_agent retained this internal route.",
            }
        ]
        original_memories = copy.deepcopy(memories)

        progress = app._progress_text("claude_agent", "U123", 42, 0)
        app._deliver_slack_job_feedback(
            config,
            client,
            job_id=None,
            agent_name="claude_agent",
            channel_id="C123",
            thread_ts="",
            user_id="U123",
            result="COMPLETED\nClaude Agent completed the claude_agent run.",
            max_chars=3900,
            progress_ts=None,
        )
        memory_results = app._format_memory_results("claude_agent", memories)

        for rendered in (progress, str(client.posts[0]["text"]), memory_results):
            self.assertIn("Thor", rendered)
            self.assertNotIn("Claude Agent", rendered)
            self.assertNotIn("claude_agent", rendered)
        self.assertEqual(memories, original_memories)


if __name__ == "__main__":
    unittest.main()
