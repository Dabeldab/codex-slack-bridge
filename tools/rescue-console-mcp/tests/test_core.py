from rescue_console_mcp.config import Settings
from rescue_console_mcp.core import RescueConsoleCore


class FakeApi:
    @staticmethod
    def configuration():
        return {"credentialsConfigured": True, "nodeConfigured": True}

    @staticmethod
    def list_sessions():
        return {
            "nodeRef": "CHANNEL",
            "sessions": [
                {"sessionId": "123", "status": "Active", "technician": "Alex"},
                {"sessionId": "124", "status": "Waiting", "technician": "Alex"},
            ],
        }

    @staticmethod
    def read_chat(session_id):
        return {"sessionId": session_id, "available": True, "chat": "hello"}


def settings(tmp_path):
    return Settings(connector_root=tmp_path, env_file=tmp_path / ".env")


def test_status_declares_read_only_and_no_mutation_tools(tmp_path):
    result = RescueConsoleCore(settings(tmp_path), api=FakeApi()).status()

    assert result["accessMode"] == "read_only"
    assert result["mutationToolsExposed"] is False
    assert "sendEnabled" not in result


def test_session_chat_and_performance_reads(tmp_path):
    core = RescueConsoleCore(settings(tmp_path), api=FakeApi())

    sessions = core.list_sessions()
    chat = core.read_chat("123")
    performance = core.read_performance()

    assert sessions["api"]["sessions"][0]["sessionId"] == "123"
    assert chat["api"]["chat"] == "hello"
    assert performance["sessionCount"] == 2
    assert performance["byStatus"] == {"Active": 1, "Waiting": 1}
    assert performance["byTechnician"] == {"Alex": 2}


def test_chat_requires_exact_numeric_session_id(tmp_path):
    core = RescueConsoleCore(settings(tmp_path), api=FakeApi())

    assert core.read_chat("")["ok"] is False
