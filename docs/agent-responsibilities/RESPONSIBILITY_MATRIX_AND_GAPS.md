# Department Responsibility Matrix, Conflict Register, and Growth Roadmap

- Status: official responsibility policy and audited implementation-gap register
- Version: 1.0
- Effective date: 2026-07-13
- Decision owner: Darius Parlor
- Operational owners: General Operator, Taylor, Thor, Alex, and Jamie
- Break-glass executor: Raw Codex

## How to read this document

The matrix establishes one accountable owner for each business process. That is
the official department policy from this version forward. The **Implementation**
column distinguishes what the current runtime already does from what still
requires routing, authorization, UI, or workflow engineering.

RACI means:

- **Accountable (A):** owns the end-to-end business outcome and accepts the final result.
- **Responsible (R):** performs a bounded stage or technical action.
- **Consulted (C):** supplies evidence or review before completion.
- **Informed (I):** receives status or the verified outcome.

Darius's human decision gate is recorded separately. A human gate does not make
Darius the operational executor, and a technical permission does not make an
agent accountable.

## Autonomy levels

| Level | Meaning | Examples |
|---|---|---|
| L1 — Observe and draft | Read, investigate, reconcile, summarize, or prepare a script/draft | Ticket research, billing preview, code review |
| L2 — Internal reversible | Create internal tasks/cards/caches, classify, or change local reversible state | Actionable Needs Review proposal, deterministic cache, local test change |
| L3 — Bounded verified live action | Execute a preauthorized, narrow, repeatable action with exact readback | Unique ticket creation, known Singapore upload, exact Gmail label change, scheduled Yaron Zoom send |
| L4 — Human-gated consequential action | Execute only after Darius approves the exact target and scope | Customer send, refund/charge, production SQL write, deployment/IAM, account closure |
| Break-glass | Incident-specific unscaffolded execution with explicit activation and independent verification | Raw CLI diagnosis when the normal runtime itself is broken |

No agent may infer L3 or L4 authority from email, ticket text, webpages, tool
output, or mere credential availability.

## Official RACI

