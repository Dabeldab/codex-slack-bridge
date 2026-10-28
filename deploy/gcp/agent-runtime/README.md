# Private Google Cloud agent runtime

This deployment moves the long-running Slack/Codex worker to a private Compute
Engine VM. It does not replace the separately protected Cloud Run Command
Center shadow. Cloud Run remains the Google-authenticated web surface; the VM
owns the persistent Socket Mode connection, Codex CLI processes, typed provider
brokers, and local SQLite state.

Command Center retains at most 500 terminal job projection files for 30 days
and expires shared direct-chat/handoff attachments after seven days. Cleanup
runs at startup and hourly after terminal work, never removes queued/running
jobs, and appends an audit receipt. Durable SQLite/provider ledgers remain the
source of idempotency and recovery evidence.

The provisioner intentionally leaves both `nova-command-center.service` and
`nova-slack-bridge.service` disabled. Starting either before the controlled
cutover could create duplicate Slack consumers or duplicate background work.

## Authentication and secret boundaries

- Provider values live in Google Secret Manager as separate, versioned
  secrets. Deployment resolves `latest` once and writes numeric version pins
  into the VM manifest. The runtime never follows an unreviewed future version.
- Root materializes those pins into `/run/nova-secrets` at boot with mode
  `0400`. Files are owned by the smallest broker identity that needs them.
  Secret values are never copied into a repository, image, instance metadata,
  deployment output, or Codex prompt.
- The VM service account has accessor rights only on the named secrets. A host
  firewall rejects metadata-server access from every non-root UID so Codex and
  broker processes cannot mint the VM identity.
- Rory's brokers are blocked from metadata. A root-only timer mints a one-hour
  token for the dedicated `nova-rory-cloud-ops` identity and refreshes it every
  twenty minutes. That identity has project Owner plus Secret Manager payload
  access. The token is readable only by the broker, never the model process.
- The safe `gcp_github_ops` broker retains selected-repository GitHub App reads
  and guarded branch/PR publication. The separate `rory_operator_ops` broker
  uses the operator's GitHub user token with its full provider scopes and the
  server-owned Command Center bearer for all-agent health, readiness,
  job/result inspection, dispatch, handoff, and guarded restart control. Both
  credentials remain broker-only.
- Salesforce credentials belong to `nova-salesforce-broker`. Rory, Taylor,
  Alex, and Jamie can invoke only an exact lane-specific typed broker command.
  Every interactive lane can perform digest-verified ticket attachment
  status/upload and approved-template email inventory, preview, and send
  operations within its ticket record-type scope. Freehand subjects/bodies are
  absent. Every interactive lane also has the same read-only Account
  360 operation, which resolves an Account from an Account, Contact, Location,
  or ticket identity and returns its Owner, Nova Account Manager, primary
  Contact, Contacts, Locations, and related tickets; ambiguity returns
  candidates instead of falling through to a demo Account. Nova SQL
  is inside that broker: bounded reads for the business lanes, and Taylor-only
  guarded UPDATE/INSERT/temp-table operations with mandatory table backup,
  preview hash, affected-row ceiling, and readback. DELETE/DROP and generic
  SQL/REST/admin surfaces are absent. One exact `dbo.Locations.RegionId`
  request uses a Taylor-owned no-model executor that validates the destination
  region and reviewed trigger contract, creates a full Locations backup,
  commits at most one row, and performs exact post-commit readback.
- Taylor also receives `gcp_github_ops` for read-only GCP discovery and guarded
  selected-repository branch/PR publication. This lets her implement and test
  missing typed SQL broker operations without granting protected-branch writes,
  merge, workflow edits, deployment, GCP mutation, or self-service capability
  activation. Rory may create, test, publish, and deploy any operator-requested
  agent tool or capability through the full GitHub/GCP surfaces and immutable
  release path; only an exact authenticated operator request grants that
  authority.
