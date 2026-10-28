<!-- AgentChat/coding_agent 2026-07-10T02:31:44Z -->

# Nova Ops Kanban Command Center Prototype

Static prototype built from the Telegram Desktop reference files:

- Complete target screenshot: `E6F2F1E1-F695-45DA-8FA3-A934F911642D.png`
- Sprite and asset sheet: `D5EE9C83-1663-4B42-94A2-3A3FE6D1FD42.png`
- Plan: `nova_ops_kanban_command_center_plan.md`

Open `index.html` directly in a browser. No build step is required.

The board renders from `ticket-data.js`, which is a read-only Salesforce open-ticket snapshot generated on 2026-07-09. Cards show account, days active, main issue, technical issue, opened-by, and notes preview. Hover the notes area to see full technical notes and who opened the ticket.

Board eligibility rules:

- Render only real customer accounts: exclude account names containing `demo`, `test`, or `template`.
- Render only open Salesforce tickets where the Salesforce closed flag is false.
- Support Tickets are only `1. NOVA Classic` and `2. Nova Wave` record types.
- Billing Tickets are only Billing/Nova Billing record types.
- Exclude support tickets whose Technical Issue is `Bug` or `Feature Request`.
- Exclude Account Management and Development record-type tickets from every kanban lane.
- Keep Nova Classic/Nova Wave tickets when Main Issue is `Development Service`; those are support work items that typically require SQL investigation.
- Re-route visible tickets by record type at render time: Billing record types go to Billing Tickets, support record types go to Support Tickets, and accepted active dispatch jobs go to Assigned / In Progress.
- Do not use stale age alone to put tickets in Needs Review. Needs Review should only contain explicitly flagged review/escalation tickets.
- Future `ticket-data.js` refreshes should preserve Salesforce status fields such as `Status__c`, `IsClosed`, and `ClosedDate` so closed-ticket filtering is exact instead of note-derived.
- Ticket refreshes must also preserve useful Salesforce Chatter/comments. The dashboard reads `chatterSummary`, `chatterItems`, `salesforceComments`, `caseComments`, `comments`, `feedItems`, or `feedElements` and appends them under `Salesforce Chatter / Comments` in the Technical Notes panel.
- Ticket refreshes must preserve Technical Notes plus LogMeIn/Session History context. The dashboard reads `logmeinSessionId`, `rescueSessionId`, `Rescue_Session_ID__c`, `sessionHistorySummary`, `sessionHistoryItems`, `Session_History__c`, `Session_History__r`, and similar Rescue/Zoom/session fields, then shows a compact `LogMeIn / Session History` section above the Technical Notes when available.

Ticket refresh:

- The browser loads the static `ticket-data.js` first so the board works when the gateway is down.
- When the gateway is running, the browser reads live cached tickets from `GET http://127.0.0.1:17866/ops/tickets` and checks that cache every 60 seconds.
- Background refreshes must preserve scroll positions in the kanban lanes, detail notes, agent replies, email drawer, meetings, activity feed, analytics, and Spotify library. Do not replace a scrolling section without restoring its previous scroll offset.
- The Quick Stats `SYNC` button queues a read-only Salesforce refresh through `POST http://127.0.0.1:17866/ops/tickets/refresh`.
- The gateway also refreshes the ticket cache in the background using `ops_ticket_refresh_interval_seconds` from `config/agents.yaml`.
- The live cache is written to `data/command_center/ops_tickets.json`; it should include only currently open Nova Classic, Nova Wave, and Billing tickets.
- The Activity page reads current command-center jobs from `GET http://127.0.0.1:17866/jobs?limit=200` and derives each agent's current queued/running work or latest completed/failed update. Do not use static placeholder activity for the live dashboard.
- For deeper operator debugging, `GET http://127.0.0.1:17866/runtime/status?limit=50` returns bridge job counts, recent jobs, persistent Codex sessions, and runtime locks. Use this when an agent appears stuck, waiting, or blocked by another surface.
- The Analytics page reads compact KPI cache data from `GET http://127.0.0.1:17866/ops/kpi-dashboard`.
- The Analytics `SYNC KPI` button queues Taylor/Ops through `POST http://127.0.0.1:17866/ops/kpi-dashboard/refresh` to read the Google KPI dashboard read-only and write `data/command_center/ops_kpi_dashboard.json`.
- KPI refreshes also run in the background using `ops_kpi_dashboard_interval_seconds` from `config/agents.yaml`. The browser should never directly load or process heavy Google Sheets/dashboard data.