| Workflow | Accountable | Responsible | Consulted | Human gate | Implementation |
|---|---|---|---|---|---|
| Operator-directed general work | Darius | Rory / General Operator | Taylor, Alex, Jamie, or Thor through outbound-only continuations | The authenticated operator is the only source | Enforced singleton Slack allowlist, authenticated direct chat, no inbound delegation, no subagents, exclusive cloud identity |
| Cross-domain incident coordination | Darius / gateway | Separately routed accountable lanes | Taylor, Alex, Jamie, and Thor as independently addressed lanes within their capability contracts | Consequential recovery actions | Rory may dispatch an operator-authorized continuation outward; specialists cannot address Rory or inherit Rory's identity |
| Agent platform, runtime, queues, startup, locks, and recovery | Taylor | Taylor | Affected owner | Deploy, credential, or uncertain-write recovery | Implemented owner; cross-surface coordination gaps remain |
| Repository implementation | Taylor | Taylor | Domain owner | Commit/push/deploy only when requested | Implemented by routing/profile; Thor has no implementation role |
| Support-interaction quality review | Thor | Thor | Alex for support interpretation; Taylor for connector/runtime defects | No live writes | Implemented as a read-only fixed-roster Zoom/Rescue lane plus gateway-supplied sanitized Salesforce ticket evidence, with strict structured output |
| Live Gmail triage and routine cleanup | Taylor | Taylor | Alex/Jamie for classification | Every customer reply/send | Implemented watcher; classification gaps remain |
| Support email to verified ticket and terminal support outcome | Alex | Taylor qualifies/creates ticket; gateway sequences; Alex researches and classifies | Jamie for billing clue; Taylor for platform clue | Customer-facing work or consequential fix; Needs Review only for a concrete proposed action waiting for Darius | Current early Gmail acknowledgement violates target completion boundary |
| Billing email to verified ticket and terminal billing outcome | Jamie | Taylor classifies/creates ticket; Jamie researches and classifies | Alex for support context | Financial/customer action; Needs Review only for a concrete proposed action waiting for Darius | Not implemented as an end-to-end lane |
| Nova Classic/Wave support ticket | Alex | Alex | Taylor for engineering/Zoom; Jamie for billing | Customer send, production data write, ambiguous close | Implemented profile; shared tool routing is ambiguous |
| Billing, Maxio/Chargify, invoice, subscription, refund, and allocation | Jamie | Jamie | Alex for ticket context; Taylor for tooling | All money/subscription/tax/closure changes | Implemented profile; enforcement and routing gaps remain |
| Support SQL diagnosis/repair | Alex owns diagnosis; Taylor owns execution | Alex prepares exact evidence/mapping; Taylor previews, backs up, executes, and reads back | Accountable support owner | Every production write | Taylor-only typed executor implemented; direct/native writes prohibited |
| Billing SQL diagnosis/repair | Jamie owns diagnosis; Taylor owns execution | Jamie prepares exact evidence/mapping; Taylor previews, backs up, executes, and reads back | Accountable billing owner | Every production write | Taylor-only typed executor implemented; direct/native writes prohibited |
| Engineering schema/migration implementation | Taylor | Taylor | Alex for support mapping | Every production execution | Partly implemented |
| Development Service / Account Copy | Taylor | Alex prepares business/data map; Taylor implements | Accountable support owner | Every production execution | Current registry names multiple primaries; single A now established |
| Singapore background service | Taylor | Deterministic runner; gateway schedules, caches, acknowledges, and reports | Alex only for an explicit brand-new interface ticket; Julio for verified non-submission | Unknown/new configuration enters ticket intake; routine outcomes never enter review | Implemented five-minute background lane with direct sanitized reporting |
| Propelr/NMI intake and support follow-up | Alex | Taylor qualifies/creates ticket; Alex accepts/researches | Jamie if billing-related | External configuration/customer action | Ticket stage exists; Alex acceptance/research gate is missing |
| Live LogMeIn Rescue session | Alex | Alex | Taylor for connector/platform failure; Thor may review bounded historical evidence for quality | Unplanned customer-visible action | Alex owns live support; Thor's exact four-tool inventory is read-only |
| Rescue connector, `/remote-support`, and hosted platform | Taylor | Taylor | Alex supplies support requirements | Deploy/config change | Implemented engineering owner; platform map wording is ambiguous |
| Zoom admin, ZVA, Contact Center config, and hosted Zoom operations | Taylor | Taylor | Alex for support requirements | Publish/config/user/queue mutation | Implemented owner; broad access policies conflict |
| Read-only Zoom support-monitor exception handling | Alex | Alex | Taylor for auth/runtime/scope failure | Reply/takeover/transfer/config | Monitor exists; exception-to-owner workflow is incomplete |
| Weekly Yaron support report | Alex | Alex | Taylor for Zoom runtime; Jamie for cross-check | None for scheduled verified recipient | Implemented recurring owner |
| Thor support-quality audit | Thor | Thor | Alex for support follow-up; Taylor for connector/runtime defects | No live writes | Implemented as a scheduled fixed-roster Zoom/Rescue analysis with gateway-supplied sanitized Salesforce ticket evidence and strict `THOR_SUPPORT_QUALITY_RESULT` output |
| Julio/Wiko employee-request DM | Taylor, Alex, or Jamie in the active task lane | Same lane resolves only the configured Julio or Wiko alias and sends once through the typed broker; every other employee request uses a tagged Salesforce ticket | Taylor for broker/runtime failure | Request, authorization context, and stable idempotency key required | Implemented with shared daily greeting state, pending journal, and message-id/body readback |
| KPI and schedule refresh | Taylor | Taylor | Domain owner interprets | Any resulting live mutation | Implemented watcher |
| Support KB correction | Alex | Alex defines content; Taylor implements/syncs | Domain owner verifies | Customer-visible publication if consequential | Split exists but is not encoded as one workflow |
| Needs Review decision and continuation | Original accountable agent | Gateway returns one concrete solution/proposed action to that agent | Supporting agents as needed | Darius selects Continue, Close, or Abandon | Remove after execution/readback; closed or resolved tickets retain none |
| Raw break-glass operation | Darius | Raw Codex | Taylor and affected domain owner | Explicit incident-only activation | Lane exists; required audit/credential controls are not enforced |

