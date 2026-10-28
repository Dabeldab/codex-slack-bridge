from __future__ import annotations

import json
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from threading import Condition, Lock, Thread
from types import SimpleNamespace

from codex_slack_bridge.command_center_server import (
    CommandCenterRuntime,
    _command_center_authority_kind,
    _payload_idempotency_key,
    _read_direct_agent_chat_events,
    build_voice_direct_agent_chat_prompt,
    make_handler,
)


class _FakeLocalVoiceRoom:
    def status(self):
        return {"ok": True, "enabled": True, "ready": True, "provider": "local"}

    def transcribe(self, audio: bytes):
        assert audio == b"RIFF-local-test"
        return {"ok": True, "transcript": "Ask Alex to review the logs."}

    def warmup(self):
        return {"ok": True, "whisperLoaded": True, "kokoroLoaded": True, "whisperActiveDevice": "cuda"}

    def synthesize(self, text: str, voice: str):
        assert text == "Ready."
        assert voice == "af_heart"
        return b"RIFF-local-audio"


def _serve_fake_runtime():
    runtime = SimpleNamespace(local_voice_room=_FakeLocalVoiceRoom())
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(runtime))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, f"http://127.0.0.1:{server.server_address[1]}"


def test_local_voice_http_status_transcription_and_synthesis():
    server, thread, base_url = _serve_fake_runtime()
    try:
        status = json.loads(urllib.request.urlopen(f"{base_url}/voice/local/status", timeout=2).read())
        assert status["provider"] == "local"
        transcribe_request = urllib.request.Request(
            f"{base_url}/voice/local/transcribe",
            data=b"RIFF-local-test",
            method="POST",
            headers={"Content-Type": "audio/wav"},
        )
        transcript = json.loads(urllib.request.urlopen(transcribe_request, timeout=2).read())
        assert transcript["transcript"] == "Ask Alex to review the logs."

        warmup_request = urllib.request.Request(f"{base_url}/voice/local/warmup", data=b"{}", method="POST")
        warmup = json.loads(urllib.request.urlopen(warmup_request, timeout=2).read())
        assert warmup["whisperLoaded"] is True

        synth_request = urllib.request.Request(
            f"{base_url}/voice/local/synthesize",
            data=json.dumps({"text": "Ready.", "voice": "af_heart"}).encode(),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(synth_request, timeout=2) as response:
            assert response.headers.get_content_type() == "audio/wav"
            assert response.headers["Cache-Control"] == "no-store"
            assert response.read() == b"RIFF-local-audio"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_local_voice_transcription_rejects_non_wav_content_type():
    server, thread, base_url = _serve_fake_runtime()
    try:
        request = urllib.request.Request(
            f"{base_url}/voice/local/transcribe",
            data=b"not-wav",
            method="POST",
            headers={"Content-Type": "application/octet-stream"},
        )
        try:
            urllib.request.urlopen(request, timeout=2)
            raise AssertionError("request should fail")
        except urllib.error.HTTPError as exc:
            assert exc.code == 415
            assert "audio/wav" in exc.read().decode()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_wait_for_job_change_returns_immediately_on_revision_change(tmp_path):
    runtime = object.__new__(CommandCenterRuntime)
    runtime._lock = Lock()
    runtime._job_changed = Condition(runtime._lock)
    runtime._jobs = {"voice-job": {"id": "voice-job", "status": "running", "updatedAtUtc": "new"}}
    runtime.jobs_dir = tmp_path

    record = runtime.wait_for_job_change("voice-job", updated_at="old", timeout_seconds=1)

    assert record["status"] == "running"
    assert record["updatedAtUtc"] == "new"


def test_voice_transcript_routes_to_non_authoritative_distinct_source():
    runtime = object.__new__(CommandCenterRuntime)
    runtime.config = SimpleNamespace(agents={"tickets_agent": {}})
    captured = {}

    def fake_submit_prompt(**kwargs):
        captured.update(kwargs)
        return {"accepted": True, "job_id": "job-local-voice"}

    runtime.submit_prompt = fake_submit_prompt
    response = runtime.submit_direct_chat(
        {
            "source": "voice-room-local",
            "agent": "alex",
            "agentLabel": "Alex",
            "message": "Send the customer an email now.",
            "idempotencyKey": "voice-turn-123",
        }
    )

    assert response["accepted"] is True
    assert captured["source_type"] == "voice-direct-chat"
    assert captured["payload"]["type"] == "voice-direct-chat"
    assert _command_center_authority_kind("voice-direct-chat") == "automation"
    assert _command_center_authority_kind("agent-direct-chat") == "operator"
    assert "not typed operator authorization" in captured["prompt"]
    assert "typed confirmation" in captured["prompt"]
    assert "Do not perform or authorize any live write" in captured["prompt"]


def test_voice_direct_chat_keeps_idempotency_and_concise_spoken_prompt():
    payload = {
        "source": "voice-room-local",
        "agentName": "tickets_agent",
        "message": "Summarize ticket 123 read-only.",
        "idempotencyKey": "voice-turn-456",
    }
    prompt = build_voice_direct_agent_chat_prompt(payload)

    assert _payload_idempotency_key("voice-direct-chat", "tickets_agent", prompt, payload) == "voice-turn-456"
    assert "read-only research" in prompt
    assert "response will be spoken aloud" in prompt


def test_voice_direct_chat_is_visible_in_agent_chat_history(tmp_path):
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir()
    (jobs_dir / "voice-job.json").write_text(
        json.dumps({"id": "voice-job", "sourceType": "voice-direct-chat", "payload": {"type": "voice-direct-chat"}}),
        encoding="utf-8",
    )
    chat_path = tmp_path / "events.jsonl"
    chat_path.write_text(
        json.dumps(
            {
                "source": "command_center",
                "agentName": "tickets_agent",
                "role": "assistant",
                "text": "I found the read-only ticket details.",
                "threadTs": "voice-job",
            }
        ),
        encoding="utf-8",
    )

    events = _read_direct_agent_chat_events(
        path=chat_path,
        jobs_dir=jobs_dir,
        agent_name="tickets_agent",
        limit=20,
    )

    assert [event["text"] for event in events] == ["I found the read-only ticket details."]
    assert events[0]["sourceType"] == "voice-direct-chat"
