# Command Center Email and Singapore Runtime

<!-- AgentChat/direct_codex 2026-07-16T10:30:00-04:00 -->

## Purpose

This document records the authoritative runtime design for immediate email
processing and the recurring Singapore integration workflow. It exists so a
future operator can identify the active path, understand why older processes
are absent, verify service health, and safely roll back a change.

## Email processing

Command Center has one Gmail ingestion owner: `ops-inbox-ledger-collector`.
It reads Gmail history, stores durable state in
`data/command_center/inbox_work.sqlite3`, deduplicates by message and thread,
and queues agent work only for material inbound mail.

The collector runs every 10 seconds. This is near-real-time polling: expected
detection latency is up to roughly 10 seconds plus agent queue/runtime time.
Legacy Mail Watch, support-intake, Singapore-email, and NMI-email watchers stay
suppressed while the ledger is healthy because running both paths could create
duplicate jobs or duplicate external actions.

Customer-authored cancellation confirmations delivered to
`billing@novapointofsale.com` use the dedicated
`ops-billing-closure-email-intake` route. The collector stages the exact Gmail
RFC message as a bounded EML and sends one isolated job to Jamie. Jamie must
inspect the body and authoritative active-location set before classifying the
request as full-account, specific-location, or ambiguous. Subject wording such
as `close account` is never sufficient.

Jamie reuses a clearly matching open Billing/Classic/Wave request ticket or
creates one privately idempotent `3. Billing` ticket, then attaches the exact
EML by SHA-256. Source identity remains in the broker journal and never enters
Salesforce ticket fields. This intake step cannot close an Account or Location, create an order,
change Maxio, move money, or contact the customer. The runtime independently
reads the exact Salesforce ticket and attachment digest through the broker
before it marks only that Gmail message read. A mismatch or unavailable
readback leaves Gmail unread and returns the ledger item to bounded retry.

Relevant configuration:

- `ops_inbox_ledger_enabled: true`
- `ops_inbox_ledger_interval_seconds: 10`
- `ops_inbox_ledger_fail_open_to_legacy: false`
- `ops_inbox_pending_reconcile_interval_seconds: 300`
- `ops_inbox_pending_retry_seconds: 1800`

The health endpoint exposes `inboxCollector.lastPoll`, poll metrics, integrity,
current ledger states, and stale pending-obligation counts. Every five minutes,
the collector also reads a bounded set of pending message IDs back from Gmail.
Already-read mail is terminalized from live label evidence; unread work is
reclassified from its current subject/snippet and requeued only when its prior
assignment is terminal or missing and at least 30 minutes old. Legacy writers
remain disabled if the ledger is unavailable so degraded mode cannot create a
second writer.

## Singapore processing

`ops-singapore-ftp-watch` is a separate deterministic operational scheduler.
It does not belong to the legacy email fallback and must start whenever
`ops_singapore_ftp_enabled` is true, regardless of inbox-ledger state.
Its deterministic jobs use the dedicated `coding_agent:service` lane, so KPI,
ticket, and research work in ordinary background lanes cannot consume the
reserved background capacity and leave Singapore waiting.

Relevant configuration:

- `ops_singapore_ftp_enabled: true`
- `ops_singapore_ftp_interval_seconds: 300`
- `ops_singapore_ftp_local_hour: 8`
- `ops_singapore_ftp_timezone: America/New_York`

The five-minute watcher interval checks the local-time gate only. Automatic
processing runs once per calendar day at 8:00 AM Eastern, after the prior
night's normal 10:00-10:30 PM delivery window. The explicit run-now endpoint remains available.
Inbox collection still classifies Singapore messages immediately, but it defers
their assignment to the daily job instead of launching an upload on arrival.

The runner retains its existing single-flight, idempotency, thread/account/date
deduplication, guarded Gmail readback, exact-recipient Zoom rule, and private
credential boundary. Authentication failures are catalogued first, then their
exact Gmail sources are marked read with per-message label readback so failed
interfaces cannot grow the inbox. They must never cause a tight retry loop or
reveal credentials.

