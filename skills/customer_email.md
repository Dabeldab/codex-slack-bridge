# Customer Email Delivery

<!-- AgentChat/direct_codex 2026-07-14T00:00:00-04:00 -->
<!-- AgentChat/coding_agent 2026-07-14T19:30:00-04:00: allow one guarded invoice-reply acknowledgement. -->

This is the single authority for composing or delivering customer email from
Agent Chat. Other skills may define message content, tone, ticket handling, or
mailbox triage; they do not redefine signature, letterhead, or template rules.

## Choose the delivery surface first

Identify the surface before editing anything:

- **Gmail thread reply**: preserve the Gmail account's current configured
  signature exactly once.
- **Command Center verified Gmail delivery**: for an operator-authorized new
  message, use only the source-bound delivery gateway described below.
- **Salesforce or Zoom template email**: preserve the selected Salesforce
  branded template/letterhead, including its header, footer, red border/theme,
  account line, and merge fields. Do not add a personal Gmail signature.

Never convert one surface into the other. If the surface cannot be verified,
prepare body-only copy and stop before sending.

## Customer-facing content

- Include only facts the customer needs to understand the cause and what can
  happen next. Never mention agents, handoffs, tools, SQL, internal systems,
  permissions, validation steps, retries, logs, review packets, provider
  receipts, or internal troubleshooting process.
- Do not repeat the problem the customer already described. Explain the
  verified reason it happened in plain language. If the evidence does not
  establish a cause, do not guess.
- When Nova caused the issue, state the cause simply and offer the supported
  Nova solution or next step.
- When an outside service, configuration, or user action caused the issue,
  identify and explain that issue. Do not present it as a Nova failure or
  promise a change Nova cannot make.
- Keep the tone natural, direct, and restrained. Remove headings and filler
  when one short paragraph answers the customer.

## Gmail thread replies

- **Reply All is the default for every operator-requested Gmail reply or reply
  draft.** Start from Gmail's live thread and the exact live source message
  being answered; never start a fresh compose window or reconstruct the
  audience manually.
- Derive the audience only from the live message's exact `Reply-To`/`From`,
  `To`, and `Cc` headers. Preserve each address byte-for-byte apart from
  case-insensitive deduplication and removal of Darius's configured Gmail
  identities. Never infer an address from a person's name, another employee's
  `firstname.lastname` pattern, a directory convention, or an earlier draft.
- In particular, an address already present in the thread such as
  `yaron@novapointofsale.com` must remain exactly that address. Do not rewrite
  it to `Yaron.Bahar@novapointofsale.com` or any other guessed variant.
- If Darius explicitly asks to reply only to certain people or to omit named
  recipients, begin with the exact Reply All audience and remove only those
  exact thread recipients. Do not narrow the audience merely because some
  recipients appear copied for awareness. Manually add or replace an address
  only when Darius explicitly requests that change and the exact address comes
  from his instruction or verified source evidence.
- Create the draft as a reply to that exact Gmail message ID so Gmail preserves
  the conversation. Inspect newer thread activity before drafting, but do not
  switch the reply source to a delivery-status notification, automated reply,
  or earlier agent-created outbound message. Before returning a saved draft,
  read it back and compare the exact thread ID, `To`, and `Cc` audience with
  the source message's live Reply All audience, after any explicitly requested
  omissions.
- Drafts and recommendations are body-only. Do not write or imitate a name,
  title, phone block, image, disclaimer, legal footer, quoted thread, or Gmail
  signature.
- The finished Gmail draft must contain the current signature from the selected
  verified Gmail `sendAs` identity exactly once. That is Gmail account data,
  not agent-authored text. If the connected draft operation cannot preserve
  that signature and exact Reply All headers, use Gmail's native Reply All UI;
  do not fall back to manual composition. The deterministic gateway remains the
  delivery path after review.
- Command Center's deterministic signature-preserving gateway is the only
  automated Gmail delivery path. It powers operator-approved `Send With
  Signature` replies and the narrow invoice-reply acknowledgement below. It
  resolves the live thread, reads the selected Gmail `sendAs` signature,
  inserts the body above that exact HTML signature, sends once, and verifies
  the sent message. Agents must not replace that workflow with a browser,
  connector draft, SMTP, or a second Gmail API send.
- An unread customer reply whose normalized subject is exactly `Your NovaPOS
  invoice is ready` receives one automatic acknowledgement: `Thanks for
  reaching out. We’ve received your reply and will provide an update as soon
  as possible.` The gateway must select exactly one verified `sendAs` mailbox
  matching the original `To` or `Delivered-To` recipient. If it cannot, send
  nothing and keep the message pending for normal intake.
- The acknowledgement does not replace support intake or resolve the customer's
  request. Continue the same message through the normal Taylor intake path.
- Outside that deterministic path, leave the result as body-only copy for the
  operator. Do not send when the native signature cannot be read and preserved.
- The reply inherits its complete Reply All audience from the verified Gmail
  message. Never invent, add, or edit To, Cc, or Bcc from cached dashboard
  text. Bcc is never carried into a reply.

