# Codex Slack Bridge

<!-- AgentChat/coding_agent 2026-07-09T00:32:51Z -->

Local Slack bridge for a coding and support assistance environment.

The bridge uses Slack Socket Mode, so the laptop opens an outbound WebSocket to
Slack and does not need ngrok or a public HTTP endpoint. Configured Slack
channels route to local `codex exec` agents.

The Codex lanes inherit whatever the local Codex CLI can access: filesystem,
configured MCP servers, installed/enabled Codex plugins, ChatGPT auth, and local
network. They do not automatically inherit every connector visible in another
ChatGPT or Codex app session. Install or configure those tools in the local
Codex CLI before expecting a Slack-triggered agent to use them.

## What It Gives You

- Native Windows Agent Chat desktop app for direct local agent messaging without
  Slack.
- Direct local Codex CLI bridge from Slack to `codex exec`.
- Tech Support team channels divided by engineering, tickets, and billing
  responsibilities.
- Bridge-managed read-only Codex subagents for deeper investigations.
- Slack thread context collection with configurable limits.
- Top-level channel replies by default, so responses are visible without
  opening a thread.
- One progress message per request that is updated into the final answer.
- Per-agent long-term memory with SQLite durability and optional LanceDB vector
  indexing.
- Knowledge-base ingestion for exported Google Drive / Zoom / Moira docs into
  shared agent memory.
- Slack file downloads into local storage and allow-listed Slack file uploads
  from agent output.
- Bridge-loaded skill files for security, Nova knowledge, internet research,
  Google Drive, and browser/Windows control guidance.
- `!search` for public internet lookups through OpenAI hosted web search when
- Optional Windows startup task.
- SQLite-backed job and Slack event tracking.
- Per-channel serialized execution by default.
- Read-only or write-capable Codex lanes by channel.
- No secrets committed to the repo.

## Default Agents

`config/agents.yaml` defines a general computer lane, specialized operational
lanes, and a raw escape hatch:

The official roster, responsibility boundaries, handoffs, RACI, SLAs, and gap
register are maintained in the
[`Nova Tech Support Agent Responsibility Handbook`](docs/agent-responsibilities/README.md).
That handbook supersedes informal channel names and older UI persona labels.

- `direct_codex` / Rory: operator-only remote access with full authenticated
  GCP, GitHub, Salesforce, Maxio/Chargify, Rescue, Zoom, Gmail, Drive, Docs, and
  Sheets provider APIs; delegation, shared sessions, and subagents stay disabled.
- `raw_codex`: persistent unscaffolded Codex CLI session for explicit escape-hatch
  use; it has no injected memory or subagents and is not the default Slack lane.

- `coding_agent` / Taylor: Tech Support; engineering, implementation, automation,
  Gmail intake, Singapore background automation, SQL writes, and scoped Zoom reads.
- `claude_agent` / Thor: Tech Support; read-only support-quality review across
  the fixed Zoom Contact Center roster and LogMeIn Rescue evidence.
- `tickets_agent` / Alex: Tech Support; ticket research, Rescue, and explicit
  brand-new Singapore interface tickets rooted at `auto-tickets`.
- `billing_agent` / Jamie: Tech Support; billing and subscription responsibilities rooted at
  `rainfall`.

In the private GCP runtime Rory has an exclusive operator broker with full
native API access under the authenticated provider accounts. Credentials remain
outside the model process and mutations are idempotency-journaled. Taylor owns
repo implementation and Singapore operations; Alex and Taylor retain their
fixed Zoom read brokers, Thor has a separate quality-only Zoom/Rescue broker,
and all other specialist scopes remain unchanged.

Each specialized lane also loads a durable profile file:

- `profiles/coding_agent.md`
- `profiles/claude_agent.md`
- `profiles/tickets_agent.md`
- `profiles/billing_agent.md`

`direct_codex` can select its configured read-only subagents automatically.
Specialized lanes currently use manual subagent mode, so they run helpers only
when the request asks for depth/parallel agents or uses `!deep`/`!subagents`.

