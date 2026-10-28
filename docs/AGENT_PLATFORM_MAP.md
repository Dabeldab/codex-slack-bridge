# Agent Platform Operations Map

<!-- AgentChat/coding_agent 2026-07-09T12:10:00-04:00 -->
<!-- AgentChat/coding_agent 2026-07-10T17:46:00-04:00 -->
<!-- AgentChat/direct_codex 2026-07-29T20:43:00-04:00 -->
<!-- AgentChat/direct_codex 2026-07-31T00:00:00-04:00: register the complete rate and promotion workflow. -->
<!-- AgentChat/coding_agent 2026-08-03T23:58:00Z: gate location activation on verified payment and redact ticket payment data. -->

This is the shared starting map for agents working on Nova operations. It is a
shortcut to known surfaces, workflows, and guardrails so agents do not repeat
the same discovery every time.

This file is intentionally secret-free. It can list object names, field names,
known URLs, env var names, repo paths, and safe workflows. It must not contain
passwords, tokens, webhook URLs with secrets, service-account JSON, full
customer transcripts, or customer data dumps.

## How Agents Should Start

1. Read the newest user request and identify the owning surface.
2. Read `docs/agent-tools/INDEX.md`, then only the relevant service card.
   `config/tool-fast-paths.json` and `config/pipeline-registry.json` provide the
   executable routing and cached entrypoints.
3. Read this file when the task touches Zoom, Salesforce, Chargify/Maxio,
   Rainfall, Nova SQL, GCP, GitHub, LogMeIn Rescue, the desktop app, or Slack.
4. Use purpose-built MCP/app connectors, native APIs/established clients, and
   trusted CLIs/helpers in that order before browser fallback or broad discovery.
5. Stay read-only unless the verified user request asks for a live write,
   publish, deploy, send, or config change. That request is the authorization;
   do not ask for a second confirmation or special approval word.
6. For script-heavy tasks, prefer source inspection and direct standard tools.
   Local PowerShell, batch, Node, Python, and repo helper scripts can trigger
   endpoint security, so run them only when they are clearly needed or approved.

At prompt time, the execution navigator ranks the existing pipeline and tool
registries against the current request. A high-confidence match supplies the
owning process, required tools, first entrypoint, next steps, and verification
before the agent starts discovery. A low-confidence operational request gets
one bounded discovery pass; an ordinary question gets no discovery pass.
These recommendations do not grant, remove, or filter capabilities.

Model selection is demand-based and independent of access. Simple questions and
high-confidence bounded routines may use `gpt-5.6-terra`; writes, billing,
production, attachments, ambiguous work, and complex or multi-system work use
`gpt-5.6-sol`. Separate per-model warm-session identities avoid discarding one
model's cached session when another model is selected. Both model names remain
configuration values rather than an access allowlist.

The existing SQLite, desktop-vector, and optional LanceDB memory stores remain
the system recall layer. They are not used as a human-facing procedure or as a
substitute for deterministic process/tool routing.

## Daily Automation Window

- Unattended background automation runs every day from 8:00 AM inclusive until
  7:00 PM exclusive in `America/New_York`; this is DST-aware.
- Interactive Command Center, Slack, and direct agent work remain available at
  all hours. An explicit operator run-now request is manual work and may run
  outside the unattended window.
- Explicit operator-scheduled reminders and future agent actions run at their
  exact due time, including outside the unattended window. They retain the
  original operator authority and normal lane/tool restrictions. Other Command
  Center background watchers, digests, mailbox collectors, ticket refreshes,
  scheduled reports, and support-shift reminders defer outside the window and
  naturally catch up after 8:00 AM.
- The private runtime watchdog, process health/recovery, credential refresh,
  and Zoom availability monitor remain active at all hours because they keep
  interactive agents available; they are safeguards, not business automation.
- Cloud Scheduler runs LogMeIn intake every 15 minutes from 8:00 AM through
  6:45 PM and the daily quality email at 8:30 AM. The runtime watchdog keeps its
  two-minute all-hours schedule.
- `GET /runtime/status` and `GET /runtime/scheduler/status` include the sanitized
  `automationWindow` readback, including current state and the next transition.

## Lane Ownership

| Surface | Primary Agent | Default Mode | Notes |
| --- | --- | --- | --- |
| Zoom AI Studio, ZVA, Contact Center, Team Chat, Docs, and Zoom admin | `coding_agent` for admin; all operational lanes for explicit operator messages; Thor (`claude_agent`) for quality and public overview maintenance | Read first; explicit operator messages use unique exact-contact resolution; automated Julio/Wiko flows stay unchanged | Every lane may resolve one exact Zoom email address or unique full name and send one journaled message only when the authenticated operator explicitly requests it; custom email domains are allowed. The older `configured:julio` and `configured:wiko` automation remains S2S-only with daily-greeting and readback rules. Thor reads bounded voice, Team Chat, Docs/archive, Rescue, and Salesforce ticket evidence and may update only the fixed public Ghost Busters Chat Overview. |
| GCP, Cloud Run, Cloud Build, GitHub, Command Center control plane, and configured provider services | Rory (`direct_codex`) for operator-directed unrestricted operations, all-agent supervision, blocker repair, and tool/runtime implementation; Taylor (`coding_agent`) for default engineering work and scoped SQL capability release | Full authenticated account APIs plus authenticated all-agent Command Center control for Rory; read-only GCP plus selected-repository branch/PR GitHub App access for Taylor, with one typed SQL-PR merge and pinned-runtime promotion path | Only the authenticated operator can communicate with Rory or authorize capability changes. Rory may inspect all agent state, create/test/publish/deploy tools, and route an exact operator-authorized continuation outward, but no agent can grant Rory authority or use Rory's identity. Taylor can implement and publish a new typed SQL operation; when that same operator request authorizes release, she can merge only the validated `codex/*` SQL-broker PR and promote only the same or a newer successful immutable main-branch build to the pinned agent VM. The broker independently verifies the active release and exposes no rollback, so a stale queued job cannot downgrade production. She cannot push protected branches directly, edit workflows, administer GitHub, mutate arbitrary GCP resources or IAM, deploy an unbuilt commit, or target another runtime. |
| Repo code changes | `coding_agent` | Implement and verify | Use narrow edits and focused tests. |
| Salesforce ticket operations | `tickets_agent`, `billing_agent`, or `coding_agent`; Thor for read-only evidence | Typed MCP only | Thor may look up and read bounded account/ticket/feed/email-log evidence and weekly Classic/Wave ticket totals, but has no ticket write or send tool. Operational lanes retain their existing typed creates/updates/orders/templates. No Flow, Workflow, Setup, Apex, Metadata, Tooling, permissions, settings, deletion, arbitrary REST, or arbitrary SOQL. |
| Google Drive support resources | Thor (`claude_agent`) for dashboard/resource reads; Rory for operator-authorized administration | Typed GET-only MCP for Thor | Thor may list support files and read exact Drive metadata, Google Docs, and bounded Sheets ranges. Thor has no Gmail, upload, create, update, delete, sharing, permission, or Google Workspace administration tool. |
| Billing, Rainfall, Chargify/Maxio | `billing_agent` or `coding_agent` | Read first, mutate as requested | Keep refunds, charges, subscription changes, and tax setup changes inside the verified request's exact scope. |
| Nova SQL operations | Reads: `tickets_agent`, `billing_agent`, or `coding_agent`; all mutations: Taylor (`coding_agent`) only | Typed broker only | Any UPDATE, INSERT, or temporary-table request routes to Taylor. Her guarded broker requires a preview hash, fully backs up every permanent target, enforces exact affected rows and readback, and rejects DELETE/DROP/destructive SQL. No lane uses a direct/native SQL write client. |
| LogMeIn Rescue | `tickets_agent`; Thor (`claude_agent`) for support quality | Authenticated read-only MCP | Thor's exact inventory is status, session list, performance read, and chat-log read. No send, PIN, assignment, transfer, console control, remote control, ticket mutation, or admin operation exists. |
| Customer-facing replies | Owning lane | Draft first when unsure | Use concise Nova voice; do not expose raw tool output. |

