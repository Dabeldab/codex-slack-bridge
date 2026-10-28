# Zoom Support Chat Monitor

Use this skill only for Alex/tickets-agent read-only monitoring of Zoom support
conversations. It does not authorize Zoom administration, AI Studio edits,
message sending, queue/routing changes, engagement takeover, whisper/barge, or
employee surveillance.

## Supported monitoring surfaces

- Completed Zoom Virtual Agent chat engagements and their transcripts through
  the ZVA Report APIs.
- Current Zoom Contact Center messaging engagement metadata through the open
  engagements API.
- Zoom Team Chat sessions/messages only for the exact member IDs and chat-report
  session IDs explicitly allowlisted in runtime configuration. An empty
  allowlist means Team Chat monitoring is disabled.

Zoom does not expose an account-level stream of every live ZVA message. Treat
ZVA report data as completed/post-processed conversation evidence. Contact
Center open-engagement data is live status metadata; completed transcripts may
arrive later.

## Fast path

From the bridge root, run:

```powershell
py -3 -m codex_slack_bridge.zoom_chat_monitor --output data/command_center/zoom_chat_monitor.json
```

Read the resulting local cache. Report only the sessions relevant to the
support request: current state, assigned agent/queue, customer-last-message or
handoff risk, topic, and the smallest next action. Do not paste full transcripts
into Slack, Salesforce, or the Drawing Board unless Darius explicitly asks.

## Required access

Use the existing backend-only Zoom OAuth configuration. Never print tokens or
secret values. The app needs these read scopes for complete coverage:

- ZVA: `zva:read:list_engagements:admin` and
  `zva:read:list_transcripts:admin` (classic fallback:
  `zva_report:read:admin`).
- Contact Center: `contact_center:read:list_engagements:admin` for open
  engagements; completed detail may also require
  `contact_center:read:engagement:admin`.
- Optional allowlisted Team Chat: `team_chat:read:list_user_sessions:admin` and
  `team_chat:read:list_user_messages:admin`, plus the required Zoom Chat
  Messages role permission.

If a surface returns 401/403, preserve the other successful surfaces and report
the exact missing scope/license category without attempting browser or admin
configuration. Delegate scope/app configuration to `coding_agent`.

## Privacy and safety

- Keep raw data local and short-lived. Prefer redacted snippets and metadata.
- Do not monitor organization-wide private Team Chat. Require an explicit
  allowlist for every member, contact, or channel.
- Never mark messages read, react, reply, send files, transfer, reassign,
  takeover, whisper, barge, or change a flow.
- Correlate a conversation to Salesforce only when the identifiers support a
  high-confidence match. Do not copy an entire transcript into ticket notes.
- Routine monitoring stays quiet in the dashboard/cache; alert Darius only
  when an escalation policy or direct request calls for it.