For recurring platform work, agents should start with
`docs/AGENT_PLATFORM_MAP.md`, `config/tool-fast-paths.json`, and
`config/pipeline-registry.json`. These files map known Zoom, Salesforce,
Chargify/Maxio, Nova SQL, GCP, LogMeIn, Slack, and desktop app entrypoints so
agents can avoid rediscovering the same safe paths.

The main lanes currently run with broad local filesystem/tool access. Their
business ownership and write boundaries are workflow-specific and documented in
the responsibility handbook; use actual per-agent read-only credentials or
capability allowlists where hard enforcement is required.

## Setup

1. Create a Slack app from `slack-app-manifest.yaml`.
2. Install it to the workspace and add it to the target channels.
3. Copy `.env.example` to `.env` and fill in:
   - `SLACK_APP_TOKEN`, from Slack app-level tokens, starts with `xapp-`.
   - `SLACK_BOT_TOKEN`, from OAuth install, starts with `xoxb-`.
4. Replace the placeholder channel IDs in `config/agents.yaml`.
5. Install dependencies and run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\run.ps1
```

The scripts install dependencies into a project-local `.packages` directory and
set `PYTHONPATH` at run time.

Optional LanceDB vector indexing:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install-memory.ps1
```

If LanceDB is not installed or fails at runtime, memory still works through the
SQLite store at `data/memory.sqlite3`.

Optional PDF knowledge ingestion and desktop automation packages:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install-knowledge.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\install-desktop-tools.ps1
```

For background operation:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\status.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\stop.ps1
```

## Slack And Command Center

<!-- AgentChat/direct_codex 2026-07-17T17:32:53-04:00: retire the standalone desktop client. -->

The standalone Agent Chat desktop client is retired. Operator communication is
supported through Slack and the loopback-only Command Center. The legacy build
and start scripts fail closed so the desktop client cannot be relaunched by
accident. Historical desktop conversations and the shared vector knowledge
index are retained as local data; they are not an active communication surface.

Agent runs use the same `config/agents.yaml`, profile files, skill files,
workspaces, sandbox values, and Codex CLI path across Slack and Command Center.
They are prompted to work in loops:
inspect the real local context, act narrowly, verify, then retry with a better
hypothesis when a command or assumption fails. The generated prompt also gives
each lane the current local access map:

- Runtime env files: `config/ops.env`, `.env`, and
  `config/logmein-rescue.env` when present. Agents may use names, but must not
  print values.
- Secure vault:
  `C:\Users\redma\AppData\Local\CodexBillingAgent\secure-vault`.
- Vault helper script:
  `C:\Users\redma\AppData\Local\CodexBillingAgent\secure_secret_store.ps1`.
  Avoid running it by default. Prefer existing env/app connector context. If
  secret-backed access is required and approved, list names only or inject
  selected secrets without printing values.
- Google Drive helper script:
  `scripts/google-drive-tool.ps1`. It uses local Google Application Default
  Credentials at
  `C:\Users\redma\AppData\Roaming\gcloud\application_default_credentials.json`
  and supports read-only `status`, `search`, `list-folder`, `metadata`, and
  `export` commands. Prefer Google Drive connector/app tools when available. Do
  not print or inspect the ADC credential contents.
- Edge browser helper script:
  `scripts/edge-browser-tool.ps1`. Prefer built-in browser/app connectors and
  already-available browser sessions. For Nova Zoom AI Studio work, agents
  should use displayed `Profile 1` at
  `https://novapointofsale.zoom.us/ai-studio/virtual-agent`. On this machine,
  displayed Edge Profile 1 is stored in the internal `Default` directory, while
  internal `Profile 1` displays as Profile 2. Agents must not use displayed
  Profile 2. Agents should open new tabs by default, avoid navigating the
  user's active tab, and use CDP/browser APIs that do not move the physical
  mouse. A verified request authorizes the helper steps reasonably needed to
  complete it. Guarded Edge restarts should preserve the Profile 1 session when
  possible; physical Windows GUI automation remains a last resort.
