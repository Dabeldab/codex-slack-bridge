from __future__ import annotations

import hmac
import io
import json
import os
import threading
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
import time


ALLOWED_VOICES = ("af_heart", "af_bella", "af_nicole", "bf_emma")
MAX_WAV_BYTES = 8 * 1024 * 1024
MAX_WAV_SECONDS = 30.0
MAX_TEXT_CHARS = 2_000
MAX_JSON_BYTES = 16 * 1024
MAX_TTS_SECONDS = 120


class WorkerState:
    def __init__(self) -> None:
        self.token = _required_env("LOCAL_VOICE_TOKEN")
        if len(self.token) < 32:
            raise RuntimeError("LOCAL_VOICE_TOKEN is too short")
        self.whisper_path = _required_path("LOCAL_VOICE_WHISPER_MODEL", directory=True)
        self.kokoro_path = _required_path("LOCAL_VOICE_KOKORO_MODEL")
        self.voices_path = _required_path("LOCAL_VOICE_KOKORO_VOICES")
        self.whisper_threads = max(1, min(int(os.environ.get("LOCAL_VOICE_WHISPER_THREADS", "8")), 16))
        requested_device = os.environ.get("LOCAL_VOICE_WHISPER_DEVICE", "cpu").strip().lower()
        self.whisper_device = requested_device if requested_device in {"cpu", "cuda"} else "cpu"
        default_compute_type = "float16" if self.whisper_device == "cuda" else "int8"
        self.whisper_compute_type = (
            os.environ.get("LOCAL_VOICE_WHISPER_COMPUTE_TYPE", default_compute_type).strip().lower()
            or default_compute_type
        )
        self.whisper_cpu_fallback = _truthy_env("LOCAL_VOICE_WHISPER_CPU_FALLBACK", True)
        self.whisper_cpu_compute_type = (
            os.environ.get("LOCAL_VOICE_WHISPER_CPU_COMPUTE_TYPE", "int8").strip().lower() or "int8"
        )
        self.whisper_active_device: str | None = None
        self.whisper_active_compute_type: str | None = None
        self.whisper_fallback_used = False
        self.whisper: Any = None
        self.kokoro: Any = None
        self.model_lock = threading.Lock()
        self.operation_lock = threading.Lock()

    def get_whisper(self) -> Any:
        with self.model_lock:
            if self.whisper is None:
                from faster_whisper import WhisperModel

                try:
                    self.whisper = self._load_whisper(
                        WhisperModel,
                        device=self.whisper_device,
                        compute_type=self.whisper_compute_type,
                    )
                    self.whisper_active_device = self.whisper_device
                    self.whisper_active_compute_type = self.whisper_compute_type
                except Exception:
                    if self.whisper_device != "cuda" or not self.whisper_cpu_fallback:
                        raise
                    self.whisper = self._load_whisper(
                        WhisperModel,
                        device="cpu",
                        compute_type=self.whisper_cpu_compute_type,
                    )
                    self.whisper_active_device = "cpu"
                    self.whisper_active_compute_type = self.whisper_cpu_compute_type
                    self.whisper_fallback_used = True
            return self.whisper

    def _load_whisper(self, model_type: Any, *, device: str, compute_type: str) -> Any:
        return model_type(
            str(self.whisper_path),
            device=device,
            compute_type=compute_type,
            cpu_threads=self.whisper_threads,
            num_workers=1,
            local_files_only=True,
        )

    def get_kokoro(self) -> Any:
        with self.model_lock:
            if self.kokoro is None:
                from kokoro_onnx import Kokoro

                self.kokoro = Kokoro(str(self.kokoro_path), str(self.voices_path))
            return self.kokoro


