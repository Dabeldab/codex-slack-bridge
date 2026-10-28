from __future__ import annotations

import pytest
from mcp.client.session import ClientSession
from mcp.shared.memory import create_connected_server_and_client_session

from scoped_operations_mcp.approval_probe_server import build_mcp


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_approval_probe_is_a_guarded_write_with_no_external_mutation():
    async with create_connected_server_and_client_session(build_mcp(), raise_exceptions=True) as session:
        tools = {tool.name: tool for tool in (await session.list_tools()).tools}
        probe = tools["approval_probe"]
        assert probe.annotations.readOnlyHint is False
        assert probe.annotations.destructiveHint is True
        assert probe.annotations.idempotentHint is True
        assert probe.annotations.openWorldHint is True

        response = await session.call_tool("approval_probe", {"nonce": "approval-probe-test-1234"})
        assert response.isError is False
        assert response.structuredContent == {
            "ok": True,
            "probeExecuted": True,
            "nonce": "approval-probe-test-1234",
            "externalMutation": False,
        }
