[CmdletBinding()]
param(
    [string]$ProjectId = "gen-lang-client-0051653266",
    [string]$Region = "us-central1",
    [string]$Service = "nova-command-center-shadow",
    [string]$Repository = "nova-agent-shadow",
    [string]$ServiceAccountName = "nova-command-center-shadow",
    [string]$GithubAppIdSecret = "nova-agents-github-app-id",
    [string]$GithubAppInstallationIdSecret = "nova-agents-github-app-installation-id",
    [string]$GithubAppPrivateKeySecret = "nova-agents-github-app-private-key",
    [string]$OperatorSigningKeySecret = "nova-agents-operator-signing-key",
    [string]$SalesforceClientIdSecret = "nova-agents-salesforce-client-id",
    [string]$SalesforceClientSecretSecret = "nova-agents-salesforce-client-secret",
    [string]$SalesforceLoginUrlSecret = "nova-agents-salesforce-login-url",
    [string]$SalesforceInstanceUrlSecret = "nova-agents-salesforce-instance-url",
    [string]$RescueUserSecret = "nova-agents-rescue-user",
    [string]$RescuePasswordSecret = "nova-agents-rescue-password",
    [string]$RescueBaseSecret = "nova-agents-rescue-base",
    [string]$RescueNodeIdSecret = "nova-agents-rescue-node-id",
    [string]$ChargifyApiKeySecret = "nova-agents-chargify-api-key",
    [string]$ChargifyBaseUrlSecret = "nova-agents-chargify-base-url",
    [string]$GoogleClientIdSecret = "nova-command-center-google-client-id",
    [string]$GoogleClientSecretSecret = "nova-command-center-google-client-secret",
    [string]$GoogleAllowedEmailsSecret = "nova-command-center-google-allowed-emails",
    [string]$RelayRepository = "dariusmakesstuff/codex-slack-bridge",
    [string]$RelayBranch = "reasoning-relay-bus",
    [string[]]$AllowedUserEmail,
    [switch]$OAuthRedirectConfigured,
    [switch]$Apply
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path

function Resolve-Gcloud {
    $command = Get-Command gcloud.cmd -ErrorAction SilentlyContinue
    if (-not $command) { $command = Get-Command gcloud -ErrorAction SilentlyContinue }
    if (-not $command) { throw "Google Cloud CLI was not found." }
    return $command.Source
}

function Invoke-Gcloud {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    & $script:Gcloud @Arguments "--billing-project=$ProjectId"
    if ($LASTEXITCODE -ne 0) {
        throw "gcloud command failed with exit code $LASTEXITCODE."
    }
}

function Test-GcloudResource {
    param([Parameter(Mandatory = $true)][scriptblock]$Command)
    $previous = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        & $Command *> $null
        return $LASTEXITCODE -eq 0
    }
    finally { $ErrorActionPreference = $previous }
}

function Test-Secret {
    param([string]$SecretName)
    return Test-GcloudResource { & $script:Gcloud secrets describe $SecretName "--project=$ProjectId" "--billing-project=$ProjectId" }
}

if (-not $AllowedUserEmail -or $AllowedUserEmail.Count -eq 0) {
    throw "At least one exact -AllowedUserEmail is required."
}
if (-not $OAuthRedirectConfigured) {
    throw "Refusing deployment until the exact Google OAuth callback is registered."
}

$script:Gcloud = Resolve-Gcloud
$commit = (& git -C $repoRoot rev-parse --verify HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $commit -notmatch '^[0-9a-f]{40}$') {
    throw "Could not resolve the deployment commit."
}
$dirty = & git -C $repoRoot status --porcelain
if ($LASTEXITCODE -ne 0 -or $dirty) {
    throw "Refusing to deploy an uncommitted worktree. Commit the migration first."
}

$shortCommit = $commit.Substring(0, 12)
$image = "$Region-docker.pkg.dev/$ProjectId/$Repository/chatgpt-relay:$shortCommit"
$serviceAccount = "$ServiceAccountName@$ProjectId.iam.gserviceaccount.com"
$publicOrigin = "https://$Service-3qcpmfwo7a-uc.a.run.app"
$redirectUri = "$publicOrigin/auth/google/callback"

