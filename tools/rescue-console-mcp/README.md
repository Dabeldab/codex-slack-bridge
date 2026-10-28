# LogMeIn Rescue Read-Only MCP

Local stdio MCP for authenticated LogMeIn Rescue reporting. It uses the Rescue
API and deliberately has no Technician Console controller or mutation path.

## Tools

- `rescue_console_status`: sanitized local/API readiness.
- `rescue_list_sessions`: bounded Rescue API session listing.
- `rescue_read_performance`: aggregate session-performance summaries.
- `rescue_read_chat`: bounded API chat-log readback for one session.
- No customer-message, session-control, assignment, console-control, or
  administrative mutation tool is exported.

## Local development

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
.\.venv\Scripts\python.exe -m pytest
```

## Verification sequence

1. Call `rescue_console_status` and confirm `accessMode` is `read_only`.
2. Enumerate MCP tools and confirm only the four documented read tools exist.
3. Call `rescue_list_sessions`, `rescue_read_performance`, and
   `rescue_read_chat` as needed.
4. Confirm send, prepare-send, console-control, PIN, assignment, transfer, and
   admin tools are absent.

Remote control, file transfer, scripts, reboot, UAC/elevation, credential entry,
chat sending, and Rescue administration are intentionally outside this MCP.
