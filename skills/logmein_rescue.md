# LogMeIn Rescue

Current owner: Alex (`tickets_agent`). Taylor and Jamie must delegate live
Technician Console work to Alex. Direct Codex retains access for testing and
operator support. Do not treat Rescue chat as a Taylor email-watch duty.

Use the existing `logmein-connector` repo as the source of truth for LogMeIn Rescue, Nova Live Support, and Salesforce ticket automation:

- Repo: `C:\Users\redma\Workworkworkworkworkwork\auto-tickets\logmein-connector`
- Agent Chat config: `C:\Users\redma\Workworkworkworkworkwork\codex-slack-bridge\config\logmein-rescue.env`
- Main service: FastAPI in `src/main.py`
- Rescue API helpers: `src/logmein_api.py`
- Session/ticket webhooks: `src/endpoints/webhook.py`
- PIN and Calling Card APIs: `src/endpoints/rescue_session.py`
- Remote-support handoff/page: `src/endpoints/remote_support.py`
- Ticket-agent dashboard: `/ticket-agent` and `src/endpoints/ticket_agent.py`
- Windows Live Support protocol helper: `scripts/windows_live_support_launcher`
- Local Technician Console MCP: `tools/rescue-console-mcp`

## Capabilities

- Inspect and explain Rescue session-start/session-end ticket creation.
- Use connector code and docs to diagnose Salesforce ticket matching, deduplication, surveys, chatlog retrieval, Zoom correlation, and remote-support handoffs.
- Generate or describe API calls for:
  - `POST /api/rescue/create-session` for LogMeIn Rescue PIN sessions.
  - `POST /api/rescue/calling-card` for Calling Card download links.
  - `POST /api/rescue/handoff` for agent/customer remote-support messages.
  - `GET /remote-support` for the customer-facing Nova Live Support launch page.
- Run local read-only inspections, tests, or helper scripts from the connector repo when needed.
- Use the registered `rescue_console` MCP to inspect the same-user Technician
  Console, list/read live sessions, and send an explicitly requested customer
  chat message without moving the physical mouse.

## Operating Rules

- Never print, copy, or commit Rescue, Salesforce, Zoom, Twilio, SMTP, or connector API secrets.
- Use Agent Chat's own `config/logmein-rescue.env` for Rescue/runtime credentials when present; do not assume the connector repo has a local `.env`.
- Do not put real credentials into Agent Chat config examples, profiles, skills, memory, or prompts.
- Treat live Rescue PIN creation, Calling Card handoff generation for a real customer, Salesforce ticket mutation, outbound customer messages, and webhook replay as live actions. Do them only when the user explicitly asks for that action in the current conversation and gives enough customer/session context.
- For Technician Console chat, call `rescue_console_status`,
  `rescue_list_sessions`, and `rescue_read_chat` before `rescue_send_chat`.
  Use the exact visible session label and a unique idempotency key. Do not retry
  an uncertain send, and never send spontaneously without a verified operator
  instruction. A verified instruction needs no second confirmation.
- Default to read-only discovery for investigations: inspect logs, docs, code, Salesforce ticket comments, Rescue session ids, pending rows, and generated outputs before proposing writes.
- Keep `logmein-connector` repo work separate from live Salesforce or Zoom admin work. If the user asks for a native admin change, stay in the native admin surface instead of editing connector code.

## Key Entry Points

- `README.md`: service map, webhooks, survey, poller, protected routes, deployment shape.
- `config/logmein-rescue.env.example` in the Agent Chat repo: private Rescue config template.
- `README_REPORTER.md`: bulk chatlog reporter, `rescue_reporter run`, `rescue_reporter fetch`, reporting auth and rate limits.
- `docs/SECURITY-AND-ENTRY-POINTS.md`: protected routes, webhook secrets, C-field mapping, API-key rules.
- `docs/TICKET-LIFECYCLE.md`: account/contact lookup, dedup layers, placeholder tickets, fallback/skip behavior.
- `docs/CHATLOGS.md`: `getChat`, chatlog report limitations, pending chatlog retry queue.
- `docs/openapi-zoom-connect-create-rescue-session.yaml`: request/response contract for `create-session` and `calling-card`.
- `tools/rescue-console-mcp/README.md`: local MCP tools, send preflight, hashed
  audit behavior, and live-session test sequence.

## Important Details

- Default Rescue C-fields are name -> `CField0`, phone -> `CField1`, company/account username -> `CField2`, and location/store -> `CField3`-`CField5`.
- For PIN creation, the connector maps JSON fields to SOAP `requestPINCodeV2`, `requestPINCodeV3`, or `requestPINCodeV4` through `request_pin_code_dispatch`.
- `node_id` can come from the request body, `RESCUE_PIN_NODE_ID`, `RESCUE_NODE_ID`, or `RESCUE_GROUP_NODE_ID`.
- Rescue auth for PIN creation comes from `RESCUE_API_TOKEN` or a fresh authcode using `RESCUE_EMAIL`/`RESCUE_USER` and `RESCUE_PWD`/`RESCUE_PASS`. Never place these in request JSON.
- Webhooks use `LOGMEIN_WEBHOOK_SECRET` or `WEBHOOK_SHARED_SECRET`; protected APIs use `Authorization: Bearer <API_KEY>` or `X-API-Key`.
- The connector dedupes Rescue-created tickets through in-process tracking, Salesforce `Rescue_Session_ID__c` when available, and the `created_ticket` table as fallback.
- `Session_History__c` is a Salesforce lookup, not a plain Rescue session-id text field. Do not write LogMeIn ids there as text.
- If `SKIP_TICKET_IF_NO_ACCOUNT_MATCH=true`, unmatched sessions should not create fallback-account tickets.
- The `/remote-support` page defaults to `novapos-livesupport://start`; the Windows helper launches an existing Calling Card, installed Calling Card executable, or falls back to downloading `supportLatest.msi`.

## Useful Commands

Run from `C:\Users\redma\Workworkworkworkworkwork\auto-tickets\logmein-connector`:

```powershell
py -3 -m pytest tests/test_rescue_session.py tests/test_remote_support.py tests/test_rescue_reporter.py tests/test_ticket_agent.py
py -3 run_poller.py
py -3 -m src.rescue_reporter_cli fetch --start YYYY-MM-DD --end YYYY-MM-DD --dry-run
```

Before browser debugging local UI routes, verify the app is serving on port 8000 or use the lightweight status endpoint if available.