def make_handler(state: WorkerState):
    class Handler(BaseHTTPRequestHandler):
        server_version = "LocalVoiceWorker/1"
        sys_version = ""

        def log_message(self, _format: str, *_args: object) -> None:
            return

        def do_GET(self) -> None:
            if not self._authorized():
                return
            if self.path != "/health":
                self._error(404, "Not found.")
                return
            self._json(
                200,
                {
                    "ok": True,
                    "whisperLoaded": state.whisper is not None,
                    "whisperRequestedDevice": state.whisper_device,
                    "whisperRequestedComputeType": state.whisper_compute_type,
                    "whisperActiveDevice": state.whisper_active_device,
                    "whisperActiveComputeType": state.whisper_active_compute_type,
                    "whisperCpuFallbackEnabled": state.whisper_cpu_fallback,
                    "whisperFallbackUsed": state.whisper_fallback_used,
                    "kokoroLoaded": state.kokoro is not None,
                    "networkFallbackAllowed": False,
                },
            )

        def do_POST(self) -> None:
            if not self._authorized():
                return
            if self.path == "/shutdown":
                self._json(200, {"ok": True})
                threading.Thread(target=self.server.shutdown, name="local-voice-shutdown", daemon=True).start()
                return
            if self.path not in {"/warmup", "/transcribe", "/synthesize"}:
                self._error(404, "Not found.")
                return
            if not state.operation_lock.acquire(blocking=False):
                self._error(429, "Local Voice Room is busy.")
                return
            try:
                if self.path == "/warmup":
                    started = time.perf_counter()
                    state.get_whisper()
                    state.get_kokoro()
                    self._json(200, {
                        "ok": True,
                        "whisperLoaded": True,
                        "kokoroLoaded": True,
                        "whisperActiveDevice": state.whisper_active_device,
                        "whisperActiveComputeType": state.whisper_active_compute_type,
                        "whisperFallbackUsed": state.whisper_fallback_used,
                        "warmupMs": round((time.perf_counter() - started) * 1000),
                    })
                elif self.path == "/transcribe":
                    self._transcribe()
                else:
                    self._synthesize()
            except Exception:
                self._error(500, "Local inference failed. Check the installed runtime and model files.")
            finally:
                state.operation_lock.release()

        def _transcribe(self) -> None:
            if self.headers.get_content_type() != "audio/wav":
                self._error(415, "Content-Type must be audio/wav.")
                return
            audio = self._read_body(MAX_WAV_BYTES)
            if audio is None:
                return
            message = _wav_error(audio, MAX_WAV_SECONDS)
            if message:
                self._error(400, message)
                return
            model = state.get_whisper()
            segments_iter, info = model.transcribe(
                io.BytesIO(audio),
                language="en",
                beam_size=1,
                best_of=1,
                temperature=0.0,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 400},
                condition_on_previous_text=False,
            )
            segments = []
            transcript_parts = []
            for segment in segments_iter:
                text = str(segment.text).strip()
                if text:
                    transcript_parts.append(text)
                    if len(segments) < 100:
                        segments.append(
                            {"start": round(float(segment.start), 3), "end": round(float(segment.end), 3), "text": text}
                        )
            transcript = " ".join(transcript_parts).strip()[:16_000]
            self._json(
                200,
                {
                    "ok": True,
                    "text": transcript,
                    "language": str(getattr(info, "language", "en")),
                    "duration": round(float(getattr(info, "duration", 0.0)), 3),
                    "segments": segments,
                    "device": state.whisper_active_device,
                    "computeType": state.whisper_active_compute_type,
                    "cpuFallbackUsed": state.whisper_fallback_used,
                },
            )

        def _synthesize(self) -> None:
            if self.headers.get_content_type() != "application/json":
                self._error(415, "Content-Type must be application/json.")
                return
            body = self._read_body(MAX_JSON_BYTES)
            if body is None:
                return
            try:
                payload = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._error(400, "A valid JSON body is required.")
                return
            text = str(payload.get("text", "")).strip() if isinstance(payload, dict) else ""
            voice = str(payload.get("voice", "")).strip().lower() if isinstance(payload, dict) else ""
            if not text or len(text) > MAX_TEXT_CHARS:
                self._error(400, f"Text must contain 1 to {MAX_TEXT_CHARS} characters.")
                return
            if voice not in ALLOWED_VOICES:
                self._error(400, f"Voice must be one of: {', '.join(ALLOWED_VOICES)}.")
                return
            samples, sample_rate = state.get_kokoro().create(text, voice=voice, speed=1.0, lang="en-us")
            wav_bytes = _samples_to_wav(samples, int(sample_rate))
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(len(wav_bytes)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(wav_bytes)

        def _authorized(self) -> bool:
            supplied = self.headers.get("Authorization", "")
            expected = f"Bearer {state.token}"
            if not hmac.compare_digest(supplied, expected):
                self._error(401, "Unauthorized.")
                return False
            return True

        def _read_body(self, limit: int) -> bytes | None:
            raw_length = self.headers.get("Content-Length")
            try:
                length = int(raw_length or "")
            except ValueError:
                self._error(411, "A valid Content-Length is required.")
                return None
            if length <= 0:
                self._error(400, "A non-empty request body is required.")
                return None
            if length > limit:
                self._error(413, "Request body is too large.")
                return None
            body = self.rfile.read(length)
            if len(body) != length:
                self._error(400, "The request body was incomplete.")
                return None
            return body

        def _json(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _error(self, status: int, message: str) -> None:
            self._json(status, {"ok": False, "error": message})

    return Handler


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def _truthy_env(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _required_path(name: str, *, directory: bool = False) -> Path:
    path = Path(_required_env(name)).expanduser().resolve()
    if not path.exists() or (directory and not path.is_dir()) or (not directory and not path.is_file()):
        raise RuntimeError(f"{name} does not exist")
    return path


def _wav_error(audio: bytes, max_seconds: float) -> str | None:
    try:
        with wave.open(io.BytesIO(audio), "rb") as recording:
            channels = recording.getnchannels()
            width = recording.getsampwidth()
            rate = recording.getframerate()
            frames = recording.getnframes()
            compression = recording.getcomptype()
    except (wave.Error, EOFError):
        return "The recording must be a valid PCM WAV file."
    if compression != "NONE" or width != 2 or channels not in {1, 2}:
        return "WAV audio must be 16-bit PCM mono or stereo."
    if not 8_000 <= rate <= 48_000:
        return "WAV sample rate must be between 8 kHz and 48 kHz."
    if frames <= 0 or frames / rate > max_seconds:
        return f"WAV audio must be no longer than {int(max_seconds)} seconds."
    return None


def _samples_to_wav(samples: Any, sample_rate: int) -> bytes:
    import numpy as np

    flattened = np.asarray(samples, dtype=np.float32).reshape(-1)
    if sample_rate < 8_000 or sample_rate > 48_000 or flattened.size == 0:
        raise ValueError("invalid synthesized audio")
    if flattened.size > sample_rate * MAX_TTS_SECONDS:
        raise ValueError("synthesized audio is too long")
    pcm = (np.clip(flattened, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
    output = io.BytesIO()
    with wave.open(output, "wb") as recording:
        recording.setnchannels(1)
        recording.setsampwidth(2)
        recording.setframerate(sample_rate)
        recording.writeframes(pcm)
    return output.getvalue()


def main() -> None:
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    state = WorkerState()
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(state))
    server.daemon_threads = True
    port = int(server.server_address[1])
    print(json.dumps({"ready": True, "port": port}, separators=(",", ":")), flush=True)
    try:
        server.serve_forever(poll_interval=0.25)
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
