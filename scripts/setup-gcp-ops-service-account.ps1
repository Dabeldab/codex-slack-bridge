# AgentChat/coding_agent 2026-07-09T00:00:00Z: create/configure a least-privilege GCP ops service account for Agent Chat.
param(
    [string]$Project = "gen-lang-client-0051653266",
    [string]$ServiceAccountId = "agent-chat-ops",
    [string]$DisplayName = "Agent Chat Ops",
    [string]$KeyPath = "$env:LOCALAPPDATA\CodexBillingAgent\gcloud\agent-chat-ops.json",
    [switch]$GrantManageRoles,
    [switch]$CreateKey,
    [switch]$WriteOpsEnv
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$OpsEnvPath = Join-Path $RepoRoot "config\ops.env"

function Find-GCloud {
    if (Get-Command "gcloud.cmd" -ErrorAction SilentlyContinue) {
        return "gcloud.cmd"
    }
    if (Get-Command "gcloud" -ErrorAction SilentlyContinue) {
        return "gcloud"
    }
    $candidates = @(
        "$env:LOCALAPPDATA\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd",
        "$env:ProgramFiles\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd",
        "${env:ProgramFiles(x86)}\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd"
    )
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) {
            return $candidate
        }
    }
    throw "gcloud was not found. Install Google Cloud SDK or add gcloud.cmd to PATH."
}

function Set-OpsEnvValue {
    param([string]$Name, [string]$Value)
    $lines = @()
    if (Test-Path -LiteralPath $OpsEnvPath) {
        $lines = @(Get-Content -LiteralPath $OpsEnvPath)
    }
    $pattern = "^\s*#?\s*$([regex]::Escape($Name))\s*="
    $replacement = "$Name=$Value"
    $updated = $false
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ([string]$lines[$i] -match $pattern) {
            $lines[$i] = $replacement
            $updated = $true
            break
        }
    }
    if (-not $updated) {
        $lines += $replacement
    }
    $parent = Split-Path -Parent $OpsEnvPath
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    Set-Content -LiteralPath $OpsEnvPath -Value $lines -Encoding UTF8
}

$gcloud = Find-GCloud
$email = "$ServiceAccountId@$Project.iam.gserviceaccount.com"

$existing = & $gcloud iam service-accounts describe $email "--project=$Project" "--format=value(email)" 2>$null
if (-not $existing) {
    Write-Host "Creating service account $email"
    & $gcloud iam service-accounts create $ServiceAccountId "--project=$Project" "--display-name=$DisplayName"
} else {
    Write-Host "Service account already exists: $email"
}

$roles = @(
    "roles/logging.viewer",
    "roles/monitoring.viewer",
    "roles/run.viewer",
    "roles/cloudsql.viewer",
    "roles/artifactregistry.reader",
    "roles/secretmanager.viewer"
)

if ($GrantManageRoles) {
    $roles += @(
        "roles/run.developer",
        "roles/cloudbuild.builds.editor",
        "roles/artifactregistry.writer",
        "roles/iam.serviceAccountUser"
    )
}

foreach ($role in $roles) {
    Write-Host "Granting $role to $email"
    & $gcloud projects add-iam-policy-binding $Project "--member=serviceAccount:$email" "--role=$role" --quiet | Out-Null
}

if ($CreateKey) {
    $resolvedKeyPath = [Environment]::ExpandEnvironmentVariables($KeyPath)
    $keyDir = Split-Path -Parent $resolvedKeyPath
    New-Item -ItemType Directory -Force -Path $keyDir | Out-Null
    if (Test-Path -LiteralPath $resolvedKeyPath) {
        throw "Key file already exists at $resolvedKeyPath. Move it or choose a different -KeyPath before creating a new key."
    }
    Write-Host "Creating service-account key at $resolvedKeyPath"
    & $gcloud iam service-accounts keys create $resolvedKeyPath "--iam-account=$email" "--project=$Project"
}

if ($WriteOpsEnv) {
    Set-OpsEnvValue -Name "GCP_PROJECT_ID" -Value $Project
    Set-OpsEnvValue -Name "GCP_DEFAULT_REGION" -Value "us-central1"
    Set-OpsEnvValue -Name "GCP_OPS_SERVICE_ACCOUNT_EMAIL" -Value $email
    Set-OpsEnvValue -Name "GOOGLE_APPLICATION_CREDENTIALS" -Value ([Environment]::ExpandEnvironmentVariables($KeyPath))
    Write-Host "Updated $OpsEnvPath with service-account path only. Secret key contents were not printed."
}

Write-Host "Done. Verify with:"
Write-Host "  powershell -ExecutionPolicy Bypass -File .\scripts\gcloud-ops-tool.ps1 -Action status"
Write-Host "  powershell -ExecutionPolicy Bypass -File .\scripts\gcloud-ops-tool.ps1 -Action activate-service-account"