- A direct authenticated Alex close instruction such as `close ticket
  <number>`, `close it <number>`, or `this ticket should be closed <number>`
  uses the deterministic ticket-close executor. Command Center persists the
  request and idempotency key before invoking a broker-only CLI, then requires
  Salesforce close and resolution-Chatter readback. One same-request
  reconciliation is allowed after a transient provider/readback failure; it
  reuses the original idempotency key and reads the ticket and Chatter before
  any mutation. The executor has no email, generic update, SQL, or model-user
  invocation path.
- Taylor's API-customer recipient cohort uses a separate SQL login that can
  select only `Username`, `DatabaseName`, and `ApiExpirationDate` from
  `POS_Main.dbo.users`. The typed operation has no caller-supplied SQL, applies
  fixed Salesforce active-account/active-location checks, deduplicates valid
  email addresses, and cannot send mail. The credential file is readable only
  by `nova-salesforce-broker`.
- Chargify credentials belong to `nova-maxio-broker`. Taylor and Jamie receive
  bounded reads plus guarded non-delete `POST`, `PUT`, and `PATCH` operations for
  lane-owned Maxio work. A mutation requires a stable idempotency key, durable
  pending journal entry, and provider readback. Generic `DELETE` and record
  deletion remain absent. Jamie alone receives a typed immediate subscription
  cancellation preview/apply operation using Maxio's documented cancellation
  endpoint; it preserves history, requires zero balance, and cannot refund,
  credit, void, schedule, or email.
- Rescue credentials belong to `nova-rescue-broker` and expose read-only
  session, performance, and chat-log tools to Alex and Thor. Thor receives
  exactly status, session-list, performance-read, and chat-read operations;
  there are no Rescue mutations. Zoom credentials stay inside broker
  identities. Weekly
  call metrics reuse the existing `Support Dashboard Calls` S2S app and its
  read-only engagement-log scope. The added agent-performance dataset scope is
  retained for diagnostics but is not used for the report count. The operation
  is pinned to the exact six-agent roster in
  `config/zoom-weekly-support-agents.json`, counts each engagement once per
  participating report agent, and includes all channels and queues; no new
  Marketplace app or Team Chat scope is required. General OAuth remains
  isolated to the Zoom and Rory operator brokers behind one group-protected
  state file and cross-process lock. Singapore Team Chat delivery and the
  weekly Yaron message instead reuse the `Support Dashboard Calls` S2S app,
  bind its token owner to the explicitly configured Nova sender, and require
  exact sender, recipient, body, and message-ID readback. Alex and Taylor
  receive typed Zoom reads, while Thor receives a
  separate fixed-roster quality-only inventory for capabilities, health, voice
  engagements, agent performance, engagement recordings, and transient
  transcript evidence. Thor also receives bounded read-only Salesforce ticket
  evidence, including the existing Classic/Wave weekly-total operation; he has
  no Salesforce mutation, recipient resolver, admin, Gmail, or ticket-write
  tool. The Singapore background service retains its guarded send/upload path.
- Gmail OAuth material is available only to the root-owned preflight and the
  `nova-runtime` Command Center process. The weekly Yaron workflow uses the
  typed Zoom Team Chat sender with per-window dedupe and exact message
  readback; email delivery and fallback are disabled.
- Rory's operator broker receives ACL-only read access to the existing provider
  credentials plus separate full-scope Google Workspace ADC and GitHub operator
  token secrets. Taylor, Alex, Jamie, Thor, Raw, `nova-runtime`, and Rory's
  model UID cannot read those files or invoke the operator broker.
- Taylor's ordinary cloud broker exposes one mutation family only when Darius
  directly authorizes SQL-tool implementation and release: validate and
  squash-merge a bounded `codex/*` scoped-SQL PR, then promote its successful
  immutable Cloud Build artifact to the pinned private VM. It cannot push main
  directly, edit workflows, administer GitHub, change IAM, target another
  resource, or deploy an unbuilt commit.
- Slack app/bot tokens are available only to the runtime systemd services.
  Rory never receives them.
- Rory accepts only the singleton operator Slack allowlist and authenticated
  Command Center direct chat. Application policy rejects every non-direct
  Command Center source except one deterministic tool-repair escalation that
  preserves a verified operator-origin request. That route is limited to one
  repair attempt per obligation, resets the specialist handoff depth, and
  cannot expand provider ownership or write authority. Ordinary inbound agent
  delegation remains rejected. Rory may continue the repaired obligation
  outward to the owning specialist, cannot launch subagents, and cannot share
  his identity. Rory's brokered Command Center control plane can inspect and
  supervise all configured lanes because agent state is evidence rather than
  authority.
