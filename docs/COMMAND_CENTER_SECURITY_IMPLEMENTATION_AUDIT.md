<!-- AgentChat/Fable 2026-07-15T02:57:27-04:00: independent read-only implementation audit of the Command Center security and GCP migration plan. -->

# Command Center Security Implementation Audit

> Historical audit note: the 2026-07-22 runtime policy supersedes this report's
> source-bound read-only Jamie finding. Proactive billing jobs now retain scoped
> lane-owned Salesforce and non-delete Maxio write authority with idempotency,
> durable intent, and readback. Permission administration, raw credentials,
> cross-lane escalation, Rory/local-agent bypass, and Salesforce/Maxio deletion
> remain unavailable.

Audit date: 2026-07-15

Auditor: Fable / AgentChat

Mode: read-only evidence review; no provider records, secrets, credentials, jobs, services, or configuration were changed

## Executive verdict

The [security and GCP migration plan](COMMAND_CENTER_SECURITY_AND_GCP_MIGRATION_PLAN.md) is a strong target architecture, but the current implementation is **not audit-ready and does not yet enforce the plan's principal isolation guarantees**.

The current system has valuable application controls: signed provenance, source-bound read-only execution for selected automations, idempotency and recovery logic, exact financial-proposal hashing, a permanent reconciliation retirement gate, deletion denials, attachment validation, lane-oriented role documents, and a substantial automated test inventory. The focused security/regression suite executed during this audit passed **313 tests**.

However, the main security boundary is still the shared Windows user and shared host. All six lanes use `danger-full-access`; most are persistent; Claude is launched with a permission-bypass flag; Raw Codex is persistent break glass without enforced activation; trusted jobs inherit most ambient credentials; MCP access is denylist-based; authenticated browser and local helper state are shared; the typed broker is disabled example configuration rather than the exclusive production path; local audit stores are mutable; and the local Command Center write API has loopback/origin checks but no independent operator authentication or request nonce.

The plan therefore matches the important gaps, but its future-state claims must not be presented as deployed controls. An external auditor should receive this document as a gap assessment and migration baseline, not as evidence that least privilege is already operating.

## Classification scale

- **VERIFIED** — implemented and supported by direct code, configuration, metadata, or readback evidence.
- **PARTIALLY_VERIFIED** — meaningful implementation exists, but the stated control is incomplete or bypassable.
- **CONTRADICTED** — current implementation directly conflicts with the proposed control.
- **NOT_IMPLEMENTED** — only planned, documented, scaffolded, or tested in isolation; not part of the active enforcement path.

## Scope and evidence

This audit inspected:

- the actual agent configuration, role documents, orchestration code, safety policy, secret broker, tool registry, pipeline registry, session runtime, shared chat/artifact/memory stores, review workflow, reconciliation retirement, financial approval workflow, tests, and local Command Center HTTP surface;
- sanitized metadata from 1,645 Command Center job files, 839 runtime session events, 1,607 shared chat events, and 2,263 artifact-index events;
- local process, listener, environment-name, credential-path, and ACL metadata without reading secret values;
- enabled MCP server names and permissions without printing credentials;
- read-only GCP metadata for projects `gen-lang-client-0051653266` and `supportkpis`;
- a focused 313-test security and recovery regression run.

The available Command Center job evidence covers approximately **2026-07-09 through 2026-07-15**, not the 90-day period contemplated by the plan. Provider business records were not queried because no customer-data dump was needed to establish the architectural findings. Salesforce object permissions, Maxio key capabilities, Gmail mailbox contents, Zoom account scopes, and Rescue customer sessions therefore remain provider-side verification items.

## Current operating picture

### Agent runtime and lane boundaries

The role model is well documented, but it is not a technical security boundary:

- Direct Codex, Raw Codex, Taylor, Claude, Alex, and Jamie are all configured with `danger-full-access` in [agents.yaml](../config/agents.yaml#L447).
- Direct Codex and Raw Codex use `C:/Users/redma` as their workspace, while Taylor and Claude can see the broader work tree. Most lanes are persistent; Raw Codex is persistent and shared. Claude is ephemeral but uses `--dangerously-skip-permissions` ([agents.yaml](../config/agents.yaml#L719)).
- MCP restrictions are implemented as a per-agent **disabled-server list**, not a positive allowlist ([agents.py](../src/codex_slack_bridge/agents.py#L786)). Tool fast-path exclusions filter generated guidance, not executable host access ([agents.py](../src/codex_slack_bridge/agents.py#L2123)).
- The role documents accurately acknowledge these gaps: [Alex](agent-responsibilities/ALEX_TICKETS_AGENT.md#L10), [Jamie](agent-responsibilities/JAMIE_BILLING_AGENT.md#L13), [Taylor](agent-responsibilities/TAYLOR_CODING_AGENT.md#L9), [Claude](agent-responsibilities/CLAUDE_AGENT.md#L10), [Direct Codex](agent-responsibilities/DIRECT_CODEX.md#L9), and [Raw Codex](agent-responsibilities/RAW_CODEX.md#L7).
- Read-only helper subagents are technically launched in a read-only sandbox, which is useful defense in depth. Their full-access parents can still access the host directly.

### Workload evidence and task parity

The six-day job sample contained 728 Taylor jobs, 559 Alex jobs, 357 Jamie jobs, and one Claude job. It contained no Command Center job-file sample for Direct or Raw Codex. Major sources included 273 now-retired billing-reconciliation jobs, 269 Singapore jobs, 224 ticket refreshes, 196 email-watch jobs, 175 support-email intake jobs, 128 KPI jobs, 125 direct agent chats, and 98 dispatches.

This supports lane specialization, but it does not prove 99% task parity under the target architecture:

| Lane | Observed work and required future capability | Parity assessment |
|---|---|---|
| Alex | Salesforce ticket research/writeback, Nova SQL read/preview, Rescue/Zoom support evidence, support messaging | **PARTIALLY_VERIFIED** — high-volume lane is clear; typed replacements for Salesforce, SQL, Rescue, Zoom, and customer messaging are not deployed. |
| Jamie | Billing-ticket investigation, Salesforce/Maxio/Nova BillingAutomation reads, exact refund/rate proposals, approved execution | **PARTIALLY_VERIFIED** — read-only proactive investigation and proposal hashing exist; isolated financial executor and provider-scoped identity do not. |
| Taylor | Repository/GitHub, GCP/Cloud Run, Zoom administration, email intake, KPI and Singapore operations | **PARTIALLY_VERIFIED** — broad current access supports tasks, but no evidence proves the proposed narrow brokers cover every deploy, log, IAM, Zoom, email, and recovery variation. |
| Claude | Independent review, code/document analysis, delegated read-only research | **PARTIALLY_VERIFIED** — intended workload is narrow and compatible with an ephemeral review worker, but only one Command Center job was available and the current process has permission bypass. |
| Direct Codex | Routing, diagnosis, cross-lane coordination, exceptional operator-directed work | **NOT_IMPLEMENTED** for the target model — no metadata-only discovery plane or capability-reducing routing token exists. Current access overlaps every lane. |
| Raw Codex | Incident-only break glass | **CONTRADICTED** — current persistent full-access lane has no enforced activation, MFA, dual approval, TTL, or automatic revocation. |

Historical routing also shows drift: Singapore work appears under both Alex and Taylor, and Jamie's retired reconciliation is still described in its responsibility document. Machine-readable ownership must become authoritative before migration replay can be trusted.

### Local data and credential exposure

- Trusted child jobs default to inherited environment access. The runtime removes Salesforce and Maxio/Chargify prefixes, but leaves other ambient secret families available ([safety.py](../src/codex_slack_bridge/safety.py#L159), [safety.py](../src/codex_slack_bridge/safety.py#L461)). Fifteen secret-like environment variable names were present during inspection, including Slack, Zoom, and Google credential indicators; values were not read or printed.
- Local metadata confirmed a Google ADC path, a Gmail OAuth token file, a Spotify token file, the trusted-message signing key, local vault/storage paths, and service-specific application directories. Most inspected paths inherit ACLs accessible to the shared user and sandbox group; only the dedicated `agent_vault` directory showed a protected owner/system/administrator ACL. Because the main workers run as the same user with full access, ACL inheritance does not isolate lanes.
- Gmail is wired to a local token with `gmail.modify` scope ([command_center_server.py](../src/codex_slack_bridge/command_center_server.py#L240)). The enabled Rescue MCP is configured with sending allowed. These permissions are operationally useful but accessible outside a task-scoped broker boundary.
- Shared chat stores up to 6,000 characters per event ([shared_chat.py](../src/codex_slack_bridge/shared_chat.py#L20)); memory applies logical agent/global filtering ([memory.py](../src/codex_slack_bridge/memory.py#L368)); artifact listing also applies logical lane filters ([shared_artifacts.py](../src/codex_slack_bridge/shared_artifacts.py#L83)). These are application filters over shared host files, not filesystem or identity isolation.
- Artifact registration accepts arbitrary resolved paths and the ID lookup has no caller ACL in the registry layer ([shared_artifacts.py](../src/codex_slack_bridge/shared_artifacts.py#L18), [shared_artifacts.py](../src/codex_slack_bridge/shared_artifacts.py#L126)). The Drawing Board download route adds a useful sandbox-root containment check ([command_center_server.py](../src/codex_slack_bridge/command_center_server.py#L6455)), but that does not protect the underlying index from full-access agents.

### Active GCP state

Read-only GCP inspection found:

| Project | Cloud Run | Secret Manager | Relevant network observation |
|---|---:|---:|---|
| `gen-lang-client-0051653266` | 2 services: `logmein-connector`, `rainfall` | 0 listed secrets | Both services report ingress `all`; neither has a VPC connector or controlled VPC egress setting. |
| `supportkpis` | 0 services/jobs | 0 listed secrets | No agent control plane, broker, or audit service is deployed. |

The current services use service accounts, but they are existing application services—not the proposed per-lane workers, typed brokers, workflow coordinator, or immutable audit sink. The GCP migration phases are therefore **NOT_IMPLEMENTED**. Existing public ingress and unrestricted outbound networking also do not satisfy the plan's target network policy.

## Control-by-control assessment

| ID | Plan control | Status | Evidence and conclusion |
|---|---|---|---|
| I-01 | Deny-by-default per-lane capabilities | **CONTRADICTED** | All lanes are full-access host processes. Profiles and role docs guide behavior, but shell, filesystem, browser, and local credentials remain available. |
| I-02 | Separate worker identity and storage per lane | **NOT_IMPLEMENTED** | Agents share one Windows identity, host, process environment, browser state, runtime files, and storage roots. |
| I-03 | No raw secrets, ADC, or vault access in agent workers | **CONTRADICTED** | Trusted jobs inherit most ambient secrets; shared full-access user can reach local credential paths and ADC. |
| I-04 | Positive MCP/tool/endpoint allowlists | **CONTRADICTED** | Runtime only disables named MCP servers; fast-path exclusions are prompt-generation filters. Direct, Raw, Alex, and Claude can receive the enabled Rescue MCP, while Claude has no business ownership of it. |
| I-05 | Typed broker is the exclusive production integration path | **NOT_IMPLEMENTED** | [secret-broker.example.yaml](../config/secret-broker.example.yaml#L5) disables the broker, all providers, and its only sample operation. Production orchestration does not instantiate it. Direct helpers and CLIs remain active. |
| I-06 | Broker operation schemas and response secret checks | **PARTIALLY_VERIFIED** | The broker scaffold validates typed operations, rejects secret-return operations, and checks responses. It is well tested but not the active exclusive route. |
| I-07 | Salesforce/Maxio deletion impossible through every path | **PARTIALLY_VERIFIED** | Safety classification and broker code permanently deny named deletion ([safety.py](../src/codex_slack_bridge/safety.py#L208), [secret_broker.py](../src/codex_slack_bridge/secret_broker.py#L529)). The classifier depends on recognized text, the broker is disabled, provider permissions were not removed in this audit, and generic host/browser/CLI paths remain. |
| I-08 | Retired Jamie reconciliation cannot return | **VERIFIED** | The collector no longer ingests location/order deltas, `_billing_reconciliation_enabled()` always returns false, queued legacy work is cancelled, current metadata showed zero active reconciliation jobs and no reconciliation review cards ([command_center_server.py](../src/codex_slack_bridge/command_center_server.py#L4019), [command_center_server.py](../src/codex_slack_bridge/command_center_server.py#L4092)). |
| I-09 | Source-bound read-only proactive investigation | **VERIFIED** for named sources | Selected proactive ticket and financial-follow-up sources are forced to actual read-only, fresh, non-shared execution ([command_center_server.py](../src/codex_slack_bridge/command_center_server.py#L5462)). This is not a general lane boundary. |
| I-10 | Signed, expiring, one-use, audience-bound task envelopes | **PARTIALLY_VERIFIED** | HMAC signing binds source, actor, channel, thread, authority, and text. The payload has no timestamp/expiry, nonce, one-time ledger, assigned-agent audience, environment, parent-authority hash, or capability set ([safety.py](../src/codex_slack_bridge/safety.py#L481)). Replay and authority reduction are not enforced. |
| I-11 | Delegation can only reduce authority | **PARTIALLY_VERIFIED** | Helper subagents are launched read-only, but cross-lane task routing has no cryptographically bound parent capability set or resource scope. The full-access parent can bypass delegation entirely. |
| I-12 | Exact financial approval | **PARTIALLY_VERIFIED** | Refund/rate proposals bind ticket, account, target, amount/current/proposed value, currency, reason, and effects into a SHA-256-derived hash; approval text must exactly match ([command_center_server.py](../src/codex_slack_bridge/command_center_server.py#L7755)). Missing controls: expiry, one-use consumption ledger, before-state hash, provider drift recheck, revocation, value thresholds, and dual approval. |
| I-13 | Idempotency, account serialization, and uncertain-write readback | **PARTIALLY_VERIFIED** | Command Center has payload idempotency, durable job state, runtime locks, review-version fencing, and recovery tests. There is no single cross-provider saga/resource-lock service covering UI, CLI, SQL, API, and broker routes. |
| I-14 | Durable, immutable, correlated audit | **CONTRADICTED** | Current records are mutable local JSONL/JSON/SQLite files. Broker audit uses a bounded in-memory deque and swallows audit-sink exceptions ([secret_broker.py](../src/codex_slack_bridge/secret_broker.py#L482), [secret_broker.py](../src/codex_slack_bridge/secret_broker.py#L598)). Writes do not universally fail closed on audit outage. |
| I-15 | Task-scoped data, memory, and artifacts | **PARTIALLY_VERIFIED** | Logical filters, redaction, attachment signature checks, expiry, and Drawing Board containment exist. Shared host storage and broad workspaces allow direct bypass; chat and artifact indexes retain operational content and absolute paths. |
| I-16 | Ephemeral, allowlisted browser executor | **CONTRADICTED** | Browser/CDP and Edge processes share authenticated local state. No isolated UI executor, fresh per-task profile, domain/action template, or guaranteed destruction flow exists. |
| I-17 | Controlled network egress and no alternate route | **NOT_IMPLEMENTED** | Local workers have general network access. Existing Cloud Run services use ingress `all` and lack VPC egress control. No egress proxy or destination-deny evidence was found. |
| I-18 | Foolproof authenticated operator UI | **PARTIALLY_VERIFIED** | Command Center binds loopback, rejects non-loopback clients, caps JSON, and checks an Origin when supplied ([command_center_server.py](../src/codex_slack_bridge/command_center_server.py#L9863)). Requests without Origin are accepted; `null` and any loopback origin are allowed; ordinary mutation POSTs have no operator token, CSRF nonce, or reauthentication. Any process under the local user can call them. |
| I-19 | Safe review lane with substantive operator decisions | **PARTIALLY_VERIFIED** | Review gating, proposal cards, and instruction suppression are implemented. Metadata still contains historical `recovery_review_required` outcomes, so durable projection repair needs continued negative testing and cleanup evidence. |
| I-20 | Resource, rate, volume, cost, and concurrency limits | **PARTIALLY_VERIFIED** | File/image limits, batch caps, per-agent concurrency, retry bounds, and some API limits exist. No central policy enforces task-wide records, bytes, cost, mutation count, customer scope, or provider-rate budgets. |
| I-21 | Provider-side least privilege | **NOT_IMPLEMENTED / NOT VERIFIED** | No current evidence proves Salesforce delete permissions removed, Maxio credentials made deletion-incapable, Gmail/Zoom/Rescue scopes minimized, or separate service identities per operation. Current local integration access is broader than the target. |
| I-22 | Per-lane GCP workers and service accounts | **NOT_IMPLEMENTED** | No Command Center worker, broker, coordinator, or audit workload is deployed in either inspected project. |
| I-23 | Secret Manager with pinned versions and short rollback | **NOT_IMPLEMENTED** | Zero secrets were listed in both inspected projects. Local files, environment variables, and OAuth/browser state remain in use. |
| I-24 | Immutable audit sink, alerts, RTO/RPO, and recovery drills | **NOT_IMPLEMENTED** | No separate audit project/sink/archive evidence, formal RTO/RPO evidence, or canary rollback drill record was found. Local recovery logic is useful but not equivalent. |
| I-25 | Software supply-chain controls | **NOT_IMPLEMENTED** | No complete evidence of signed images, provenance attestations, SBOM enforcement, admission policy, dependency scanning gates, or deployment identity separation was found. |
| I-26 | Break-glass governance | **CONTRADICTED** | Raw Codex is persistent, full-access, and lacks enforced incident ID, dual approval, MFA, scope, TTL, automatic revocation, and post-use credential rotation. Its own charter acknowledges this ([RAW_CODEX.md](agent-responsibilities/RAW_CODEX.md#L118)). |
| I-27 | Documentation is generated from current policy | **CONTRADICTED** | Jamie's role still owns and documents location reconciliation despite the hard runtime retirement ([JAMIE_BILLING_AGENT.md](agent-responsibilities/JAMIE_BILLING_AGENT.md#L40)). Human docs and runtime policy can drift independently. |
| I-28 | Negative and recovery tests | **PARTIALLY_VERIFIED** | The focused audit run passed 313 safety, broker, review, scheduler, runtime-lock, capability-router, reconciliation, ledger, and Command Center security tests. They validate application behavior, not OS identity, provider IAM, browser isolation, or network denial. |

## Highest-priority bypasses and risks

### P0 — close before handing operations to a less technical manager

1. **Shared full-access identity defeats lane isolation.** A prompt or UI rule cannot stop an agent from using shell, filesystem, browser, native client, or inherited credential state outside its lane.
2. **Credentials remain reachable by agents.** Move credentials into out-of-process brokers under identities that workers cannot impersonate. Do not grant workers Secret Manager access.
3. **Direct integration bypasses remain.** Make typed brokers the only route; remove generic provider credentials, provider CLIs, shared browser profiles, and general outbound access from workers.
4. **Deletion is not yet an upstream impossibility.** Remove Salesforce delete permissions from every integration identity and ensure Maxio credentials exposed to brokers cannot delete. Network policy must prevent use of a different credential or endpoint.
5. **Audit is mutable and fail-open.** Add synchronous write-ahead intent logging for every mutation, immutable correlated result/readback events, and denial when the audit sink is unavailable.
6. **Raw Codex is permanently dangerous.** Disable persistent Raw Codex now. Reintroduce only as a 30-minute, incident-bound, dual-approved, MFA-protected ephemeral worker with automatic revocation and credential rotation.
7. **Local Command Center mutation routes need operator authentication.** Add a local-session secret or OS-bound authentication, per-request nonce, CSRF defense, short expiry, and action-specific confirmation for high-risk endpoints.

### P1 — close before GCP production migration

1. Implement signed task envelopes with TTL, nonce, one-time use, audience, environment, exact resources/data classes, rate budgets, approval class, and parent-capability hash.
2. Deploy separate control, broker, audit, staging, and production projects or equivalently strong boundaries; give each lane and broker a distinct service account.
3. Put workers behind private ingress and route all outbound traffic through controlled proxies with destination, method, path, and operation allowlists.
4. Build the financial executor with proposal expiry, before-state hash, approval revocation, execution-time drift rejection, one-use consumption, and dual approval above a recorded threshold.
5. Replace shared browser sessions with a separate ephemeral UI executor. Capture redacted evidence and destroy profile, cookies, cache, downloads, and session state after every task.
6. Make artifact and memory authorization server-side and identity-bound. Encrypt task stores, use customer/account-scoping tokens, and deny direct bucket/database access to workers.
7. Generate responsibility docs and UI badges from the same versioned capability policy that the brokers and coordinator enforce.

## Required evidence gates

Do not advance migration phases by calendar alone. Require these gates:

1. **Inventory gate:** every credential copy, provider identity, local helper, browser profile, CLI, endpoint, field set, data class, and observed task maps to an owner and disposition.
2. **Observation gate:** at least 30 days of policy shadow logs show no unexplained task denial or cross-lane dependency.
3. **Broker gate:** representative historical tasks produce equivalent business outcomes through typed brokers, with direct routes disabled in staging.
4. **Isolation gate:** negative tests prove every worker cannot access environment secrets, vaults, ADC, other-lane storage, unauthorized MCPs, generic HTTP, shell-based provider access, shared browsers, or service-account impersonation.
5. **Financial gate:** proposal expiry, exact binding, changed proposal, drift, replay, revocation, threshold, timeout, duplicate, and audit-outage tests all pass.
6. **Destructive-action gate:** Salesforce and Maxio deletion fail through broker, API, CLI, generic HTTP, SQL/proxy aliases, browser, delegation, recovery, and old persisted tasks.
7. **Parity gate:** replay a representative sample for Alex, Jamie, Taylor, Claude, and Direct Codex and obtain accountable-owner signoff that the same business result is achieved. Raw Codex is tested as break glass, not routine parity.
8. **Operations gate:** canary reversal, previous secret-version rollback, queue pause/resume, RTO/RPO recovery, compromised-worker isolation, and audit-outage fail-closed drills are recorded.

## Plan amendments required before external audit

The existing plan already names most architectural gaps. Add or make explicit:

- a control owner, implementation artifact, evidence artifact, test, review frequency, and exception expiry for every control;
- the exact current-state status from this matrix beside each future-state requirement;
- evidence-gated migration phases instead of week-based acceptance;
- an authoritative task/account scoping token used by every broker and data store;
- provider-side permission removal as a prerequisite, not merely an application denial;
- local Command Center authentication and action-specific authorization during the pre-GCP period;
- proposal expiry, before-state hashing, revocation, execution-time drift checks, one-use consumption, and high-value dual approval;
- hard record, result-byte, mutation, cost, rate, and concurrency limits;
- supply-chain controls, RTO/RPO values, quarterly access review, and retention/privacy ownership;
- a requirement that policy-generated docs replace hand-maintained role ownership statements.

## Validation performed

- Focused tests: **313 passed in 4.20 seconds**.
- Reconciliation readback: zero active reconciliation jobs in inspected metadata; latest legacy work is cancelled; no current reconciliation review card.
- Local listener readback: Command Center listened only on `127.0.0.1:17866` during inspection.
- GCP readback: one active CLI identity was configured; two existing Cloud Run services were inspected read-only; no Secret Manager entries were listed in either project.
- Secret values and customer record contents were not displayed, copied, or stored in this report.

## Final assessment

The plan is **solid as a destination and remediation roadmap**. The actual system is **not yet locked down to that design**. Its strongest controls are currently application-layer guardrails inside a shared, highly privileged host boundary. The handoff should wait until P0 controls are enforced outside agent prompts, the broker and GCP isolation path is deployed, provider permissions are reduced upstream, and the evidence gates above pass.

External-audit posture today: **readiness gap assessment only**.

Expected posture after verified P0/P1 remediation and evidence-gated replay: **suitable for SOC 2 Security/Availability readiness review, with NIST CSF or CIS Controls mapping**.
