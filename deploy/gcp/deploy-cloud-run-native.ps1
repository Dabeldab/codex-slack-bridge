[CmdletBinding()]
param(
    [string]$ProjectId = "gen-lang-client-0051653266",
    [string]$Region = "us-central1",
    [string]$Service = "nova-command-center-shadow",
    [string]$Repository = "nova-agent-shadow",
    [string]$ServiceAccountName = "nova-command-center-shadow",
    [string]$CloudSqlInstance,
    [string]$CloudSqlDatabase = "nova",
    [string]$CloudSqlUser = "nova",
    [string]$CloudSqlPasswordSecret = "nova-agents-cloudsql-password",
    [string]$SlackBotTokenSecret = "nova-agents-slack-bot-token",
    [string]$SlackAppTokenSecret = "nova-agents-slack-app-token",
    [string]$GoogleClientIdSecret = "nova-command-center-google-client-id",
    [string]$GoogleClientSecretSecret = "nova-command-center-google-client-secret",
    [string]$GoogleAllowedEmailsSecret = "nova-command-center-google-allowed-emails",
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

if (-not $CloudSqlInstance) {
    throw "CloudSqlInstance is required. Pass the existing LogMeIn Cloud SQL instance connection name (project:region:instance)."
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
$image = "$Region-docker.pkg.dev/$ProjectId/$Repository/cloud-native:$shortCommit"
$serviceAccount = "$ServiceAccountName@$ProjectId.iam.gserviceaccount.com"
$publicOrigin = "https://$Service-63366976264.$Region.run.app"
$redirectUri = "$publicOrigin/auth/google/callback"

Write-Host "Cloud Run native deployment"
Write-Host "Service: $Service"
Write-Host "Pinned commit: $commit"
Write-Host "Cloud SQL: $CloudSqlInstance / $CloudSqlDatabase / $CloudSqlUser"
Write-Host "URL: $publicOrigin"
Write-Host "OAuth callback: $redirectUri"
Write-Host "Architecture: one Cloud Run service; no VM gateway"

$requiredSecrets = @(
    $CloudSqlPasswordSecret,
    $SlackBotTokenSecret,
    $SlackAppTokenSecret,
    $GoogleClientIdSecret,
    $GoogleClientSecretSecret,
    $GoogleAllowedEmailsSecret
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

& $script:Gcloud services enable run.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com secretmanager.googleapis.com sqladmin.googleapis.com iap.googleapis.com --project=$ProjectId --quiet
if ($LASTEXITCODE -ne 0) { throw "Could not enable required Google Cloud APIs." }

if (-not (Test-GcloudResource { & $script:Gcloud artifacts repositories describe $Repository "--project=$ProjectId" "--location=$Region" })) {
    Invoke-Gcloud artifacts repositories create $Repository "--project=$ProjectId" "--location=$Region" "--repository-format=docker" "--description=Nova Cloud Run images" --quiet
}
if (-not (Test-GcloudResource { & $script:Gcloud iam service-accounts describe $serviceAccount "--project=$ProjectId" })) {
    Invoke-Gcloud iam service-accounts create $ServiceAccountName "--project=$ProjectId" "--display-name=Nova Cloud Run native runtime"
}
Invoke-Gcloud projects add-iam-policy-binding $ProjectId "--member=serviceAccount:$serviceAccount" "--role=roles/cloudsql.client" --quiet
foreach ($secret in $requiredSecrets) {
    Invoke-Gcloud secrets add-iam-policy-binding $secret "--project=$ProjectId" "--member=serviceAccount:$serviceAccount" "--role=roles/secretmanager.secretAccessor" --quiet
}

Invoke-Gcloud builds submit $repoRoot "--project=$ProjectId" "--region=$Region" "--config=$repoRoot\deploy\gcp\cloudbuild-cloud-native.yaml" "--substitutions=_IMAGE=$image" --quiet

$envVars = @(
    "BRIDGE_CONFIG=/app/config/agents.cloud-native.yaml",
    "COMMAND_CENTER_HOST=0.0.0.0",
    "COMMAND_CENTER_PORT=8080",
    "COMMAND_CENTER_DISABLE_WATCHERS=0",
    "COMMAND_CENTER_GOOGLE_AUTH_ENABLED=1",
    "COMMAND_CENTER_URL=http://127.0.0.1:8080",
    "NOVA_AGENT_RUNTIME_MODE=cloud_run",
    "NOVA_DATABASE_BACKEND=cloudsql",
    "NOVA_DB_SOCKET=/cloudsql/$CloudSqlInstance",
    "NOVA_DB_NAME=$CloudSqlDatabase",
    "NOVA_DB_USER=$CloudSqlUser",
    "NOVA_DB_CONNECT_TIMEOUT_SECONDS=10",
    "COMMAND_CENTER_UPSTREAM_URL=",
    "COMMAND_CENTER_UPSTREAM_TOKEN_PATH=",
    "COMMAND_CENTER_UPSTREAM_TIMEOUT_SECONDS=0",
    "NOVA_COMMAND_CENTER_STARTUP_GRACE_SECONDS=15"
) -join ","

$secrets = @(
    "NOVA_DB_PASSWORD=$CloudSqlPasswordSecret:latest",
    "SLACK_BOT_TOKEN=$SlackBotTokenSecret:latest",
    "SLACK_APP_TOKEN=$SlackAppTokenSecret:latest",
    "GOOGLE_CLIENT_ID=$GoogleClientIdSecret:latest",
    "GOOGLE_CLIENT_SECRET=$GoogleClientSecretSecret:latest",
    "GOOGLE_OAUTH_ALLOWED_EMAILS=$GoogleAllowedEmailsSecret:latest"
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
    "--concurrency=16" `
    "--min=1" `
    "--max=1" `
    "--cpu=2" `
    "--memory=2Gi" `
    "--timeout=300" `
    "--execution-environment=gen2" `
    --no-cpu-throttling `
    "--add-cloudsql-instances=$CloudSqlInstance" `
    "--set-env-vars=$envVars" `
    "--set-secrets=$secrets" `
    "--labels=application=nova-command-center,environment=cloud-run-native,commit=$shortCommit" `
    --quiet
Invoke-Gcloud run services update-traffic $Service "--project=$ProjectId" "--region=$Region" --to-latest --quiet

$iapServiceAgent = "service-63366976264@gcp-sa-iap.iam.gserviceaccount.com"
Invoke-Gcloud run services add-iam-policy-binding $Service "--project=$ProjectId" "--region=$Region" "--member=serviceAccount:$iapServiceAgent" "--role=roles/run.invoker" --quiet
foreach ($email in @($AllowedUserEmail | ForEach-Object { $_.Trim().ToLowerInvariant() } | Sort-Object -Unique)) {
    Invoke-Gcloud iap web add-iam-policy-binding "--project=$ProjectId" "--region=$Region" "--resource-type=cloud-run" "--service=$Service" "--member=user:$email" "--role=roles/iap.httpsResourceAccessor" --quiet
}

Write-Host "Deployment complete. Verify /health, Slack Socket Mode readiness, and Cloud SQL-backed job state before removing the old VM resources."
