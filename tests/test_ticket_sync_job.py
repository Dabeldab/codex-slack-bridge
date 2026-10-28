from __future__ import annotations

import json

from codex_slack_bridge import ticket_sync_job


def test_ticket_sync_job_runs_deterministic_refresh_and_shuts_down(monkeypatch, capsys):
    events = []

    class _Runtime:
        def __init__(self, config_path):
            events.append(("init", str(config_path)))

        def refresh_ticket_board_deterministic(self):
            events.append(("refresh",))
            return {
                "ok": True,
                "status": "ok",
                "total": 8,
                "source": "deterministic_refresh",
                "deterministic": True,
                "firestore": {"ok": True, "written": 8},
            }

        def run_ticket_recon_batch(self):
            events.append(("recon",))
            return {
                "ok": True,
                "enabled": True,
                "considered": 2,
                "claimed": 1,
                "completed": 1,
                "needsAttention": 0,
                "failed": 0,
            }

        def shutdown(self):
            events.append(("shutdown",))

    monkeypatch.setattr(ticket_sync_job, "CommandCenterRuntime", _Runtime)
    monkeypatch.setattr(ticket_sync_job, "_stage_codex_auth", lambda: events.append(("auth",)))
    monkeypatch.setenv("BRIDGE_CONFIG", "config/test.yaml")

    ticket_sync_job.main()

    output = json.loads(capsys.readouterr().out)
    assert output["total"] == 8
    assert output["firestore"] == {"ok": True, "written": 8}
    assert output["recon"]["completed"] == 1
    assert events[0] == ("auth",)
    assert events[1][0] == "init"
    assert events[1][1].replace("\\", "/") == "config/test.yaml"
    assert events[2:] == [("refresh",), ("recon",), ("shutdown",)]