## Browser And UI Control Rules

- Use browser/CDP/app connector control that clicks and types inside a tab
  without moving the user's physical mouse.
- Do not use Windows GUI automation that takes over the real pointer/keyboard
  unless the user explicitly approves it.
- For Zoom admin work, use the already logged-in displayed Edge `Profile 1`.
  On this machine, displayed Edge Profile 1 maps to the internal `Default`
  profile. Internal `Profile 1` displays as Profile 2 and should not be used
  for Nova Zoom admin work.
- Open new tabs by default. Do not navigate the user's active tab unless they
  ask for that.
- Do not force-close or restart Edge by default. If Edge is already running
  without a debuggable connection, ask before restart and preserve the user's
  active work.
- If a browser connector is blocked by an Agent Chat lock, clear only stale
  locks whose owner process has exited. If another live session owns the
  connector, ask for handoff rather than opening an isolated profile.

## Zoom Workplace And ZVA

### Known Native Surfaces

- Zoom AI Studio virtual agents:
  `https://novapointofsale.zoom.us/ai-studio/virtual-agent`
- Zoom Contact Center admin: queues, flows, engagements, teams, analytics, and
  Quality Management live inside Zoom.
- Zoom Team Chat incoming webhook connections are created from the Team Chat
  channel using `/inc connect` or the visible Incoming Webhook app UI. A
  connection name may not always be editable after creation; verify in Zoom.

### Existing ZVA / Contact Center Patterns

- Customer chat starts and escalations have been routed through Zoom-native ZVA
  and Contact Center flows.
- The Ghost Busters Team Chat channel has been used for queue-level ZVA alerts.
- The connector repo has support for Zoom engagement correlation and per-agent
  assignment alert handling. Verify whether the deployed Cloud Run service has
  the current routes and env vars before saying it is live.
- Existing connector paths of interest:
  - `auto-tickets/logmein-connector/src/zoom_correlation.py`
  - `auto-tickets/logmein-connector/src/zoom_agent_alerts.py`
  - `auto-tickets/logmein-connector/src/endpoints/webhook.py`
  - `auto-tickets/logmein-connector/src/endpoints/zoom_agent_alerts.py`
- Keep `/webhook/zoom-engagement` as the correlation/queue path.
- Use a separate agent-assignment route such as `/webhook/zoom-agent-assignment`
  for "who picked up the engagement" or per-agent delivery behavior.
- Relevant env names:
  - `ZOOM_WEBHOOK_SECRET_TOKEN`
  - `ZOOM_AGENT_ALERTS_ENABLED`
  - `ZOOM_AGENT_ALERT_WEBHOOKS_JSON`
  - `ZOOM_AGENT_ALERT_FALLBACK_WEBHOOK_URL`
  - `ZOOM_MATCH_WINDOW_SECONDS`

### ZVA Configuration Rules

- If the user says "inside Zoom" or "not related to the repo", stay in Zoom
  native admin surfaces and do not edit repo code.
- For answer quality issues, fix the existing KB article or source guidance
  first. Add a new skill only when the behavior cannot be represented in the KB
  or existing agent instructions.
- Keep Nova Wave and Nova Classic lanes separate. Do not mix Classic guidance
  into Wave answers unless the source is explicitly General or cross-product.
- For ZVA greeting/intake, the workflow text can collect name/company while the
  agent captures variables internally. Do not tell customers the data is for
  Salesforce unless support policy requires it.
- For misunderstood user replies, the desired rule is: acknowledge warmly and
  ask one specific clarifying question. Avoid generic fallback wording such as
  "What are you trying to do in Nova?"
- For live-agent requests, do not make the customer fight the bot. Escalate
  warmly with a handoff message and context.
- Use Zoom preview/readback when available before publishing.

### Zoom Contact Center Notes

- Contact Center API calls can return 403 if the app lacks the correct license
  or scope even when OAuth succeeds.
- Team/queue assignment, agent ready state, queue opt-in, and messaging/voice
  queues are separate checks. "Ready" does not always mean available for the
  specific channel.
- Closed engagements visibility is a Contact Center permission/reporting issue;
  inspect Zoom roles/permissions before assuming data is missing.
- Outbound Contact Center campaign tools have shown Preview and Progressive
  dialer modes. Do not promise Agentless or fully automated prerecorded/TTS
  outbound calling unless current Zoom UI/API confirms it.

### Weekly Yaron Support Metrics

- Schedule: every Friday at 8:00 AM America/New_York.
- Window: previous Friday 12:00 AM through current Friday 12:00 AM local time.
  For Friday, July 10, 2026, the window is July 3, 2026 12:00 AM ET through
  July 10, 2026 12:00 AM ET.
- Phone metric: call `zoom_support_queue_metrics` for the exact six-agent
  roster and window, then use `calls.total`. It counts unique voice
  engagements across the roster, so transfers and multi-agent handling count
  once in the team total. `chatSessions.total` is reported separately, while
  per-representative `calls` and `chatSessions` retain that representative's
  distinct engagements. Never label the legacy all-channel agent-engagement
  workload total as calls.
