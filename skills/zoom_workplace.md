# Zoom Workplace Ops

<!-- AgentChat/coding_agent 2026-07-09T11:45:00-04:00 -->
<!-- AgentChat/coding_agent 2026-07-10T17:30:00-04:00 -->

Use this skill when the user asks about Zoom Contact Center, engagement logs,
queue/agent metrics, Zoom Phone call history, Zoom users, meetings/recordings,
webhook correlation with Salesforce tickets, or connector health for Zoom
integrations.

## Tool priority

1. **Zoom MCP** — prefer any configured Zoom MCP server tools when available in
   this session.
2. **Local S2S OAuth + API** — use `ZOOM_ACCOUNT_ID`, `ZOOM_CLIENT_ID`, and
   `ZOOM_CLIENT_SECRET` from `config/ops.env` (or bridge `.env`) to obtain a
   Server-to-Server access token, then call Zoom REST APIs with `curl` or
   equivalent. Do not build a full client library unless needed for a one-off
   request.
3. **Established connector/helper** - use existing connector code or a registered
   local helper after MCP/API paths are confirmed insufficient.
4. **Logged-in browser UI** - when the user explicitly asks for a Zoom admin
   change and API/MCP cannot perform it, use non-disruptive browser automation
   before giving up. Prefer a built-in browser/app connector or an
   already-debuggable browser session. For Zoom AI Studio and Nova virtual-agent
   edits, use displayed `Profile 1` only and the exact Nova URL:
   `https://novapointofsale.zoom.us/ai-studio/virtual-agent`. Open a new tab by
   default and do not navigate the user's active tab unless explicitly
   requested. CDP/Playwright clicks/fills are allowed because they do not move
   the physical mouse. Do not use Windows GUI automation that moves the user's
   real pointer unless the verified task specifically requires it. On this machine, displayed Edge
   Profile 1 is stored in the internal `Default` directory, while internal
   `Profile 1` displays as Profile 2. Use Chrome only when `Profile 1` is the
   confirmed logged-in controllable profile. If Zoom asks for login or MFA, ask
   the user to complete that in the same visible displayed Profile 1 account,
   then retry the same task from the current/new tab. Do not open displayed
   Edge Profile 2, an isolated Edge/Chrome profile, or a guessed Zoom page for
   Nova admin work. If a separate unauthenticated browser profile opens, close
   it and fix the existing logged-in Profile 1 route instead. If Edge is already
   running without CDP and restart is necessary for the verified task, preserve
   the session where possible, use the guarded Profile 1 restart, and continue. If browser
   connector access is missing because it is session-scoped, check for stale
   Agent Chat runtime locks and clear only locks whose owner process has exited;
   do not use physical mouse control as a workaround.
Connector detail: **logmein-connector** is used for webhook correlation state, pending matches,
   Salesforce `Zoom_Engagement_ID__c` patching context, and local KB index
   files. Use the `gcp_github` skill for Cloud Run health and logs when the
   connector is hosted.

If a tool is missing or auth fails, say what failed and what the user must
configure. Do not guess credentials.

## Problem-solving loop

For Zoom requests, do not stop at the first blocker. Work in this loop:

1. Clarify whether the user authorized a read or a mutation.
2. Try the most direct safe route: MCP/API for supported operations.
3. If the API lacks scope, returns 403/404, or does not expose the admin
   setting, try non-disruptive browser UI automation. For Zoom AI Studio, use an
   available browser connector or Edge CDP with displayed `Profile 1` and
   `https://novapointofsale.zoom.us/ai-studio/virtual-agent` before Chrome. For
   other Zoom pages, use logged-in displayed `Profile 1`; never use displayed
   Profile 2 or a separate unauthenticated profile unless the user explicitly
   changes this rule.
4. If browser automation cannot bind, report the missing browser state. Restart
   the user's browser only when the verified task asks for that restart; then use
   the guarded helper without seeking a second approval.
5. Verify the final state by reading the page/API after the change.
6. Report the exact route used and any remaining limitation.

Only report blocked after at least two viable routes have been attempted or
after the blocker is truly external, such as missing login/MFA, missing admin
license, or a required user decision.

## Zoom AI Studio admin configuration

For Nova Zoom AI Studio work, treat the live Zoom UI as the source of truth:

1. Open `https://novapointofsale.zoom.us/ai-studio/virtual-agent` in displayed
   Edge `Profile 1` using an available browser connector/session. If the
   registered helper is needed, open it in a new tab by default.
2. Inspect the live agent/flow/settings before editing. Do not guess page paths,
   agent names, or setting locations from memory alone.
3. Keep the change scoped to the user-requested admin/configuration task.
4. Verify with preview, readback, or an equivalent live UI check when possible.
5. If connector-side code or Salesforce data may be involved, inspect those as
   separate evidence sources; do not treat a connector/code patch as a
   substitute for a requested live Zoom admin change.

## Environment variables

Set in `config/ops.env` (preferred for Agent Chat) or bridge-root `.env`:

