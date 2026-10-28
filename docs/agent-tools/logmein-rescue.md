<!-- AgentChat/coding_agent 2026-07-10T18:20:00-04:00 -->

# LogMeIn Rescue Operations

Owners: Alex (`tickets_agent`) for support operations and Thor (`claude_agent`
compatibility ID) for read-only support-quality review. Taylor, Jamie, Direct
Codex, and Raw Codex do not receive the `rescue_console` MCP.

## Fast route

Use the registered `rescue_console` MCP. Despite its legacy server name, it is
an API-only read surface and exports only authentication status, session lists,
performance summaries, and chat-log reads. It has no console controller,
message send, PIN creation, Calling Card mutation, session assignment, or admin
tool. Read
`skills/logmein_rescue.md` and `config/logmein-rescue.env.example` for current
non-secret names and precedence; never print auth codes, passwords, tokens, PIN
payloads, customer chat, or webhook secrets.

## Common workflow

- Confirm connector readiness with its light health route before deeper debug.
- Cloud Rescue auth/session/chat reads use the portable client bundled in
  `tools/rescue-console-mcp`; they do not import another workstation repo at
  runtime. The fuller local connector remains in
  `auto-tickets/logmein-connector/src/logmein_api.py`. Expired authcodes require
  reauthentication; `POLLRATEEXCEEDED` requires backoff, not rapid retries.
- Session webhooks must pass configured authentication/signature checks. Resolve
  the real Salesforce Account/Contact before ticket mutation; ambiguous matches
  remain skipped.
- Allowed order is `rescue_console_status` -> `rescue_list_sessions` ->
  `rescue_read_performance` and/or `rescue_read_chat`.
- Thor's complete Rescue inventory is exactly those four tools. Thor may use
  their transient evidence to score quality, but may not create or update a
  Salesforce ticket, correlate an unresolved customer identity, send a message,
  control a session, or mutate Rescue.
- If asked to send, control, assign, create, or administer anything in Rescue,
  state that this lane does not have that access or ability. Do not attempt to
  change the MCP, credentials, scopes, or Technician Console.

Canonical sources: `skills/logmein_rescue.md`, connector
`src/logmein_api.py`, `src/endpoints/rescue_session.py`,
`docs/SECURITY-AND-ENTRY-POINTS.md`, and
`docs/openapi-zoom-connect-create-rescue-session.yaml`, plus
`tools/rescue-console-mcp/README.md` for the enforced read-only MCP.