- GCP ops helper script:
  `scripts/gcloud-ops-tool.ps1`. It loads `config/ops.env` and `.env`,
  supports service-account activation from `GOOGLE_APPLICATION_CREDENTIALS`,
  and provides guarded Cloud Run services/jobs/logs commands for `auto-tickets`
  and `rainfall`. It never prints the service-account key contents. Prefer
  native read-only `gcloud` commands or Google Cloud connectors before using the
  helper.
- Agent sandboxes: `data/agent_sandboxes/<agent>`. New tools, docs, scripts,
  reports, prototypes, and scratch files belong there unless the user explicitly
  asks for a named repo/file edit.
- Agents should answer normal questions directly in chat. They should create
  Markdown files, handoff files, or other deliverables only when the user asks
  for a file, the output is too large for chat, or a durable record is clearly
  useful.
- Billing credential names agents should look for: `CHARGIFY_API_KEY` or
  `MAXIO_API_KEY`, plus `CHARGIFY_BASE_URL` or `CHARGIFY_SUBDOMAIN`.

### Tool Fast Paths

Agents receive a trusted fast-path registry before memory or user-provided
context. The registry lives at `config/tool-fast-paths.json` and covers
Chargify/Maxio, Nova SQL, Salesforce, GCP, and Zoom. It is intentionally
non-secret: it stores credential names, safe read-only defaults, known repo
paths, and the first command or file to inspect.

Agents should inspect `config/tool-fast-paths.json`,
`config/pipeline-registry.json`, cached facts, known config paths, app
connectors, native APIs, and standard read-only CLIs before running helper
scripts. The old preflight helper still exists at
`scripts/agent-toolkit.ps1`, but it should not be run by default because local
scripts may trigger endpoint security. Use it only when explicitly approved or
when a lower-noise direct path is not enough.

Targeted tool names remain `chargify`, `nova_sql`, `salesforce`, `gcp`, and
`zoom`. In the private runtime Rory uses both the safe discovery broker and the
operator-only unrestricted provider broker; Taylor and Alex keep their fixed
Zoom read brokers, and Thor has a read-only quality broker without send,
recipient-resolution, ticket, or administration tools.

### Pipeline Registry

Agents also receive reusable playbooks from `config/pipeline-registry.json`.
The registry classifies common work into pipelines such as GCP/Cloud Run health,
Zoom/ZVA admin, Salesforce ticket investigation, Nova SQL diagnostics, repo code
changes, and KB corrections. It is prompt-time guidance only; it does not start
background jobs or execute scripts.

The registry points agents to `data/pipeline_cache` for non-secret known facts
such as project ids, regions, service names, object names, safe URLs, and last
successful verification methods. It must never store secret values, tokens,
service-account JSON contents, passwords, or private customer data dumps.

Nova SQL report and migration templates live in `agent-sql-toolbox/`. They are
generalized from the local SSMS folders, with read-only report scripts under
`reports/` and dry-run-first write templates under `migration/` and
`maintenance/`.

To auto-start both local services when Windows logs in:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install-startup-task.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\install-command-center-startup-task.ps1
```

These idempotent installers use per-user `HKCU\...\Run` entries, so elevation is
not required. They verify the exact command and remove same-service legacy
scheduled tasks or Startup-folder launchers to prevent duplicate processes. The
gateway writes stdout and stderr under `logs\command_center\`.

Remove the entries with:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\uninstall-startup-task.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\uninstall-command-center-startup-task.ps1
```

## Adding Agent Channels

Add a channel ID under `channels`, then point it at an agent under `agents`.

```yaml
channels:
  C_NEW_CHANNEL_ID:
    agent: tickets_agent
    listen: all_messages
```

Use `listen: all_messages` for dedicated agent channels. Use `listen: mention`
when the bot should respond only when mentioned.

## Subagents