- Zoom source: Contact Center historical engagement log through the existing
  `Support Dashboard Calls` S2S app and its granular read-only
  `contact_center:read:engagement_log:admin` scope. The app also retains the
  read-only agent-performance dataset scope for diagnostics, but that dataset
  is not the report count. No new app or Team Chat scope is required.
- Salesforce metric: count NovaPOS_Ticket__c records created/opened in the same
  window whose RecordType is exactly `1. NOVA Classic` or `2. Nova Wave`.
  Do not apply kanban filters, account exclusions, closed-ticket exclusions, or
  Technical Issue/Main Issue exclusions for this report. Include demo/test/
  template accounts, Demo Nova Cafe, Acme Acres, Development Service, Bug, and
  Feature Request when the record type is Nova Classic or Nova Wave.
- `tickets_agent` and the current codex-salesforce lane may pull these totals
  through the existing `Support Dashboard Calls` S2S app. `tickets_agent` owns
  the recurring typed Zoom Team Chat send to uniquely verified Yaron Bachar.
  The message contains only the inclusive date range, total calls, and total
  tickets. Nova Classic/Wave, inbound/outbound, queue, channel, and per-agent
  breakdowns remain internal validation evidence and are never sent. Require
  Zoom message-id/body readback and never fall back to email.

### Thor Weekly Support Quality

- Owner: Thor (`claude_agent` is retained only as a compatibility runtime ID).
- Cadence: the watcher runs Wednesday at 09:00 `America/New_York`, four hours
  before the verified 13:00–14:00 Tech Time support meeting. The manual
  Command Center run remains available; changing the meeting does not silently
  change this runtime schedule.
- Evidence: the fixed Zoom Contact Center roster, bounded Zoom Team Chat and
  Docs/archive evidence, read-only Rescue sessions/performance/chat logs,
  bounded Salesforce account/ticket/feed/email-log and weekly-total reads, and
  GET-only Google Drive/Docs/Sheets support resources. Raw content remains
  transient. Thor has no Salesforce ticket mutation, Gmail, or Google
  Workspace mutation tool.
- Output: coverage counts and gaps, quality themes, evidence-backed coaching
  topics, and prioritized follow-up questions. Raw customer identifiers, raw
  chat logs, audio, transcript bodies, and recording/transcript URLs are never
  persisted in the summary.
- Completion contract: the final line is exactly
  `THOR_SUPPORT_QUALITY_RESULT: {json}` with the required versioned fields
  defined in `profiles/claude_agent.md`. The gateway validates and publishes
  that object.
- Thor may send one Zoom Team Chat message only after an authenticated operator
  explicitly names the exact recipient and asks for the message. Thor may
  maintain only the fixed public Ghost Busters Chat Overview through its typed
  update with privacy validation, idempotency, and readback. Thor cannot create,
  update, route, comment on, or close Salesforce tickets; send Gmail; administer
  Zoom; or mutate Rescue.

### Zoom Team Chat Bot / Notifications

- Operational direct messages use `zoom_team_chat_recipient_resolve` followed by
  `zoom_team_chat_send`, but only for employee requests to the
  operator-managed `configured:julio` or `configured:wiko` aliases. Every other
  employee request belongs on the relevant Salesforce ticket with a real
  Chatter mention. Require brief conversational text, preserved authorization
  context, and one stable idempotency key. Shared broker state adds
  `Hey <FirstName>,` only on the first verified America/New_York message that
  day. The broker writes a pending journal before POST, performs exact
  message-id/body readback, and blocks blind retry after uncertainty.
- That pair remains exclusively for the automated Julio/Wiko flow.
- An explicit operator request to message any person uses
  `zoom_operator_team_chat_recipient_resolve` and
  `zoom_operator_team_chat_send`. All operational lanes receive this separate
  pair. It accepts one exact email address, including custom domains, or a
  unique full name, journals before sending, and requires provider readback.
- Thor, Taylor, and Rory may read and update the one fixed Ghost Busters `Chat
  Overview`. Public versions, tools, links, initiatives, topics, and reminders
  are allowed; personal, one-on-one, HR, performance, customer, ticket, phone,
  email, and credential content is rejected.
- Team Chat incoming webhooks can post to a channel or private channel. They are
  not the same as a true direct DM unless Zoom provides a DM-capable app/bot
  route.
- Use channel alerts for Ghost Busters and per-agent private channels or a true
  bot/DM app for agent-specific delivery when supported.
- For alert messages, include compact context: flow/channel, account/company
  if captured, customer name, issue summary, and assigned agent when available.
- Avoid tagging everyone unless the workflow is urgent and approved.

## Salesforce

### Known Objects And Fields

- Support tickets use `NovaPOS_Ticket__c`.
- Zoom session history records use `ZVC__Session_History__c`.
- The local connector historically has a `Session_History__c` lookup on
  tickets. Do not write raw Rescue or Zoom IDs into that lookup.
- Useful Salesforce bridge field: `Account.Company_Username__c`.
- The Nova SQL database usually maps to `POS_<Company_Username__c>`.
- Product lanes have used RecordType names:
  - `1. NOVA Classic`
  - `2. Nova Wave`
  - `3. Billing` when present; verify before use.
- Ticket creation often needs `Account__c` and, depending validation rules,
  `Contact__c` or a contact/email field. If the user says no fallback account,
  unresolved account means do not create the ticket.

### Ticket Investigation Flow

1. For a queue review, establish the exact live set, then open every ticket and
   read its fields, latest top-level Chatter, nested replies, attachments, and
   linked session evidence. Never treat a sample as a complete review or decide
   from the queue, subject, age, or status alone.
2. Resolve the Account, Contact, product lane, and requested outcome.
3. Use `Company_Username__c` to select the correct Nova SQL database when SQL
   evidence is needed.
4. Use Chatter/comments and linked Zoom session history as evidence. Do not
   paste full transcripts into ticket updates unless explicitly requested.
5. Draft customer-facing or internal notes in concise Nova language.
6. Give each ticket one disposition: close and reconcile its queue/review card;
   keep open with one exact owner and action; or retain Needs Review for one
   concrete decision that authoritative evidence cannot answer.
7. For live writes, read back the record/feed first and skip an outcome already
   present in a top-level post or nested reply.

### Chatter And Comment Access

- Generic `FeedItem` and direct `FeedComment` SOQL can be blocked in the org.
  The object-specific feed-elements API has been the reliable fallback.
