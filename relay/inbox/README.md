# Relay inbox

Each `*.json` file in this directory is one immutable operator request. A push to
`main` triggers `.github/workflows/github-agent-relay.yml`.

Do not edit or reuse an existing task file. Create a new task id and file for a
new instruction.

Example:

```json
{
  "version": 1,
  "task_id": "chatgpt-20260917-001",
  "agent": "rory",
  "title": "Check agent runtime health",
  "instruction": "Inspect the current private agent runtime and report any unhealthy lanes. Do not change anything.",
  "reasoning_provider": "codex_cli",
  "timeout_seconds": 900,
  "created_at": "2026-09-17T17:00:00Z"
}
```

Supported agent names are `rory`, `taylor`, `alex`, `jamie`, `thor`, or their
canonical runtime lane ids. The relay uses the existing Command Center
`agent-direct-chat` path so normal operator authority, lane ownership, broker
policy, idempotency, and readback rules still apply.

Default provider: `codex_cli`. Explicit optional alternative:
`"reasoning_provider": "chatgpt_relay"`. A failed selected provider is
reported without rerunning through the other one. Do not expose sensitive
Salesforce or SQL records through GitHub inbox/outbox files.