Subagents are configured under each Codex agent. They run as separate ephemeral
read-only `codex exec` jobs and return short reports to the primary agent. This
gives the bridge parallel investigation without granting subagents write access.

Manual triggers:

- `!deep`
- `!subagents`
- `use subagents`
- `parallel check`

## Memory

Each configured agent has its own memory namespace. The bridge also supports a
shared `global` namespace.

Slack commands:

```text
!remember this agent-specific note
!remember-global this shared note
!memory
!memory search terms
```

Every completed interaction is also stored as a redacted memory when
`memory_auto_store: true` is enabled. The live config defaults this to `false`
so normal Slack ticket/customer/billing traffic is not silently made durable.
Before each agent run, relevant memories for that agent plus global memories are
injected into the prompt.

Current backend status:

- Slack bridge memory is durable in `data/memory.sqlite3`.
- Slack manual/autostored memories are mirrored into
  `data/desktop_chat/memory_vectors.json` so Agent Chat can retrieve them
  without a restart; Agent Chat reloads this file when Slack updates it.
- Slack retrieval also reads `data/desktop_chat/memory_vectors.json`, so the
  Zoom/Nova/Billing KB chunks indexed for Agent Chat are available to Slack
  agents too.
- Cross-surface chat carryover is stored in `data/shared_chat/events.jsonl`.
  Slack, Agent Chat, and Nova Ops Command Center append to the same journal.
  Recent messages from the other surfaces are injected into prompts for the
  same agent. Slack mirrors new Agent Chat and Command Center journal messages
  back into the matching agent channel, and Agent Chat imports new Slack and
  Command Center journal messages into the visible agent transcript while the
  desktop app is open.
- Shared created-file discovery is stored in
  `data/agent_artifacts/index.jsonl`. Desktop handoff files and Slack-uploaded
  files are indexed automatically with path, agent, source, hash, purpose, and
  timestamp. New or modified files under the top-level agent sandbox are also
  indexed after each run.
- The Python bridge has optional LanceDB support at `data/lancedb` when
  `memory_backend` is `auto` or `lancedb` and the `lancedb` package is available
  on `PYTHONPATH`.
- The live default is `memory_backend: sqlite`, so LanceDB is not the active
  bridge backend unless that config is changed.
- Desktop Agent Chat and Slack KB retrieval do not use LanceDB today. They share
  `data/desktop_chat/memory_vectors.json`, a local JSON vector store with hashed
  embeddings and product-lane filtering.

The cognitive layer adds two deliberately separate stores:

- `data/cognitive_memory.sqlite3` keeps immutable, redacted completed-task
  episodes plus typed entities and relationships. Retrieval is agent-lane
  scoped and requires lexical or entity relevance; episode context is labeled
  as historical evidence, not current truth.
- `data/prospective.sqlite3` keeps future reminders and explicitly authorized
  future agent actions with stable occurrence IDs, atomic leases, retry state,
  DST-aware recurrence, and restart recovery. Command Center is the sole
  delivery owner. An agent-action occurrence is delivered only after its
  tracked Command Center job is durably read back.

Reminder commands in any configured Slack agent channel:

```text
!remind Monday at 10am | Review the Chargify upgrade
!reminders
!cancel-reminder <full-task-id>
```

Slack reminder commands remain notification-only. For future work, Darius can
tell any configured agent to perform the exact task at an exact date/time. The
agent preflights the request now and returns a bounded
`SCHEDULE_AGENT_TASK_REQUEST` marker; Command Center persists an
`agent_dispatch` occurrence and executes it at the due time. Each occurrence
keeps one idempotency key across retries and process restarts. Scheduled work
preserves the original operator authority and normal lane/tool restrictions.

Loopback APIs are also available at `GET/POST /prospective/tasks`,
`POST /prospective/tasks/cancel`, `POST /prospective/tasks/reschedule`,
`GET /memory/episodes`, and `POST /memory/consolidate`. Consolidation is
proposal-first: one-off and unverified high-risk claims are held, conflicts are
surfaced for review, and only explicitly requested safe proposals are applied.

