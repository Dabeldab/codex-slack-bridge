from __future__ import annotations

import atexit
import io
import json
import os
import queue
import secrets
import subprocess
import threading
import urllib.error
import urllib.request
import wave
import time
from pathlib import Path
from typing import Any


ALLOWED_LOCAL_VOICES = ("af_heart", "af_bella", "af_nicole", "bf_emma")
MAX_WAV_BYTES = 8 * 1024 * 1024
MAX_WAV_SECONDS = 30.0
MAX_TEXT_CHARS = 2_000
MAX_JSON_BYTES = 256 * 1024
MAX_SYNTHESIZED_WAV_BYTES = 24 * 1024 * 1024
STARTUP_TIMEOUT_SECONDS = 15.0
TRANSCRIBE_TIMEOUT_SECONDS = 45.0
SYNTHESIZE_TIMEOUT_SECONDS = 45.0


class LocalVoiceRoomError(RuntimeError):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


class LocalVoiceRoomGateway:
    """Own a private, lazy local speech worker without network-provider fallback."""

    def __init__(
        self,
        enabled: bool,
        bridge_root: str | os.PathLike[str],
        runtime_python_path: str | os.PathLike[str],
        worker_script_path: str | os.PathLike[str],
        whisper_model_path: str | os.PathLike[str],
        kokoro_model_path: str | os.PathLike[str],
        kokoro_voices_path: str | os.PathLike[str],
        default_voice: str = "af_heart",
        whisper_threads: int = 8,
        whisper_device: str = "cpu",
        whisper_compute_type: str | None = None,
        whisper_cpu_fallback: bool = True,
        whisper_cpu_compute_type: str = "int8",
    ) -> None:
        self.enabled = bool(enabled)
        self.bridge_root = Path(bridge_root).expanduser().resolve()
        self.runtime_python_path = self._resolve(runtime_python_path)
        self.worker_script_path = self._resolve(worker_script_path)
        self.whisper_model_path = self._resolve(whisper_model_path)
        self.kokoro_model_path = self._resolve(kokoro_model_path)
        self.kokoro_voices_path = self._resolve(kokoro_voices_path)
        voice = str(default_voice or "af_heart").strip().lower()
        self.default_voice = voice if voice in ALLOWED_LOCAL_VOICES else "af_heart"
        self.whisper_threads = max(1, min(int(whisper_threads), 16))
        requested_device = str(whisper_device or "cpu").strip().lower()
        self.whisper_device = requested_device if requested_device in {"cpu", "cuda"} else "cpu"
        default_compute_type = "float16" if self.whisper_device == "cuda" else "int8"
        self.whisper_compute_type = str(whisper_compute_type or default_compute_type).strip().lower()
        self.whisper_cpu_fallback = bool(whisper_cpu_fallback)
        self.whisper_cpu_compute_type = str(whisper_cpu_compute_type or "int8").strip().lower()
        self._process: subprocess.Popen[str] | None = None
        self._port: int | None = None
        self._token: str | None = None
        self._lifecycle_lock = threading.RLock()
        self._operation_lock = threading.Lock()
        self._atexit_registered = False

    def _resolve(self, value: str | os.PathLike[str]) -> Path:
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = self.bridge_root / path
        return path.resolve()

    def status(self) -> dict[str, Any]:
        missing = self._missing_paths()
        running = self._process is not None and self._process.poll() is None
        return {
            "ok": True,
            "enabled": self.enabled,
            "ready": self.enabled and not missing,
            "provider": "local",
            "transport": "loopback-http",
            "speechToText": "faster-whisper-base.en",
            "speechToTextDevice": f"{self.whisper_device}-{self.whisper_compute_type}",
            "speechToTextCpuFallbackEnabled": self.whisper_cpu_fallback,
            "speechToTextCpuFallbackDevice": f"cpu-{self.whisper_cpu_compute_type}",
            "textToSpeech": "kokoro-onnx-v1.0-int8",
            "defaultVoice": self.default_voice,
            "allowedVoices": list(ALLOWED_LOCAL_VOICES),
            "workerRunning": running,
            "modelsLoadedLazily": True,
            "networkFallbackAllowed": False,
            "missing": missing,
        }

    def transcribe(self, audio_wav: bytes) -> dict[str, Any]:
        self._require_ready()
        _validate_wav(audio_wav, max_seconds=MAX_WAV_SECONDS)
        if not self._operation_lock.acquire(blocking=False):
            raise LocalVoiceRoomError(429, "Local Voice Room is busy. Try again in a moment.")
        try:
            body, content_type = self._request(
                "/transcribe",
                audio_wav,
                "audio/wav",
                timeout=TRANSCRIBE_TIMEOUT_SECONDS,
                response_limit=MAX_JSON_BYTES,
            )
            if content_type != "application/json":
                raise LocalVoiceRoomError(502, "The local speech worker returned an invalid response type.")
            try:
                result = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise LocalVoiceRoomError(502, "The local speech worker returned invalid JSON.") from exc
            if not isinstance(result, dict) or not isinstance(result.get("text"), str):
                raise LocalVoiceRoomError(502, "The local speech worker returned an invalid transcript.")
            return result
        finally:
            self._operation_lock.release()

    def warmup(self) -> dict[str, Any]:
        """Start the private worker and load both models before the first turn."""
        self._require_ready()
        if not self._operation_lock.acquire(blocking=False):
            raise LocalVoiceRoomError(429, "Local Voice Room is busy. Try again in a moment.")
        try:
            started = time.perf_counter()
            body, content_type = self._request(
                "/warmup", b"{}", "application/json", timeout=STARTUP_TIMEOUT_SECONDS + 45.0,
                response_limit=MAX_JSON_BYTES,
            )
            if content_type != "application/json":
                raise LocalVoiceRoomError(502, "The local speech worker returned an invalid warmup response.")
            result = json.loads(body.decode("utf-8"))
            if not isinstance(result, dict) or result.get("ok") is not True:
                raise LocalVoiceRoomError(502, "The local speech worker could not warm its models.")
            result["gatewayWarmupMs"] = round((time.perf_counter() - started) * 1000)
            return result
        finally:
            self._operation_lock.release()

    def synthesize(self, text: str, voice: str | None = None) -> bytes:
        self._require_ready()
        cleaned = str(text or "").strip()
        if not cleaned:
            raise LocalVoiceRoomError(400, "Text to speak is required.")
        if len(cleaned) > MAX_TEXT_CHARS:
            raise LocalVoiceRoomError(413, f"Text to speak must be {MAX_TEXT_CHARS} characters or fewer.")
        selected_voice = str(voice or self.default_voice).strip().lower()
        if selected_voice not in ALLOWED_LOCAL_VOICES:
            raise LocalVoiceRoomError(400, f"Voice must be one of: {', '.join(ALLOWED_LOCAL_VOICES)}.")
        if not self._operation_lock.acquire(blocking=False):
            raise LocalVoiceRoomError(429, "Local Voice Room is busy. Try again in a moment.")
        try:
            payload = json.dumps(
                {"text": cleaned, "voice": selected_voice}, separators=(",", ":")
            ).encode("utf-8")
            body, content_type = self._request(
                "/synthesize",
                payload,
                "application/json",
                timeout=SYNTHESIZE_TIMEOUT_SECONDS,
                response_limit=MAX_SYNTHESIZED_WAV_BYTES,
            )
            if content_type not in {"audio/wav", "audio/x-wav"}:
                raise LocalVoiceRoomError(502, "The local speech worker returned an invalid audio type.")
            _validate_wav(body, max_seconds=120.0, max_bytes=MAX_SYNTHESIZED_WAV_BYTES)
            return body
        finally:
            self._operation_lock.release()

    def shutdown(self) -> None:
        with self._lifecycle_lock:
            process = self._process
            if process is None:
                return
            if process.poll() is None and self._port and self._token:
                try:
                    self._request(
                        "/shutdown",
                        b"{}",
                        "application/json",
                        timeout=2.0,
                        response_limit=MAX_JSON_BYTES,
                        ensure_worker=False,
                    )
                except LocalVoiceRoomError:
                    pass
                try:
                    process.wait(timeout=3.0)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    try:
                        process.wait(timeout=2.0)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=2.0)
            self._process = None
            self._port = None
            self._token = None

    def _missing_paths(self) -> list[str]:
        checks = (
            ("runtime_python", self.runtime_python_path, True),
            ("worker_script", self.worker_script_path, True),
            ("whisper_model", self.whisper_model_path, False),
            ("kokoro_model", self.kokoro_model_path, True),
            ("kokoro_voices", self.kokoro_voices_path, True),
        )
        missing = [
            label
            for label, path, must_be_file in checks
            if not path.exists() or (must_be_file and not path.is_file())
        ]
        if self.whisper_model_path.is_dir():
            required_whisper_files = ("config.json", "model.bin", "tokenizer.json", "vocabulary.txt")
            if any(not (self.whisper_model_path / name).is_file() for name in required_whisper_files):
                if "whisper_model" not in missing:
                    missing.append("whisper_model")
        return missing

    def _require_ready(self) -> None:
        if not self.enabled:
            raise LocalVoiceRoomError(503, "Local Voice Room is disabled.")
        missing = self._missing_paths()
        if missing:
            raise LocalVoiceRoomError(503, f"Local Voice Room runtime is incomplete: {', '.join(missing)}.")

    def _ensure_worker(self) -> None:
        with self._lifecycle_lock:
            if self._process is not None and self._process.poll() is None and self._port and self._token:
                return
            self._process = None
            self._port = None
            self._token = secrets.token_urlsafe(32)
            env = os.environ.copy()
            # Keep the inference worker genuinely isolated from the bridge's
            # shared .packages directory and any machine-level Python runtime.
            env.pop("PYTHONPATH", None)
            env.pop("PYTHONHOME", None)
            env.update(
                {
                    "LOCAL_VOICE_TOKEN": self._token,
                    "LOCAL_VOICE_WHISPER_MODEL": str(self.whisper_model_path),
                    "LOCAL_VOICE_KOKORO_MODEL": str(self.kokoro_model_path),
                    "LOCAL_VOICE_KOKORO_VOICES": str(self.kokoro_voices_path),
                    "LOCAL_VOICE_WHISPER_THREADS": str(self.whisper_threads),
                    "LOCAL_VOICE_WHISPER_DEVICE": self.whisper_device,
                    "LOCAL_VOICE_WHISPER_COMPUTE_TYPE": self.whisper_compute_type,
                    "LOCAL_VOICE_WHISPER_CPU_FALLBACK": "1" if self.whisper_cpu_fallback else "0",
                    "LOCAL_VOICE_WHISPER_CPU_COMPUTE_TYPE": self.whisper_cpu_compute_type,
                    "HF_HUB_OFFLINE": "1",
                    "HF_HUB_DISABLE_TELEMETRY": "1",
                    "TRANSFORMERS_OFFLINE": "1",
                    "PYTHONNOUSERSITE": "1",
                    "PYTHONUNBUFFERED": "1",
                }
            )
            creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            try:
                process = subprocess.Popen(
                    [str(self.runtime_python_path), str(self.worker_script_path)],
                    cwd=str(self.bridge_root),
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    shell=False,
                    creationflags=creationflags,
                )
            except OSError as exc:
                self._token = None
                raise LocalVoiceRoomError(503, "The local speech worker could not be started.") from exc
            self._process = process
            try:
                announcement = _readline_with_timeout(process, STARTUP_TIMEOUT_SECONDS)
                details = json.loads(announcement)
                port = int(details["port"])
                if details.get("ready") is not True or not 1 <= port <= 65535:
                    raise ValueError("invalid worker announcement")
                self._port = port
                self._request(
                    "/health",
                    None,
                    None,
                    timeout=2.0,
                    response_limit=MAX_JSON_BYTES,
                    method="GET",
                    ensure_worker=False,
                )
            except (LocalVoiceRoomError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
                if process.poll() is None:
                    process.terminate()
                self._process = None
                self._port = None
                self._token = None
                raise LocalVoiceRoomError(503, "The local speech worker did not start safely.") from exc
            if not self._atexit_registered:
                atexit.register(self.shutdown)
                self._atexit_registered = True

    def _request(
        self,
        path: str,
        data: bytes | None,
        content_type: str | None,
        *,
        timeout: float,
        response_limit: int,
        method: str = "POST",
        ensure_worker: bool = True,
    ) -> tuple[bytes, str]:
        if ensure_worker:
            self._ensure_worker()
        if not self._port or not self._token:
            raise LocalVoiceRoomError(503, "The local speech worker is unavailable.")
        headers = {"Authorization": f"Bearer {self._token}", "Accept": "application/json, audio/wav"}
        if content_type:
            headers["Content-Type"] = content_type
        request = urllib.request.Request(
            f"http://127.0.0.1:{self._port}{path}",
            data=data,
            method=method,
            headers=headers,
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read(response_limit + 1)
                response_type = response.headers.get_content_type()
        except urllib.error.HTTPError as exc:
            message = "The local speech worker rejected the request."
            try:
                error_body = exc.read(MAX_JSON_BYTES + 1)
                error_data = json.loads(error_body.decode("utf-8"))
                if isinstance(error_data.get("error"), str):
                    message = error_data["error"]
            except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
                pass
            raise LocalVoiceRoomError(exc.code, message) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise LocalVoiceRoomError(504, "The local speech worker timed out or stopped responding.") from exc
        if len(body) > response_limit:
            raise LocalVoiceRoomError(502, "The local speech worker response was too large.")
        return body, response_type


def _readline_with_timeout(process: subprocess.Popen[str], timeout: float) -> str:
    if process.stdout is None:
        raise ValueError("worker stdout unavailable")
    result: queue.Queue[str] = queue.Queue(maxsize=1)

    def read_line() -> None:
        result.put(process.stdout.readline())

    thread = threading.Thread(target=read_line, name="local-voice-startup", daemon=True)
    thread.start()
    try:
        line = result.get(timeout=timeout)
    except queue.Empty as exc:
        raise ValueError("worker startup timed out") from exc
    if not line:
        raise ValueError("worker exited before startup")
    return line


def _validate_wav(audio: bytes, *, max_seconds: float, max_bytes: int = MAX_WAV_BYTES) -> None:
    if not isinstance(audio, bytes) or not audio:
        raise LocalVoiceRoomError(400, "A non-empty WAV recording is required.")
    if len(audio) > max_bytes:
        raise LocalVoiceRoomError(413, "The WAV recording is too large.")
    try:
        with wave.open(io.BytesIO(audio), "rb") as recording:
            channels = recording.getnchannels()
            sample_width = recording.getsampwidth()
            frame_rate = recording.getframerate()
            frames = recording.getnframes()
            compression = recording.getcomptype()
    except (wave.Error, EOFError) as exc:
        raise LocalVoiceRoomError(400, "The recording must be a valid PCM WAV file.") from exc
    if compression != "NONE" or sample_width != 2 or channels not in {1, 2}:
        raise LocalVoiceRoomError(400, "WAV audio must be 16-bit PCM mono or stereo.")
    if not 8_000 <= frame_rate <= 48_000:
        raise LocalVoiceRoomError(400, "WAV sample rate must be between 8 kHz and 48 kHz.")
    duration = frames / frame_rate if frame_rate else 0.0
    if duration <= 0 or duration > max_seconds:
        raise LocalVoiceRoomError(413, f"WAV audio must be no longer than {int(max_seconds)} seconds.")
