# Support Quality

Use this workflow only in Thor's read-only `claude_agent` compatibility lane.

## Inputs

- Exact UTC reporting window
- Fixed Support Dashboard Calls roster
- Typed Zoom voice-engagement, performance, recording, and transcript readers
- Exact four-tool read-only Rescue surface
- Gateway-supplied sanitized Salesforce ticket-quality projection for the exact
  window and fixed roster
- Sanitized prior weekly quality summaries

## Rules

1. Inventory evidence before sampling it.
2. Use only fixed-roster voice interactions and bounded Rescue sessions.
3. Treat missing or processing transcripts and an unavailable/degraded gateway
   ticket projection as coverage gaps.
4. Show audited sample size for each representative and each score.
5. Keep raw transcript and chat content transient.
6. Do not include customer identifiers, phone numbers, recording URLs, or raw
   excerpts in durable output.
7. Separate representative coaching from product, documentation, and process
   gaps.
8. Carry unresolved topics across weeks only when evidence supports them.
9. Use only the supplied ticket counts, field-presence facts, and opaque
   `ticket:` references. Never query Salesforce or infer customer/ticket
   identity.
10. Use `THOR_SUPPORT_QUALITY_RESULT` only for the managed
   `ops-weekly-support-quality` source. Direct chat, general quality tasks, and
   admitted quality handoffs use a normal leading `COMPLETED`,
   `COMPLETED_WITH_ISSUES`, or `BLOCKED` answer. Do not create tickets or send
   messages on either path.

## Result

For the managed weekly source, follow the strict schema and forbidden-field
list in `profiles/claude_agent.md`. `partial` is the correct weekly status when
useful evidence exists but coverage is incomplete. `blocked` is reserved for a
run that cannot produce evidence-supported quality findings. For other sources,
use the normal leading outcome and a sanitized plain-language answer.