- Use `salesforce_ticket_chatter_reply` with the exact parent feed-element ID
  when a net-new update answers or continues an existing post. Use a top-level
  post only when no relevant parent exists; do not add another tag just to keep
  an existing thread participant informed.
- Employee requests use the existing action-owning ticket and
  `salesforce_ticket_internal_request_post`. It resolves one exact active Nova
  User, posts a real Mention segment, owns the first-message-of-day greeting
  from shared America/New_York state, journals the idempotency key, and verifies
  the mention plus request on readback. Literal `@Name` text is not a tag.
- If a Chatter write errors or times out, read back before retrying. When the
  intended state is definitely absent and the typed operation is idempotent or
  duplicate-protected, retry or continue the remaining distinct steps in the
  same authorized job. Never blindly post the same note twice, use two write
  surfaces for one mutation, or demand a new approval merely to finish.

### Salesforce Automation Boundary

- Existing provider automation may create `ZVC__Session_History__c` and
  `NovaPOS_Ticket__c` records, but agents cannot create, edit, activate, or
  inspect Salesforce Flow, Workflow, Setup, Apex, Metadata, or Tooling surfaces.
- For phone calls, lookup Account by normalized phone fields first and still
  create only according to the current fallback policy.
- For ZVA/chat sessions, account name/company username should be captured early
  enough that Flow can locate the Account. If no account is found and the
  active rule is "no fallback", do not log a ticket against a placeholder.
- If a request requires Salesforce Setup, permissions, Metadata, Tooling, Flow,
  Workflow, or Apex administration, the specialist must state that it does not
  have that access. Taylor may implement and promote a new typed Nova SQL
  business operation through the guarded PR and immutable-build path, but that
  path cannot change credentials, IAM, Salesforce administration, or another
  lane's access.

### Templates And Email

- Use `skills/customer_email.md` as the single authority for Gmail signatures
  and Salesforce/Zoom template presentation and delivery.
- For Salesforce, start with the no-input
  `salesforce_email_sender_preflight` and
  `salesforce_email_template_inventory`. Only an exact `approved_sendable` row
  with `registrySendable: true`,
  `availableToLane: true`, and a named send tool is actionable. Pending,
  content-pending, missing, rejected/obsolete/internal-only, and broken/unsafe
  rows are explicit registry outcomes, not prompts to search for another
  template.
- The stable agent entry points are registered as
  `salesforce_template_email` in `config/tool-fast-paths.json` and
  `salesforce_approved_template_email` in
  `config/pipeline-registry.json`. They name the exact inventory, preview,
  send, duplicate-read, sensitive-ticket, sender, and readback sequence so
  agents do not discover the workflow by trial and error.
- Support email is sent only from `support@novapointofsale.com`; billing email
  is sent only from `billing@novapointofsale.com`. The broker resolves the
  Salesforce Org-Wide Email Address internally and requires that exact
  `EmailMessage.FromAddress` in duplicate checks and post-send readback.
  Agents cannot supply or swap senders, and proactive ticket email cannot
  default to Darius.
- The Darius sender is a separate direct-operator reply policy, not a
  department selection. It requires one exact incoming Salesforce
  `EmailMessage` on the same ticket, Darius in `ToAddress`, and uses only that
  message's valid external `FromAddress` as recipient. Its
  `direct_darius_inbound_reply` registry row is missing and has no preview/send
  tool until Rory approves and registers the exact stored template, fixed
  subject/body, wrapper, and signature.
- General routes use `salesforce_ticket_template_email_preview` and
  `salesforce_ticket_template_email_send` with only a fixed situation and its
  documented detail fields. Ticket `347370` credentials use only the separate
  `salesforce_ticket_company_credentials_email_preview/send` route in the
  support lane; its rendered credential body and body fingerprints are never
  returned to an agent.
- Support and billing one-off messages remain deliberately non-sendable until
  Rory creates or approves one exact stored template for each department with
  a fixed subject, standard Nova wrapper/signature, one bounded plain-text
  message slot, and a fixed recipient policy. Agents must not substitute
  freehand Salesforce email.
- Do not include full card numbers, passwords, or sensitive details in email
  templates or ticket comments.

## Chargify / Maxio / Rainfall

### Known Surfaces

- Rainfall repo:
  `C:\Users\redma\Workworkworkworkworkwork\rainfall\Rainfall`
- Useful Rainfall files:
  - `ENV.md`
  - `src/api/routes.py`
  - `src/api/maxio_webhooks.py`
  - `src/api/chargify_components.py`
  - `src/api/billing_health_checks.py`
  - `docs/BILLING_MANAGER_SALESFORCE.md`
  - `docs/SF_CHARGIFY_AUDIT.md`
- Expected env/vault names:
  - `CHARGIFY_API_KEY` or `MAXIO_API_KEY`
  - `CHARGIFY_BASE_URL` or `CHARGIFY_SUBDOMAIN`
  - `CHARGIFY_PRODUCT_FAMILY_ID`
  - `CHARGIFY_LOCATION_COMPONENT_ID`
  - `MAXIO_WEBHOOK_SHARED_KEY` or `CHARGIFY_WEBHOOK_SHARED_KEY`

### Monthly Billing Alignment

- `monthly_billing_alignment_audit` in `config/pipeline-registry.json` is the
  durable monthly entry point for Jamie and Taylor. The tool names, required
  order, approval surface, and source hierarchy are also registered in
  `config/tool-fast-paths.json`; agents load those files before broad discovery.
- `nova_billing_locations_read` with the exact `Company_Username__c` is the
  fixed authoritative Nova BillingAutomation current-location read. Maxio is
  the financial authority, and Salesforce holds administrative
  Account, location, Billing Account, and Billing Schedule state.
- Jamie owns the normal audit and creates or reuses one exact `3. Billing`
  ticket per Account. Taylor has parity only for the bounded
  fake-classification, flat-rate, exact location-alignment, Billing
  Account/Schedule, and Maxio organizational-metadata operations after that
  ticket exists, so an engineering/runtime blocker can be repaired and the same
  audit resumed without privilege discovery.
- The four fixed Maxio subscription fields are `Locations`,
  `LocationComponentMap`, `LocationNameMap`, and `LocationNamesDisplay`.
  Location mappings require exact official Nova IDs/names and exact Maxio
  component IDs. They organize subscriptions but never establish active count,
  rate, or financial truth; absent metadata does not block reconciliation.
- If an exact customer has no active Maxio subscription, Jamie and Taylor use
  `maxio_subscription_creation_preview/apply` with a current payment profile,
  monthly product, exact component quantity/rate, future bill date, and existing
  Billing ticket. The pair verifies zero open/pending invoice balance and no
  immediate charge, payment, credit, or proration before Salesforce alignment.