## Official system boundaries

| Shared system or tool | Business owner by intent | Other permitted role | Transfer rule |
|---|---|---|---|
| Salesforce | Alex for support; Jamie for billing; Taylor for admin/Flow/integration | General Operator intake; Thor has no direct Salesforce access and may consume only the gateway-supplied sanitized support-quality projection | Route by record type and requested outcome, never the word `Salesforce` alone |
| Nova SQL | Alex/Jamie own domain diagnosis; Taylor is sole mutation executor | Thor has no SQL access | Every UPDATE, INSERT, temporary-table, or schema-migration request transfers to Taylor with exact mapping/count/readback requirements; DELETE/DROP and arbitrary ALTER are prohibited, the fixed `dbo.Locations` migration is the sole ALTER exception, and permanent targets are backed up first |
| Maxio/Chargify | Jamie | Taylor only for client/integration/runtime implementation | A billing decision always returns to Jamie |
| Gmail | Taylor for mailbox operation | Alex/Jamie receive signed domain handoffs | Source label acknowledgement follows the workflow's business completion gate |
| Zoom admin and platform | Taylor | Alex read-only support monitor; Taylor, Alex, and Jamie may send only configured Julio/Wiko employee-request DMs while all other staff requests use tagged Salesforce tickets; Alex owns the established Yaron send; Thor has fixed-roster quality reads only | Any admin/config scope transfers to Taylor; Thor never resolves recipients or sends |
| LogMeIn Rescue | Alex for live sessions | Taylor for connector/runtime; Thor for bounded historical quality reads | Session action and connector implementation are separate obligations; Thor cannot control or mutate Rescue |
| Singapore uploader/state | Taylor | Deterministic runner performs transfer/private-state writes; Alex handles only explicit brand-new interface tickets | Operational outcomes never create tickets/review; retired interfaces stay silent unless reactivated |
| Repositories and local services | Taylor | General Operator for general machine work; Thor has no implementation role | Business acceptance stays with Alex/Jamie when code serves their workflow |
| Customer communication | Accountable domain owner prepares; Darius authorizes | Gateway may execute only an explicit preauthorized recurring recipient/action | No agent repeats an uncertain send |
| Slack/Command Center/Desktop transport | Taylor owns platform | Gateway executes routing | Transport acceptance is not business completion |

## Transfer conditions

### Alex to Jamie

Transfer when the requested outcome is primarily a refund, charge, payment,
credit, invoice, subscription, allocation, cancellation, tax setup, or billing
reconciliation. Alex supplies the verified support ticket, customer/account,
problem history, requested outcome, and current communication state. Jamie must
accept the financial identity and scope before Alex stops tracking the support obligation.

### Alex to Taylor

Transfer a bounded technical stage when the outcome requires code, deployment,
Zoom admin/config, GCP, hosted health, integration implementation, Rescue
connector work, or any SQL mutation. For SQL, Alex supplies the exact database,
target tables, mapping/parameters, expected rows, and verification evidence;
Taylor owns backup, execution, and readback. Alex remains accountable for the
support result unless the row above assigns Taylor as A.

### Jamie to Taylor

Transfer when the billing decision is established but Rainfall code, API client,
automation, deployment, environment, future-task automation, or any SQL mutation
must change. SQL handoffs include the exact database, targets, mapping/parameters,
expected rows, and verification evidence; Taylor owns backup/execution/readback.
Jamie supplies exact billing invariants and acceptance criteria; Taylor returns
implementation evidence. Jamie verifies the financial business result.

### Any owner to Thor

Delegate only a bounded support-interaction quality question that can be
answered from Thor's fixed-roster Zoom and read-only Rescue evidence. The
handoff contains no ticket action, Salesforce or Gmail work, recipient
resolution, send, provider administration, or mutation. Thor returns sanitized
findings and the strict quality result; the accountable owner retains every
follow-up action.

### Any owner to the General Operator

Prohibited. Only Darius may communicate with Rory. The gateway or Darius routes
separate work directly to the accountable specialist without an agent-authored
Rory handoff.

