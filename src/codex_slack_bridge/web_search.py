from __future__ import annotations

import re

from .config import BridgeConfig

SECRETISH_RE = re.compile(
    r"(?i)(xox[baprs]-|xapp-|sk-[a-z0-9_-]{20,}|client[_ -]?secret|password|passwd|api[_ -]?key)"
)


def run_public_web_search(config: BridgeConfig, query: str) -> str:
    clean_query = query.strip()
    if not clean_query:
        return "Usage: `!search public question or lookup`"
    if SECRETISH_RE.search(clean_query):
        return (
            "I blocked that web search because it appears to include a secret or credential. "
            "Do not send customer-private, credential, token, or internal-only data to public web search."
        )
    return "Public web search is unavailable in the Codex-only bridge runtime."


def is_web_search_command(text: str) -> bool:
    lowered = text.strip().lower()
    return lowered.startswith("!search ") or lowered.startswith("!web ")


def web_search_query(text: str) -> str:
    stripped = text.strip()
    if stripped.lower().startswith("!search "):
        return stripped[len("!search ") :].strip()
    if stripped.lower().startswith("!web "):
        return stripped[len("!web ") :].strip()
    return stripped