The persisted Singapore result is deliberately writable by two processes: the
broker owns successful/blocked workflow output, while Command Center may publish
a fail-safe result if the child process exits before producing one. Both run in
the dedicated `nova-singapore-shared` group, the directory is setgid, and every
replacement uses a unique atomic temporary file. This preserves broker
readability across alternating writers and prevents concurrent cache/job writes
from racing on one fixed `.tmp` pathname.

Every Singapore source message is reconciled independently. An upload source
is complete only after remote size verification and Gmail `UNREAD` label
readback. A non-submission source is complete only after one Julio Zoom message
has provider readback and that exact Gmail message is verified read. Failed or
unmatched sources remain catalogued; authentication failures are completed in
the inbox ledger only after Gmail readback proves the source is read. A globally
successful scan never completes sources in bulk.

Pure zero-sales notices are a separate terminal class: they require store-owner
confirmation, not Nova action, so the inbox collector or Singapore runner marks
each exact message read and verifies the Gmail label change. Mixed notices still
extract and deliver true non-submit dates before their source is acknowledged.

The headless runner reuses the desktop uploader's shared transfer sessions and
retry helper without launching the UI. Authentication rejection opens a
15-minute per-server probe circuit. Daily scheduling now provides the effective
retry bound while allowing corrected credentials to recover on the next run.

The retirement policy is deliberately evidence-based. An active interface is
eligible for a credential-free retired tombstone only after 90 observed days in
which both conditions remain true: there is no verified successful submission,
and there is no verified customer configuration, resubmission, or reactivation
contact. A success or contact resets the 90-day clock. Missing evidence fails
closed, so the migration cannot retire an interface merely because its current
credentials fail.

## Change record

On 2026-07-29, billing closure confirmations were moved out of generic Taylor
support triage and into a typed Jamie intake. The new route preserves the
customer email as Salesforce evidence, creates a Billing ticket when no matching
request ticket exists, treats location-narrowing text as stronger than
account-like subject wording, and gates Gmail acknowledgement on independent
ticket-plus-digest readback.

On 2026-07-15, the inbox collector was found healthy but configured for a
75-second poll. The Singapore watcher was also incorrectly guarded by
`legacy_email_fallback`, which prevented its recurring five-minute thread from
starting whenever the inbox ledger was active.

The correction:

1. Reduced the authoritative Gmail collector interval from 75 seconds to 10.
2. Kept legacy email writers suppressed to preserve single-writer behavior.
3. Removed Singapore from the legacy-email condition so its scheduler is
   independent.
4. Added regression coverage proving the ledger and Singapore watchers start
   together while legacy email writers remain absent.

Later on 2026-07-15, a second regression was identified: upload failures were
omitted from the top-level status, and a globally complete scan could complete
all assigned Singapore inbox items without per-message Gmail readback. The
correction:

1. Makes any failed, unmatched, authentication-blocked, or non-complete upload
   produce top-level `partial`.
2. Reconciles upload, server-configuration, and non-submission sources by exact
   Gmail message ID.
3. Uses the uploader's existing retry helper while retaining remote-size
   verification before Gmail acknowledgement.
4. Persists and reuses Julio's exact Zoom message ID/body, preventing a resend
   when only Gmail label readback needs retrying.
5. Caps authentication suppression at 15 minutes and then performs one bounded
probe per affected server.

A third correction restored non-submission backlog handling:

1. Non-submission matching now uses the same canonical runtime `servers.json`
   as uploads instead of the desktop repo's older copy.
2. A 14-day recovery scan includes notices that an older runner marked read
   before Julio delivery was verified.
3. Consolidation preserves every Gmail source ID for per-message readback.
4. Verified source IDs are journaled in private runtime state so scheduled
   cycles do not resend the same notice to Julio.
5. Singapore uses a dedicated deterministic service lane and can start while
   the ordinary background-model capacity is full.
