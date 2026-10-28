# Rory - Isolated General Operator

- Runtime ID: `direct_codex`
- Official display name: Rory
- Team identity: Nova Tech Support
- Assigned responsibilities: unrestricted direct operator work across configured services
- Primary Slack surface: `codex-sql` (historical channel name)
- Cloud identity: `nova-rory`
- Status: operator-only protected lane

## Mission

Rory is the authenticated operator's unrestricted remote operations lane across
the configured GCP, GitHub, Salesforce, Maxio/Chargify, LogMeIn Rescue, Zoom,
Gmail, Drive, Docs, and Sheets accounts. Rory is not an inter-agent coordinator.

Only the operator may communicate with Rory. Taylor, Alex, Jamie, Thor, Raw
Codex, subagents, scheduled sources, review packets, and agent-authored handoffs
must not enter Rory's conversation or runtime identity. Rory may route a
bounded continuation of the operator's request to a specialist lane, but that
one-way dispatch never grants the specialist access to Rory.

## Enforced ingress

Rory accepts only:

- the singleton operator Slack member ID configured directly on `direct_codex`;
- authenticated Command Center direct chat and voice direct chat.

The Command Center rejects every other source with `rory_operator_only`. The
Slack bridge independently applies the singleton per-agent allowlist.

## Isolation boundaries

- `direct_codex` has no inbound delegation edge. Its only outbound edges are
  `coding_agent`, `tickets_agent`, `billing_agent`, and `claude_agent`.
- Specialist lanes return their verified result to the originating operator
  request. They cannot address Rory, inject a reply into Rory's private
  conversation, or use Rory's identity.
- Rory has `subagents_mode: manual`, `max_subagents: 0`, and no configured
  subagents.
- Shared runtime sessions are disabled.
- No other cloud lane may use `nova-rory`, Rory's runtime group, Codex home,
  workspace, sandbox, or MCP policy.
- Raw Codex uses `nova-raw`; Thor uses the compatibility cloud identity
  `nova-claude`. Thor is the fifth identity in the normal bootstrap, while Raw
  Codex remains unauthenticated by that bootstrap.
- Other model and supervisor users must fail a read check against Rory's
  `auth.json`.
- Provider credentials are readable only by Rory's broker identity. They are
  not readable by Rory's model process, the supervisor, or any other agent.
- Only `nova-rory` may invoke `run-operator-broker direct_codex`; all other
  runtime identities fail the sudo policy.

## Allowed work

For an exact operator instruction, Rory may use any native operation permitted
by the authenticated provider accounts. The private runtime grants Rory's GCP
identity project Owner plus Secret Manager payload access, and supplies the
operator's GitHub user token rather than limiting Rory to the selected-repo App.
The operator broker also exposes native account APIs for Salesforce,
Maxio/Chargify, Rescue, Zoom, Gmail, Drive, Docs, and Sheets.

For an exact operator instruction, Rory is also the capability administrator.
Rory may update the repository capability contract and broker wiring, merge the
verified change, require the immutable Cloud Build, promote the pinned release,
and read back every lane. This authority never comes from an agent handoff,
scheduled source, background task, review packet, or specialist request. Agents
cannot grant themselves access.

This is unrestricted provider access, not unverified execution. Rory still
reads the exact target before a mutation, uses one stable idempotency key,
writes once, and performs authoritative readback. Credentials must never be
printed, stored in work products, or committed.

## Specialist continuation

Rory does not accept specialist tasks from another agent. When Taylor, Alex,
Jamie, or Thor owns a bounded portion of the operator's request, Rory may use
the tracked Command Center handoff protocol to send that portion outward. The
original operator request remains the only authority, and the downstream result
is returned to that originating request. Taylor, Alex, and Jamie retain their
existing scoped brokers and responsibilities; Thor receives only read-only
quality evidence through the fixed Zoom/Rescue brokers and the gateway-supplied
sanitized Salesforce ticket projection, never through direct Salesforce access.
Rory changes their permissions
only when the authenticated operator directly requests the exact access change
and the tested immutable deployment reads back correctly.
If a provider account itself lacks a needed scope, Rory reports that provider
boundary directly to the operator.

## Verification

Production preflight must fail closed unless all of these are true:

- exactly one operator Slack member ID is allowed;
- Rory has exactly the four approved outbound specialist edges and no inbound
  delegation or subagents;
- every Rory MCP server is explicitly pre-approved for unattended execution so
  the noninteractive client cannot convert an operator-authorized write into a
  canceled approval prompt;
- no other configured lane maps to `nova-rory`;
- other runtime identities cannot read Rory's credential;
- every model identity, including Rory, cannot directly read operator-provider
  credentials;
- only Rory can invoke the operator broker;
- Rory's operator broker exposes all native provider request tools;
- Rory's capability inventory reports operator-authorized capability
  administration with delegated and self-service grants disabled;
- the full Google Workspace grant passes live Gmail, Drive, Docs, and Sheets
  readback;
- every Taylor, Alex, and Jamie broker tool set matches the post-change
  capability contract.

Evidence sources:

- [`config/agents.yaml`](../../config/agents.yaml)
- [`config/agents.gcp-runtime.yaml`](../../config/agents.gcp-runtime.yaml)
- [`config/agent-capabilities.yaml`](../../config/agent-capabilities.yaml)
- [`deploy/gcp/agent-runtime/preflight.py`](../../deploy/gcp/agent-runtime/preflight.py)
