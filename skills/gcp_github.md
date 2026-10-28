# GCP and GitHub Ops

<!-- AgentChat/coding_agent 2026-07-10T17:30:00-04:00 -->

Use this skill when the user asks about hosted services, deployments, CI, logs,
metrics, env vars, Cloud Run, GitHub Actions, pull requests, or production
debugging.

In the private GCP runtime Rory has two complementary fast paths. The existing
`gcp_github_ops` broker remains a safe discovery and selected-repository
branch/PR surface. The operator-only `rory_operator_ops` broker uses Rory's
project-owner GCP identity and the authenticated operator's GitHub user token,
including Secret Manager, deployments, IAM, workflows, merges, and repository
administration wherever those provider accounts allow them. Taylor retains
repository implementation ownership but cannot hand work to Rory; only the
authenticated operator may instruct Rory.

## Tool priority

1. **Rory operator MCP** - use `rory_operator_ops` for exact operator-directed
   GCP or GitHub work requiring full account permissions. Mutations require an
   idempotency key and provider readback.
2. **Scoped cloud MCP** - use `gcp_github_ops` for safe discovery and
   selected-repo GitHub reads/branch/PR work.
3. **Codex plugins and MCP** - prefer the GitHub plugin and any configured GCP
   MCP tools when available in a trusted operator session.
4. **`gh` CLI** - repos, PRs, Actions runs, workflow logs, releases.
5. **`gcloud` CLI / native Google APIs** - Cloud Run, Logging, Monitoring,
   Secret Manager metadata, deploys, and env var updates.
6. **`scripts/gcloud-ops-tool.ps1`** - registered fallback wrapper for Cloud Run
   services, jobs, logs, and service-account activation.

If a tool is missing or auth fails, say what failed and what the user must
configure. Do not guess credentials.

## Verified request authority

A verified operator request or signed internal delegation authorizes the exact
GitHub or GCP mutation it asks for. For investigations and explicitly read-only
requests, use these surfaces:

- List/describe Cloud Run services, revisions, jobs, and traffic splits
- Read Cloud Logging entries and Monitoring metrics
- Inspect GitHub repos, branches, PRs, checks, and workflow run logs
- Read Secret Manager secret names and versions — never print secret values
- Run `gh pr view`, `gh run list`, `gh run view --log`, `gcloud run services describe`

## Verified mutations

The verified request authorizes the exact mutation it asks for (for example,
"update the env var", "deploy this", or "merge the PR"). Do not seek a second
approval. Remain read-only when it does not ask for a mutation.

- Update Cloud Run env vars or deploy a new revision
- Change service scaling, traffic, or IAM bindings
- Create/update GitHub PRs, merge PRs, trigger workflows, change repo settings
- Create or rotate secrets

Before mutating production:

1. State what will change (service, project, region, env var names, PR number).
2. Confirm scope is limited to what was requested.
3. Prefer the smallest change that satisfies the request.
4. Report the command/API used and the outcome.

## Security

- Never print tokens, PATs, service account keys, or secret payloads.
- Redact sensitive values in logs and command output.
- Do not paste customer-private data into public GitHub comments or issues.
- Prefer project-scoped service accounts with least privilege.

## Common workflows

### Check Cloud Run health

```
gcloud run services list --project=PROJECT --region=REGION
gcloud run services describe SERVICE --project=PROJECT --region=REGION
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="SERVICE"' --project=PROJECT --limit=50 --freshness=1h
```

### Debug a failing GitHub Actions run

```
gh run list --repo OWNER/REPO --limit 10
gh run view RUN_ID --repo OWNER/REPO --log-failed
```

### Update an env var on Cloud Run (authorized only)

```
gcloud run services update SERVICE --project=PROJECT --region=REGION --update-env-vars KEY=VALUE
```

### Review an open PR

```
gh pr view NUMBER --repo OWNER/REPO
gh pr diff NUMBER --repo OWNER/REPO
gh pr checks NUMBER --repo OWNER/REPO
```

## Known infrastructure

Discovered from local workspace config (not live `gcloud` — verify after auth):

| Item | Value |
|------|-------|
| GCP project ID | `gen-lang-client-0051653266` |
| GCP project number | `63366976264` (in Cloud Run hostname) |
| Primary region | `us-central1` |
| Billing/Rainfall build region | `us-south1` (see `rainfall/Rainfall/cloudbuild.yaml`) |
| Cloud SQL instance | `gen-lang-client-0051653266:us-central1:rainfall-spacey` |
| Artifact Registry repo | `cloud-run-source-deploy` |

### Cloud Run (Nova / auto-tickets)

| Service / job | Region | Notes |
|---------------|--------|-------|
| `logmein-connector` | `us-central1` | FastAPI connector; URL pattern `https://logmein-connector-63366976264.us-central1.run.app` |
| `logmein-poller` | `us-central1` | Scheduled poller job (see deploy docs) |
| `logmein-connector-deploy` | `us-central1` | Alternate job name in some scheduler configs |
| `rainfall` | `us-south1` | Rainfall billing app image (`rainfall/Rainfall/cloudbuild.yaml`) |

Local paths tied to hosted ops:

- Connector repo: `auto-tickets/logmein-connector` → GitHub `dariusmakesstuff/logmein-connector`
- Billing app: `rainfall/Rainfall` (Cloud Build present; also has Render docs)
- Bridge coding agent workspace: `C:/Users/redma/Workworkworkworkworkwork`

### GitHub repos (local remotes found)

| Repo | Local path |
|------|------------|
| `dariusmakesstuff/logmein-connector` | `auto-tickets/logmein-connector` |
| `dariusmakesstuff/KPI-Project` | `KPI-Project` |
| `Dabeldab/Daily-Devotionals` | `Daily-Devotionals` |

Use `gh run list --repo OWNER/REPO` and `gh pr checks` against the repo that
matches the service you are debugging.

## Setup reference

See `config/ops.env.example`, `config/codex-mcp.example.toml`, and `.env.example`
in the bridge repo for local auth and MCP configuration. Typical setup:

- `gh auth login` for GitHub
- `gcloud auth login` and `gcloud config set project PROJECT` for GCP
- Optional: `GOOGLE_APPLICATION_CREDENTIALS` for a dedicated ops service account
- Preferred Agent Chat wrapper:
  `powershell -ExecutionPolicy Bypass -File "scripts/gcloud-ops-tool.ps1" -Action status`
- To activate a configured local service-account key:
  `powershell -ExecutionPolicy Bypass -File "scripts/gcloud-ops-tool.ps1" -Action activate-service-account`
- GitHub plugin is enabled in Codex when `github@openai-curated` is on