6. Alternate `Sales submission issue` subjects and table layouts without a
   `Machine ID:` colon are parsed from current-message rows rather than quoted
   thread history.

On 2026-07-16, operator policy changed the routine again:

1. Automatic Singapore processing runs once at the 8 AM Eastern automation
   opening, after the prior night's observed daily delivery window.
2. The inbox collector stopped launching Singapore immediately on receipt.
3. Catalogued authentication failures are marked read only after exact Gmail
   readback; no customer reply, Salesforce ticket, or Needs Review item is made.
4. A durable, secret-free evidence ledger tracks last verified success and last
   verified customer resubmission/configuration/reactivation contact.
5. Automatic retirement requires both signals to be absent for 90 observed
   days and writes a credential-free tombstone through the typed private patch
   operation. Missing evidence prevents retirement.

## Verification

After changing runtime code or configuration:

1. Run the focused inbox-ledger and scheduler tests.
2. Run the full repository test suite.
3. Drain active agent jobs before restarting supervised services.
4. Confirm `/health` reports `paused: false`, `degraded: false`, and a current
   successful inbox poll.
5. Confirm an inbound controlled email produces exactly one ledger item/job.
6. Verify the 8 AM Eastern daily due gate across both EST and EDT, plus one
   explicit run-now path without duplicate notifications.
7. Record any remaining Singapore authentication failures by sanitized machine
   identifier only.

## Rollback

Email latency and Singapore scheduling are independently reversible:

- To reduce Gmail API polling frequency, restore
  `ops_inbox_ledger_interval_seconds` without enabling legacy email writers.
- To stop Singapore intentionally, set `ops_singapore_ftp_enabled: false` in an
  authorized configuration change. Do not couple it to inbox-ledger state.
- After rollback, drain and restart safely, then repeat email deduplication and
  daily-gate and explicit-run verification.

## 2026-07-15 deployment evidence

- Focused inbox, scheduler, security, and configuration tests: 157 passed.
- Authoritative bridge suite: 679 passed.
- Rescue and scoped-operations connector suites: 16 passed.
- Gateway reloaded from process 39588 to process 14428 and reported
  `paused: false` and `degraded: false`.
- Startup logs confirmed `ops-inbox-ledger-collector` at 10 seconds and
  `ops-singapore-ftp-watch` at 300 seconds.
- Gmail collector timestamps advanced continuously through
  `2026-07-15T18:59:51Z` with successful polls and no queue buildup.
- Consecutive Singapore runs completed at `2026-07-15T18:54:33Z` and
  `2026-07-15T18:59:28Z`; the next run was scheduled for
  `2026-07-15T19:04:18Z`.
- The second Singapore run reported zero authentication-blocked servers.

That final zero-authentication statement is historical evidence for the earlier
deployment only. It must not be treated as current health; use the latest
`ops_singapore_ftp.json` per-message details and live cycle readback.

Latest recovery test evidence before activation: 52 uploader tests, 180
focused scheduler/Gmail/Singapore/ledger tests, and 686 complete bridge tests
passed.

Final live readback on 2026-07-16:

- Gateway PID `28164` was healthy, unpaused, and non-degraded; the Gmail
  collector continued successful 10-second polling.
- Backlog reconciliation recorded 17 verified non-submission source messages
  only after Julio delivery and per-message Gmail readback succeeded.
- Natural cycles `cc-20260716T040443Z-1ad94faf70` and
  `cc-20260716T040944Z-c13c6c65c1` completed on `coding_agent:service` without
  duplicate delivery.
- Before the 2026-07-16 policy change, upload completion was externally blocked: 27 unread source messages
  map to three servers that reject authentication (`2000117`: 11,
  `8000860`: 8, `8000784`: 8). The runner reports `partial` and performs no
  Gmail acknowledgement for them. The current policy replaces that behavior
  with catalog-first, per-message verified Gmail acknowledgement.