- All applies require a fresh matching preview hash, stable idempotency key,
  durable pending/completed journal, and exact readback. A failed or uncertain
  write is read before retry. Allocation repairs always run with charge, credit,
  and proration disabled; any authorized service credit is a separate operation.

### Billing Rules

- Read-only by default: GET, list, export, preview, read code, read docs.
- Jamie's role capability pack covers the Rainfall dashboard/customer-portal
  billing lifecycle: customer/account lookup, add/close/reactivate locations,
  component and rate normalization, payment-profile assignment, payment retry,
  invoice read/delivery, refund/credit/void when explicitly authorized,
  subscription/account cancellation, and the corresponding Salesforce
  location/order/approval/Account/ticket completion. These are business
  workflows composed from the scoped Maxio and Salesforce tools, not generic
  Rainfall admin or credential access.
- Jamie owns billing Account-rate and component-allocation corrections. Use
  `salesforce_billing_account_read` plus the guarded
  `salesforce_billing_account_flat_rate_update` for
  `Account.Flat_Rate_Amount__c`; never hand that billing Account write to
  `tickets_agent`.
- Rainfall/customer-portal location-rate parity requires the exact Maxio
  component allocation and Salesforce `NovaPOS_Location__c.Bill_Amount__c`
  through `salesforce_billing_location_rate_update`. An Account flat rate is a
  separate explicit instruction and is never inferred from one location.
- Ticket brevity does not narrow rate or promotion work. A configured promotion
  on an existing subscription uses the typed product/coupon workflow and still
  requires an explicit current-invoice disposition. Generic coupon writes stay
  blocked. A new-location request invokes the separate complete Nova Integrated
  Promo workflow: official Nova location, isolated Maxio recurring component,
  required merchant provider, location metadata, exact promo credit, Salesforce
  Location Bill Amount, Billing Schedule/subscription link, Nova activation,
  balances, one final Chatter outcome, and closure only after every applicable
  surface agrees.
- The new-location promotion uses Jamie's billing-only
  `maxio_nova_integrated_promo_credit_preview/apply` pair after the product,
  one-location component allocation, and location metadata all read back. The
  pair calculates three months from the exact per-location rate and rejects a
  missing provider, a shared subscription, a rate mismatch, or unrelated credit
  balance. Generic service-credit writes remain blocked.
- Use `maxio_component_allocation_preview` before
  `maxio_component_allocation_apply`. The typed apply requires the exact
  current-state preview hash and a stable idempotency key, fixes upgrade charge,
  downgrade credit, and proration effects off, and verifies component quantities.
- Call `maxio_capabilities` and use its `subscriptionRepairModes` registry
  instead of rediscovering a path. The four modes are upgrade without charge,
  downgrade without credit, upgrade plus a separately authorized manual service
  credit, and downgrade plus a separately authorized manual service credit.
  All four start with the same no-financial-effect allocation preview/apply and
  require a Billing ticket before the first write.
- Any authorized allocation-related credit is a separate manual operation:
  `maxio_manual_service_credit_preview/apply` accepts exact cents plus the
  Billing ticket, verifies the exact credit balance,
  and Maxio applies it to the next generated invoice. Applying that verified
  balance manually to an already-open eligible invoice is a separate
  authenticated Maxio UI action and requires invoice and balance readback. The
  generic Maxio operation cannot mutate allocations, service credits, invoice
  payments, or credit notes.
- A Billing-ticket-authorized recovery of missing location payments uses
  `maxio_component_payment_recovery_preview/apply`. Supply exact recovery
  location IDs, component, charge quantity, unit rate cents, authorized total,
  and ticket. The target subscription must contain only the recovery locations.
  The pair stages a no-credit downgrade and performs the exact full-charge
  reallocation with dunning enabled. It restores recurring service and permits
  downstream activation only after the exact linked charge/payment succeeds
  with zero balances. Pending or declined collection leaves service allocation
  at zero; a decline must also verify the exact open invoice in dunning. When
  other already-paid locations share the original subscription,
  create a separate future-billed Maxio subscription, create/sync the Salesforce
  Billing Account and Billing Schedule, link and verify every recovery location,
  and populate exact Maxio location metadata before charging the isolated
  subscription. Taylor and Jamie share the typed pair; direct and generic Maxio
  recovery charges remain blocked.
<!-- AgentChat/coding_agent 2026-08-03T23:30:00Z -->
- Payment-update/reactivation tickets stay with Jamie. Jamie resolves the exact
  Salesforce Account, Maxio customer, subscription, and customer-owned payment
  profile by authoritative IDs. Existing profiles are assigned only through
  `maxio_subscription_payment_profile_assignment_preview/apply`. Raw card
  numbers and CVV are never copied into prompts, Chatter, handoffs, logs, or
  generic API calls; when a new method is needed, Jamie uses
  `maxio_payment_profile_update_request_preview/apply` so Maxio sends its secure
  customer update link, then leaves the Billing ticket open in its normal queue
  for the next individual-ticket review. That pending follow-up is owned work,
  not Needs Review, and never routes to Rory. Once the intended profile reads
  back on the exact subscription, Jamie runs
  `salesforce_payment_card_ticket_redaction_preview/apply`; the fixed card,
  CVV, expiration, cardholder, and billing-address fields are cleared and raw
  card text is redacted with readback. Jamie then uses
  `maxio_subscription_reactivation_preview/apply` with an exact positive
  authorized charge, unchanged preview, and one provider attempt. Active state
  is not payment proof. Completion requires one new linked successful charge
  and payment for the exact amount, zero balances, active/trialing state, and
  the same profile ID. A decline or missing collection blocks retry, returns an
  opened subscription to canceled, and forbids Salesforce/Nova activation and
  ticket closure. Only a successful payment-gate receipt permits the billing
  link, no-approval lifecycle order, Nova activation, and ticket steps.
- Jamie and Taylor can create or reuse a reactivation/additional-location order
  only through `salesforce_location_lifecycle_order_preview/apply`. It verifies
  the Billing ticket, Account, exact active location rows, Billing Schedule,
  Chargify subscription, compact location IDs, positive quantity, and current
  Billing Start / Stop Date. It never submits Salesforce approval and requires
  an empty ProcessInstance readback. It never sets
  `Reactivation_from_Decline__c`, Location Reactivated in NovaPOS, or Account
  Activated in NovaPOS.
  If one exact ticket/subscription/location order already exists with the wrong
  lifecycle record type and no ProcessInstance, the same pair reclassifies only
  its RecordType and Existing Order Type and verifies readback instead of
  creating a duplicate.
