from __future__ import annotations

import re


MENTION_RE = re.compile(r"<@[A-Z0-9]+>")
STEER_COMMAND_RE = re.compile(
    r"^/(?P<command>btw|steer)\b(?:\s*[:,-]\s*|\s+)?(?P<text>[\s\S]*)$",
    re.IGNORECASE,
)


def strip_bot_mentions(text: str) -> str:
    return MENTION_RE.sub("", text or "").strip()


def parse_steer_command(value: str) -> tuple[str, str]:
    """Return the steering command name and payload, or empty command for normal text."""
    text = str(value or "").strip()
    match = STEER_COMMAND_RE.match(text)
    if not match:
        return "", text
    return str(match.group("command") or "").lower(), str(match.group("text") or "").strip()


def format_queued_steering_prompt(value: str, fallback: str = "") -> str:
    command, text = parse_steer_command(value)
    if not command:
        return str(value or "").strip()
    note = text or fallback or "Use this as steering for the current work."
    return (
        f"Operator steering note (/{command}): {note}\n"
        "Steering delivery rule: apply this as a separate queued follow-up after any in-flight lane work. "
        "The bridge did not inject it into an already in-flight turn. Do not paste the slash "
        "command into external systems, customer messages, email, Zoom, SQL, or notes."
    )


def chunk_for_slack(text: str, max_chars: int) -> list[str]:
    if not text:
        return ["No response."]
    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    remaining = text
    while len(remaining) > max_chars:
        split_at = remaining.rfind("\n", 0, max_chars)
        if split_at < max_chars // 2:
            split_at = max_chars
        chunks.append(remaining[:split_at].rstrip())
        remaining = remaining[split_at:].lstrip()
    if remaining:
        chunks.append(remaining)
    return chunks