- Rory, Thor, Taylor, Alex, and Jamie run under separate Linux users and separate
  Codex homes. Rory stays on the OpenAI Codex CLI. `forced_login_method` is
  `chatgpt`; no OpenAI Platform API key and no Gemini fallback are configured.
- Every unattended Codex home disables anonymous analytics, feedback
  submission, and OpenTelemetry log, metric, and trace export. The supervising
  Command Center, Slack bridge, authentication, and preflight services also set
  `DO_NOT_TRACK=1` and `OTEL_SDK_DISABLED=true`; boot preflight fails closed if
  any lane's effective Codex configuration loses those controls.
- Every unattended Codex home uses `approval_policy = "never"` so an
  interactive elicitation or automatic-review failure cannot cancel a
  host-authorized background write. This does not grant provider authority:
  signed operator provenance, lane MCP allowlists, typed broker operations,
  idempotency journals, duplicate checks, and authoritative readback remain the
  enforcement boundary. Each template also predeclares only its exact lane
  workspace as trusted so the first unattended invocation never needs to mutate
  runtime policy. Raw remains non-writing with no MCP servers. Thor is
  non-writing and receives only the read-only Rescue and Zoom quality MCP
  servers.
  Boot preflight compares every effective home and MCP allowlist with the
  release; a separate harmless MCP probe verifies both a fresh and resumed Alex
  session.
- Rory's four configured MCP servers and Jamie's two scoped billing-write
  servers additionally use `default_tools_approval_mode = "approve"`. Without
  this explicit server pre-approval, Codex can convert an unattended operator
  or Billing-ticket write into `user cancelled MCP tool call` before the
  broker receives it. Jamie still has only the typed Salesforce Billing and
  Maxio tools; the setting does not add generic provider access.
- Raw Codex and Thor have separate `nova-raw` and compatibility `nova-claude`
  users, homes, and workspaces. Thor has only its exact read-only Rescue/Zoom
  MCP policy. Bootstrap checks Thor when it is available, but Thor's login,
  quality-only broker lanes, and live Rescue/Zoom quality connectors are
  degraded-only checks: they cannot stop Command Center, Slack, or the four
  required work lanes. Raw remains unauthenticated with an empty MCP policy.
  Neither reuses `nova-rory` or Rory's credential home.
- The Singapore result cache is a two-writer boundary shared only by
  `nova-runtime` and `nova-singapore-broker`. A setgid group plus atomic unique
  temporary files lets either writer replace the result without making the next
  broker run unreadable. Boot preflight exercises both write directions.

Rory's unrestricted provider surface does not remove write hygiene. Native API
mutations require a stable idempotency key, are appended to the protected
operator journal, and must be followed by provider readback. This is an
execution safeguard, not an action allowlist.

The preferred fallback when workspace access-token creation is disabled is an
interactive ChatGPT device-code login performed directly on the private VM.
Provision with an explicit mode so a missing token can never silently weaken
an access-token deployment:

```powershell
.\deploy\gcp\agent-runtime\provision-private-runtime.ps1 -CodexAuthMode device
.\deploy\gcp\agent-runtime\provision-private-runtime.ps1 -CodexAuthMode device -Apply
```

The VM remains staged: neither Slack nor any writer starts, and provider
preflight requires Rory, Taylor, Alex, and Jamie. Thor is reported as degraded
until its independent quality lane is authenticated. Each `~/.codex` is a
file-backed, mode-`0600` credential store bind-mounted from the encrypted,
non-auto-delete state disk. Authenticate through IAP, one identity at a time:

```powershell
gcloud compute ssh nova-agent-runtime-staging `
  --project=gen-lang-client-0051653266 --zone=us-central1-a `
  --tunnel-through-iap `
  --command="sudo /opt/nova/bin/begin-codex-device-auth rory"