Write-Host "Cloud Run ChatGPT relay deployment (smoke test sizing)"
Write-Host "Service: $Service"
Write-Host "Pinned commit: $commit"
Write-Host "URL: $publicOrigin"
Write-Host "OAuth callback: $redirectUri"
Write-Host "Relay: $RelayRepository @ $RelayBranch"
Write-Host "No Cloud SQL. No Slack Socket Mode. min=0 max=1 cpu=1 memory=1Gi."

$requiredSecrets = @(
    $GithubAppIdSecret,
    $GithubAppInstallationIdSecret,
    $GithubAppPrivateKeySecret,
    $OperatorSigningKeySecret,
    $SalesforceClientIdSecret,
    $SalesforceClientSecretSecret,
    $SalesforceLoginUrlSecret,
    $SalesforceInstanceUrlSecret,
    $RescueUserSecret,
    $RescuePasswordSecret,
    $RescueBaseSecret,
    $RescueNodeIdSecret,
    $ChargifyApiKeySecret,
    $ChargifyBaseUrlSecret,
    $GoogleClientIdSecret,
    $GoogleClientSecretSecret,
    $GoogleAllowedEmailsSecret,
    "codex-cli-oauth"
)
foreach ($secret in $requiredSecrets) {
    if (-not (Test-Secret $secret)) {
        throw "Required Secret Manager secret was not found: $secret"
    }
}

if (-not $Apply) {
    Write-Host "PLAN ONLY: no cloud resources were changed."
    exit 0
}

& $script:Gcloud services enable run.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com secretmanager.googleapis.com iap.googleapis.com --project=$ProjectId --quiet
if ($LASTEXITCODE -ne 0) { throw "Could not enable required Google Cloud APIs." }

if (-not (Test-GcloudResource { & $script:Gcloud artifacts repositories describe $Repository "--project=$ProjectId" "--location=$Region" })) {
    Invoke-Gcloud artifacts repositories create $Repository "--project=$ProjectId" "--location=$Region" "--repository-format=docker" "--description=Nova Cloud Run images" --quiet
}
if (-not (Test-GcloudResource { & $script:Gcloud iam service-accounts describe $serviceAccount "--project=$ProjectId" })) {
    Invoke-Gcloud iam service-accounts create $ServiceAccountName "--project=$ProjectId" "--display-name=Nova Cloud Run native runtime"
}
foreach ($secret in $requiredSecrets) {
    Invoke-Gcloud secrets add-iam-policy-binding $secret "--project=$ProjectId" "--member=serviceAccount:$serviceAccount" "--role=roles/secretmanager.secretAccessor" "--condition=None" --quiet
}

Invoke-Gcloud builds submit $repoRoot "--project=$ProjectId" "--region=$Region" "--config=$repoRoot\deploy\gcp\cloudbuild-cloud-run-chatgpt.yaml" "--substitutions=_IMAGE=$image" --quiet

$envVars = @(
    "BRIDGE_CONFIG=/app/config/agents.cloud-run-chatgpt.yaml",
    "COMMAND_CENTER_HOST=0.0.0.0",
    "COMMAND_CENTER_PORT=8080",
    "COMMAND_CENTER_DISABLE_WATCHERS=1",
    "COMMAND_CENTER_GOOGLE_AUTH_ENABLED=1",
    "COMMAND_CENTER_URL=http://127.0.0.1:8080",
    "COMMAND_CENTER_PUBLIC_ORIGIN=$publicOrigin",
    "GOOGLE_REDIRECT_URI=$redirectUri",
    "NOVA_AGENT_RUNTIME_MODE=primary",
    "NOVA_COMMAND_CENTER_STARTUP_GRACE_SECONDS=15",
    "SLACK_SOCKET_MODE_ENABLED=0",
    "REASONING_RELAY_ENABLED=1",
    "REASONING_RELAY_REQUIRED=0",
    "REASONING_RELAY_REPOSITORY=$RelayRepository",
    "REASONING_RELAY_BRANCH=$RelayBranch",
    "REASONING_RELAY_POLL_SECONDS=2",
    "REASONING_RELAY_RESPONSE_TIMEOUT_SECONDS=900",
    "REASONING_RELAY_JOB_TIMEOUT_SECONDS=3600",
    "REASONING_RELAY_MAX_ROUNDS=20",
    "REASONING_RELAY_BROKER_COMMAND=/usr/local/bin/python -m codex_slack_bridge.reasoning_relay_broker",
    "GITHUB_ALLOWED_REPOSITORIES=$RelayRepository",
    "GITHUB_APP_ID_PATH=/run/nova-secrets/github-app-id/value",
    "GITHUB_APP_INSTALLATION_ID_PATH=/run/nova-secrets/github-app-installation-id/value",
    "GITHUB_APP_PRIVATE_KEY_PATH=/run/nova-secrets/github-app-private-key/value",
    "SALESFORCE_USE_CLIENT_CREDENTIALS=1",
    "CODEX_HOME=/home/nova/.codex",
    "FIRESTORE_ENABLED=1",
    "FIRESTORE_PROJECT_ID=$ProjectId",
    "COMMAND_CENTER_TRUSTED_BEARER_PATH=/run/nova-relay-secrets/command-center-upstream-token"
) -join ","