### General Operator to a specialist owner

Allowed only as a tracked continuation of Darius's original request. Rory may
target Taylor, Alex, Jamie, or Thor. The handoff preserves the original
operator authority and returns the specialist's verified result to that
originating request; it does not create an inbound route to Rory.

### Any lane to Raw Codex

Agents may not autonomously activate Raw Codex. Darius must approve an incident-
specific invocation and name the specialist who will independently verify it.

## Current overlap and conflict map

| Area | Current overlap/conflict | Official resolution |
|---|---|---|
| Salesforce | Alex, Jamie, and Taylor are all tool primaries; alias `salesforce` routes to Jamie | Classify support vs billing vs admin/integration before routing |
| Nova SQL | All lanes retain reads, while only Taylor receives mutation tools | Alex/Jamie own domain diagnosis; every mutation routes to Taylor's backed-up guarded executor, with schema changes limited to the fixed `dbo.Locations` migration |
| Maxio | Jamie and Taylor are both listed | Jamie owns billing decisions/writes; Taylor owns tooling/runtime |
| Singapore | Older docs assigned Alex and created remediation-ticket/review handoffs | Taylor owns the background service; only an explicit brand-new interface request may enter Alex's ticket lane |
| Rescue | Alex owns live session; Taylor owns connector/platform; Thor consumes bounded historical quality evidence | Keep Thor to the exact four read tools and route all action to Alex or Taylor |
| Weekly Yaron | Registry names several primary agents | Alex owns report and single send; Taylor/Jamie only support |
| Account Copy | Registry names Alex or Taylor | Taylor A for execution; Alex owns the preparation package |
| Thor identity | Runtime/config paths retain `claude_agent` only for compatibility | Official visible identity is Thor, Nova Tech Support Support Quality; `thor`, `support_quality`, and `quality` aliases resolve to the compatibility ID |
| Agent names | Tool index says Kento/billing and Jamie/tickets | Retire Kento and Jamie/tickets; canonical roster is Taylor/Alex/Jamie/Thor |
| Specialist access | All managed lanes now use `workspace-write`; Rory-only privilege routing and reduce-only delegation are enforced, while shared-host OS isolation remains incomplete | Keep the narrow role boundary; move workers to separate OS/service identities for stronger host isolation |
| Input channels | Slack, Command Center, Desktop, and watchers use different queues/locks | Add one execution ledger and resource locks across surfaces |

## Gap register

Priorities:

- **P0:** safety, data integrity, duplicate-write, credential, or ungoverned break-glass risk.
- **P1:** material correctness, ownership, routing, recovery, or unattended-work risk.
- **P2:** visibility, maintainability, documentation, measurement, or efficiency gap.

### P0 — immediate controls

| ID | Gap | Consequence | Required resolution | State |
|---|---|---|---|---|
| G-001 | Slack, Command Center, Desktop, and watchers do not share a resource-level execution coordinator | Same-resource writes may overlap while unrelated reads serialize | Add one durable execution ledger and locks such as `salesforce-ticket:<id>`, `gmail-thread:<id>`, `maxio-subscription:<id>`, `rescue-session:<id>`, `singapore-uploader`, and `repo:<root>` | Recommended, not implemented |
| G-002 | Support Gmail can be marked read after Alex queue acceptance rather than a durably classified terminal disposition or actionable proposal | Source obligation can disappear while downstream work fails or stalls | Make support-source acknowledgement the final step of its durable saga; restore/retain unread on child failure | Recommended, not implemented |
| G-003 | Legacy lanes still have broader host access than their business scopes | Prompt-only department boundaries create cross-system blast radius | Continue per-agent credential/capability isolation and time-bound break-glass grants | Thor now uses a read-only sandbox, exact Zoom/Rescue MCP allowlist, and a brokered sanitized Salesforce projection with no direct Salesforce credential; broader lane isolation remains open |
| G-004 | Raw Codex is persistent, unscaffolded, full-access, and lacks enforced activation/audit criteria | Highest-capability lane has the least governance | Make ephemeral and incident-only; require approver, reason, expiry, credential scope, readback, and post-use purge | Charter added; runtime control not implemented |
| G-005 | Loopback Command Center state-changing HTTP requests lack a per-launch authorization token/nonce | Another same-user local process can mint trusted work | Add authenticated local transport, CSRF protection, and rejection of unauthenticated/no-Origin mutations | Recommended, not implemented |