```

Repeat for `taylor`, `alex`, and `jamie`, then run the non-mutating preflight.
Authenticate `thor` separately to enable its quality lane; a missing Thor login
does not block the required production services.
The URL and one-time device code are safe only for the active sign-in attempt;
never paste `auth.json` into chat or a ticket.

If workspace access tokens later become available, the original unattended
mode remains supported. Save a token to a local ACL-protected file outside the
repository and import only that token without rotating verified providers:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File `
  .\deploy\gcp\agent-runtime\sync-agent-runtime-secrets.ps1 `
  -OnlyCodexAccessToken `
  -CodexAccessTokenPath C:\secure\codex-access-token.txt `
  -Apply
```

The access token is a ChatGPT workspace credential consumed by `codex login
--with-access-token`; it is not an OpenAI API key or Platform API route. Do not
copy a workstation `auth.json` into the VM because concurrent refreshes can
race and the file can contain reusable credentials.

## Deployment sequence

1. Configure a dedicated trigger through the existing GitHub app connection in
   plan mode, then apply it once:

   ```powershell
   .\deploy\gcp\configure-agent-runtime-cloud-build.ps1
   .\deploy\gcp\configure-agent-runtime-cloud-build.ps1 -Apply
   ```

   The trigger follows `dariusmakesstuff/codex-slack-bridge` `main`, runs both
   the repository and scoped-provider test suites, and publishes
   `releases/<commit>.tar.gz` to the private runtime source bucket. It uses a
   dedicated build identity that can create and read objects in only that
   bucket, write build logs, and invoke a build through a one-permission custom
   role (`cloudbuild.builds.create`). It does not receive the broader Cloud
   Build Builder role and cannot deploy, restart, or activate the production
   worker. The setup verifies this trigger before deleting the obsolete
   Google-generated Cloud Run auto-deploy trigger.
2. Commit the changes, push the review branch, and fast-forward `main` only
   after tests pass. Require the triggered Cloud Build to succeed. The
   provisioner independently verifies that local `HEAD` equals GitHub
   `origin/main` and that the corresponding Cloud Build artifact exists; it no
   longer uploads an operator-workstation archive.
3. Run `sync-agent-runtime-secrets.ps1 -OnlyRoryOperatorSecrets -VerifyExisting`
   after authorizing full Google Workspace scopes, then run the ordinary
   `-VerifyExisting` check and require every
   provider readback to match. In device mode, the Codex access-token secret is
   intentionally absent. In access-token mode, use `-OnlyCodexAccessToken` for
   the final token.
4. Run `provision-private-runtime.ps1` without `-Apply`; inspect the project,
   region, private network, service identity, commit, numeric secret readiness,
   and `startsSlackOrWriters: false`.

In access-token mode, the provisioner refuses `-Apply` while the Codex token or
any pinned provider secret is absent. Device mode requires every pinned provider
secret but stages the worker with `interactiveCodexAuthRequired: true`. Core
isolation and runtime-policy checks must pass before Command Center cutover.
Rory, Taylor, Alex, and Jamie device logins should be green before their work is
routed; missing logins, Thor, and provider health remain visible as degraded
readiness without taking down Command Center.
5. Run the provisioner with `-Apply`. It creates a Shielded VM with no public
   address, Cloud NAT with a stable egress IP, and a non-auto-delete persistent
   state disk. Bootstrap installs Codex and ODBC and materializes provider
   secrets. Access-token mode runs the read-only provider preflight immediately;
   device mode defers it until the required interactive logins are complete.
   Neither mode starts Slack or writers.

For an already activated private VM, never create or replace it implicitly. Use
the guarded promotion switch with the VM's existing Codex auth mode:

```powershell
.\deploy\gcp\agent-runtime\provision-private-runtime.ps1 `
  -CodexAuthMode device -UpdateExisting
.\deploy\gcp\agent-runtime\provision-private-runtime.ps1 `
  -CodexAuthMode device -UpdateExisting -Apply
```