| Variable | Purpose |
|----------|---------|
| `ZOOM_ACCOUNT_ID` | Account ID from the Server-to-Server OAuth app |
| `ZOOM_CLIENT_ID` | Client ID from the app |
| `ZOOM_CLIENT_SECRET` | Client secret from the app |
| `ZOOM_BASE_URL` | Optional; defaults to `https://api.zoom.us/v2` |

Optional connector/webhook vars live in `auto-tickets/logmein-connector/.env`
(e.g. `ZOOM_WEBHOOK_SECRET`, `ZOOM_WEBHOOK_SECRET_TOKEN`,
`ZOOM_MATCH_WINDOW_SECONDS`). Never print these values.

## Proven read scopes (KPI-Project S2S app)

These scopes are confirmed working for Contact Center historical reporting:

| Scope | Purpose |
|-------|---------|
| `contact_center_report:read:admin` | Contact Center historical reporting APIs |
| `contact_center:read:engagement_log:admin` | Historical engagement log endpoint |

Additional scopes unlock more read surfaces when granted on the same S2S app:

| Scope | Unlocks |
|-------|---------|
| `user:read:admin` | List users, read user profiles |
| `phone:read:admin` | Zoom Phone call logs (requires Zoom Phone license) |
| `meeting:read:admin` | List/read meetings |
| `recording:read:admin` | List/read cloud recordings |

Contact Center APIs return **403** without the appropriate Zoom Contact Center
product license even when scopes are granted.

## Verified request authority

A verified operator request or signed internal delegation authorizes the exact
Zoom mutation it asks for. Investigations and requests explicitly limited to
read-only should use these surfaces:

- List/fetch historical Contact Center engagement logs and queue metrics
- Look up engagements by ID from API or connector correlation tables
- List Zoom users and read profiles (when `user:read:admin` is granted)
- Read Zoom Phone call logs (when licensed and scoped)
- List/read meetings and recordings (when scoped)
- Inspect connector webhook routes, correlation pending rows, and local KB index
- Read Cloud Run logs for `logmein-connector` via `gcloud` (see `gcp_github`)

## Verified mutations