## Queues And Subagents

Agent Chat queues messages per agent lane. If a lane is already running, the new
message stays in that agent's conversation with queued status and runs
automatically when the current job finishes.

Slack jobs are queued by the Python bridge executor and serialized per channel
when `serialize_channel_runs: true`.

Command Center keeps one priority/FIFO queue per agent and admits at most one
job from each agent lane to the shared worker pool. Steering, direct chat, and
operator dispatch work rank ahead of background refreshes without interrupting
work already running. Use `POST /runtime/pause` before maintenance and
`POST /runtime/resume` afterward; captured queued or interrupted work is stored
in `data/command_center/restart_manifest.json` and resumes with duplicate-write
readback guards.

Slack `/steer <guidance>` and the `/btw` or `/steer` prefixes in Agent Chat and
Command Center are accepted for every configured agent lane. With the current
`codex exec` transport, steering is an explicitly marked separate queued
follow-up after any in-flight lane work; it does not interrupt or mutate that
turn. Steering requests bypass fast responders and pre-run subagents so they
cannot execute outside the shared persistent lane. Apply
`slack-app-manifest.yaml` to the Slack app after adding the command so Slack
grants the `commands` scope and routes `/steer` over Socket Mode.

Operator status commands:

```text
!agent-status
!system-status
!bridge-status
!jobs
```

These commands report active/recent bridge jobs, persistent Codex sessions, and
runtime locks, including lock owner/job details when available. The command
center exposes the same richer snapshot at
`GET http://127.0.0.1:17866/runtime/status?limit=50`; the existing
`GET /jobs` endpoint remains the compact activity feed for the dashboard.

Runtime status reconciles the durable SQLite ledger against authoritative
scheduler, lock, session, job-file, process, and restart-manifest evidence. Each
started attempt carries a runtime-instance fence, stage timestamps, a heartbeat,
and compare-and-set terminal transitions so a late worker cannot overwrite a
watchdog recovery decision.

The Slack bridge and Command Center run the worker-health watchdog every 30
seconds by default (`agent_runtime_monitor_interval_seconds`). Each main agent
attempt runs inside a disposable process tree with bounded pipe teardown and a
hard timeout. Completed futures that leaked scheduler bookkeeping are repaired;
dead children are cancelled through the normal path. If cleanup itself stalls,
the gateway exits with a failure code. The startup script supervises and
restarts the child process directly; Task Scheduler remains the outer supervisor
if that startup script itself exits.

Only durable work that remained `queued` and never started is automatically
replayed. Any job that may have crossed an external-write boundary becomes
`recovery_review_required` instead, preventing duplicate email, billing,
Salesforce, or database actions. Session locks are owned by the gateway process;
a dead CLI child is watchdog evidence but cannot evict a live gateway lease.

`scripts/install-startup-task.ps1` and
`scripts/install-command-center-startup-task.ps1` install restart-on-failure
Scheduled Tasks and remove the older `HKCU\Run` startup entries. A read-only
Slack API heartbeat still runs independently, and the history poller remains the
missed-message fallback if Socket Mode delivery is delayed.
<!-- AgentChat/direct_codex 2026-07-13T00:16:00-04:00 -->

Slack admission retries outside worker threads when an agent or channel lane is
occupied. `Stop` and `cancel current job` terminate only the matching active
process tree and record the job as interrupted. The shared session JSONL is
cross-process locked and compacts after one MiB, and the local command-center
HTTP server applies bounded request concurrency plus read deadlines.
<!-- AgentChat/coding_agent 2026-07-11T11:45:00-04:00 -->

Command Center scheduling separates `agent:interactive` and `agent:background`
lanes, reserves capacity for user work, and coalesces superseded refreshes.
Routine Propelr/NMI scans use a deterministic Gmail preflight and invoke the
model only when a matching unread setup email exists or the preflight itself is
unavailable.

