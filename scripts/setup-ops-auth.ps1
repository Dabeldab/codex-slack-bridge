$ErrorActionPreference = "Continue"

$root = Split-Path -Parent $PSScriptRoot
$opsEnv = Join-Path $root "config\ops.env"

function Find-Tool {
    param([string]$Name, [string[]]$Candidates)
    if (Get-Command $Name -ErrorAction SilentlyContinue) {
        return $Name
    }
    foreach ($path in $Candidates) {
        if (Test-Path $path) {
            return $path
        }
    }
    return $null
}

$gcloud = Find-Tool "gcloud" @(
    "$env:LOCALAPPDATA\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd",
    "$env:ProgramFiles\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd",
    "${env:ProgramFiles(x86)}\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd"
)
$gh = Find-Tool "gh" @(
    "$env:ProgramFiles\GitHub CLI\gh.exe",
    "$env:LOCALAPPDATA\Programs\GitHub CLI\gh.exe"
)

Write-Host ""
Write-Host "=== Codex Slack Bridge - ops auth setup (read-only) ===" -ForegroundColor Cyan
Write-Host "Bridge root: $root"
Write-Host ""

Write-Host "--- GitHub (gh) ---" -ForegroundColor Yellow
if (-not $gh) {
    Write-Host "gh not found. Install: winget install GitHub.cli" -ForegroundColor Red
    Write-Host "  Or: https://cli.github.com/"
} else {
    Write-Host "Found: $gh"
    & $gh auth status
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Run: gh auth login" -ForegroundColor DarkYellow
    }
}
Write-Host "Codex GitHub plugin: enable github@openai-curated in %USERPROFILE%\.codex\config.toml"
Write-Host "Optional token file: copy config\ops.env.example -> config\ops.env and set GITHUB_TOKEN"
Write-Host ""

Write-Host "--- Google Cloud (gcloud) ---" -ForegroundColor Yellow
if (-not $gcloud) {
    Write-Host "gcloud not found. Install: https://cloud.google.com/sdk/docs/install" -ForegroundColor Red
} else {
    Write-Host "Found: $gcloud"
    $project = & $gcloud config get-value project 2>&1
    Write-Host "Active project: $project"
    & $gcloud auth list --filter=status:ACTIVE '--format=table(account,status)' 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Run: gcloud auth login" -ForegroundColor DarkYellow
        Write-Host "Run: gcloud auth application-default login" -ForegroundColor DarkYellow
    }
    Write-Host ""
    Write-Host "Suggested project (from local repo config): gen-lang-client-0051653266"
    Write-Host "Run: gcloud config set project gen-lang-client-0051653266"
    Write-Host ""
    Write-Host "Cloud Run services (if authenticated):"
    & $gcloud run services list --project=gen-lang-client-0051653266 '--format=table(name,region)' 2>&1
}
Write-Host ""
Write-Host "Agent Chat gcloud helper:" -ForegroundColor DarkYellow
Write-Host "  powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\gcloud-ops-tool.ps1 -Action status"
Write-Host "  powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\gcloud-ops-tool.ps1 -Action activate-service-account"
Write-Host "  powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\gcloud-ops-tool.ps1 -Action run-services -Region us-central1"
Write-Host "  powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\gcloud-ops-tool.ps1 -Action logs -Service logmein-connector -Region us-central1"
Write-Host ""

Write-Host "--- Local env files ---" -ForegroundColor Yellow
if (-not (Test-Path $opsEnv)) {
    Write-Host "No config\ops.env yet. Copy the example:" -ForegroundColor DarkYellow
    Write-Host "  Copy-Item config\ops.env.example config\ops.env"
} else {
    Write-Host "config\ops.env exists (values not shown)."
}
if (Test-Path (Join-Path $root ".env")) {
    Write-Host "Bridge .env exists (values not shown)."
}
Write-Host "Agent Chat passes config\ops.env and .env into codex child processes."
Write-Host ""

Write-Host "--- Suggested read-only IAM for an ops service account ---" -ForegroundColor Yellow
@(
    "roles/logging.viewer",
    "roles/monitoring.viewer",
    "roles/run.viewer",
    "roles/cloudsql.viewer",
    "roles/artifactregistry.reader",
    "roles/secretmanager.viewer"
) | ForEach-Object { Write-Host "  $_" }
Write-Host ""
Write-Host "For controlled Cloud Run env/deploy changes (only when explicitly authorized):"
Write-Host "  roles/run.developer (scope to specific services)"
Write-Host ""
Write-Host "Do not commit service account keys or tokens. Set GOOGLE_APPLICATION_CREDENTIALS"
Write-Host "in config\ops.env only on this machine. Keep the JSON key outside this repo,"
Write-Host "for example under %LOCALAPPDATA%\CodexBillingAgent\gcloud\."
Write-Host ""
Write-Host "=== Test in Agent Chat ===" -ForegroundColor Cyan
Write-Host "1. Rebuild Agent Chat if you changed MainWindow.xaml.cs:"
Write-Host "     .\scripts\build-agent-chat.ps1"
Write-Host "2. Open coding_agent and ask (read-only), for example:"
Write-Host "     Check Cloud Run health for logmein-connector in us-central1"
Write-Host "     List recent failed GitHub Actions for dariusmakesstuff/logmein-connector"
Write-Host "3. Enable Subagents if you want the cloud-status helper."