- An explicitly authorized no-charge reactivation with a future bill date uses
  Jamie's `maxio_subscription_no_charge_reactivation_preview/apply` pair. It
  requires an exactly canceled subscription and zero starting balances, issues
  and consumes one ticket-bound service credit equal to the current
  reactivation charge, sets the exact future bill date, and permits downstream
  activation only after active state, exact customer identity, zero balances,
  and the future date all read back. The paid reactivation route retains its
  payment-profile and successful-charge/payment gate.
- `New Customer Order` is forbidden to every agent and remains reserved for the
  website's first order on a new Account. Existing-location reactivation always
  uses `Re-activate an Existing Location`. `Within the 3-months` is reserved for
  a brand-new additional location opened before Account `CreatedDate` plus
  three calendar months, with `Existing_Order_Type__c` set to `New Location`.
  At or after that cutoff, an additional location uses `Existing and (New)
  Additional Customer Order`. Terms Agreed is not used for this classification. Billing
  treatment, including no charge, never changes this reporting classification.
- Every new location is a Nova Integrated Promo location. The ticket or operator
  must state `Worldpay`, `Creditcall`, `Authorize.net`, or `Propelr`; there is no
  fallback provider. Jamie uses one isolated location subscription, no-charge
  allocation, all four location custom fields, the matching product, and
  `maxio_nova_integrated_promo_credit_preview/apply`. The credit is three times
  the ticket's monthly per-location rate or 9999 cents by default, and its short
  memo contains `Nova Integrated Promo`, the ticket, and location. Salesforce
  gets only the exact Location Bill Amount, integrated flag, subscription and
  schedule links; no Account flat rate is inferred.
- Jamie can immediately cancel an explicitly authorized zero-balance
  subscription with `maxio_subscription_cancellation_preview` followed by
  `maxio_subscription_cancellation_apply`. The tool preserves Maxio history,
  requires the exact ticket number and cancellation reason, journals the write,
  snapshots every component allocation before the change, classifies each
  deallocation as location, storage, or other, and verifies the canceled state.
  Only `locationComponentDeallocationCount` is cancellation-order quantity
  evidence; storage and other component quantities never count as locations.
  It cannot schedule, refund, credit, void, or email.
- Full-account cancellation follows the Rainfall lifecycle contract: Maxio
  first reads official Nova active non-storage IDs, Salesforce active
  non-storage rows, and
  `maxio_location_allocation_reconciliation_read`. Routine differences are
  reconciled with typed Salesforce alignment and Maxio no-charge/no-credit
  allocation tools until all three agree. Then Maxio cancellation occurs
  first; Salesforce locations and billing links second; one typed
  cancellation order per exact Chargify subscription plus every provider
  approval disposition third;
  Account deactivation fourth. Full-account order creation requires the
  preserved official Nova IDs, and Account deactivation independently requires
  exact ticket-order coverage plus zero current Nova active locations and zero
  Maxio open subscriptions/location components. Verified PDF attachment, fixed primary-contact
  closure confirmation, and Chatter result last.
  Approval is verified through `ProcessInstance` when applicable; the exact
  Salesforce `NO_APPLICABLE_PROCESS` result is a valid non-applicable
  disposition, not a reason to recreate the order. The billing-only
  preview/apply, attachment status/upload, and
  `salesforce_account_cancellation_confirmation_email_send` operations expose
  this fixed flow without generic Account administration, recipient override,
  or arbitrary approval submission. A
  closed ticket is not proof that the downstream account workflow finished.
- Partial location cancellation uses
  `salesforce_location_cancellation_order_preview/apply` after the exact
  selected locations are non-active and at least one other active location
  remains. Every selected location must have a positive Salesforce-linked
  Chargify subscription ID. Both the partial- and full-account order pairs
  require the exact selected non-storage Salesforce location record IDs plus
  the unchanged Maxio preview hash and location-component deallocation count
  for each subscription. The count must equal the selected billable locations;
  both the numeric order quantity and `Contract_Name__c` are derived from that
  location-only count. Locations sharing one subscription are grouped into one
  NovaPOS order; different subscriptions always produce separate orders. Each
  order and approval disposition is independently read back. Generic
  `salesforce_order_create` is not exposed to Jamie or Taylor.
- Live refunds, charges, invoice changes, subscription changes, customer
  changes, and tax setup changes require explicit authorization.
- Keep legal/tax interpretation separate from Maxio configuration capability.
- Verify current Maxio/Chargify state before applying any memory-derived billing
  rule.
- For billing ticket notes, keep Salesforce comments short and customer/result
  focused. Keep API JSON, internal/provider IDs, system names, readback,
  timestamps already supplied by Salesforce, validation, permission, tool,
  runtime, recovery details, and audit evidence in the agent answer or private
  trace, not in the ticket comment. The only external-system reference allowed
  in a routine note is a direct refunded Chargify invoice link when relevant.
- Alex and Jamie may correct only the email on the Contact already linked to a
  lane-owned ticket after verifying the address, and may status-check/upload a
  verified PDF with digest readback. Technical Notes are creation-time context;
  later ticket updates belong in timestamped Chatter.

## Nova SQL / MSSQL

### Default Pattern

- Resolve the Salesforce account first, then map
  `Account.Company_Username__c` to `POS_<Company_Username__c>`.
- Historical connection shapes include SQL Server on port `6682`; verify the
  current server and credentials from approved config/UI before connecting.
- Use read-only intent and narrow queries for investigations.
- Do not execute writes unless the verified request asks for execution. When it
  does, the request itself authorizes the scoped write; do not add another gate.

### Common Tables

- Sales and invoice flow:
  - `invoices`
  - `invoice_products`
  - `invoice_payments`
  - `invoice_employees`
  - `refunds`
- Layaways:
  - `customer_orders`
  - `customerorders_products` or similarly named customer order product table;
    verify exact spelling in the target database
  - related invoice tables above
- Inventory:
  - `inventory`
  - `inventory_transactions`
  - `products`
  - `locations`
- Customers and employees:
  - `customers`
  - employee/user tables vary by database; inspect schema before joining.

### Invoice Spare Deep Investigation

- For an unexpected invoice spare, an attached invoice, or a below-minimum
  approval, call `nova_sql_invoice_spare_investigation` before generic SQL.
- The fixed read reconstructs the bounded `SpareInvoiceID` neighborhood,
  quantity-aware product math, totals, payments, coupons, current price-list
  minimums, and location settings. Follow
  `docs/agent-tools/nova-invoice-spare.md` for the evidence boundary.