### P1 — correctness and unattended workflow

| ID | Gap | Consequence | Required resolution | State |
|---|---|---|---|---|
| G-101 | No durable parent saga for support email and other cross-agent workflows | Parent can finish while child, review, or acknowledgement is pending | Persist stage state, accountable owner, child acceptance, readback, and terminal obligation | Recommended |
| G-102 | Generic Salesforce alias/channel routes to Jamie without business classification | Support or admin work can enter the wrong lane | Route by record type and intent: Alex support, Jamie billing, Taylor admin/integration | Policy established; code pending |
| G-103 | Taylor owns engineering plus most watchers/intake processes | One busy or failed lane stalls unrelated department work | Move support/billing business accountability to Alex/Jamie while retaining Taylor's engineering and Singapore background-service ownership; add independent watcher capacity and resource locks | RACI established; engineering pending |
| G-104 | No autonomous billing email to ticket to Jamie-outcome pipeline | Billing mail can remain unread or be misclassified as support | Add a billing classifier, unique billing ticket, Jamie acceptance/research, terminal classification, optional actionable proposal, and final Gmail acknowledgement | Not implemented |
| G-105 | Propelr/NMI acknowledges after ticket creation without Alex terminal-outcome acceptance | Ticket exists but no support owner may complete it | Reuse support saga: Taylor ticket, Alex terminal disposition or optional actionable proposal, then Gmail readback | Not implemented |
| G-106 | Quiet watchers have no failure-count or age-based escalation threshold | Repeated authentication, mapping, or queue failure remains invisible | Alert on two failed cycles, SLA age, uncertain write, rejected handoff, and terminal failure | Not implemented |
| G-107 | Singapore intent classification can let failure/auth wording override an otherwise explicit brand-new-interface request | A ticket-eligible customer task can be downgraded to routine work | Make explicit brand-new-interface intent win except for true reactivation; keep operational-only wording in the background lane | Open |
| G-108 | Access policies generically authorize Zoom/cloud/deployment while lane profiles prohibit them | Concatenated instructions conflict and behavior may vary | Make capability policy explicit and machine-enforced; remove contradictory broad text | Not implemented |
| G-109 | Desktop execution queue is in memory and lock namespace differs from Python runtimes | Restart can lose queued execution and cross-surface collisions remain possible | Persist queue obligations and use the shared execution coordinator | Not implemented |
| G-110 | Shared chat writes and other cross-process projections require consistent locking | Concurrent processes may interleave or lose projection data | Apply one cross-process file/ledger discipline and recovery tests | Partly addressed in current dirty worktree; verify before closure |

### P2 — clarity, measurement, and maintainability