The promotion requires local `HEAD` to equal GitHub `main`, both immutable GCS
artifacts to exist, every numeric secret pin to resolve, and the existing VM to
retain its private network, service account, Shielded VM, and persistent disk.
It updates metadata, gracefully stops the VM so systemd can flush state, and
starts it again. Before reboot it disables and stops the current consumers over
private IAP SSH. A transient systemd gate then keeps Command Center, its local
health-repair timer, Slack, and the Zoom timer stopped until the persistent activation marker makes bootstrap
run and pass the full provider/MCP preflight for the new immutable release.
The core gate is intentionally independent of provider availability. It remains
fail-closed for Rory identity isolation and the effective runtime/MCP policy of
the four work lanes. Codex logins, provider authentication, typed broker
inventory, connector health, Singapore readiness, and Thor's quality lane are
reported as degraded checks. A failure gates the affected operation at its
typed broker but does not stop the verified Command Center or Slack services.
A failed general Zoom check also leaves the Zoom monitor disabled.

The promotion also sets an expiring `nova-watchdog-hold-until` label before its
intentional stop. Its bounded start helper confirms `RUNNING` and a `finally`
path makes a second compensating start attempt before the process can return an
error. The label is removed only after that readback; if the promotion process
is killed outright, the label expires after 15 minutes instead of suppressing
recovery indefinitely.

Bootstrap installs three in-VM service safeguards.
`nova-command-center.service` uses `Restart=always`, and
`nova-command-center-healthcheck.timer` calls the loopback `/healthz` endpoint
every minute with a five-second deadline. A failed check restarts the service
once and verifies the endpoint after restart. The health timer is stopped
during guarded promotions and is enabled only after the production preflight
marker is restored. If an activated runtime has no current-release preflight
marker, `nova-runtime-recovery.timer` reruns the same read-only, fail-closed
preflight every two minutes. It restores Command Center, its health timer, and
Slack exactly once after required readiness is green; it restores the Zoom
monitor only when its separate marker exists and never bypasses a failed
required check.

Install the out-of-VM repair loop separately. Plan first, then apply:

```powershell
.\deploy\gcp\runtime-watchdog\install-runtime-watchdog.ps1
.\deploy\gcp\runtime-watchdog\install-runtime-watchdog.ps1 -Apply
```

The installer creates two dedicated identities: a workflow identity with only
`compute.instances.get` and `compute.instances.start` on this exact VM, and a
scheduler trigger identity with Workflows Invoker. Cloud Scheduler runs the
workflow every two minutes. It does nothing while the VM is running or starting,
honors an unexpired promotion hold, and starts only a `TERMINATED` VM. The
installer finishes with IAM, workflow, scheduler, and live no-op execution
readback. This external control plane is required because systemd
service recovery and Compute Engine automatic restart cannot recover a VM that
an operator or interrupted promotion explicitly stopped.
6. Read back the preflight. Require the core gate to be green for Rory identity
   isolation and the effective four-lane runtime/MCP policy. Record Slack,
   Gmail, Salesforce, Nova SQL, Chargify, Codex-login, connector, and broker
   failures as operation-specific degradation without taking the Command Center
   down. If Zoom live health is degraded, verify that
   `nova-zoom-monitor.timer` remains disabled; do not treat that optional outage
   as authority to widen its broker access.
7. Stop the local Slack bridge first, take a consistent state snapshot, copy it
   through IAP to the persistent disk, and verify file ownership and SQLite
   integrity. Only then create the root-owned activation marker and start the
   cloud Command Center followed by the Slack bridge:

   ```bash
   sudo install -m 0400 -o root -g root /dev/null /var/lib/nova/activation/production-cutover.enabled
   sudo systemctl enable --now nova-command-center.service nova-slack-bridge.service
   ```

   The marker persists on the non-auto-delete state disk. Subsequent manually
   promoted immutable releases must pass provider authentication plus exact
   lane/broker MCP startup before bootstrap restarts either production service.
8. Confirm one Rory Slack message is processed exactly once through Codex CLI,
   then test lane routing and non-mutating provider health/readback calls. Enable
   background jobs individually after their real readback checks; never enable
   all watchers as part of the initial cutover.

If any cutover verification fails, stop both cloud services before restarting
the local scheduled tasks. Never run the local and cloud Socket Mode consumers
at the same time.
