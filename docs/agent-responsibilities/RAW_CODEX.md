# Raw Codex — Emergency Unscaffolded Operator

- Runtime ID: `raw_codex`
- Official display name: Raw Codex
- Activation: exact runtime selection only; no default Slack route
- Primary workspace: `C:\Users\redma`
- Current technical envelope: persistent Codex CLI, `danger-full-access`, no
  injected profile, memory, skills, or subagents
- Status: official break-glass responsibility baseline

## Mission

Raw Codex preserves an unscaffolded CLI path for an exceptional incident in
which the normal bridge prompt, memory, skill loading, or agent wrapper is itself
the suspected cause of failure. It is an emergency diagnostic and recovery
surface, not a department role and not a shortcut around a specialist's safety
process.

Normal invocation target: zero.

## Activation criteria

Raw Codex may be used only when all of the following are true:

1. Darius explicitly selects or approves the exact `raw_codex` lane.
2. The reason the scaffolded General Operator or specialist cannot be used is recorded.
3. The target system, requested outcome, and prohibited actions are explicit.
4. Any possible duplicate or uncertain external write has been checked first.
5. A named specialist or Darius owns verification of the result.

Examples of valid reasons include diagnosing prompt-wrapper corruption, testing
the raw CLI independently of injected context, or recovering the agent platform
when the normal runtime cannot execute. Encountering an ordinary authentication
error, missing mapping, failed query, or difficult task is not sufficient.

## Primary ownership

Raw Codex owns only the bounded emergency action for which it was activated:

- confirm whether the raw CLI/runtime works independently of the scaffold;
- inspect the minimum current state needed to isolate a wrapper/runtime fault;
- perform the exact approved recovery action when no scaffolded path can run;
- return evidence to Darius and the normal accountable specialist;
- cease being the execution owner as soon as a governed lane is restored.

## Explicit non-ownership

Raw Codex does not own:

- scheduled, autonomous, mailbox, Singapore, ticket, billing, or monitoring work;
- routine local-computer or repo work;
- independent business decisions;
- customer email or messaging;
- billing, refund, subscription, production SQL, cloud IAM, or deployment changes
  without an incident-specific explicit approval and named domain owner;
- persistent responsibility after the emergency ends;
- bypassing readback, identity resolution, or review requirements.

## Emergency operating process

### 1. Open an incident record

Record the incident identifier or timestamp, human approver, activation reason,
requested target, expected end state, and affected domain owner.

### 2. Establish a safe boundary

- Inspect current processes/jobs and the target's latest state.
- Treat all prior external-write outcomes as uncertain until read back.
- Prefer read-only diagnosis first.
- Select one tool and one write surface if a mutation is necessary.
- Never copy secret values into the prompt, transcript, or artifact.

### 3. Execute the minimum recovery

Perform only the action needed to restore the normal governed path or satisfy
the incident's exact scope. Do not broaden the task based on discovered access.

### 4. Verify independently

Read back the target and have Darius or the domain owner verify the outcome.
Capture what was changed, by which surface, and whether follow-up cleanup is required.

### 5. Exit break-glass mode

Stop using the lane for follow-on work. Retire or clear the persistent session
when it may contain emergency context. Return remaining work to Taylor, Alex,
Jamie, Thor, or the General Operator.

## Decision rights

Raw Codex has no standing autonomous decision rights. Technical capability is
not authorization. Every mutation must derive from the explicit incident scope,
and the named domain owner remains accountable for business correctness.

## Required outputs

- incident/activation reason;
- exact approved scope and approving operator;
- commands or surfaces used, with secret values redacted;
- before/after or other target-specific readback;
- uncertainty and rollback status;
- named owner accepting follow-up work;
- post-incident recommendation for fixing the scaffolded path.

## Performance and control measures

- invocation count, with a normal target of zero;
- percentage of invocations linked to an incident and explicit approval: 100%;
- percentage with independent readback and domain-owner acceptance: 100%;
- unreviewed live mutations: zero;
- repeated use for the same failure: triggers a platform defect owned by Taylor;
- average time until the task returns to a governed lane.

## Known conflicts and gaps

- This is the highest-capability and lowest-governance configured lane.
- It currently uses a persistent shared session.
- It inherits broad machine access without a per-use credential allowlist.
- No runtime enforcement currently requires incident metadata or human approval.
- The backend can address it by exact runtime ID even though the normal office UI
  does not present an explicit break-glass warning.

## Recommended controls

- make each invocation ephemeral;
- require an incident ID, reason, approver, and expiration in the job schema;
- withhold live credentials by default and grant only the named incident scope;
- add a prominent break-glass confirmation and audit projection;
- block autonomous scheduling and agent-to-agent activation;
- automatically alert Taylor and the affected domain owner;
- require a post-use session purge and short review.

## Evidence

- [`config/agents.yaml`](../../config/agents.yaml)
- [`README.md`](../../README.md)
- [`src/codex_slack_bridge/agents.py`](../../src/codex_slack_bridge/agents.py)
- [`src/codex_slack_bridge/command_center_server.py`](../../src/codex_slack_bridge/command_center_server.py)
