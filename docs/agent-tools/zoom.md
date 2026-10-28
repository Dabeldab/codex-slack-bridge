<!-- AgentChat/coding_agent 2026-07-10T18:20:00-04:00 -->

# Zoom API Operations

## Fast route

Use a Zoom MCP/app connector first, then native Zoom API with Server-to-Server
OAuth or the established connector client, then helpers. Use authenticated Edge
Profile 1 only when the operation is confirmed UI-only or the API returns a
documented scope/license limitation. Do not use a signed-in browser as a
credential fallback.

## Auth and execution

- The existing `Support Dashboard Calls` Server-to-Server OAuth app is the
  required credential for automated Julio/Wiko Team Chat flows, Zoom Docs
  archive inventory, and Contact Center metrics. Its credential names are
  `ZOOM_ACCOUNT_ID`, `ZOOM_CLIENT_ID`, and
  `ZOOM_CLIENT_SECRET`. `ZOOM_TEAM_CHAT_SENDER_USER_ID` must match the token
  `uid` and one active Nova Zoom user. Account-level Team Chat paths use that
  exact user ID; `me` is never an allowed fallback. Do not create or reauthorize
  another Zoom app for those operations.
- The dedicated Nova Agent Operator user OAuth app supplies exact-contact
  resolution, explicit operator Team Chat messages, visible-channel history,
  fixed Chat Overview read/update, KB sync, and configured monitors through
  `ZOOM_OAUTH_CLIENT_ID`, `ZOOM_OAUTH_CLIENT_SECRET`, and
  `ZOOM_OAUTH_REFRESH_TOKEN`.
- Obtain the access token at Zoom OAuth, then call the exact account-level API.
  Paginate every list/report endpoint and preserve the requested time zone/window.
- Contact Center 403 commonly means missing license or scope even when auth is
  valid. Record that limitation before considering UI fallback.
- For an admin/config mutation, read current state, apply the exact request, and
  read back the queue/user/flow/webhook setting. Do not publish unrelated drafts.
- Keep `/webhook/zoom-engagement` correlation-only. Agent-assignment alerts use
  their separate route and webhook signature/CRC verification.

Known implementation: `skills/zoom_workplace.md`,
`src/codex_slack_bridge/zoom_kb_sync.py`, and logmein-connector
`src/zoom_correlation.py`, `src/zoom_agent_alerts.py`,
`src/endpoints/webhook.py`, and `src/endpoints/zoom_agent_alerts.py`.

Alex/tickets-agent has one additional read-only fast path:
`skills/zoom_support_chat_monitor.md` and
`src/codex_slack_bridge/zoom_chat_monitor.py`. It may read completed ZVA chat
reports, open Contact Center messaging metadata, and explicitly allowlisted
Team Chat report sessions. It exposes no Zoom reply, mark-read, transfer,
takeover, routing, or admin operation.

In the private GCP runtime, every operational lane, including Rory and Thor,
uses a fixed invocation of the `zoom-scoped-mcp` broker. Every lane receives
`zoom_operator_team_chat_recipient_resolve` and
`zoom_operator_team_chat_send`. That pair is available only when the
authenticated operator explicitly requests a message to one exact person. It
accepts an exact Zoom email address, including custom domains, or a unique full
name; journals before sending; and requires provider message-ID/body readback.

Alex, Taylor, and Jamie also retain
`zoom_team_chat_recipient_resolve` and `zoom_team_chat_send`. The resolver
accepts only the operator-managed `configured:julio` or `configured:wiko` alias
for an employee request and never returns a directory listing. Every other
employee request belongs on the relevant Salesforce ticket with a real Chatter
mention. The sender accepts brief direct text only, requires preserved
authorization context and a stable idempotency key, and uses shared
America/New_York daily state to add `Hey <FirstName>,` only on the first
  verified message to that person that day. It atomically records the provider
  attempt before the API call and requires exact Zoom message-ID, body, and
  sender-email readback; the exact configured active contact email supplied as
  `to_contact` is the recipient proof. A configured recipient must resolve to
  exactly one active Zoom user. An uncertain result is never retried blindly.
The automated pair obtains directory, send, and readback access only from the existing
`Support Dashboard Calls` S2S app; it does not use the legacy General OAuth
refresh-token path for Team Chat.

Every lane can use `zoom_team_chat_channels`, `zoom_team_chat_history`,
`zoom_docs_archives`, and `zoom_docs_archive_content` for bounded evidence.
Thor, Taylor, and Rory can use `zoom_ghostbusters_overview_read` and
`zoom_ghostbusters_overview_update` for the one fixed public Ghost Busters
`Chat Overview`. Updates call `POST
/docs/files/{fileId}/blocks/replace_range` with `docs:update:content`, a stable
idempotency key, privacy validation, and same-document readback. Personal,
one-on-one, HR, performance, customer, ticket, phone, email, and credential
content is rejected.

The Singapore routine accepts Julio's exact active Zoom contact email only in
`ZOOM_SINGAPORE_JULIO_CONTACT`; a name, user ID, group, or channel is invalid.
It sends at most one source-safe batch of 600 characters per run and never
splits rows linked to the same source email. Before any provider call, it
atomically persists a durable outbox that binds the exact source IDs,
machine/date rows, rendered body, and hash. Exact Zoom message-ID, body,
sender-email, and configured-recipient-email readback is required before source
acknowledgement. Verified delivery coverage is persisted before Gmail mutation;
deferred sources remain unread and five-minute continuation cycles drain later
bounded batches until none remain.

Every lane can read the fixed-roster `zoom_support_queue_metrics` result with
separate unique calls, chat sessions, inbound/outbound directions, and
per-representative counts. Taylor and Alex retain bounded support-chat snapshot
reads. Alex additionally retains the fixed weekly Yaron send workflow, which
uses `calls.total` rather than the all-channel agent-engagement workload total.
The user OAuth state
serializes refresh-token rotation. The broker exposes no channel
message, attachment, reply, mark-read, transfer, takeover, routing,
configuration, or arbitrary-URL tool.