| ID | Gap | Consequence | Required resolution | State |
|---|---|---|---|---|
| G-201 | Canonical identity drift previously treated specialty labels as separate roles | Humans and routers delegate to the wrong persona | Keep Tech Support as the shared identity and specialties as assigned responsibilities in UI, prompts, profiles, and channel docs | Implemented in shared prompt, profiles, config, and Command Center labels |
| G-202 | README calls Alex/Jamie read-only although live policy permits scoped writes | Operators misunderstand authority and risk | Replace with workflow-specific autonomy levels and link this handbook | Handbook added; README correction pending |
| G-203 | Specialized agents use manual subagent mode, so trigger lists do not auto-run | Configured specialization appears autonomous but is dormant | Choose manual intentionally or enable auto per workflow with read-only budgets/evals | Not implemented |
| G-204 | Alex defines seven subagents with a cap of six; `reply-drafter` is unreachable in `all` mode | A documented helper is silently omitted | Raise cap, reorder, or add explicit triggers and tests | Not implemented |
| G-205 | `config/agents.example.yaml` references agents it does not define and fails loader validation | Fresh setup cannot start from the example | Make the example self-contained and add config-load CI | Not implemented |
| G-206 | Command Center frontend omits several operational sources | Active autonomous work is not visible as normal operational cards | Render every workflow with A, executor, age, SLA, blocker, and next step | Not implemented |
| G-207 | No due date, severity, escalation owner, or accepted-at field on review/handoff records | Aged work has no accountable escalation | Add workflow metadata fields and dashboard states | Not implemented |
| G-208 | Evaluation coverage remains uneven across operational lanes | Result quality, forbidden actions, handoffs, and recovery regressions may be unmeasured | Add per-agent outcome, safety, SLA, and blocker-recovery cases | Thor inventory, result-contract, and forbidden-action tests added; broader coverage remains open |
| G-209 | Singapore instruction surfaces previously conflicted on ownership, tickets, review, retired interfaces, and customer replies | Agents could choose the wrong workflow or expose unnecessary operational detail | Keep skill, profiles, registry, runtime, and docs on the single background-service policy | Resolved in current policy update |
| G-210 | Python and Desktop load skills differently | Same runtime ID can receive materially different instructions by channel | Normalize skill selection and record the effective instruction set per job | Not implemented |
| G-211 | Autonomous tickets can be attributed to Darius rather than the automation identity | Audit history obscures the actual executor | Record automation identity, human initiator, workflow/source IDs, and department owner separately | Not implemented |

## SLA and escalation baseline

These are starting service targets. Measure actual distributions for 30 days,
then tune without weakening the failure visibility rules.

| Workflow | Initial target | Escalation |
|---|---|---|
| Interactive request | Start within 2 minutes P95; visible progress within 1 minute | Owner notified at 5 minutes queued |
| Support or billing email detection | Within 5 minutes | P1 if the intake service is unavailable for 30 minutes |
| Qualified email to verified ticket | Within 10 minutes | P2 after two cycles; P1 at 30 minutes |
| Verified ticket to terminal disposition or actionable proposal | Within 20 minutes | P2 at 30 minutes; report blockers outside Needs Review |
| Singapore scan | Every 5 minutes | P1 if all scans fail for 30 minutes |
| Singapore active source to remote result or compact direct outcome | Within 15 minutes | Direct-chat failure after two cycles; P2 service incident at 30 minutes |
| Propelr/NMI source to Alex acceptance | Within 15 business minutes | P2 if no accepted owner |
| Actionable review proposal waiting on Darius | Warn at 4 business hours | Escalate at 1 business day; remove immediately after verified execution or ticket resolution |
| Weekly Yaron report | Delivered by 8:15 AM Friday | P2 at 8:30 AM |
| Background queue age | Warn at 10 minutes | Critical at 30 minutes |
| Uncertain external write | Immediate stop/readback | P1; no retry until resolved |
| Duplicate or wrong-recipient write | Immediate stop | P0 and Darius notification |

Escalation classes:

- **P0:** suspected secret exposure, wrong recipient/account, duplicate live write,
  or data corruption. Stop the affected automation.
- **P1:** uncertain money/SQL/customer send, department-wide intake failure,
  repeated runtime crash, or loss of source obligations.
- **P2:** one item blocked for two cycles, missing mapping/credential, rejected
  handoff, or aged review packet.
- **P3:** routine no-match, informational drift, or low-value cleanup; daily digest only.

Normal success and no-match scans may remain quiet. Silence ends at an SLA or
risk threshold.

## Agent KPI scorecards

| Agent | Core effectiveness measures | Safety/quality measures |
|---|---|---|
| General Operator | first-route accuracy; owner-acceptance latency; cross-domain closure time | duplicate coordination; domain-boundary violations; verification completeness |
| Taylor | platform availability; recovery time; email-to-ticket latency; Singapore background outcomes; implementation throughput | deployment rollback rate; Gmail false-positive rate; Singapore repeat-failure rate; stale/duplicate worker incidents; readback rate |
| Thor | roster/window coverage; evidence-backed quality themes; coaching-topic acceptance; coverage-gap closure | raw-customer-data persistence, false-positive findings, ticket/send/mutation attempts, target zero |
| Alex | ticket-to-terminal-outcome latency; actionable-proposal handling; explicit new-interface ticket handling; Rescue response | identity accuracy; reopen/rework rate; aged unread support sources; readback rate |
| Jamie | reconciliation and approval-to-completion time | preview variance; duplicate/wrong billing actions; reopen rate; readback rate |
| Raw Codex | invocation count, target zero in normal operations | incident-linked/approved/read-back percentage, target 100%; unreviewed writes, target zero |

