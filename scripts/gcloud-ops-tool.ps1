# AgentChat/coding_agent 2026-07-09T00:00:00Z: guarded gcloud helper for Agent Chat ops lanes.
param(
    [ValidateSet("status", "activate-service-account", "run-services", "run-jobs", "describe-service", "logs")]
    [string]$Action = "status",

    [string]$Project = "",
    [string]$Region = "",
    [string]$Service = "",
    [int]$Limit = 50,
    [switch]$Json
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot

function Import-DotEnv {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        return
    }
    foreach ($line in Get-Content -LiteralPath $Path) {
        $trimmed = ([string]$line).Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#")) {
            continue
        }
        if ($trimmed -notmatch '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$') {
            continue
        }
        $name = $Matches[1]
        $value = $Matches[2].Trim()
        if (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'"))) {
            $value = $value.Substring(1, $value.Length - 2)
        }
        if (-not [Environment]::GetEnvironmentVariable($name, "Process")) {
            [Environment]::SetEnvironmentVariable($name, $value, "Process")
        }
    }
}

function Find-GCloud {
    # Prefer the Windows command shim. PowerShell may resolve gcloud.ps1 first,
    # which fails under the host's restricted execution policy.
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
    return $null
}

function Enable-GCloudCredentialFallback {
    param([string]$GCloud)

    if ($env:CLOUDSDK_AUTH_ACCESS_TOKEN) {
        return "access_token_env"
    }

    try {
        & $GCloud auth print-access-token 1>$null 2>$null
        $cliExitCode = $LASTEXITCODE
    } catch {
        $cliExitCode = if ($LASTEXITCODE -is [int]) { $LASTEXITCODE } else { 1 }
    }
    if ($cliExitCode -eq 0) {
        return "gcloud_cli"
    }

    # Drive/Workspace reauthentication maintains a valid authorized-user ADC
    # even when the separate gcloud CLI refresh token has expired. Keep the
    # short-lived token process-local; never persist or print it.
    try {
        $adcToken = (& $GCloud auth application-default print-access-token 2>$null | Select-Object -First 1)
        $adcExitCode = $LASTEXITCODE
    } catch {
        $adcToken = ""
        $adcExitCode = if ($LASTEXITCODE -is [int]) { $LASTEXITCODE } else { 1 }
    }
    # On Windows the .cmd shim can leave LASTEXITCODE from the preceding failed
    # user-token probe even after returning a valid ADC token. The non-empty
    # token is the authoritative success signal here.
    if (-not [string]::IsNullOrWhiteSpace([string]$adcToken)) {
        $env:CLOUDSDK_AUTH_ACCESS_TOKEN = [string]$adcToken
        return "application_default_credentials"
    }
    return "unavailable"
}

function Write-JsonObject {
    param([object]$Value)
    $Value | ConvertTo-Json -Depth 12
}

Import-DotEnv (Join-Path $RepoRoot "config\ops.env")
Import-DotEnv (Join-Path $RepoRoot ".env")

if (-not $Project) {
    $Project = $env:GCP_PROJECT_ID
}
if (-not $Project) {
    $Project = $env:CLOUDSDK_CORE_PROJECT
}
if (-not $Project) {
    $Project = "gen-lang-client-0051653266"
}
if (-not $Region) {
    $Region = $env:GCP_DEFAULT_REGION
}
if (-not $Region) {
    $Region = "us-central1"
}

$gcloud = Find-GCloud
if (-not $gcloud) {
    throw "gcloud was not found. Install Google Cloud SDK or add gcloud.cmd to PATH."
}
$credentialMode = if ($Action -eq "activate-service-account") {
    "configuration"
} else {
    Enable-GCloudCredentialFallback -GCloud $gcloud
}

$keyPath = $env:GOOGLE_APPLICATION_CREDENTIALS
$keyExists = $false
if ($keyPath) {
    $expandedKeyPath = [Environment]::ExpandEnvironmentVariables($keyPath)
    $keyExists = Test-Path -LiteralPath $expandedKeyPath
}

if ($Action -eq "status") {
    $activeProject = (& $gcloud config get-value project 2>$null)
    $accounts = (& $gcloud auth list --filter=status:ACTIVE '--format=value(account)' 2>$null)
    $value = [PSCustomObject]@{
        ok = $true
        gcloud = $gcloud
        project = $Project
        configured_project = ($activeProject | Select-Object -First 1)
        region = $Region
        active_accounts = @($accounts)
        auth_ready = $credentialMode -ne "unavailable"
        credential_mode = $credentialMode
        service_account_key_configured = -not [string]::IsNullOrWhiteSpace($keyPath)
        service_account_key_present = $keyExists
        service_account_key_path = if ($keyPath) { "[configured path hidden]" } else { "" }
        next_step = if ($keyPath -and $keyExists) { "Run activate-service-account if gcloud is not using the desired account." } else { "Set GOOGLE_APPLICATION_CREDENTIALS in config/ops.env to a local service-account key path, or use gcloud auth login." }
    }
    if ($Json) { Write-JsonObject $value } else { $value | Format-List }
    exit 0
}

if ($credentialMode -eq "unavailable") {
    throw "No usable gcloud CLI or Application Default Credentials token is available. Reauthenticate before retrying."
}

if ($Action -eq "activate-service-account") {
    if (-not $keyPath -or -not $keyExists) {
        throw "GOOGLE_APPLICATION_CREDENTIALS is not set to an existing local key file. Store the key outside the repo and set only the path in config/ops.env."
    }
    & $gcloud auth activate-service-account "--key-file=$expandedKeyPath"
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & $gcloud config set project $Project
    exit $LASTEXITCODE
}

if ($Action -eq "run-services") {
    & $gcloud run services list "--project=$Project" "--region=$Region" '--format=table(name,region,url)'
    exit $LASTEXITCODE
}

if ($Action -eq "run-jobs") {
    & $gcloud run jobs list "--project=$Project" "--region=$Region" '--format=table(name,region)'
    exit $LASTEXITCODE
}

if ($Action -eq "describe-service") {
    if (-not $Service) {
        throw "describe-service requires -Service."
    }
    $format = if ($Json) { "json" } else { "yaml" }
    & $gcloud run services describe $Service "--project=$Project" "--region=$Region" "--format=$format"
    exit $LASTEXITCODE
}

if ($Action -eq "logs") {
    if (-not $Service) {
        throw "logs requires -Service."
    }
    $query = "resource.type=""cloud_run_revision"" AND resource.labels.service_name=""$Service"""
    $format = if ($Json) { "json" } else { "table(timestamp,severity,textPayload)" }
    & $gcloud logging read $query "--project=$Project" "--limit=$Limit" "--freshness=1h" "--format=$format"
    exit $LASTEXITCODE
}