The office floor uses `assets/office-map/nova-ops-office-map.png`, generated with the installed `generate2dmap` workflow as a character-free office map. Alex, Jamie, Taylor, and Thor use the active PNG sprites in `assets/forge-office-agents/`; the team lead uses `assets/team-lead-desk/team-lead-1.png`, regenerated as a seated-at-desk sprite.

Movement semantics:

- `working`: agent stays at their desk with orange status.
- `complete`: agent walks from their desk to the center handoff point, pauses, then walks back to their desk with green status.
- `waiting`: agent walks to a spot beside the team lead and stays there until feedback is given.
- handoff: when a card already assigned to one agent is dropped onto another agent, the source agent walks an actual route to the receiving agent's desk, pauses, and returns.
- Taylor is a Tech Support team member with engineering and operations
  responsibilities. She remains at the engineering desk unless her activity
  state is `waiting`.
- Thor is the lower-right flying support-quality lane and maps to the
  compatibility runtime ID `claude_agent`. Thor accepts general quality tasks,
  never Salesforce ticket drops.

Ticket board sizing:

- Drag the cyan/green handle between the office and the ticket lanes to slide the ticket board up or down.
- The height is stored in `localStorage.novaOpsTicketBoardHeight` so the dashboard opens at the last chosen split.
- Sliding the board upward is a local view preference only; it does not change Salesforce ticket state or agent assignment.

Spotify widget:

- The topbar Spotify control uses Spotify's lightweight embed iframe, loaded only when the widget is expanded.
- It stores the last pasted Spotify URL in `localStorage.novaOpsSpotifyUrl`.
- It accepts `open.spotify.com` URLs or `spotify:` URIs for tracks, playlists, albums, artists, shows, and episodes.
- Account linking uses the command-center gateway with Spotify Authorization Code + PKCE. Configure a Spotify Developer app with redirect URI `http://127.0.0.1:17866/ops/spotify/callback`, set `SPOTIFY_CLIENT_ID` in the command-center environment, then restart the gateway.
- Connected account tokens are stored locally at `data/command_center/spotify_account.json`; do not commit or print that file.
- Account mode can browse playlists, playlist songs, saved tracks, and track search through the Spotify Web API. Playback controls target the user's active Spotify Connect device and require Spotify Premium for start/resume playback.
- Agent music reactions are CSS-only and activate only when the Spotify playback status reports `isPlaying`; the toggle is stored in `localStorage.novaOpsSpotifyAgentDance`. Each office sprite gets a lightweight dance/groove animation plus small pixel speech and music-note bubbles, with staggered timing so they do not all move identically.

Dispatch semantics:

- Selecting a ticket, dropping it on an agent, or dropping it anywhere on the compact Agent Dispatch form attaches that Salesforce ticket to the dispatch form.
- Dropping a ticket on an agent selects that ticket and agent, but does not move the ticket into Assigned / In Progress by itself.
- Choosing an agent and submitting notes builds a prompt payload containing the ticket number, Salesforce URL, account, issue fields, opened-by value, and operator instruction.
- The Agent Dispatch mode switch supports `Ticket` and `General Task`. Use `General Task` for DevOps, repo, research, tool, or operational work that is not tied to a Salesforce ticket. General task payloads use `type: general-agent-task`, a `taskId`, a `taskTitle`, and a prompt that explicitly says there is no Salesforce ticket context unless the operator says otherwise.
- Dispatch prompts also include a trimmed Technical Notes / Chatter context block from the selected ticket. Long raw chat logs are omitted from the dispatch prompt, but remain visible in the dashboard/ticket when present.
- Dispatch payloads include a stable idempotency key built from ticket, agent, and instruction. The browser disables the submit button while a send is in flight, and the gateway ignores duplicate ticket/write dispatches inside `command_center_mutation_idempotency_seconds` instead of creating extra agent jobs.
- Ticket-note/Chatter, review-packet close/follow-up, and guarded Gmail-send prompts must tell agents to read back the target feed/thread before retrying, post/send at most once, and skip the write when the same note/body/result is already present.
- Do not emit successful dispatches through local browser events or `postMessage`; those fallback channels can create a second delivery path and flood an agent. The local dispatch queue is only for gateway-unavailable fallback storage and is deduped by idempotency key.
- The page posts dispatches to the standalone Nova Ops Command Center gateway at `http://127.0.0.1:17866/dispatch`, which queues the prompt into the existing persistent agent lane. The gateway can run in the background even when Agent Chat Desktop and this static dashboard are closed.
- Before dispatch, the browser checks `GET http://127.0.0.1:17866/health` and refuses to send unless the service is `nova-ops-command-center`. This prevents accidental sends to the Agent Chat Desktop listener on `17865`.
- The live gateway issues a per-launch browser session when `/dashboard/` is opened. Every API read requires that session; every browser mutation also requires the exact loopback origin and the dashboard CSRF token. Trusted native bridge/supervisor clients use the separate per-launch bearer stored outside the workspace. Anonymous and `Origin: null` API requests are rejected, and sensitive responses use `Cache-Control: no-store`.
- Assigned / In Progress is populated from `GET http://127.0.0.1:17866/jobs?active=1&limit=100`; queued or running command-center jobs from active source types appear there, including ticket dispatches, review-packet jobs, general tasks, and active background ops jobs.
- A temporary review packet is created only for a concrete, ready-to-execute proposal whose remaining dependency is an explicit operator decision. `FAILED` jobs never create review tasks; their original instruction, job payload, and failure result remain together on the originating job/chat surface. Blockers and status-only outcomes also stay out of review unless they contain a supported explicit operator-action disposition.
- The browser reads qualifying review packets from `GET http://127.0.0.1:17866/ops/review-packets` and renders them in Needs Review as packet cards. A packet replaces the normal support/billing card for the same ticket until it is resolved, so actionable context stays in one place.
- Selecting a packet exposes `Send Follow-up`, `Abandon`, and `Proceed & Close`. `Send Follow-up` queues `/ops/review-packets/continue` with the packet plus the operator note. `Proceed & Close` queues `/ops/review-packets/proceed-close`; the agent must re-check live Salesforce before closing.
- `Abandon` posts to `/ops/review-packets/abandon` and removes the local review packet only. It does not close Salesforce, write Chatter, notify the customer, or store a resolution learning entry. Use it for miscategorized/out-of-scope packets such as tickets that belong to Development or another team.
- When a Nova Classic/Nova Wave `Development Service` ticket is completed or closed, the agent must also set Salesforce `Development Service Status` to `Completed`, after confirming the exact field API name and allowed picklist value from live describe metadata, then read it back.
- Review packets are temporary. After the close job verifies Salesforce closure and returns `CLOSED_PACKET:<packet-id>`, the gateway deletes the packet and stores the reusable resolution pattern in shared agent memory. Do not convert packets into markdown handoff files.
- Start the gateway with `scripts/start-command-center-server.ps1` when ready. This source change does not start or restart it automatically.
- To make the gateway launch at Windows sign-in, install the startup task with `scripts/install-command-center-startup-task.ps1`. Remove it with `scripts/uninstall-command-center-startup-task.ps1`.
- If the gateway is not running, the page stores the most recent payloads in `localStorage.novaOpsAgentDispatchQueue` only; it does not emit browser dispatch events.
- Salesforce tickets may include linked Zoom Contact Center session history, Smart Notes, call transcript/recording metadata, and Technical Notes. The dashboard should treat those as ticket-linked context and avoid copying full transcripts into routine dispatch prompts unless needed.

Ops mail and schedule:

- The Email tab and the right-column Mail slideout read the current live-verified unread-and-unanswered action queue from `data/command_center/ops_email_watch.json` through `/ops/email-watch`. The JSON is replaceable queue state, not an Inbox mirror, archive, failure feed, or FYI history.
- The Mail SCAN button queues Taylor/Ops through `/ops/email-watch/scan` to reconcile candidates against live Gmail, read their threads, search matching email templates, and write body-only reply recommendations. It must remove read threads and threads whose latest message is `SENT`; a newer unread inbound message after a reply can reappear. Failures, FYI, automated status, waiting-without-action, and no-action mail stay out. Scanning must not send mail, modify drafts, or overwrite the existing Gmail signature.
- The Mail drawer shows `Mark read / no action` for cached emails and posts to `/ops/email-watch/mark-read`; the backend validates the cached Gmail thread/message and allows only removing `UNREAD`, then removes the item from the visible cache. Salesforce notification emails are still treated as ticket-context alerts, but the same no-action control is available for any email Darius wants cleared without a reply.
- Each Mail recommendation has an editable body. `Copy Body` copies the edited body for manual paste above the existing Gmail signature.
- `Send With Signature` is separate from scan and posts to `/ops/email-watch/send-reply`. The backend validates the selected Gmail thread/message id, subject, and sender against the current email-watch cache, rejects browser-supplied To/Cc/Bcc fields, reads the active Gmail `sendAs` HTML signature, inserts the edited body above it, sends directly to the verified thread, and reads the exact sent message back. No agent/browser compose step is used. If the native signature or sent-message readback cannot be verified, the gateway stops without a blind retry.
- If send returns `not found`, the dashboard should first verify `/health` is the `nova-ops-command-center` service and then tell the operator to reload the dashboard or restart the gateway after jobs finish. This usually means the browser is on a stale build or the port is not serving the command-center gateway.
- Email send requests receive a server-side idempotency key from the verified thread/message/body. A durable send journal and an RFC message header prevent double-clicks, page retries, uncertain results, or repeated POSTs from sending a duplicate.
- The left-column Meetings panel reads `data/command_center/ops_schedule.json` through `/ops/schedule`.
- The Meetings SYNC button queues Taylor/Ops through `/ops/schedule/scan` to inspect Google Calendar, Gmail, and Zoom read-only for upcoming meetings.
- An operational or critical email, or concrete meeting preparation explicitly directed to Darius, may create one deterministic, operator-owned Drawing Board brief keyed to its source thread/event. The brief requires a concrete outcome, immediate next action, Darius's exact owner action, source, and objective done criteria. It is updated rather than duplicated and is never auto-dispatched. Support-ticket mail, Salesforce notifications, automated telemetry/failures, Singapore existing/retired-interface, authentication/upload-status/remediation mail, and vague invitations never become Drawing Board briefs.
- When the gateway is running, it refreshes the mail cache using `ops_email_watch_interval_seconds`; the schedule cache is checked daily but auto-refreshes only once per configured weekly schedule window, currently Tuesday in `America/New_York`, through `ops_schedule_watch_weekday` and `ops_schedule_watch_timezone` in `config/agents.yaml`. The Meetings SYNC button remains available for manual refreshes.
- Singapore POS upload and non-submission work is a separate Taylor/Ops background workflow. The gateway reads `data/command_center/ops_singapore_ftp.json` through `/ops/singapore-ftp`, queues the guarded headless runner through `/ops/singapore-ftp/scan`, and checks it on the configured five-minute interval. Private Gmail and canonical server state remains outside the repo under `C:\Users\redma\Uploader`; agents must never expose or copy raw values into logs, prompts, docs, memory, or chat. Taylor ignores zero-sales, sales-verification content, and canonically retired interfaces unless explicit reactivation is requested. Operational upload/status/authentication/remediation/configuration/reactivation outcomes never create Salesforce tickets or Needs Review packets; only an explicit brand-new integration/interface request may enter the ticket lane. Active work produces one compact sanitized direct Agent Chat update. True non-submission dates go only to the exact configured Julio Zoom contact, with source-message acknowledgement after message-id readback.
- Runtime ownership, configuration, verification, and rollback for the consolidated Gmail collector and independent Singapore scheduler are documented in `docs/COMMAND_CENTER_EMAIL_AND_SINGAPORE_RUNTIME.md`.
