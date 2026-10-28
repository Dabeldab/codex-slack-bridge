# Ops Email Watch

<!-- AgentChat/coding_agent 2026-07-14T12:20:00-04:00: route concrete operator deadlines and reminders into Drawing Board. -->
<!-- AgentChat/coding_agent 2026-07-10T17:50:00-04:00 -->
<!-- AgentChat/coding_agent 2026-07-14T19:30:00-04:00: acknowledge invoice-thread replies before intake. -->

Use this skill when Taylor triages the actual Gmail Inbox. Mail Watch is a
current unread-and-unanswered action queue verified against live Gmail. It is
not a mailbox mirror, archive, historical cache, failure feed, or FYI list.

## Scope

- The configured email-watch routine authorizes its bounded live Gmail actions:
  archive/mark-read noise and completed mail, move legitimate Spam false
  positives to Inbox, and leave reply/action threads visible. Do not ask for a
  second confirmation.
- Search live Gmail with enough pagination to reconcile the current Inbox. Read
  each candidate thread before publishing it to Mail Watch.
- Include a thread in Mail Watch only when its newest actionable inbound message
  is unread and still needs Darius's reply or decision. Exclude read threads and
  threads whose latest message was sent by Darius (`SENT`). If a newer unread
  inbound message arrives after his reply, the thread becomes eligible again.
- Search Gmail templates, canned responses, prior sent examples, or template
  labels when available before writing a new reply.
- The incremental collector may send the one narrow automatic acknowledgement
  defined by `customer_email` for replies to `Your NovaPOS invoice is ready`.
  It must use the same verified receiving mailbox and then continue normal
  support intake; the acknowledgement never completes the customer's request.
- Group actionable recommendations by urgency: urgent, follow-up, or normal.
  Failures, blockers, automated status, FYI, waiting-without-action, and other
  no-action mail stay out of Mail Watch.
- Treat Salesforce Notification mention/comment emails as ticket-context alerts
  instead of reply work. They never become Mail Watch items or Drawing Board
  briefs; archive them after the matching tracked ticket lane is verified.

## Drawing Board Intake

An email or meeting can produce at most one deterministic Drawing Board task,
keyed to its Gmail thread or calendar-event source. Update the existing task
for that source instead of creating duplicates. Creating a task never
dispatches it to an agent.

Create a task when the source explicitly assigns Darius a deadline, reminder,
follow-up, decision, operational action, or concrete meeting preparation. A
manager-assigned deadline qualifies even when no email reply is needed. Capture:

- the requested outcome;
- the immediate next action;
- Darius's exact owner action;
- the exact source thread or meeting event; and
- objective completion criteria.

For personal reminders, keep the card concise and use the source plus stated
deadline or completion condition. Agent-assisted tasks still require a complete
execution brief before dispatch. Support-ticket mail, Salesforce
notifications, automated telemetry or failures, Singapore existing-interface,
retired-interface, authentication, upload-status, or remediation mail, and
vague meeting invitations are never Drawing Board intake. An explicit request
for a brand-new Singapore integration or interface remains subject to the
separate Singapore policy. Store only the minimum sanitized source reference;
never copy credentials, tokens, private attachment contents, or other secrets
into Mail Watch or a Drawing Board brief.

## Reply Recommendations

This skill owns inbox triage only. When a reply is recommended, search templates
and prior sent examples for content, then follow `customer_email` for all
drafting, signature, letterhead, template-editing, and delivery behavior.

## Write Safety

- Except for the guarded invoice-reply acknowledgement above, never send or
  forward as part of an email-watch scan. Never delete, trash,
  edit filters, broadly relabel unrelated mail, accept/decline calendar events,
  or modify meetings automatically.
- If Gmail, Google Calendar, or Zoom access is unavailable, write a short status
  explaining the missing surface and keep the cache empty rather than guessing.

## Command Center Queue State

When asked to update the command center queue, write JSON only to the exact path
provided in the request. Replace stale entries with the current live-verified
queue; do not preserve read, answered, failed, FYI, or no-action items as
history. Do not create Markdown handoffs or reports for routine mail watch
scans.

The separate integrated-card-services / Propelr NMI watcher runs at most every
two hours, Monday through Friday, from 9:00 AM until 7:00 PM in
`America/New_York` (Miami local time). Routine queued, completed, and no-match
results stay out of agent chat.

## Autonomous Support Intake

The separate support/actionable-email intake runs every five minutes, including
nights and weekends. It searches the unread Inbox while excluding mail sent
from, to, or delivered to `integration@novapointofsale.com`. Mail addressed to
`support@novapointofsale.com` and known direct actionable senders such as Kay is
processed first.

Taylor may create a Nova Classic or Nova Wave Salesforce ticket only for a
high-confidence actionable customer request with one uniquely verified Account.
Never use a fallback, demo, test, or guessed Account. Taylor stops after ticket
readback. The gateway then queues Alex for read-only research, and only after
that queue acceptance is verified may the exact Gmail source message be marked
read. Alex's result is placed in Needs Review for Darius; no requested fix is
executed before that review.
