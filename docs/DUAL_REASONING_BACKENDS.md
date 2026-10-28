# Dual reasoning backends — Codex CLI and ChatGPT Work relay

The three active production lanes (Taylor, Alex, Jamie) retain `provider: codex_cli` in `config/agents.chatgpt-runtime.yaml`. Their Codex OAuth staging, Codex command, model selection, usage/cost accounting and retry flow stay in place. An optional ChatGPT Work reasoning relay is an **additional** provider, never a replacement or implicit fallback.

## Selection

Normal Command Center and Slack jobs continue with Codex CLI. For an explicit authenticated operator direct-chat request, include `reasoningProvider: "chatgpt_relay"` in the body of `POST /agent-chat/send` alongside `agentName` and `message`. This selection is persisted into the job and verified again by the isolated worker. `reasoningProvider: "codex_cli"` selects Codex explicitly. Other backend names, and backend overrides in background/dispatch jobs, are rejected.

Example read-only operator chat request (must go through the existing authenticated Command Center ingress):

```json
{"agentName":"tickets_agent","message":"Summarize the current ticket workload. Read-only; do not update records.","reasoningProvider":"chatgpt_relay"}
```

Relay execution requires `REASONING_RELAY_ENABLED=1` and a working brokered GitHub transport; its tool access still requires signed operator authority and lane-specific MCP restrictions. This switch is a **routing choice**, not permission to read or write data outside the lane. Relay failure is reported on that job without automatically retrying via Codex (which could repeat a side effect).

## Independence and outages

`REASONING_RELAY_ENABLED` means optional relay selection is allowed. It does not reroute Codex jobs. `REASONING_RELAY_REQUIRED=0` permits the Codex Cloud Run service to start when optional relay transport preflight fails; explicit relay jobs then fail closed. The relay consumer (ChatGPT Work event trigger), Nova Control connection, GCP invoker IAM and fresh end-to-end probe still require separate activation/verification.

The original command-center and relay worker use the same signed trusted request, immutable job identifier, capability-lane restrictions, and durable job/result interface. Nova SQL through the Salesforce scoped MCP is read-only for Alex/Jamie; Taylor alone owns preview-and-guarded SQL mutations with operator authorization.

Nothing in this addition merges the separate GCP invoker identity fix (PR #197), grants GCP IAM permissions, enables automatic ChatGPT Work tasks, or deploys production traffic.
