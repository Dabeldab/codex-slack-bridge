import os
import sys
from collections.abc import AsyncGenerator

import pytest
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.shared.memory import create_connected_server_and_client_session

from rescue_console_mcp.config import Settings
from rescue_console_mcp.core import RescueConsoleCore
from rescue_console_mcp.server import build_mcp


class StubApi:
    @staticmethod
    def configuration():
        return {"credentialsConfigured": False, "nodeConfigured": False}

    @staticmethod
    def list_sessions():
        return {"nodeRef": "CHANNEL", "sessions": []}

    @staticmethod
    def read_chat(session_id):
        return {"sessionId": session_id, "available": False, "chat": ""}


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def client_session(tmp_path) -> AsyncGenerator[ClientSession]:
    core = RescueConsoleCore(
        Settings(connector_root=tmp_path, env_file=tmp_path / ".env"),
        api=StubApi(),
    )
    async with create_connected_server_and_client_session(
        build_mcp(core),
        raise_exceptions=True,
    ) as session:
        yield session


@pytest.mark.anyio
async def test_mcp_exposes_only_read_tools(client_session):
    response = await client_session.list_tools()
    tools = {tool.name: tool for tool in response.tools}

    assert set(tools) == {
        "rescue_console_status",
        "rescue_list_sessions",
        "rescue_read_chat",
        "rescue_read_performance",
    }
    for name, tool in tools.items():
        assert tool.annotations.readOnlyHint is True, name
        schema = str(tool.inputSchema).casefold()
        assert "password" not in schema
        assert "token" not in schema
        assert "authcode" not in schema
        assert "send" not in name
        assert "prepare" not in name


@pytest.mark.anyio
async def test_protocol_status_is_sanitized(client_session):
    response = await client_session.call_tool("rescue_console_status", {})

    assert response.isError is False
    assert response.structuredContent["ok"] is True
    assert response.structuredContent["accessMode"] == "read_only"
    assert response.structuredContent["mutationToolsExposed"] is False
    assert "password" not in str(response.structuredContent).casefold()
    assert "token" not in str(response.structuredContent).casefold()


@pytest.mark.anyio
async def test_real_stdio_transport_initializes(tmp_path):
    safe_env = {
        "PYTHONIOENCODING": "utf-8",
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", r"C:\Windows"),
        "TEMP": os.environ.get("TEMP", ""),
        "TMP": os.environ.get("TMP", ""),
        "LOCALAPPDATA": os.environ.get("LOCALAPPDATA", str(tmp_path)),
    }
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "rescue_console_mcp.server"],
        env={key: value for key, value in safe_env.items() if value},
    )

    async with stdio_client(parameters) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tools = await session.list_tools()
            status = await session.call_tool("rescue_console_status", {})

    assert len(tools.tools) == 4
    assert status.isError is False
    assert status.structuredContent["accessMode"] == "read_only"
