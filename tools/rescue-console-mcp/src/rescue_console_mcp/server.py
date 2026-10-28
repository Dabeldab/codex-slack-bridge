from __future__ import annotations

import argparse
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .config import Settings
from .core import RescueConsoleCore


READ_ONLY_LOCAL = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)
READ_ONLY_RESCUE = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=True,
)
def build_mcp(core: RescueConsoleCore) -> FastMCP:
    mcp = FastMCP(
        "LogMeIn Rescue Read Only",
        instructions=(
            "Read authenticated LogMeIn Rescue session, performance, and chat-log data. "
            "This MCP intentionally exposes no customer-message, session-control, assignment, "
            "technician-console, or administrative mutation tools."
        ),
        json_response=True,
        stateless_http=True,
    )

    @mcp.tool(annotations=READ_ONLY_LOCAL)
    def rescue_console_status() -> dict[str, Any]:
        """Return console, API, chat-input, and send readiness without exposing secrets."""
        return core.status()

    @mcp.tool(annotations=READ_ONLY_RESCUE)
    def rescue_list_sessions() -> dict[str, Any]:
        """List current sessions through the authenticated read-only Rescue API."""
        return core.list_sessions()

    @mcp.tool(annotations=READ_ONLY_RESCUE)
    def rescue_read_chat(session_id: str = "") -> dict[str, Any]:
        """Read the chat log for one numeric Rescue session ID."""
        return core.read_chat(session_id=session_id)

    @mcp.tool(annotations=READ_ONLY_RESCUE)
    def rescue_read_performance() -> dict[str, Any]:
        """Return bounded session and technician counts from the Rescue sessions API."""
        return core.read_performance()

    return mcp


def main() -> None:
    parser = argparse.ArgumentParser(description="Portable read-only LogMeIn Rescue MCP")
    parser.add_argument("--transport", choices=("stdio",), default="stdio")
    args = parser.parse_args()
    build_mcp(RescueConsoleCore(Settings.from_env())).run(transport=args.transport)


if __name__ == "__main__":
    main()
