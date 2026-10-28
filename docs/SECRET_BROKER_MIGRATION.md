# Secret Broker Migration

## Security boundary

Environment scrubbing is useful defense-in-depth, but it is not hard isolation on the current host. Agent processes run under the same Windows identity with broad filesystem access, so they can potentially read that user's credential files, ADC, environment files, or same-user DPAPI vault. Moving values to Google Secret Manager alone does not solve this: any process allowed to call `AccessSecretVersion` receives plaintext.

The required boundary is a trusted broker that agents cannot impersonate or inspect:

```text
agent -> typed, allowlisted operation -> isolated broker -> Secret Manager/downstream API
                                      <- sanitized result <-
```

The broker should run either:

- on Cloud Run with a dedicated user-managed service account, or
- as a local Windows service under a separate OS identity with ACL-isolated files and IPC.

Cloud Run is preferred because its service identity can use attached credentials without a downloaded service-account key. Agents receive no Secret Manager IAM role and never receive raw secret values.

The Google provider is an optional install on the broker host only:

```powershell
py -3 -m pip install -e ".[google-secret-manager]"
```

Do not install or configure Secret Manager credentials in an agent runtime.

## Current Google Cloud readiness

A read-only check on 2026-07-13 found that project `supportkpis` already has the Secret Manager API enabled and contains zero secrets. No Google Cloud resources or IAM bindings were changed. The project is ready for staged setup, but no live credential should be moved until its brokered operation exists and passes the tests below.

## Broker contract

Expose business operations, not credentials. Examples include `drive.read_document(document_id)` or `salesforce.lookup_account(account_id)`. Every operation must have a fixed request/response schema, destination allowlist, authorization check, timeout, size limit, and redaction policy.

Never expose:

- a generic `get_secret`, `read_file`, or environment-dump method;
- arbitrary URLs, commands, PowerShell, shells, scripts, or executable paths;
- raw downstream tokens, refresh tokens, client secrets, private keys, or unfiltered error bodies;
- Secret Manager resource references in agent prompts when the agent does not need them.

Only the isolated broker resolves a logical credential name to a Secret Manager resource such as `projects/supportkpis/secrets/<name>/versions/<number>`. Production configuration must pin a numeric version, not `latest`.

## IAM and observability

- Give the broker service identity `roles/secretmanager.secretAccessor` on each individual secret it needs, not at project scope.
- Give a separate operator or rotation identity version-management rights. The broker should not create, modify, disable, or destroy versions.
- Give agent identities no Secret Manager permissions and no ability to impersonate the broker identity.
- Prefer service identity, ADC metadata, or Workload Identity Federation. Do not download or export service-account JSON keys.
- Enable Secret Manager Data Access audit logs for `AccessSecretVersion`. Alert on unexpected identities, secrets, regions, or access rates.
- Keep application logs metadata-only. Never log secret payloads, authorization headers, full upstream responses, or sensitive request fields.

## Staged migration

1. **Inventory without values.** Record each logical credential, owner, downstream system, consumers, rotation method, and revocation procedure. Do not place values in tickets, docs, source control, prompts, or migration manifests.
2. **Build the typed operation.** Add one broker operation and its schemas, destination allowlist, redaction, rate limit, and audit correlation ID. Keep the existing credential path active.
3. **Create and authorize.** An operator creates the secret/version through a secure input path and grants the broker identity per-secret access. Pin the broker configuration to the new numeric version.
4. **Verify in isolation.** Exercise the broker directly, confirm the agent identity is denied Secret Manager access, and inspect logs for leakage before enabling agent routing.
5. **Cut over one consumer.** Route only the typed operation through the broker. Monitor failures, access logs, and downstream behavior during a defined soak period.
6. **Rotate upstream.** After successful cutover, issue a new upstream credential where supported so any former local copy becomes invalid. Update the broker to the new pinned version.
7. **Retire local copies.** Remove the credential from environment files, user ADC/service-account files when applicable, DPAPI vault entries, scheduled-task environments, and documentation. Verify absence by name and path without printing values.
8. **Retire old versions.** Disable the prior Secret Manager version after the rollback window, then destroy it according to the retention policy.

Repeat these steps credential by credential. Do not bulk-migrate values before all required broker operations exist.

## Rotation and rollback

Rotation should create a new version, validate it through the broker, update the pinned numeric version, soak, and then disable the old version. Keep creation/rotation permissions separate from runtime access.

Rollback changes only the broker's pinned version or operation route; it must never return a secret to an agent. A previous version is usable only while both it and the corresponding upstream credential remain valid. Define that window before rotating or revoking the upstream credential, and record who may authorize rollback.

## Acceptance tests

Migration of a credential is complete only when all of these pass:

- trusted and untrusted agent child environments contain no sensitive variables;
- agent prompts and logs contain no values or local credential-store paths;
- direct `AccessSecretVersion` calls and broker-identity impersonation fail for the agent identity;
- filesystem and process inspection from the agent identity cannot read broker credentials or memory through same-user access;
- only registered operations and approved destinations are accepted; generic secret reads, arbitrary URLs, and shell execution are rejected;
- broker responses and errors are schema-validated, size-limited, and redacted;
- audit logs attribute each secret access to the broker identity and correlate it to an approved operation without recording payloads;
- rotation succeeds using a new numeric version, and rollback succeeds within the declared window;
- after cutover, old local copies are absent and revoked, and the prior Secret Manager version is disabled or destroyed on schedule.

Until the broker runs under a distinct identity, environment scrubbing and prompt cleanup reduce accidental exposure but must not be represented as a guarantee that agents cannot access secrets.