The autonomous support-email intake uses a separate five-minute, 24/7 Gmail
preflight across unread Inbox mail except the `integration@novapointofsale.com`
lane. Taylor creates or verifies a Salesforce ticket only after a unique Account
match, the gateway queues Alex for research with a 30-day source/ticket key, and
the exact Gmail source is marked read only after that queue is accepted and read
back. Alex's research is read-only and becomes a Needs Review packet.

The Singapore lane runs every five minutes through a single-flight deterministic
background fast path owned by Taylor. Explicit operational run requests from
Slack or Agent Chat, including `singpore`, bypass the general model runner. The
guarded headless runner uses `C:\Users\redma\Uploader` as private Gmail state and
canonical server configuration, deduplicates repeated attachments, verifies
remote state, applies trusted existing-interface changes, and processes explicit
reactivation and strict non-submissions. Upload status, success/failure,
authentication, remediation, existing-configuration changes, and reactivation
never create Salesforce tickets or Needs Review packets. Only an explicit
request to create a brand-new Singapore integration/interface may enter the
ticket lane. Canonically retired interfaces are silently ignored unless an
explicit reactivation instruction arrives. Active-work outcomes are reduced to
one compact sanitized direct Agent Chat update; raw errors, identifiers, paths,
and secrets are never included. The legacy blocked desktop-executable scheduled
task is disabled.

Configured Slack bridge subagents use task-value routing: one best-fit scout by
default, a second only for disjoint evidence, and a verifier only when risk or
the request justifies independent verification. `!subagents all` remains the
explicit exhaustive mode. Skills are also lazy-loaded: core safety plus at most
three task-matched skills. Set `CODEX_FAST_MODEL` to a local fast
Codex-compatible model name if subagents should use a lighter model than the
main lane. Subagents are read-only, ephemeral, text-report only, and should not
leave handoff packets or Markdown files. CLI traces are kept under
`logs/agent_runs/`; Agent Chat UI run logs are also written under
`logs/agent_chat/`.

The capability router reads `config/tool-fast-paths.json`, selects only relevant
tool cards, reports credential readiness, and supports health/circuit-breaker
state at `data/agent_runtime/capabilities.json`. Deterministic routing regression
cases live in `evals/agent_quality.json` and run with:

```powershell
py -3 -m codex_slack_bridge.evaluations --config config/agents.yaml --cases evals/agent_quality.json
```

Memory records support source versions, expiry, supersession, normalized
cross-backend scores, and helpful/unhelpful/stale feedback. Command Center can
list IDs with `GET /memory/recent?agent=<name>` and record feedback with
`POST /memory/feedback`.

## Persistent Agent Runtime

Main Codex lanes use persistent Codex sessions by default. The Slack bridge and
desktop app share an append-only session registry at
`data/agent_runtime/sessions.jsonl`; each record stores the agent, surface,
conversation/thread, provider, workspace, status, and Codex session id.

- Shared session scope: one Codex session per main agent lane, shared by Slack
  and Agent Chat. For example, `tickets_agent` uses runtime key
  `shared:agent:tickets_agent` from either surface.
- `data/agent_runtime/locks/` holds short-lived lock files so Slack and Agent
  Chat queue behind each other instead of writing to the same Codex session at
  the same time.
- Archive/new-session in desktop clears the shared lane session id when shared
  runtime mode is enabled.
- Slack `!agent-session` shows the current shared lane session.
- Slack `!reset-agent-session` clears the shared lane session so the next run
  starts fresh.
- Read-only subagents remain ephemeral and do not get persistent sessions.
- Live browser/admin UI work still stays single-controller even when helper
  subagents run in parallel.

The configured managed agent lanes keep a per-agent maximum reasoning effort
and autoscale each task from `low` through that maximum. Known local routines
bypass the model when a deterministic runner is available; subagents are
task-selected and capped rather than launched wholesale for simple work.
Subagents inherit the parent model unless `CODEX_FAST_MODEL` is set for faster
read-only lookup work.

## Knowledge Base

