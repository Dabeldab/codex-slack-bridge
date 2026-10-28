# Thor Support Quality Operations

Thor (`claude_agent`, compatibility ID) has two read-only broker surfaces.
Command Center also supplies one sanitized, gateway-owned Salesforce ticket
quality projection for the managed weekly window. That projection is data, not
a Thor broker or Salesforce capability.

## Zoom quality tools

The `zoom_quality_ops` server exposes only:

- `zoom_capabilities`
- `zoom_health`
- `zoom_quality_voice_engagements`
- `zoom_quality_agent_performance`
- `zoom_quality_engagement_recordings`
- `zoom_quality_transcript`

It reuses the existing Support Dashboard Calls S2S OAuth app. Voice
engagements and performance rows are restricted to the fixed roster in
`config/zoom-weekly-support-agents.json`. A recording request must first prove
that the engagement is a fixed-roster voice engagement in the supplied bounded
window. A transcript request must select a recording returned by Zoom. The
downloader accepts no caller URL, requires HTTPS on a Zoom-owned host, sends the
OAuth bearer token only from the broker, and never returns a transcript URL.

Transcript absence, processing delay, app scope failure, or disabled
transcription is returned as a coverage gap.

## Rescue tools

The `rescue_console` server exposes exactly:

- `rescue_console_status`
- `rescue_list_sessions`
- `rescue_read_chat`
- `rescue_read_performance`

There is no message, assignment, transfer, PIN, session-control, Technician
Console, or administration tool.

## Sanitized ticket-quality projection

Before dispatching the managed weekly job, Command Center invokes a dedicated
runtime-only reader as `nova-salesforce-broker`. Only `nova-runtime` may execute
that launcher. It accepts the exact fixed six-person roster and a UTC window of
at most eight days, reads only Nova Classic/Wave tickets with fixed fields, and
returns:

- per-representative ticket, open, and closed counts;
- lifecycle, documentation, and category-field presence counts;
- bounded attribution-field counts;
- server-owned category-field presence labels; and
- opaque `ticket:<hash>` evidence references.

It never returns ticket IDs/numbers, account/contact/customer data, notes,
descriptions, chatter, email, phone, URLs, raw bodies, provider errors, or a
write/send/query surface. Command Center validates the entire receipt before
placing it in Thor's prompt. If unavailable, Thor receives only a sanitized
Salesforce source gap and must use `partial` when other evidence was audited.
Thor still has no Salesforce MCP and never works a ticket.

## Cadence

The enabled watcher runs Wednesdays at 09:00 `America/New_York`, four hours
before the verified 13:00–14:00 Tech Time support meeting. An operator may also
run the same bounded workflow manually. Neither path modifies the calendar.

## Durable-output boundary

Raw Zoom transcripts and Rescue chat logs are transient model context. The
gateway ticket projection is already sanitized and is the only permitted ticket
evidence. For the
managed `ops-weekly-support-quality` source, Thor returns the sanitized
`THOR_SUPPORT_QUALITY_RESULT` described in `profiles/claude_agent.md`; Command
Center validates and publishes that object. Direct chat, admitted general
quality tasks, and bounded quality handoffs instead use a normal leading
`COMPLETED`, `COMPLETED_WITH_ISSUES`, or `BLOCKED` answer with sanitized
evidence. There is no ticket or send step on either path.
