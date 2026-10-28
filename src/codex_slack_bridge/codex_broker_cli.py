from __future__ import annotations

"""Shell fallback for the same ephemeral lane-scoped broker used by MCP."""

import argparse
import json
from typing import Any

from .codex_mcp_proxy import _broker_call


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="action", required=True)
    list_parser = subparsers.add_parser("list")
    list_parser.add_argument("server")
    call_parser = subparsers.add_parser("call")
    call_parser.add_argument("server")
    call_parser.add_argument("tool")
    call_parser.add_argument("arguments", nargs="?", default="{}")
    args = parser.parse_args()
    if args.action == "list":
        result = _broker_call(args.server, "tools/list", {})
    else:
        arguments: Any = json.loads(args.arguments)
        if not isinstance(arguments, dict):
            raise ValueError("arguments must be one JSON object")
        result = _broker_call(
            args.server,
            "tools/call",
            {"name": args.tool, "arguments": arguments},
        )
    print(json.dumps(result, ensure_ascii=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
