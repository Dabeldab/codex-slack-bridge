from __future__ import annotations

import io
import json
import wave

import pytest

from codex_slack_bridge.local_voice_room import (
    ALLOWED_LOCAL_VOICES,
    LocalVoiceRoomError,
    LocalVoiceRoomGateway,
)


def _wav(seconds: float = 0.1, rate: int = 16_000) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as recording:
        recording.setnchannels(1)
        recording.setsampwidth(2)
        recording.setframerate(rate)
        recording.writeframes(b"\0\0" * int(seconds * rate))
    return output.getvalue()


def _ready_gateway(tmp_path) -> LocalVoiceRoomGateway:
    runtime = tmp_path / "runtime-python.exe"
    script = tmp_path / "local-voice-worker.py"
    whisper = tmp_path / "whisper"
    kokoro = tmp_path / "kokoro.onnx"
    voices = tmp_path / "voices.bin"
    runtime.write_bytes(b"stub")
    script.write_text("# stub", encoding="utf-8")
    whisper.mkdir()
    for name in ("config.json", "model.bin", "tokenizer.json", "vocabulary.txt"):
        (whisper / name).write_bytes(b"stub")
    kokoro.write_bytes(b"stub")
    voices.write_bytes(b"stub")
    return LocalVoiceRoomGateway(True, tmp_path, runtime, script, whisper, kokoro, voices)


def test_status_is_local_and_never_claims_network_fallback(tmp_path) -> None:
    gateway = _ready_gateway(tmp_path)

    status = gateway.status()

    assert status["ready"] is True
    assert status["provider"] == "local"
    assert status["speechToTextDevice"] == "cpu-int8"
    assert status["allowedVoices"] == list(ALLOWED_LOCAL_VOICES)
    assert status["networkFallbackAllowed"] is False
    assert "token" not in json.dumps(status).lower()


def test_transcribe_validates_wav_then_uses_mocked_private_worker(tmp_path, monkeypatch) -> None:
    gateway = _ready_gateway(tmp_path)
    captured = {}

    def fake_request(path, data, content_type, **kwargs):
        captured.update(path=path, data=data, content_type=content_type, kwargs=kwargs)
        return b'{"ok":true,"text":"hello there","language":"en","segments":[]}', "application/json"

    monkeypatch.setattr(gateway, "_request", fake_request)

    result = gateway.transcribe(_wav())

    assert result["text"] == "hello there"
    assert captured["path"] == "/transcribe"
    assert captured["content_type"] == "audio/wav"


def test_warmup_loads_both_private_models_and_reports_device(tmp_path, monkeypatch) -> None:
    gateway = _ready_gateway(tmp_path)
    monkeypatch.setattr(gateway, "_request", lambda *args, **kwargs: (
        b'{"ok":true,"whisperLoaded":true,"kokoroLoaded":true,"whisperActiveDevice":"cuda"}',
        "application/json",
    ))
    result = gateway.warmup()
    assert result["whisperActiveDevice"] == "cuda"
    assert result["gatewayWarmupMs"] >= 0


def test_transcribe_rejects_non_wav_before_starting_worker(tmp_path, monkeypatch) -> None:
    gateway = _ready_gateway(tmp_path)
    monkeypatch.setattr(gateway, "_request", lambda *_args, **_kwargs: pytest.fail("worker called"))

    with pytest.raises(LocalVoiceRoomError) as caught:
        gateway.transcribe(b"not-a-wave")

    assert caught.value.status == 400


def test_synthesize_allows_only_curated_voices_and_validates_mocked_wav(tmp_path, monkeypatch) -> None:
    gateway = _ready_gateway(tmp_path)

    def fake_request(path, data, content_type, **_kwargs):
        assert path == "/synthesize"
        assert content_type == "application/json"
        assert json.loads(data) == {"text": "Good morning", "voice": "af_bella"}
        return _wav(), "audio/wav"

    monkeypatch.setattr(gateway, "_request", fake_request)

    assert gateway.synthesize("Good morning", "af_bella").startswith(b"RIFF")

    with pytest.raises(LocalVoiceRoomError) as caught:
        gateway.synthesize("Good morning", "unknown")
    assert caught.value.status == 400


def test_gateway_fails_closed_when_runtime_is_missing(tmp_path) -> None:
    gateway = LocalVoiceRoomGateway(
        True,
        tmp_path,
        "missing-python.exe",
        "missing-worker.py",
        "missing-whisper",
        "missing-kokoro.onnx",
        "missing-voices.bin",
    )

    assert gateway.status()["ready"] is False
    with pytest.raises(LocalVoiceRoomError) as caught:
        gateway.transcribe(_wav())
    assert caught.value.status == 503
    assert "incomplete" in str(caught.value)


def test_gateway_clamps_threads_and_falls_back_to_safe_default_voice(tmp_path) -> None:
    gateway = _ready_gateway(tmp_path)
    gateway = LocalVoiceRoomGateway(
        True,
        tmp_path,
        gateway.runtime_python_path,
        gateway.worker_script_path,
        gateway.whisper_model_path,
        gateway.kokoro_model_path,
        gateway.kokoro_voices_path,
        default_voice="not-a-voice",
        whisper_threads=999,
    )

    assert gateway.default_voice == "af_heart"
    assert gateway.whisper_threads == 16


def test_gateway_reports_configured_cuda_with_local_cpu_fallback(tmp_path) -> None:
    ready = _ready_gateway(tmp_path)
    gateway = LocalVoiceRoomGateway(
        True,
        tmp_path,
        ready.runtime_python_path,
        ready.worker_script_path,
        ready.whisper_model_path,
        ready.kokoro_model_path,
        ready.kokoro_voices_path,
        whisper_device="cuda",
        whisper_compute_type="float16",
        whisper_cpu_fallback=True,
        whisper_cpu_compute_type="int8",
    )

    status = gateway.status()

    assert status["speechToTextDevice"] == "cuda-float16"
    assert status["speechToTextCpuFallbackEnabled"] is True
    assert status["speechToTextCpuFallbackDevice"] == "cpu-int8"