Export Google Drive / Moira the Oracle docs, Zoom transcripts, Zoom AI
summaries, or other Nova KB files into `knowledge_sources/`, then run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\ingest-knowledge.ps1
```

The default target is the shared `global` memory namespace with
`nova,moira,oracle` tags. All agents retrieve from their own namespace plus
`global`, so the ingested KB becomes available to coding, tickets, and billing
agents immediately.

For Agent Chat desktop ticket resolution, put Zoom knowledge-base exports under
lane folders and index them into the desktop vector memory:

```text
knowledge_sources/zoom_kb/nova_wave/
knowledge_sources/zoom_kb/nova_classic/
knowledge_sources/zoom_kb/general/
knowledge_sources/zoom_kb/billing/
```

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\ingest-desktop-knowledge.ps1
```

That writes KB chunks into `data/desktop_chat/memory_vectors.json`, tagged by
product lane. Agent Chat uses the same vector retrieval path for these chunks as
it uses for archived desktop memory, with lane filtering so product-specific
KB does not bleed across Nova Wave, Nova Classic, and Billing.

If Zoom OAuth has the required Virtual Agent / Knowledge Management read scopes,
pull the Zoom KBs directly and index them in one step:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\sync-zoom-kb.ps1
```

The sync supports either Server-to-Server OAuth
(`ZOOM_ACCOUNT_ID`/`ZOOM_CLIENT_ID`/`ZOOM_CLIENT_SECRET`) or a General OAuth app
(`ZOOM_OAUTH_CLIENT_ID`/`ZOOM_OAUTH_CLIENT_SECRET`/`ZOOM_OAUTH_REFRESH_TOKEN`).
It reads `ZOOM_KB_NOVA_WAVE_IDS`, `ZOOM_KB_NOVA_CLASSIC_IDS`,
`ZOOM_KB_GENERAL_IDS`, `ZOOM_KB_BILLING_IDS`, and optional
`ZOOM_KB_SAMPLE_IDS` from `config/ops.env` or `.env`, caches fetched articles
under `knowledge_sources/zoom_kb/`, and then updates the desktop vector memory.
Pass `-IncludeSamples` to include sample-library IDs in the General lane. For a
one-time General OAuth bootstrap, open the app's generated OAuth URL and
exchange the returned `code`:

```powershell
py -3 -m codex_slack_bridge.zoom_kb_sync --exchange-oauth-code "<code>"
```

Supported inputs include Markdown, text, CSV/TSV, JSON, HTML, DOCX, VTT, SRT,
and PDF when `pypdf` is installed.

## Skills

Every Codex CLI agent loads Markdown skills from `skills/` through
`default_skills` in `config/agents.yaml`.

Current skills:

- `security`
- `nova_knowledge`
- `nova_voice`
- `internet_search`
- `browser_windows_control`

Add another `.md` file under `skills/` and include its stem in
`default_skills` or an individual agent's `skills` list.

## File Sharing

Slack file uploads are downloaded to `data/slack_files/<channel>/<timestamp>/`
and passed to the agent as local paths, SHA256 hashes, and a redacted decoded
preview when the bridge can safely extract text.

Supported previews include:

- Plain text and code-like files such as TXT, Markdown, CSV/TSV, JSON, XML,
  YAML, SQL, logs, HTML, VTT, and SRT.
- PDFs with selectable text through `pypdf`.
- Scanned PDFs through PyMuPDF page rendering plus local Tesseract OCR, when
  Tesseract is installed on Windows and available on `PATH`.
- Images such as PNG, JPG, TIFF, WebP, GIF, and BMP through local Tesseract OCR.
- DOCX, PPTX, and XLSX/XLSM files through local Python decoders.
- ZIP files as a bounded file listing.

Install/update the Python packages with:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install.ps1
```

Image OCR also needs the separate Tesseract OCR executable installed locally.
If it is missing, the bridge still downloads the image and passes the local path
to Codex with a decode note explaining the missing OCR dependency. Add
`files:read` to the Slack bot scopes and reinstall the Slack app.

