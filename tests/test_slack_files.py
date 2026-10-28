from __future__ import annotations

# AgentChat/direct_codex 2026-07-13T01:28:53-04:00: verify attachment type confusion and ingest bounds.

from pathlib import Path

import pytest

from codex_slack_bridge import slack_files
from codex_slack_bridge.config import BridgeConfig


class FakeDownloadResponse:
    def __init__(self, body: bytes, content_type: str) -> None:
        self._body = body
        self._offset = 0
        self.headers = {
            "Content-Length": str(len(body)),
            "Content-Type": content_type,
        }

    def __enter__(self) -> "FakeDownloadResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            size = len(self._body) - self._offset
        chunk = self._body[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk


def test_slack_image_download_rejects_sign_in_html(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    response = FakeDownloadResponse(b"<!DOCTYPE html><title>Slack</title>", "text/html; charset=utf-8")
    monkeypatch.setattr(slack_files.urllib.request, "urlopen", lambda *_args, **_kwargs: response)
    destination = tmp_path / "screenshot.jpg"

    with pytest.raises(ValueError, match="files:read"):
        slack_files._download_private_url(
            "https://files.slack.com/private-image",
            destination,
            "test-token",
            1024,
            timeout_seconds=5,
            expected_mimetype="image/jpeg",
        )

    assert not destination.exists()


def test_slack_image_download_rejects_sign_in_html_when_content_type_lies(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    response = FakeDownloadResponse(b"<!DOCTYPE html><html><title>Slack sign in</title>", "image/jpeg")
    monkeypatch.setattr(slack_files.urllib.request, "urlopen", lambda *_args, **_kwargs: response)
    destination = tmp_path / "screenshot.jpg"

    with pytest.raises(ValueError, match="files:read"):
        slack_files._download_private_url(
            "https://files.slack.com/private-image",
            destination,
            "test-token",
            1024,
            timeout_seconds=5,
            expected_mimetype="image/jpeg",
        )

    assert not destination.exists()


def test_slack_image_download_rejects_invalid_image_signature(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    response = FakeDownloadResponse(b"not-really-a-jpeg", "image/jpeg")
    monkeypatch.setattr(slack_files.urllib.request, "urlopen", lambda *_args, **_kwargs: response)
    destination = tmp_path / "screenshot.jpg"

    with pytest.raises(ValueError, match="image signature"):
        slack_files._download_private_url(
            "https://files.slack.com/private-image",
            destination,
            "test-token",
            1024,
            timeout_seconds=5,
            expected_mimetype="image/jpeg",
        )

    assert not destination.exists()


def test_slack_image_download_keeps_real_image_bytes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    jpeg = b"\xff\xd8\xff\xe0" + b"image-bytes"
    response = FakeDownloadResponse(jpeg, "image/jpeg")
    monkeypatch.setattr(slack_files.urllib.request, "urlopen", lambda *_args, **_kwargs: response)
    destination = tmp_path / "screenshot.jpg"

    slack_files._download_private_url(
        "https://files.slack.com/private-image",
        destination,
        "test-token",
        1024,
        timeout_seconds=5,
        expected_mimetype="image/jpeg",
    )

    assert destination.read_bytes() == jpeg


def test_slack_download_allows_an_intentional_html_attachment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    html = b"<!DOCTYPE html><title>Uploaded report</title>"
    response = FakeDownloadResponse(html, "text/html; charset=utf-8")
    monkeypatch.setattr(slack_files.urllib.request, "urlopen", lambda *_args, **_kwargs: response)
    destination = tmp_path / "report.html"

    slack_files._download_private_url(
        "https://files.slack.com/private-html",
        destination,
        "test-token",
        1024,
        timeout_seconds=5,
        expected_mimetype="text/html",
    )

    assert destination.read_bytes() == html


def test_slack_attachment_ingest_caps_file_count(tmp_path: Path) -> None:
    config = BridgeConfig(
        defaults={
            "slack_file_download_dir": str(tmp_path),
            "slack_file_max_files_per_event": 5,
        },
        channels={},
        agents={},
    )
    event = {
        "channel": "C",
        "ts": "1.0",
        "files": [{"id": f"F{index}", "name": f"file-{index}.txt"} for index in range(8)],
    }

    records = slack_files.download_event_files(config=config, event=event, client=object())

    assert len(records) == 5
    assert [item["id"] for item in records] == ["F0", "F1", "F2", "F3", "F4"]


def test_slack_image_prompt_includes_local_file_even_without_ocr_preview(tmp_path: Path) -> None:
    image_path = tmp_path / "screenshot.jpg"
    image_path.write_bytes(b"\xff\xd8\xff\xe0image-bytes")

    prompt = slack_files.format_files_for_prompt(
        [
            {
                "id": "F1",
                "name": "screenshot.jpg",
                "mimetype": "image/jpeg",
                "size": image_path.stat().st_size,
                "local_path": str(image_path),
                "preview": "",
                "preview_notes": ["Image OCR is unavailable."],
            }
        ]
    )

    assert f"Local path: {image_path}" in prompt
    assert "Decode note: Image OCR is unavailable." in prompt
