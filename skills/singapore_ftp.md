# Singapore POS Upload and Non-Submission Workflow

<!-- AgentChat/direct_codex 2026-07-16T10:30:00-04:00 -->

Use this for the established recurring Singapore upload-failure, trusted
server-change, and non-submission routines.

## Boundary

- Do not launch the desktop UI. Run its established Gmail detection and
  FTP/SFTP modules through the headless verified runner.
- Automatic runs perform verified Grab & Upload, apply authenticated trusted
  server-change notices, and run the strict non-submission parser. Julio is
  messaged only when that parser returns true missing dates. The private
  transfer catalog does not gate a valid customer non-submission notice.
- Automatic processing runs once daily at 11 PM America/New_York, after the
  normal 10-10:30 PM delivery window. Inbox ingestion classifies immediately
  but does not launch Singapore work; explicit run-now remains available.
- Upload status, success/failure, authentication, remediation, existing-interface
  configuration, and reactivation are background-service operations. They never
  create Salesforce tickets or Needs Review packets.
- Only an explicit request to create/build/add/provision/onboard/set up a
  brand-new Singapore integration/interface may create a Salesforce ticket.
- Silently ignore a canonically retired/deactivated interface without processing
  or operator notification unless an explicit reactivation instruction arrives.
- Use only the deterministic background-service endpoint. It resolves its parser,
  transfer modules, credentials, and canonical interface configuration internally.
  Agents must not locate, inspect, reproduce, or directly execute those private
  implementation surfaces.

## Operator Authority

- A verified instruction from Darius is authorization to perform the requested
  action. Do not ask for a special approval phrase or a second confirmation.
- Do not initiate sends, mailbox mutations, server-list changes, or unrelated
  writes without a verified operator instruction or the configured recurring
  routine authorization.
- Verify target identifiers and read back writes. Never retry an uncertain
  write blindly.

## Email Rules

- Search unread Gmail for `Unable to send file to ftp server` and the uploader's
  attachment-bearing fallback query.
- Upload only attachments whose filename matches the canonical private server list.
- Before uploading, check whether the same remote filename and size already
  exist. Treat that as complete without uploading again.
- After one upload attempt, verify the remote file size. Never retry an uncertain
  upload until the remote state has been read back.
- Record every attempted tenant in the private service status catalog
  as working, authorization failed, transfer failed, unresolved, or configured
  but not yet verified. Do not store credentials in the catalog.
- Catalog every automated upload outcome first. Mark authentication-failure
  sources read only with exact per-message Gmail label readback so the inbox
  does not accumulate known failures. No operational source is gated on a Salesforce ticket or
  Alex review handoff. Verified retired-only sources are omitted from work and
  operator results, silently ignored, and acknowledged only through guarded
  Gmail readback.
- For active work, send Darius at most one compact sanitized direct Agent Chat
  line with success, partial, or failure plus allowlisted counts. Never include
  raw exceptions, identifiers, filenames, paths, hostnames, usernames, tokens,
  passwords, or message bodies. Do not notify customers automatically.
- When an unread human message names a problem tenant, it still belongs to this
  background-service lane unless it explicitly requests a brand-new integration
  or interface. Operational human wording does not authorize a ticket.
- Search Gmail for `Non-Submission`, `Non Submission`, `non-submission`,
  `nonsubmission`, `Non-Submission of POS Sales Data`, and alternate
  `Sales submission issue` subjects whose current message body contains true
  non-submit rows.
- Include true missing-submission dates even when the machine is not present in
  the private transfer catalog. Catalog membership controls FTP/SFTP work only.
- Dedupe by machine and date across both the durable delivery journal and
  verified historical Zoom sends. A new source that repeats an already-sent
  machine/date is reminder work, not a new resubmission request.
- Never include zero-sales or sales-verification content in the Julio message.
  Mark pure zero-sales notices read automatically with per-message Gmail
  readback because they require the store owner's response, not Nova action.
  Mixed notices must process true non-submit rows before acknowledgement.
- Keep every source email's linked new machine/date rows in the same normal Zoom
  batch. Reply once to each applicable prior Zoom request with the short
  reminder text for repeated machine/dates. Mark a source read only after every
  linked date has either a verified new request or a verified reminder reply.
  Deferred sources remain unread until a later bounded cycle verifies them.

## Private Server List

- A verified operator instruction or authenticated trusted credential-change
  email may update, fix, or retire an existing private interface entry through
  the deterministic service.
  Reactivate a tombstone only from explicit reactivation instruction. Never add
  an unknown entry automatically; catalog an explicit brand-new-interface
  request for the ticket-only path without writing configuration.
- An active interface may be automatically retired only after 90 observed days
  with neither a verified successful submission nor a verified customer
  configuration, resubmission, or reactivation contact. Either event resets the
  clock. Missing evidence fails closed. Retirement uses the typed operation to
  replace connection fields with a credential-free tombstone.
- Use only the service's typed, guarded configuration operation. The service owns
  its private backups, journals, and atomic write/readback behavior; agents must
  not open or edit those artifacts directly.

- The tool requires an exact trusted sender-domain match plus SPF, DKIM, and
  DMARC passes, creates a private backup, writes atomically, and reports only
  the key and changed field names. Gmail acknowledgement follows verified
  service readback and never depends on Salesforce or Needs Review.
- Do not guess missing values or log secret fields.

## Julio Zoom Message

- `ZOOM_SINGAPORE_JULIO_CONTACT` must contain Julio's exact Zoom contact email,
  not a name, user ID, group, or channel. Resolve that email to exactly one
  active Zoom user before sending.
- Julio delivery is Zoom-only. Never send or fall back to Gmail. When Zoom is
  unavailable or unverified, record the blocker and leave the source
  non-submission messages unread for a safe later retry.
- Use the existing `Support Dashboard Calls` Server-to-Server OAuth credential.
  `ZOOM_TEAM_CHAT_SENDER_USER_ID` must exactly match the S2S token owner and one
  active Nova Zoom user. Account-level calls must never use `me`.
- Send at most one source-safe new-request batch per run. The rendered body must
  be no more than 600 characters, and rows linked to one source email must never
  be split across new-request batches. In the same run, one short reply may be
  sent to each verified prior request whose machine/date is repeated.
- Before the Zoom API call, atomically write a durable outbox entry binding the
  exact source message IDs, machine/date rows, rendered body, and body hash.
  Reconcile any pending or verified outbox entry before creating another batch.
- Require exact Zoom message ID, body, sender email, and configured-recipient
  email readback, plus the exact parent message ID for reminders, before
  acknowledging any source email. Persist machine/date/source delivery coverage
  before Gmail label mutation so a partial Gmail failure retries only Gmail and
  never resends the tenant/date rows.
- Reminder reply text is exactly:

```text
Hey Julio, just a reminder on this Singapore resubmission. Thanks.
```
- Leave overflow rows deferred and unread. The five-minute background cycles
  bypass the daily-hour gate, retain exact inbox-ledger ownership, and continue
  one bounded batch at a time until the discovered backlog is drained.
- Format:

```text
Hey Julio, can you please resubmit these Singapore integrations? 8000640: 5/10-15, 7/4, 7/10. Thanks.
```

Keep these messages warm, relaxed, and straightforward. Include only the
request plus the tenant/date list Julio needs. Do not add ticket numbers,
workflow narration, or unnecessary background.

Use M/D for the current year, include a two-digit year only when the date is in
another year, and collapse contiguous dates within one month as `M/D-D`.
