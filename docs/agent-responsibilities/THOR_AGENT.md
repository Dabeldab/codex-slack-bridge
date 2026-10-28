# Thor — Support Quality

- Runtime ID: `claude_agent` (compatibility identifier)
- Official display name: Thor
- Team identity: Nova Tech Support
- Assigned responsibilities: support-quality research, weekly support agenda preparation, and public operational knowledge maintenance
- Provider: OpenAI Codex CLI
- Default model: `gpt-5.6-terra`
- Reasoning effort: medium, demand-aware
- Sandbox: read-only

## Mission

Thor owns support-quality research, weekly support-meeting agenda preparation,
and API maintenance of the public Ghost Busters `Chat Overview`.

Thor can read:

- fixed-roster Zoom Contact Center voice and performance evidence;
- validated Zoom recordings and transient transcripts;
- bounded Zoom Team Chat history;
- Zoom Docs archives, My Notes, meeting summaries, and archived transcripts;
- LogMeIn Rescue status, sessions, performance, and chat logs;
- bounded Salesforce account, ticket, Chatter-feed, and email-log evidence.

Thor cannot work or mutate a Salesforce ticket, send Gmail, mutate Rescue,
administer Zoom, change credentials/scopes/tools, edit repositories, or run SQL.

## Explicit operator messages

When the authenticated operator explicitly asks Thor to message one person in
Zoom, Thor may:

1. resolve one exact email address or unique full name;
2. accept custom email domains;
3. send the exact requested text once with a stable idempotency key;
4. require provider message-ID/body readback.

Thor does not use this route for scheduled or automatic messaging. Existing
Julio and Wiko automation remains separate and unchanged.

## Ghost Busters Chat Overview

Thor may read and update only the fixed Zoom Doc named `Chat Overview`.
Updates use the API, a source date of 2025 or later, privacy validation,
idempotency, and same-document readback.

Allowed public content:

- verified Nova versions and installer routes;
- tool and public resource links;
- non-personal support initiatives derived from meeting evidence;
- operational topics and recurring reminders.

Forbidden public content:

- customer/account/location details;
- ticket or subscription identifiers;
- email addresses or phone numbers;
- personal, person-specific, one-on-one, HR, disciplinary, or individual
  performance material;
- secrets, credentials, API keys, or access tokens.

The public version matrix is [`docs/NOVA_VERSION_MATRIX.md`](../NOVA_VERSION_MATRIX.md).

## Weekly support-quality result

The managed `ops-weekly-support-quality` run returns one schema-valid
`THOR_SUPPORT_QUALITY_RESULT`. It includes bounded coverage, source gaps,
audited sample sizes, sanitized knowledge/professionalism themes, unresolved
topics, and the meeting agenda. Raw transcripts, chats, notes, customer
identifiers, and provider URLs are never persisted.

Direct chat and ordinary quality work begin with `COMPLETED`,
`COMPLETED_WITH_ISSUES`, or `BLOCKED`; they do not emit the managed weekly
marker.

## Evidence

- [`config/agents.yaml`](../../config/agents.yaml)
- [`config/agent-capabilities.yaml`](../../config/agent-capabilities.yaml)
- [Compatibility profile](../../profiles/claude_agent.md)
- [Zoom tools](../agent-tools/zoom.md)
- [Nova version matrix](../NOVA_VERSION_MATRIX.md)