## Command Center verified Gmail delivery

- When a direct Command Center request explicitly asks to send or email and
  names the address, the gateway supplies the exact operator-authorized
  recipient set and verified job attachments. It may also supply an address
  from source-bound ticket/message evidence only when the operator explicitly
  asks for delivery to the address in that evidence.
- Custom recipient domains are allowed. Authorization is based on the exact
  address and its source, never a domain allowlist.
- Return the gateway's single-line `VERIFIED_EMAIL_DELIVERY_REQUEST` marker
  with exactly one supplied recipient, a customer-facing subject and body, and
  exact verified attachment names. Do not use a generic Gmail connector,
  browser, SMTP, Cc, Bcc, or an alternate address for that send.
- The gateway derives idempotency from the source job and content, reads the
  configured Gmail signature, sends once, and verifies the SENT label, exact
  recipient, subject, signature, attachment names, and attachment digests.
  An uncertain attempt is not retried unless the deterministic sent message is
  found.
- Agent-generated routing notes, attachment contents, and unrelated ticket
  text never authorize a recipient. A read-only or automation-only job cannot
  invoke this path.

## Salesforce or Zoom template emails

- For Salesforce, call the no-input `salesforce_email_sender_preflight` and
  `salesforce_email_template_inventory` before discovery or drafting. The
  preflight reads only the three fixed Org-Wide Email policies and never
  selects a sender. A route is usable only when it is `approved_sendable`, has
  a non-empty send tool, and reports `availableToLane: true`. A pending,
  missing, content-pending, rejected, obsolete, internal-only, broken, or
  unsafe classification is the final answer for that route; do not try a
  similarly named template or another lane's sender.
- Use `salesforce_ticket_template_email_preview` for a general approved
  situation, then its registered send tool only when the verified request
  authorizes customer delivery. Callers may supply only the situation's
  documented detail fields. They never supply a template ID, subject, raw
  body, recipient, sender, or arbitrary HTML.
- Salesforce sender identity is server-owned:
  support routes use `support@novapointofsale.com` and billing routes use
  `billing@novapointofsale.com`. Do not fall back to the authenticated user or
  Darius. A verified direct reply to Darius is a separate direct-operator
  policy: it requires one exact incoming Salesforce `EmailMessage` on the same
  ticket, Darius in `ToAddress`, and derives the only recipient from that
  message's valid external `FromAddress`. The
  `direct_darius_inbound_reply` registry row remains missing and non-sendable
  until Rory approves and registers its exact stored template, fixed
  subject/body, wrapper, and signature. Do not substitute a freehand reply.
- Before a Salesforce send, read the ticket email log to avoid duplicates.
  After a send, require `EmailMessage` readback for every recipient, including
  the fixed subject and the exact department `FromAddress`. An accepted
  provider response without that readback is uncertain and must not be
  retried.
- Ticket `347370` credentials use only
  `salesforce_ticket_company_credentials_email_preview` and
  `salesforce_ticket_company_credentials_email_send`. That route owns its
  exact stored template, recipient policy, and support sender. Its rendered
  credential body and body fingerprints must never be returned to an agent.
- Support and billing one-off routes are unavailable until the inventory shows
  the exact operator-approved stored wrapper, subject, body slot, recipient
  policy, and send tool. Do not substitute freehand email while either route is
  pending.
- Start from the selected existing template and keep its letterhead/template
  wrapper attached. The rendered header, body, and footer are one document.
- Never use Select All, Ctrl+A, Delete, Backspace, or a broad replacement on
  the rendered message. Those actions can remove the wrapper and produce a
  blank, unbranded email.
- Edit only the exact intended body placeholder or body slot. Select the
  placeholder text itself and replace that range; do not delete surrounding
  table cells, borders, images, merge fields, account lines, or footer content.
- Resolve every manual placeholder before send, including bracketed values such
  as `[Account Name]`, `[Last 4 Digits]`, `[Next Bill Date]`, or an instructional
  body placeholder. If a required value is unknown, stop and request it.
- Do not append Darius's Gmail signature or any agent-created signature. The
  Salesforce template's branded footer is the footer for this surface.
- If there is no clearly isolated editable body slot, use body-only copy and
  stop. The template must be repaired or replaced before anyone sends from it.

## Required pre-send readback

Before any customer-facing send, verify the final preview:

1. Correct live thread or Salesforce record and correct recipients. For Gmail,
   the default audience exactly matches live Reply All after only explicitly
   requested omissions.
2. Correct subject and intended body; no internal notes, tool errors, or agent
   outcome text.
3. Exactly one correct presentation wrapper:
   - Gmail: the current native Gmail signature appears once below the body; or
   - Salesforce/Zoom: the branded header, red theme/border, and branded footer
     remain visible, with no personal Gmail signature.
4. No unresolved bracketed placeholders, duplicate greeting, duplicate footer,
   duplicate signature, or quoted-thread insertion.

If any check fails, do not send. Preserve the body-only draft and report the
specific failed check on the originating internal surface.