$secrets = @(
    "/run/nova-secrets/github-app-id/value=${GithubAppIdSecret}:latest",
    "/run/nova-secrets/github-app-installation-id/value=${GithubAppInstallationIdSecret}:latest",
    "/run/nova-secrets/github-app-private-key/value=${GithubAppPrivateKeySecret}:latest",
    "/run/secrets/operator-message-signing-key=${OperatorSigningKeySecret}:latest",
    "SALESFORCE_CLIENT_ID=${SalesforceClientIdSecret}:latest",
    "SALESFORCE_CLIENT_SECRET=${SalesforceClientSecretSecret}:latest",
    "SALESFORCE_LOGIN_URL=${SalesforceLoginUrlSecret}:latest",
    "SALESFORCE_INSTANCE_URL=${SalesforceInstanceUrlSecret}:latest",
    "RESCUE_USER=${RescueUserSecret}:latest",
    "RESCUE_PASS=${RescuePasswordSecret}:latest",
    "RESCUE_BASE=${RescueBaseSecret}:latest",
    "RESCUE_GROUP_NODE_ID=${RescueNodeIdSecret}:latest",
    "CHARGIFY_API_KEY=${ChargifyApiKeySecret}:latest",
    "CHARGIFY_BASE_URL=${ChargifyBaseUrlSecret}:latest",
    "GOOGLE_CLIENT_ID=${GoogleClientIdSecret}:latest",
    "GOOGLE_CLIENT_SECRET=${GoogleClientSecretSecret}:latest",
    "GOOGLE_OAUTH_ALLOWED_EMAILS=${GoogleAllowedEmailsSecret}:latest",
    "CODEX_CLI_OAUTH=codex-cli-oauth:latest",
    "/run/nova-relay-secrets/command-center-upstream-token=nova-command-center-upstream-token:4"
) -join ","

Invoke-Gcloud run deploy $Service `
    "--project=$ProjectId" `
    "--region=$Region" `
    "--image=$image" `
    "--service-account=$serviceAccount" `
    --no-allow-unauthenticated `
    --iap `
    "--ingress=all" `
    "--port=8080" `
    "--concurrency=8" `
    "--min-instances=0" `
    "--max-instances=1" `
    "--cpu=1" `
    "--memory=1Gi" `
    "--timeout=3600" `
    "--execution-environment=gen2" `
    --cpu-throttling `
    --clear-cloudsql-instances `
    "--set-env-vars=$envVars" `
    "--set-secrets=$secrets" `
    "--labels=application=nova-command-center,environment=cloud-run-chatgpt-relay,commit=$shortCommit" `
    --quiet
Invoke-Gcloud run services update-traffic $Service "--project=$ProjectId" "--region=$Region" --to-latest --quiet

$iapServiceAgent = "service-63366976264@gcp-sa-iap.iam.gserviceaccount.com"
Invoke-Gcloud run services add-iam-policy-binding $Service "--project=$ProjectId" "--region=$Region" "--member=serviceAccount:$iapServiceAgent" "--role=roles/run.invoker" --quiet
foreach ($email in @($AllowedUserEmail | ForEach-Object { $_.Trim().ToLowerInvariant() } | Sort-Object -Unique)) {
    Invoke-Gcloud iap web add-iam-policy-binding "--project=$ProjectId" "--region=$Region" "--resource-type=cloud-run" "--service=$Service" "--member=user:$email" "--role=roles/iap.httpsResourceAccessor" --quiet
}

Write-Host "Deployment complete. No Cloud SQL, no Slack Socket Mode. Verify /health and relay smoke test before granting write-capable scopes."