System-wide targets:

- external-write readback: 100%;
- blind retry after uncertain write: zero;
- duplicate live writes: zero;
- wrong account/recipient/amount actions: zero;
- unowned durable work: zero;
- SLA breach detection: 100%;
- customer or financial action without the required gate: zero.

## Responsibility expansion gate

An agent receives a new autonomous responsibility only after all of these exist:

1. one accountable owner and bounded executor;
2. exact input/source allowlist and identity requirements;
3. explicit allowed and forbidden actions;
4. least-privilege credentials/capabilities;
5. idempotency key and one write surface;
6. independent readback and uncertain-result behavior;
7. durable source obligation, handoff acceptance, and terminal state;
8. SLA, owner escalation, and visible failure state;
9. outcome, safety, and recovery evaluations;
10. 30-day measured performance at the required quality threshold;
11. rollback/disable control and named change owner;
12. updates to this handbook, routing, UI, profiles, skills, and tests.

## Improvement roadmap

### 0–30 days: restore trustworthy ownership

- Make this handbook the linked roster/source of responsibility truth.
- Correct canonical names and generic Salesforce routing.
- Move Gmail acknowledgement behind verified downstream completion.
- Add a durable parent saga for support and durable recovery state for Singapore background work.
- Implement resource-level coordination across all input surfaces.
- Restrict Raw Codex and begin per-agent credential separation.
- Add visible escalation for repeated watcher failures and aged handoffs.
- Repair and test `config/agents.example.yaml`.

### 31–60 days: measure and balance the department

- Add billing-email and complete Propelr/NMI pipelines.
- Move business accountability away from Taylor while keeping technical stages with her.
- Normalize Desktop/Python skill and queue behavior.
- Add due dates, severity, accepted-at, readback proof, and decision owner fields.
- Expand evaluations to every agent and every L3/L4 workflow.
- Establish KPI dashboards and 30-day baselines.

### 61–90 days: increase autonomy deliberately

- Promote only workflows meeting identity, readback, SLA, and quality gates.
- Expand Thor quality coverage only through the responsibility expansion gate;
  do not widen the lane into tickets, sends, provider administration, or code.
- Add automatic support/billing classification with confidence thresholds.
- Keep canonical retired-Singapore detection fail-closed, silent, and covered by regression tests.
- Add bounded platform self-recovery with rollback and external-write fencing.
- Conduct a quarterly responsibility review and retire redundant routes/tools.

## Evidence sources

- [`config/agents.yaml`](../../config/agents.yaml)
- [`config/pipeline-registry.json`](../../config/pipeline-registry.json)
- [`config/tool-fast-paths.json`](../../config/tool-fast-paths.json)
- [`config/agents.example.yaml`](../../config/agents.example.yaml)
- [`profiles/`](../../profiles)
- [`skills/`](../../skills)
- [`docs/AGENT_PLATFORM_MAP.md`](../AGENT_PLATFORM_MAP.md)
- [`docs/agent-tools/INDEX.md`](../agent-tools/INDEX.md)
- [`src/codex_slack_bridge/agents.py`](../../src/codex_slack_bridge/agents.py)
- [`src/codex_slack_bridge/command_center_server.py`](../../src/codex_slack_bridge/command_center_server.py)
- [`src/codex_slack_bridge/agent_runtime.py`](../../src/codex_slack_bridge/agent_runtime.py)
- [`src/codex_slack_bridge/shared_chat.py`](../../src/codex_slack_bridge/shared_chat.py)
- [`agent-chat-desktop/MainWindow.xaml.cs`](../../agent-chat-desktop/MainWindow.xaml.cs)
- [`evals/agent_quality.json`](../../evals/agent_quality.json)
