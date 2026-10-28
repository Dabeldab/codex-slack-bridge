# Nova agent system: authenticated GCP shadow runbook

## Decision

The first cloud release is an authenticated, read-only Command Center shadow.
The existing Windows runtime remains the sole production writer. This avoids a
big-bang cutover while the QA report's credential, lane-isolation, provider IAM,
durable audit, and task-parity gaps are still open.

The shadow is useful for validating build provenance, service identity, IAP,
Google OAuth, secret delivery, Linux portability, health/read APIs, and
rollback mechanics. It is not evidence that the full agent system is ready for
production cloud cutover.

## Trust boundaries

```text
Browser
  -> Cloud Run IAP (Google login + exact IAM member)
    -> Nova Google OAuth (verified ID token + exact app allowlist)
      -> authenticated Command Center session (CSRF protected)
        -> shadow runtime (all operational POSTs denied)
```

The Cloud Run execution identity is dedicated to this service. It receives
secret-accessor permission only on the three OAuth configuration secrets. It
gets no provider credentials and no project-wide Secret Manager role.

## Release gates

### Gate 1: source and local regression

- Branch is isolated from the live production checkout.
- Worktree is clean and the deployed image label matches the full Git commit.
- Google OAuth configuration rejects missing values, wildcard/empty
  allowlists, mismatched origins, non-HTTPS production callbacks, invalid
  issuer, unverified email, and unlisted email.
- OAuth state is browser-bound, expires, and can be consumed only once.
- Session cookies are `Secure`, `HttpOnly` where appropriate, and
  `SameSite=Lax`; browser mutations require the exact origin and CSRF token.
- Logout removes the server-side session and clears browser cookies.
- Existing local loopback bearer/session tests remain green.
- Shadow mode denies authenticated internal and browser mutation requests.

### Gate 2: cloud identity and secrets

- Direct Cloud Run IAP is enabled and verified by service readback.
- Cloud Run IAM contains neither `allUsers` nor `allAuthenticatedUsers`.
- IAP policy includes only explicitly approved Google users/groups.
- A dedicated `nova-command-center-shadow` service account is attached.
- OAuth values are Secret Manager references, not inline Cloud Run values,
  repository files, build substitutions, or command-line arguments.
- The runtime service account can access only the named OAuth secrets.

### Gate 3: live negative/positive checks

- Anonymous request does not reach the application and is redirected/denied by
  IAP.
- A Google identity without IAP membership cannot reach the application.
- An IAP-authorized but app-unlisted identity is denied by Nova OAuth.
- The allowed identity can sign in and sign out.
- Authenticated `/health` reports `runtimeMode=shadow` and
  `externalWritesEnabled=false`.
- Authenticated and internal-bearer POST `/dispatch` both return HTTP 423.
- No Slack message, email, Salesforce write, SQL action, Zoom action, Singapore
  upload, or scheduled background job occurs.

### Gate 4: rollback

- Record the deployed revision and image digest before traffic validation.
- On failure, route traffic to the previous known-good shadow revision or
  delete the shadow service. This does not affect the live Windows runtime.
- Revoke IAP membership and disable/delete OAuth secret versions if the shadow
  is abandoned.
- Preserve build and audit logs; do not delete evidence during incident review.

## Staged migration after shadow validation

1. Observe the authenticated shadow and compare read-only health/output with
   the live runtime.
2. Build typed, read-only brokers and per-lane identities in staging. Agents
   receive no raw secrets, shared ADC, browser profiles, or provider CLIs.
3. Replay representative Alex, Jamie, Taylor, and Thor — Support Quality tasks
   and measure parity/denials before any writer moves. The `claude_agent`
   runtime ID is retained only for compatibility.
4. Add durable task envelopes, resource locks, immutable write-ahead audit, and
   independent readback.
5. Move one low-risk read-only lane, canary it, and prove rollback.
6. Introduce narrowly scoped mutation executors only after provider-side IAM
   makes deletes and out-of-domain writes impossible.
7. Cut over production writers one lane at a time. Never run local and cloud
   writers concurrently for the same source/resource.

## Explicit non-goals of the first release

- No production agent execution.
- No provider credentials or customer data copied to the container.
- No SQL, email, Salesforce, Zoom, GCloud administration, LogMeIn, or Singapore
  mutations.
- No shutdown or modification of the current Windows scheduled tasks.
- No claim of production migration readiness until the QA report's P0/P1
  evidence gates are closed.
