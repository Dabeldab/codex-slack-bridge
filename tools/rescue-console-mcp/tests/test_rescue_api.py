from rescue_console_mcp.rescue_api import parse_sessions_v3


def test_parse_sessions_v3_returns_allowlisted_fields():
    raw = (
        "OK\n"
        "ID|Status|Entry|Technician|Custom Field 0|Custom Field 1|Custom Field 2|Custom Field 3\n"
        "12345|Active|Support|Taylor|Pat|555-0100|Example Cafe|Main\n"
    )

    sessions = parse_sessions_v3(raw)

    assert sessions == [
        {
            "sessionId": "12345",
            "status": "Active",
            "entry": "Support",
            "technician": "Taylor",
            "contactName": "Pat",
            "phone": "555-0100",
            "company": "Example Cafe",
            "location": "Main",
        }
    ]


def test_parse_sessions_v3_handles_empty_ok():
    assert parse_sessions_v3("OK") == []