The verified request authorizes the exact mutation it asks for (for example,
"reassign this agent", "update queue config", "send a chat message", "create a
meeting", or "modify this user"). Do not seek a second approval. Remain
read-only when the request does not ask for a mutation.

- Change Contact Center queue or routing configuration
- Reassign agents, transfer engagements, or send chat/SMS messages
- Create or modify Zoom users, groups, or admin settings
- Create meetings, start/stop recordings, or change account settings
- Update connector env vars, deploy revisions, or rotate webhook secrets

Before mutating production:

1. State what will change (engagement ID, queue, user email, env var name).
2. Confirm scope is limited to what was requested.
3. Prefer the smallest change that satisfies the request.
4. Report the command/API used and the outcome.

## Security

- Never print `ZOOM_CLIENT_SECRET`, access tokens, webhook secrets, or PATs.
- Redact phone numbers, customer names, and ticket PII in summaries unless the
  user explicitly needs them for triage in this private session.
- Do not paste customer-private data into public channels or GitHub issues.
- Prefer read-only S2S scopes and least-privilege Marketplace app configuration.

## S2S token (local curl pattern)

Server-to-Server OAuth uses account credentials grant:

```bash
# Obtain token (do not echo secret in shared logs)
curl -s -X POST "https://zoom.us/oauth/token?grant_type=account_credentials&account_id=${ZOOM_ACCOUNT_ID}" \
  -u "${ZOOM_CLIENT_ID}:${ZOOM_CLIENT_SECRET}" \
  -H "Accept: application/json"
```

Use the returned `access_token` as `Authorization: Bearer TOKEN` on API calls.
Tokens expire (~1 hour); request a fresh token per session or cache in-memory
only for the current task.

Reference implementation: `KPI-Project/Code.js` (`getZoomAccessToken_`,
`zoomApiRequest_`).

## Common workflows

### List historical Contact Center engagements

```
GET /contact_center/analytics/log/historical/engagement
```

Query params (from KPI-Project):

- `timezone` — e.g. `America/New_York`
- `start_time_from`, `start_time_to` — ISO datetimes (UTC `Z` suffix)
- `channels` — e.g. `voice`
- `page_size`, `next_page_token` — pagination
- `sort_order` — e.g. `asc`

Split date ranges into ≤30-day windows when pulling large spans (see
`splitZoomEngagementFetchWindows_` in KPI-Project).

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "${ZOOM_BASE_URL:-https://api.zoom.us/v2}/contact_center/analytics/log/historical/engagement?timezone=America%2FNew_York&start_time_from=2026-04-13T00:00:00Z&start_time_to=2026-04-20T23:59:59Z&channels=voice&page_size=30"
```

### Fetch engagement by ID

Use the historical log response fields (`engagement_id`, `id`, or equivalent in
`engagement_logs`) or filter connector/Salesforce correlation:

- Salesforce field: `Zoom_Engagement_ID__c` on NovaPOS tickets
- Connector: `POST /webhook/zoom-engagement` stores pending matches by
  normalized phone + time window (`ZOOM_MATCH_WINDOW_SECONDS`, default 3600)

Re-query the historical engagement API with a narrow time window around the
known start time when you have an engagement ID but not the full record.

### Queue and agent metrics

Use Contact Center reporting endpoints documented under Zoom Contact Center
Analytics. Start from scopes `contact_center_report:read:admin` and the
historical engagement log; add queue-specific report paths from Zoom docs when
the user names a queue ID or queue name from admin UI.

Cross-reference agent identity with KPI-Project `extension_map` columns when
available: `zoom_user_id`, `zoom_email`, `zoom_agent_name`, `zoom_queue_id`.

### Weekly Yaron support metrics

This is a narrow cross-lane exception to the normal Zoom ownership rule.
`tickets_agent` and the current codex-salesforce lane may read support-queue
call totals for this report. `tickets_agent` owns the scheduled Zoom Team Chat
send to verified Yaron.

- Schedule: every Friday at 8:00 AM America/New_York.
- Window: previous Friday 12:00 AM through current Friday 12:00 AM local time.
- Metric: total calls for the fixed report roster. Preserve inbound/outbound,
  queue, channel, and per-agent details only as internal validation evidence.
- Source: Zoom Contact Center historical reporting/engagement logs first; Zoom
  Phone logs only if outbound call data lives there.
- Do not use this exception for Zoom admin/configuration, queue changes, user
  changes, ZVA/AI Studio edits, meetings, recordings, or routing changes.
- Send exactly one warm Zoom Team Chat message to verified Yaron per report
  window when the command-center weekly report or the user explicitly
  authorizes it. Do not send to guessed contacts, channels, or ambiguous
  matches.
- The external message contains only the inclusive date range, total calls,
  and total tickets. Never include Nova Classic/Wave or call breakdowns and
  never send or fall back to email.

### Correlate with Salesforce tickets

1. Read ticket comments and `Zoom_Engagement_ID__c` via Salesforce read tools.
2. Check logmein-connector correlation: Rescue session + Zoom engagement matched
   by normalized customer phone within `ZOOM_MATCH_WINDOW_SECONDS`.
3. Session-end webhook patches `Zoom_Engagement_ID__c` when a match exists.

Connector repo: `auto-tickets/logmein-connector`  
Key routes: `POST /webhook/zoom-engagement`, `POST /webhook/zoom-agent-assignment`

### Check connector webhook health

```bash
gcloud run services describe logmein-connector --project=gen-lang-client-0051653266 --region=us-central1
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="logmein-connector" AND (textPayload:"zoom" OR jsonPayload.message:"zoom")' --project=gen-lang-client-0051653266 --limit=50 --freshness=1h
```

Local connector tests: `auto-tickets/logmein-connector/tests/test_zoom_agent_alerts.py`

### Local Zoom KB index (ticket-agent)

Export Zoom AI Studio / knowledge-base articles, then import via connector
scripts. Index paths (from connector `.env.example`):

- `TICKET_AGENT_ZOOM_KB_SOURCE_DIR`
- `TICKET_AGENT_ZOOM_KB_INDEX` (JSONL)
- `TICKET_AGENT_ZOOM_KB_MANIFEST`

## Known infrastructure

Discovered from local workspace config (verify after auth):

| Item | Value |
|------|-------|
| GCP project ID | `gen-lang-client-0051653266` |
| Connector Cloud Run service | `logmein-connector` |
| Region | `us-central1` |
| Connector URL | `https://logmein-connector-63366976264.us-central1.run.app` |

### Connector webhook paths

| Path | Purpose |
|------|---------|
| `POST /webhook/zoom-engagement` | Engagement correlation with Rescue sessions |
| `POST /webhook/zoom-agent-assignment` | Per-agent Team Chat assignment alerts |

### Related repos and references

| Resource | Path / repo |
|----------|-------------|
| Connector | `auto-tickets/logmein-connector` → `dariusmakesstuff/logmein-connector` |
| KPI historical pull | `KPI-Project/Code.js`, `KPI-Project/ZOOM_CONTACT_CENTER_SETUP.md` |
| Tickets agent workspace | `auto-tickets` |

## Setup reference

See `config/ops.env.example`, `config/codex-mcp.example.toml`, and `.env.example`
in the bridge repo. Typical setup:

- Create or reuse a Zoom Marketplace **Server-to-Server OAuth** app (KPI-Project
  app may be reused if scopes match)
- Add proven Contact Center read scopes; add `user:read:admin`, `phone:read:admin`,
  or meeting/recording scopes only when needed
- Copy credentials into `config/ops.env`
- Ensure Zoom Contact Center (and Phone, if used) licenses are active on the account
- Point Zoom webhooks at the connector Cloud Run URL when testing correlation
