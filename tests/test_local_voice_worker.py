from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace


def _worker_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "local-voice-worker.py"
    spec = importlib.util.spec_from_file_location("local_voice_worker_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _worker_env(tmp_path, monkeypatch) -> None:
    whisper = tmp_path / "whisper"
    whisper.mkdir()
    kokoro = tmp_path / "kokoro.onnx"
    voices = tmp_path / "voices.bin"
    kokoro.write_bytes(b"stub")
    voices.write_bytes(b"stub")
    monkeypatch.setenv("LOCAL_VOICE_TOKEN", "x" * 32)
    monkeypatch.setenv("LOCAL_VOICE_WHISPER_MODEL", str(whisper))
    monkeypatch.setenv("LOCAL_VOICE_KOKORO_MODEL", str(kokoro))
    monkeypatch.setenv("LOCAL_VOICE_KOKORO_VOICES", str(voices))


def test_cuda_whisper_falls_back_to_cpu_int8(tmp_path, monkeypatch) -> None:
    module = _worker_module()
    _worker_env(tmp_path, monkeypatch)
    monkeypatch.setenv("LOCAL_VOICE_WHISPER_DEVICE", "cuda")
    monkeypatch.setenv("LOCAL_VOICE_WHISPER_COMPUTE_TYPE", "float16")
    monkeypatch.setenv("LOCAL_VOICE_WHISPER_CPU_FALLBACK", "1")
    calls = []

    class FakeWhisperModel:
        def __init__(self, _path, **kwargs):
            calls.append(kwargs)
            if kwargs["device"] == "cuda":
                raise RuntimeError("CUDA unavailable")

    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=FakeWhisperModel))
    state = module.WorkerState()

    model = state.get_whisper()

    assert isinstance(model, FakeWhisperModel)
    assert [(item["device"], item["compute_type"]) for item in calls] == [
        ("cuda", "float16"),
        ("cpu", "int8"),
    ]
    assert state.whisper_active_device == "cpu"
    assert state.whisper_active_compute_type == "int8"
    assert state.whisper_fallback_used is True


def test_cuda_whisper_stays_on_gpu_when_initialization_succeeds(tmp_path, monkeypatch) -> None:
    module = _worker_module()
    _worker_env(tmp_path, monkeypatch)
    monkeypatch.setenv("LOCAL_VOICE_WHISPER_DEVICE", "cuda")
    monkeypatch.setenv("LOCAL_VOICE_WHISPER_COMPUTE_TYPE", "float16")
    calls = []

    class FakeWhisperModel:
        def __init__(self, _path, **kwargs):
            calls.append(kwargs)

    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=FakeWhisperModel))
    state = module.WorkerState()

    state.get_whisper()

    assert [(item["device"], item["compute_type"]) for item in calls] == [("cuda", "float16")]
    assert state.whisper_active_device == "cuda"
    assert state.whisper_active_compute_type == "float16"
    assert state.whisper_fallback_used is False
