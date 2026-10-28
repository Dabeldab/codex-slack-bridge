<!-- AgentChat/coding_agent 2026-07-10T18:20:00-04:00 -->
<!-- AgentChat/direct_codex 2026-07-14T02:25:00-04:00: register the durable inbox-ledger collector path. -->
<!-- AgentChat/coding_agent 2026-07-14T12:20:00-04:00: treat concrete Darius deadlines and reminders as Drawing Board tasks. -->
<!-- AgentChat/coding_agent 2026-07-14T19:30:00-04:00: add guarded same-mailbox invoice acknowledgements. -->

# Gmail Operations

## Fast route

1. Use the connected Gmail tools: `list_labels` for mailbox/thread counts,
   paginated `search_emails`, `batch_read_email`, then `read_email_thread` when
   a decision needs conversation context.
2. Mutate by exact Gmail message or thread ID. Routine triage is thread-scoped.
   For a reply or reply draft, use the exact live source message ID being
   answered and Reply All by default.
3. Use the gateway Gmail REST path only when the connected tool lacks the
   needed label/draft operation. Browser is last.
4. Read back the affected thread/draft. Never infer success from intent.

## Taylor live-inbox workflow

- Source of truth: the actual Gmail Inbox and Spam, not
  `data/command_center/ops_email_watch.json`.
- Command Center ingestion uses one native Gmail history collector every 75
  seconds. It stores bounded metadata and resumable state in
  `data/command_center/inbox_work.sqlite3`; it does not use Taylor's model lane
  when no new judgment work exists.
- The collector deterministically routes existing Singapore operations, trusted
  NMI setup mail, exact Salesforce notifications, and explicitly allowlisted
  junk before consolidating remaining customer mail into one Taylor intake job.
- Judgment-bearing intake is serialized on Taylor's dedicated `inbox` lane, so
  dashboard and schedule refreshes cannot hold new mail behind the general
  background lane; direct chat remains independently prioritized.
- Dashboard Mail Watch is projected directly from the ledger. Its authenticated
  loopback event stream is `/ops/inbox-ledger/events`, with the existing
  visible-only 60-second UI poll as fallback. Health and aggregate metrics are
  available at `/ops/inbox-ledger/status`.
- The durable states are `detected`, `classified`, `assigned`,
  `action_pending`, `write_verified`, and `complete`. A timed-out Gmail write
  must be read back through Gmail before retry; a checkpoint never advances
  beyond mail that was not durably recorded.
- Paginate live Inbox results, deduplicate by `threadId`, and read the full
  thread before deciding its current state. Mail Watch is an unread-and-
  unanswered action queue, not an inbox mirror or archive.
- Exclude a thread when it is read or its latest message has the `SENT` label.
  A newer unread inbound message after Darius's reply makes the thread eligible
  again when it still requires his reply or decision.
- Archive and mark read routine noise, completed FYI, and already-tracked
  notifications. Move obvious false positives from Spam to Inbox. Publish only
  current unread-and-unanswered action threads; failures, FYI, waiting-without-
  action, and automated status stay out.
- Email-watch triage otherwise drafts replies for review and does not send as
  part of a scan. The narrow exception is an unread customer reply whose
  normalized subject is exactly `Your NovaPOS invoice is ready`: send one
  acknowledgement through the signature-preserving gateway from the verified
  `sendAs` mailbox matching the original recipient, then continue normal
  support intake. `skills/customer_email.md` remains the single authority for
  reply delivery, signatures, and Salesforce/Zoom template preservation.
- An operator-requested Gmail reply draft is always a native thread reply, not
  a new message. Derive its audience only from the live `Reply-To`/`From`,
  `To`, and `Cc` headers; never type or infer an address from a name or company
  naming pattern. Reply All is the default. Narrow that set only when Darius
  explicitly names recipients to omit or says to reply only to a subset.
- Preserve the exact live addresses. The `Granbury Retail - OHIO Sales` thread,
  for example, contains `yaron@novapointofsale.com`; it must never be rewritten
  to a guessed `firstname.lastname` address.
- Save the draft with the selected Gmail `sendAs` identity's current signature
  exactly once and read the draft back for exact thread, To, and Cc equality.
  Agents never author a signature block. If the connected draft tool cannot
  preserve both the exact Reply All headers and signature, use Gmail's native
  Reply All UI instead of composing recipients manually.
- A separate Command Center verified-delivery gateway handles a direct
  operator request for one new message when the exact address is in the
  operator request or in explicitly referenced source-bound ticket/message
  evidence. Custom recipient domains are allowed; there is no domain
  allowlist. The runtime, not the model or connected-app approval layer,
  validates the recipient and attachment hashes, derives idempotency, preserves
  the active Gmail signature, sends once, and performs exact SENT readback.
- Do not delete/trash, change filters, or make calendar changes from email watch.
- Singapore non-submission, zero-sales, and upload-failure flows belong to the
  dedicated Singapore runner, not general inbox triage. Pure zero-sales notices
  are marked read automatically with exact Gmail readback because the store
  owner, not Nova, must respond; mixed notices still process true missing dates
  before their source message is acknowledged.

## Drawing Board candidates

- Operational mail, assigned deadlines, reminders, follow-ups, decisions, and
  concrete meeting preparation explicitly directed to Darius may create one deterministic task keyed to the Gmail
  thread or calendar event. Update that brief rather than duplicating it.
- A manager-assigned deadline is a task even when the email needs no reply.
- The source must establish a concrete outcome, immediate next action, Darius's
  exact owner action, source link or identifier, and objective done criteria.
  Otherwise create no brief.
- Brief creation never dispatches work automatically.
- Exclude support-ticket mail, Salesforce notifications, automated telemetry or
  failures, Singapore existing/retired-interface, authentication, upload-status,
  and remediation mail, and vague meeting invitations. Only an explicit request
  for a brand-new Singapore integration/interface may follow its separate ticket
  path.
- Store only a sanitized source reference in Mail Watch and Drawing Board data;
  never copy credentials, tokens, private attachment contents, or other secrets.

## Native API fallback

- Token path: `ops_gmail_oauth_token_path`; required scope: `gmail.modify`.
- Message labels: `POST /gmail/v1/users/me/messages/{id}/modify`.
- Thread labels: `POST /gmail/v1/users/me/threads/{threadId}/modify`.
- Archive: remove `INBOX` and `UNREAD`; mark read: remove `UNREAD`; restore a
  legitimate Spam thread: add `INBOX`, remove `SPAM`.
- Verify returned labels for every message in a thread. If the response is
  uncertain, GET the thread before retrying.

Canonical triage implementation: `skills/email_watch.md` and
`src/codex_slack_bridge/command_center_server.py`, with ledger and routing in
`src/codex_slack_bridge/inbox_ledger.py`. Canonical customer-email presentation
and delivery rules: `skills/customer_email.md`.

## Collector rollback

- `ops_inbox_ledger_enabled: true` makes the collector the only scheduled Gmail
  ingestion owner and suppresses the legacy Mail Watch, support-intake,
  Singapore-email, and NMI-email watchers.
- Keep the legacy flags configured only as a reversible fail-open path. To roll
  back, drain active work, pause Command Center, disable the ledger flag, restart
  once, and reconcile Gmail IDs before resuming. Never run old and new mailbox
  writers concurrently.