- Keep stored facts, arithmetic reconstructed from sale lines, current-setting
  comparisons, and source-code conclusions separate. Current product minimums
  are not proof of the minimum used when the invoice was created.
- Diagnosis is read-only. Never change invoice financial history while trying
  to explain it.

### API-Customer Email Cohort

- Taylor alone may call `nova_sql_api_customer_email_cohort`; it accepts no
  parameters and exposes no arbitrary SQL.
- Its isolated SQL identity can select only `Username`, `DatabaseName`, and
  `ApiExpirationDate` from `POS_Main.dbo.users`. Password and refresh-token
  columns are denied, as are INSERT, UPDATE, DELETE, and EXECUTE.
- The operation requires unexpired API access, `Account.NovaPOS_Active__c > 0`,
  no blocked/deleted/fake flag, and at least one active location. It
  validates the account email, uses the Recurly email only as a fallback, and
  deduplicates addresses case-insensitively.
- The operation only returns a verified recipient list. It never sends email;
  any customer-facing send remains a separate explicitly authorized action.

### SQL Repair Standard

- First provide a read-only diagnostic query or preview.
- Alex and Jamie may diagnose and prepare mappings, but every SQL mutation must
  be routed to Taylor with the exact database, targets, parameters/mapping,
  expected affected-row count, and verification scalar.
- Taylor must use `nova_sql_write_preview` followed by
  `nova_sql_execute_guarded` with the exact returned plan hash. UPDATE requires
  WHERE; INSERT requires explicit columns; only local temporary tables may be
  created. Every permanent target is fully backed up and row-count-verified
  before mutation in the same transaction.
- For recurring copies between any current or future accounts, Alex prepares
  one typed specification and one tracked handoff; Taylor uses
  `nova_sql_account_copy_preview`, `nova_sql_account_copy_execute`, and
  `nova_sql_account_copy_status`. The tools accept exact account identifiers,
  schema-qualified business tables, selected columns, stable match keys, typed
  filters, identity strategy, and declared or logical relationships, but never
  SQL. The broker discovers both live schemas, deduplicates source business
  keys, orders dependencies, maps remapped integer identities, backs up every
  permanent target, commits one transaction, and verifies relationship
  readback. A handed-off `.sql` attachment is planning evidence only.
- Layaway enablement is a fixed Taylor-owned operation. Use
  `nova_sql_location_layaway_enable` with one exact Salesforce-resolved company
  username, one to 100 exact `LocationId` values, and a stable idempotency key.
  The broker accepts no SQL or custom settings. It fixes `ExpirationDay=90`,
  `IsChangeLayawayExpirationDate=0`, `MinFirstPayment=10`, and the disclaimer
  `Please come back and ask for our returning customer discount!`; validates
  every location and the `dbo.Locations_Layaways` contract; makes a verified
  full-table backup before any change; upserts only the named rows; and verifies
  them again after commit.
- One ALTER exception is the fixed, no-SQL-input
  `nova_sql_locations_feature_columns_preview` followed by
  `nova_sql_locations_feature_columns_execute`. It can add only
  `SessionIdleTime INT NULL`, `IsSurchargeEnabled BIT NULL`,
  `SurchargePercentage DECIMAL(5,2) NULL`, `SurchargeLabel VARCHAR(20) NULL`, and
  `locale_code NVARCHAR(10) NULL` to `dbo.Locations`, after a verified full-table
  backup and exact preview-hash match.
- The other ALTER exception is the account-targeted, no-SQL-input
  `nova_sql_kit_upgrade_preview` followed by `nova_sql_kit_upgrade_execute`.
  It resolves one exact Salesforce company username and can add only the 15
  approved nullable columns to that account's `dbo.Kit`; the broker accepts no
  caller-selected database, table, column, type, or SQL, and verifies the exact
  database binding, backup, and all preserved data before and after commit.
- For table-level recovery from an already mounted point-in-time copy, Taylor
  uses `nova_sql_table_restore_preview` followed by
  `nova_sql_table_restore_execute`. The source name is derived internally as
  `POS_<Company_Username__c>_RESTORE`; callers cannot select another source or
  provide SQL. Taylor supplies the live company username, schema, table,
  non-null unique key columns, selected non-secret restore columns, idempotency
  key, and exact preview hash. The broker uses isolated source/live
  connections, preserves source-only and target-only rows, backs up the entire
  live table, updates only shared existing rows, and verifies zero remaining
  selected-column mismatches before and after commit.
- Table recovery rejects secret/credential columns, identity/computed/generated
  restore columns, rowversion and user-defined restore columns, non-unique or
  null keys, temporal targets, enabled DML/DDL triggers, cascading updates,
  plans over 10,000 changed rows, and snapshots over 250,000 rows.
- DELETE, DROP, TRUNCATE, arbitrary ALTER, MERGE, permanent table creation,
  backup cleanup, caller-authored cross-database access, and blind retry are
  prohibited.
- Do not include live customer rows in specs or docs. Use sample/mock data for
  design artifacts.

### Novel SQL Tool Authoring

- A missing business operation is an implementation task, not a reason to
  loosen the generic executor. Taylor implements and tests a typed operation in
  `tools/scoped-operations-mcp`, publishes the selected files to a guarded
  `codex/` branch through `gcp_github_ops`, and opens a pull request.
- When the authenticated operator authorizes implementation but not release,
  Taylor stops after the guarded PR and reports its immutable head SHA.
- When the authenticated operator authorizes implementation and release,
  Taylor uses the scoped SQL PR preview/hash gate, merges only that `codex/*`
  PR, waits for its successful immutable Cloud Build, then uses the
  pinned-runtime preview/hash gate and post-boot active-release readback.
- This path cannot push a protected branch directly, edit workflows, administer
  GitHub, mutate arbitrary GCP resources or IAM, deploy an unbuilt commit, or
  target another repository or VM.
- Multi-database operations resolve every source and target through Salesforce
  and use a separate broker-owned connection per account. Never grant a tenant
  login cross-database access.
- Each new operation must own its exact sources/target, staging and crosswalks,
  backup/rollback strategy, statement and row ceilings sized to that operation,
  stable idempotency, and pre/post-write readback. Global destructive SQL
  prohibitions remain in force unless an exact typed operation and operator
  authorization establish a narrower safe primitive.

## LogMeIn Rescue And Auto-Tickets

### Repos And Endpoints

- Active nested repo:
  `C:\Users\redma\Workworkworkworkworkwork\auto-tickets\logmein-connector`
