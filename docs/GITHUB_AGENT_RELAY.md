# GitHub Agent Relay

## Purpose

The GitHub Agent Relay gives ChatGPT and other authenticated GitHub operators a
durable request/response bridge into the existing Nova private agent runtime
without exposing the VM, copying provider credentials into GitHub Actions, or
making the browser Command Center API public.

The path is:

```text
ChatGPT / operator
  -> commit relay/inbox/<task-id>.json
  -> GitHub-hosted Actions runner
  -> GitHub OIDC / Google Workload Identity Federation
  -> IAM-protected nova-github-agent-relay Cloud Run service
  -> IAP-authenticated Cloud Run request
  -> Nova Command Center Cloud Run service / Firestore-backed runtime
  -> existing agent-direct-chat durable job
  -> server-side relay status polling
  -> commit relay/outbox/<task-id>.json
  -> ChatGPT / operator reads result
```

The existing `nova-command-center-shadow` service remains the human dashboard.
The relay is a separate narrow service so its machine-to-machine authentication
does not weaken the dashboard's IAP + application OAuth gates.

## Security boundaries

The relay has deliberately less authority than the Command Center UI or Rory's
provider broker:

- Cloud Run IAM denies anonymous invocation.
- GitHub Actions receives no long-lived Google key. It exchanges the GitHub OIDC
  token for the dedicated `nova-github-relay-invoker` identity.
- The Workload Identity provider is conditioned on exactly
  `dariusmakesstuff/codex-slack-bridge` and `refs/heads/main`.
- The Cloud Run relay runtime has no Salesforce, Gmail, Maxio, Zoom, Slack,
  GitHub, SQL, or Codex credential.
- The relay creates a five-minute self-signed service-account JWT through IAM
  Credentials, scoped to the exact Command Center Cloud Run URL. It sends that
  JWT in `Proxy-Authorization` and the existing pinned Command Center transport
  bearer in `Authorization`. IAP validates the first and preserves the second
  for the application, so neither credential is reused for the other boundary.
- The relay implementation exposes only `POST /v1/tasks`, `GET /v1/jobs/<id>`,
  and `GET /health`. It is not a generic HTTP proxy.
- Upstream traffic is pinned to one literal RFC1918 HTTP address and the
  existing private Command Center port.
- Tasks are submitted through `/agent-chat/send`, preserving the existing
  `agent-direct-chat` operator authority and every lane-specific broker rule.
- The outbox is evidence only. It cannot create authority or replay an action.
- A task id is also the default idempotency key, so retries resolve to the same
  Command Center mutation identity rather than silently creating duplicates.

## One-time GCP deployment

Run the deployment script in plan mode first from an authenticated operator
workstation:

```powershell
.\deploy\gcp\deploy-github-agent-relay-production.ps1
```

Then apply after reviewing the exact project, service accounts, WIF condition,
private upstream, network, secret version, and image commit:

```powershell
.\deploy\gcp\deploy-github-agent-relay-production.ps1 -Apply
```

The script creates or verifies:

- Cloud Run service `nova-github-agent-relay` in `us-central1`;
- runtime service account `nova-github-agent-relay`;
- caller service account `nova-github-relay-invoker`;
- Workload Identity Pool `nova-github-relay` and provider `github`;
- repository + main-branch-only WIF condition;
- Cloud Run Invoker only for the dedicated caller identity;
- Secret Manager access for the runtime identity only to the pinned
  `nova-command-center-upstream-token` version;
- IAP access only for the relay runtime identity to the named Command Center
  Cloud Run service; the private compute-era `:17866` endpoint is not used.

The deployment readback fails if `allUsers` or `allAuthenticatedUsers` appears
in the Cloud Run IAM policy.

## Repairing the GitHub OIDC invoker

The invoker ID `nova-github-agent-relay-invoker` had 31 characters and
was invalid for a Google service-account ID. The corrected name is
`nova-github-relay-invoker`. Both the GitHub workflow and provisioning script must
agree on that identity.

On an authenticated GCP operator workstation, run the plan first, inspect the
project, WIF scope, Cloud Run ingress and token-secret settings, then apply:

```powershell
.\deploy\gcp\deploy-github-agent-relay-production.ps1
.\deploy\gcp\deploy-github-agent-relay-production.ps1 -Apply
```

The production provisioner creates/verifies the service account, GitHub
Workload Identity pool/provider and main-branch restriction, WIF impersonation
binding, and Cloud Run `roles/run.invoker` binding. Be aware
that `-Apply` also rebuilds/redeploys the **Cloud Run relay service**
and sets its request timeout; it does not restart the private Command Center VM.

Verify IAM/WIF and IAP readbacks before sending a new, uniquely named read-only
`relay/inbox/*.json` probe. An earlier failed Action will not
automatically retry merely because the identity is corrected.

## Sending work

Create a new file under `relay/inbox/` and commit it to `main`. Example:

```json
{
  "version": 1,
  "task_id": "chatgpt-20260917-001",
  "agent": "rory",
  "title": "Inspect runtime",
  "instruction": "Check current agent/runtime health and summarize anything that needs attention. Do not mutate providers.",
  "reasoning_provider": "codex_cli",
  "timeout_seconds": 900,
  "created_at": "2026-09-17T17:00:00Z"
}
```

The Action authenticates once and submits the task. Cloud Run polls the durable private Command Center job server-side until terminal or timeout, then the Action writes `relay/outbox/chatgpt-20260917-001.json`. This avoids reusing a short-lived Google ID token during long jobs.

### Choosing the reasoning backend

The GitHub request envelope defaults to `reasoning_provider: "codex_cli"`.
That keeps Alex, Jamie, and Taylor on their already-configured Codex CLI
runtime. To use ChatGPT Work instead, explicitly select
`reasoning_provider: "chatgpt_relay"`. Provider failure never causes
automatic cross-provider fallback: that could duplicate a real mutation.

The provider is validated separately from the instruction body. Old
in-flight jobs keep their original provider. Changes to relay Python
must be deployed to the dedicated Cloud Run relay service before a new
inbox task uses the updated routing.

**Privacy:** GitHub relay outbox receipts are committed repository content.
Use this path for sanitized operational checks and aggregate results only.
Keep sensitive Salesforce ticket details and database rows in the private
Command Center until a private authenticated result path is available.

The supported aliases are:

| Alias | Runtime lane |
| --- | --- |
| `rory` | `direct_codex` |
| `taylor` | `coding_agent` |
| `alex` | `tickets_agent` |
| `jamie` | `billing_agent` |
| `thor` | `claude_agent` |

## ChatGPT operating pattern

After this is deployed, ChatGPT can use the GitHub connector as the control
plane:

1. Create one new immutable inbox envelope on `main`.
2. Observe the workflow/run or check for the matching outbox file.
3. Read the outbox result.
4. If more work is needed, create a new task id. Never edit the original inbox
   envelope to smuggle new authority into an already accepted request.

This is two-way asynchronous transport through GitHub. It does not grant a
GitHub runner or Cloud Run process access to the ChatGPT browser conversation;
GitHub is the durable mailbox between the two sides.
