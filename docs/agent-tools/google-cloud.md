<!-- AgentChat/coding_agent 2026-07-10T18:20:00-04:00 -->

# Google Cloud Operations

## Fast route

In the private cloud runtime, Rory uses `rory_operator_ops` for exact
operator-directed work requiring full project permissions and
`gcp_github_ops` for safer inventory, status, and redacted-log discovery. Then
use a connected Google Cloud tool, native `gcloud`/Google APIs, or the
registered helper. Browser is last. Prefer an already-active identity;
credential names include `GOOGLE_APPLICATION_CREDENTIALS`,
`CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE`, `GCP_PROJECT_ID`,
`GCP_DEFAULT_REGION`, and `GCP_OPS_SERVICE_ACCOUNT_EMAIL`. Never display key,
secret, token, or environment values.

Rory's broker receives a short-lived token minted by a root-only timer for the
dedicated project-Owner `nova-rory-cloud-ops` service account, including Secret
Manager payload access. Rory's model process cannot read the token or reach VM
metadata. Mutations use the operator broker's idempotency journal and provider
readback.

## Common sequence

1. Run
   `powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/gcloud-ops-tool.ps1 -Action status`
   for auth/account status without printing credentials. The explicit bypass is
   needed on this Windows host. The helper uses `gcloud.cmd` and can use a valid
   process-local ADC token when the separate gcloud user refresh token is stale.
2. Resolve project and region from live config/repo config. Auto-tickets normally
   uses `gen-lang-client-0051653266` / `us-central1`; Rainfall may use
   `us-south1`, so verify.
3. Inspect with `gcloud run services list`, `gcloud run jobs list`, service/job
   describe, revision/traffic state, and a narrowly filtered
   `gcloud logging read`.
4. For a requested deploy/env/IAM/traffic change, capture pre-state, execute the
   exact mutation, wait for readiness, read service/revision/traffic back, and
   check fresh error logs. Preserve a rollback revision/config.

Canonical sources: `skills/gcp_github.md`, `scripts/gcloud-ops-tool.ps1`,
`scripts/setup-ops-auth.ps1`, `config/ops.env.example`, connector Cloud Run
deployment docs, and Rainfall `cloudbuild.yaml`.
