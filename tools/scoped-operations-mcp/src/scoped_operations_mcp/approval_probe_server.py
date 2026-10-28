from __future__ import annotations

import re
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations


NONCE = re.compile(r"^[A-Za-z0-9._-]{8,160}$")
APPROVAL_REQUIRED_WRITE = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=True,
    idempotentHint=True,
    openWorldHint=True,
)


def build_mcp() -> FastMCP:
    mcp = FastMCP(
        "Unattended Approval Regression Probe",
        instructions=(
            "This deployment-only test server exposes one idempotent local probe. "
            "It has no credentials, network client, filesystem write, or business-system access."
        ),
        json_response=True,
        stateless_http=True,
    )

    @mcp.tool(annotations=APPROVAL_REQUIRED_WRITE)
    def approval_probe(nonce: str) -> dict[str, Any]:
        """Exercise the strongest MCP approval class without performing an external mutation."""

        clean_nonce = str(nonce or "").strip()
        if not NONCE.fullmatch(clean_nonce):
            raise ValueError("nonce is invalid")
        return {
            "ok": True,
            "probeExecuted": True,
            "nonce": clean_nonce,
            "externalMutation": False,
        }

    return mcp


def main() -> None:
    build_mcp().run(transport="stdio")


if __name__ == "__main__":
    main()