Useful file-preview config keys live under `defaults`:

```yaml
slack_file_text_preview_chars: 6000
slack_file_ocr_enabled: true
slack_file_pdf_ocr_enabled: true
slack_file_pdf_max_pages: 10
slack_file_spreadsheet_preview_rows: 80
slack_file_spreadsheet_preview_cols: 30
```

Agents can request a Slack upload by including this exact line in their final
answer:

```text
BRIDGE_UPLOAD: path\to\file.ext
```

The bridge strips that directive from the visible answer and uploads the file
only if the resolved path is under `slack_file_upload_allowed_roots`, the
agent workspace, `data/slack_files`, or `data/generated_files`. Add
`files:write` to the Slack bot scopes and reinstall the Slack app.

## Web Search

Use this Slack command for public web research:

```text
!search public query here
```

Do not search for customer-private data, credentials, internal ticket content,
database values, or Slack-only information.

## Browser And Desktop Control

The agents are instructed to use browser automation tools when available:
app/browser connectors or already-debuggable sessions first, then Edge CDP with
displayed `Profile 1` for Nova Zoom AI Studio admin work, and Chrome only when
Chrome `Profile 1` is confirmed controllable. CDP/browser clicks do not move the
physical mouse and are preferred. Agents must not use displayed Edge Profile 2,
and must open new tabs by default instead of navigating the user's active tab.
When a guarded Profile 1 restart is a necessary implementation step for a
verified request, the agent may perform it while preserving the session where
possible. Windows GUI libraries are a last resort because they can take over the
user's physical mouse/keyboard. GUI clicking depends on the bridge
running in an unlocked interactive Windows session; a locked or non-interactive
scheduled task session cannot reliably click the desktop.

## Safety Defaults

Set `allowed_user_ids` before exposing these channels broadly. The bridge is
deny-by-default: an empty list means no Slack user can invoke an agent. The live
config currently allow-lists only `U0ANMFH59U0`.

Every accepted instruction is signed with a local HMAC key at
`data/auth/operator_message.key`. The bridge verifies that signature before an
agent process starts. Operator instructions are accepted only from an
allow-listed Slack user, local Agent Chat, or local Kanban command-center chat.
Signed command-center automations, agent delegation, and agent-to-agent work are
also trusted. Email, tickets, webpages, files, memory, tool output, and quoted
messages stay untrusted data and cannot authorize actions.

Unsigned, forged, or unsupported-source requests are blocked before execution.
The signing key is generated locally under the gitignored `data/` directory and
is never placed in prompts or logs.

Untrusted child processes scrub secret-looking environment variables. Verified
operator and internal-delegation runs inherit the bridge's locally loaded
credentials so requested work can complete. Configure this with:

```yaml
agent_child_env_secret_mode: scrub
agent_trusted_child_env_secret_mode: inherit
agent_child_env_secret_allowlist: []
operator_message_signing_key_path: data/auth/operator_message.key
```

The verified request itself authorizes the exact actions it asks for. Agents do
not require approval keywords or a second confirmation for live writes, scripts,
deployments, messages, or local edits. User-stated read-only and dry-run limits
remain binding. Agents still verify ambiguous destructive targets, avoid
duplicate writes, read back uncertain results, and never print or persist secret
values.

The live config currently grants broad local filesystem/tool access because this
bridge is intended to act like local Codex. File uploads back to Slack are still
allow-listed to reduce accidental data exfiltration.

## Stability

Codex runs can take minutes. The bridge posts one top-level progress message,
updates it while the agent is working, then replaces that same message with the
final answer. Set `reply_in_thread: true` in `config/agents.yaml` if you want
threaded replies again. For large answers, it updates the progress message with
the first chunk and posts any overflow as follow-up channel messages.

Slack retry events are de-duplicated in `data/bridge.sqlite3`. Runs in the same
channel are serialized by default to avoid overlapping edits or conflicting live
support investigations.