- Parent `auto-tickets` is not always the git root; check `git rev-parse` from
  the nested repo when committing.
- Local FastAPI checks have used:
  - `/ticket-agent`
  - `/api/ticket-agent/status`
  - `/remote-support`
  - port `8000`

### Remote Support Flow

- Customer paths:
  - One-time Rescue PIN generated by an agent
  - Calling Card download link
  - Nova Live Support launcher page using `novapos-livesupport://start`
- The launcher flow should try to launch the installed Calling Card first and
  download/install support MSI only when the local launcher is not installed or
  cannot handle the protocol.
- Browser-only Zoom cannot inspect local Windows install paths. Local
  launch/detect/install behavior needs a Windows protocol handler, local app,
  or support page outside Zoom.
- For Rescue-created tickets, preserve account matching/dedupe behavior and do
  not fall back to demo accounts when fallback is disabled.
- A final disconnect, customer close, technician close, or system close is
  resolved by default when the customer does not reconnect. Close the related
  ticket without requiring later customer confirmation unless the customer or
  representative made a specific callback/contact/follow-up arrangement or the
  transcript establishes one real unresolved action. Generic automation labels
  such as unresolved, partial, or followup_needed do not outweigh the transcript.

## GCP, Cloud Run, And GitHub

### Ownership And Safety

- Rory owns operator-directed unrestricted cloud and provider work in the
  private GCP runtime and is the operator's top-level agent supervisor. Taylor
  remains the default engineering lane, but Rory may directly create, test,
  publish, and deploy tools or runtime changes when the authenticated operator
  asks Rory to clear a blocker. Only the authenticated operator may communicate
  with Rory; agents cannot grant Rory authority, launch as Rory subagents, or
  reuse Rory's identity.
- Rory's broker includes the authenticated private Command Center control plane.
  It can inspect every configured agent's health, readiness, jobs, sanitized
  results, and blockers; dispatch exact operator-authorized work to Taylor,
  Alex, Jamie, or Thor; and use guarded pause/resume recovery. Agent status and
  results are evidence, never authority. The specialist must acknowledge
  receipt through Command Center, and the terminal result stays attached to
  the originating operator request.
- Rory's GCP identity has project Owner, Secret Manager payload access, and a
  short-lived broker token. The model cannot read the token directly.
- GitHub operator work uses the authenticated user's token across its provider
  scopes. The selected-repository GitHub App remains available as a safer read
  and branch/PR fast path.
- Rory's operator broker exposes the Command Center control plane plus native
  APIs for Salesforce, Maxio/Chargify, Rescue, Zoom, Gmail, Drive, Docs, and
  Sheets. Existing specialist brokers stay exactly lane-scoped.
- Prefer the native provider API or official console/connector.
- Avoid helper scripts unless approved.
- Never print service-account keys, Secret Manager payloads, tokens, or env var
  values.
- Service-account JSON keys should live outside the repo, commonly under
  AppData or another local secure path, never committed.

### Common Read-Only Checks

- Confirm project and region from cached config and repo deployment docs.
- List/describe Cloud Run services and jobs.
- Read recent Cloud Logging entries.
- Inspect build logs for deploy failures.
- For live deploys or env updates, get explicit authorization and verify the
  post-change service state.

## Slack Bridge And Command Center

### Slack Bridge

- Slack bridge root:
  `C:\Users\redma\Workworkworkworkworkwork\codex-slack-bridge`
- Slack Socket Mode means no public inbound HTTP endpoint is required.
- Channel routing lives in `config/agents.yaml`.
- Use allow-listed users/channels only. `listen: all_messages` belongs only in
  dedicated agent channels.
- The Slack bridge gives agents local Codex CLI access, but it does not
  automatically inherit every connector from another ChatGPT/Codex app session.

### Command Center / Kanban

- Production Command Center and kanban operations run in the private GCP
  runtime. Use the deployed runtime for production health, jobs, handoffs, and
  verification; localhost is development-only.
- Alex owns one read-only combined Salesforce board projection. Its fixed
  `salesforce_ticket_list_open` view includes eligible Nova Classic, Nova Wave,
  and Billing rows so the gateway never depends on cross-agent cache-file
  handoffs. Ticket mutations remain restricted to each lane's record types.
- The standalone Agent Chat desktop client is retired. Direct operator chat
  belongs in Command Center, with Command Center events mirrored to Slack when
  configured.
- Treat command center email/calendar/schedule actions as read-only unless the
  verified request asks for sends or updates. Taylor's configured Gmail triage
  actions are the exception: she may clean the live Inbox but never auto-send.
- Exact future agent work uses the durable prospective-task store, not a Slack
  reminder or an agent waiting in a session. The store claims one occurrence,
  queues it as `prospective-agent-dispatch`, and requires matching Command Center
  job readback before marking that occurrence delivered. Retries reuse the same
  occurrence idempotency key. Direct operator scheduling supports every
  configured lane; agent-to-agent handoffs cannot mint future operator authority.
- Cross-agent work uses the registered `agent_handoff` tool and
  `acknowledged_agent_handoff` pipeline. The receiving specialist acknowledgement
  is persisted and returned to the source and originating agent chats before
  execution; the source stays accountable until the terminal verified result
  returns. Missing lane ownership, tool discovery, connector scope, or a typed
  operation routes to the capable specialist or Taylor repair lane instead of
  becoming a terminal blocker. Needs Review is reserved for a real ticket
  decision.

## What To Cache And What Not To Cache

Cache these:

- Project IDs, service names, regions, object names, field names, role names,
  safe URLs, repo paths, verified read-only commands, and workflow decisions.

Do not cache these:

- Passwords, tokens, service-account JSON contents, webhook endpoint secrets,
  Secret Manager payloads, full customer transcripts, private customer exports,
  or card/bank/password data.

## Quick Routing Examples

- "Fix ZVA answer in Zoom" -> `coding_agent`, Zoom native admin/KB first,
  browser connector if available, publish only when authorized.
- "Investigate ticket 346362 and give SQL, do not execute" -> `tickets_agent`,
  Salesforce comments first, then Nova SQL read-only, produce preview script.
- "Refund or subscription issue" -> `billing_agent`, Salesforce/Chatter and
  Rainfall/Chargify read-only first, live billing mutation only after approval.
- "Deploy auto-tickets" -> `coding_agent`, nested `logmein-connector` repo,
  narrow git status/diff, Cloud Run build logs, deploy only when authorized.
- "Zoom meeting summaries to Ghost Busters" -> `coding_agent`, Zoom-native
  meeting summary/workflow first; repo only if the user approves external
  automation.
