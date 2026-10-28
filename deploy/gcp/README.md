# Google Cloud authenticated shadow deployment

This directory deploys the Nova Command Center web/control surface in
non-writing `shadow` mode by default. After the private VM is promoted, the
same Google-authenticated service can be explicitly deployed with
`-EnablePrivateGateway`; it then proxies authenticated dashboard API requests
to the primary VM over Direct VPC egress. The Cloud Run container never holds
Salesforce, Gmail, SQL, Slack, Zoom, or Maxio credentials.

## Security model

Requests pass through two independent Google gates:

1. Cloud Run Identity-Aware Proxy (IAP) authenticates the Google account and
   checks the explicit `roles/iap.httpsResourceAccessor` membership. The Cloud
   Run service is deployed with `--no-allow-unauthenticated`; `allUsers` and
   `allAuthenticatedUsers` are forbidden by deployment readback.
2. The application runs the same authorization-code pattern as Rainfall:
   server-side one-time state, Google-signed ID-token verification, exact-email
   allowlisting, opaque server-side session, secure/HttpOnly cookies, CSRF
   validation, and session-destroying logout.

The application also refuses any non-loopback listener unless the Google OAuth
configuration is complete. An empty allowlist denies everyone. There is no
first-user bypass.

Shadow mode disables background watchers and returns HTTP 423 for every
operational POST action, even when the internal bearer is valid. OAuth logout
remains available. The container has no Slack, Salesforce, Gmail, SQL, Zoom,
or other provider secret.

Private-gateway mode keeps the local Cloud Run runtime in shadow mode and adds
one purpose-built transport only:

- Google IAP, exact-email application login, and CSRF validation run before a
  request can be forwarded.
- Direct VPC egress routes only private destinations through the dedicated
  `nova-agent-runtime` network.
- A Cloud Run revision network tag and a VPC firewall rule limit TCP 17866 to
  the tagged gateway and the tagged private VM.
- A pinned Secret Manager bearer authenticates Cloud Run to the VM. The VM
  accepts that bearer only on its Command Center HTTP service; agents never
  receive it.
- The VM has no public IP. Provider operations and persistent state remain on
  the VM and its non-auto-delete state disk.

## Files

- `Dockerfile.cloud-run-shadow`: non-root Cloud Run image.
- `cloudbuild-shadow.yaml`: pinned-image Cloud Build definition.
- `set-google-oauth-secrets.ps1`: imports OAuth settings from process
  environment into Secret Manager without printing values.
- `deploy-cloud-run-shadow.ps1`: creates the dedicated service identity,
  builds a commit-pinned image, deploys with direct Cloud Run IAP, grants exact
  IAP users, batches dashboard reads through the private gateway, and performs
  IAM/service readback. The gateway uses a 15-second upstream deadline and 16
  request slots so an unavailable private runtime fails quickly without
  exhausting the single authenticated front-end instance.
- `runtime-watchdog/`: deploys the exact-VM, maintenance-aware Workflows and
  Cloud Scheduler repair loop for an unintentionally stopped private runtime.

## Fixed shadow target

- Project: `gen-lang-client-0051653266`
- Project number: `63366976264`
- Region: `us-central1`
- Service: `nova-command-center-shadow`
- Predicted URL:
  `https://nova-command-center-shadow-63366976264.us-central1.run.app`
- OAuth callback:
  `https://nova-command-center-shadow-63366976264.us-central1.run.app/auth/google/callback`

The callback must be registered exactly on a dedicated Google OAuth web client
before deployment. Do not add wildcards and do not commit the client secret.

## Operator sequence

1. Run the focused/full tests and commit the branch. The deploy script refuses
   a dirty worktree.
2. Create a dedicated Google OAuth web client using the callback above. Use the
   same consent-screen and authorization-code behavior as Rainfall, but do not
   share Rainfall's client secret.
3. Put the client ID, client secret, and exact comma-separated allowed emails
   in the current process environment. Run `set-google-oauth-secrets.ps1`
   without `-Apply` first, then with `-Apply`.
4. Run `deploy-cloud-run-shadow.ps1` without `-Apply`. Verify the target,
   commit, URL, and redirect.
5. Run it with `-Apply -OAuthRedirectConfigured` and one or more exact
   `-AllowedUserEmail` values.
6. Verify an unauthenticated browser is stopped by IAP, an unlisted Google
   account is denied, an allowed account completes both gates, `/auth/session`
   returns the expected email, `/health` reports `runtimeMode=shadow` and
   `externalWritesEnabled=false`, and `/dispatch` returns 423.

Do not use `-EnablePrivateGateway` until the private VM artifact, pinned proxy
secret, firewall rule, service listener, agent identities, provider preflight,
and rollback state have all been verified. Shadow deployment remains the safe
default when the switch is omitted.

For the production dashboard cutover, deploy the committed image with:

```powershell
.\deploy\gcp\deploy-cloud-run-shadow.ps1 `
  -AllowedUserEmail darius@novapointofsale.com `
  -OAuthRedirectConfigured `
  -EnablePrivateGateway `
  -Apply
```

Read back `/health`, `/runtime/status`, `/jobs`, one direct agent chat receipt,
and the exact IAP/IAM/network/secret configuration before calling the dashboard
live. Never expose port 17866 to `0.0.0.0/0` or add a public VM address.

The long-running Slack/Codex worker has a separate private-VM design and
cutover sequence in [`agent-runtime/README.md`](agent-runtime/README.md). It is
deliberately not hosted inside the request-driven Cloud Run shadow.

Its GitHub-linked build is defined in `cloudbuild-agent-runtime.yaml` and the
one-time dedicated-trigger replacement is handled by
`configure-agent-runtime-cloud-build.ps1`. That build publishes a tested,
commit-addressed private artifact; it deliberately has no production deploy or
service-restart permission.
