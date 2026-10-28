from codex_slack_bridge.agents import _read_output_file


def test_agent_output_reader_prefers_utf8(tmp_path):
    output = tmp_path / "result.txt"
    output.write_bytes("COMPLETED — tenant's result".encode("utf-8"))

    assert _read_output_file(str(output)) == "COMPLETED — tenant's result"


def test_agent_output_reader_falls_back_to_windows_1252(tmp_path):
    output = tmp_path / "result.txt"
    output.write_bytes("COMPLETED — tenant’s result".encode("cp1252"))

    assert _read_output_file(str(output)) == "COMPLETED — tenant’s result"
