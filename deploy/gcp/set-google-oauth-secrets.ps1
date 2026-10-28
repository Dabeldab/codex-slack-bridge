[CmdletBinding()]
param(
    [string]$ProjectId = "gen-lang-client-0051653266",
    [string]$ClientIdSecret = "nova-command-center-google-client-id",
    [string]$ClientSecretSecret = "nova-command-center-google-client-secret",
    [string]$AllowedEmailsSecret = "nova-command-center-google-allowed-emails",
    [switch]$Apply
)

$ErrorActionPreference = "Stop"

function Resolve-Gcloud {
    $command = Get-Command gcloud.cmd -ErrorAction SilentlyContinue
    if (-not $command) {
        $command = Get-Command gcloud -ErrorAction SilentlyContinue
    }
    if (-not $command) {
        throw "Google Cloud CLI was not found."
    }
    return $command.Source
}

function Invoke-Gcloud {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    & $script:Gcloud @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "gcloud command failed with exit code $LASTEXITCODE."
    }
}

function Add-SecretVersion {
    param(
        [Parameter(Mandatory = $true)][string]$SecretName,
        [Parameter(Mandatory = $true)][string]$Value
    )

    # Windows PowerShell can promote native stderr to a terminating error when
    # ErrorActionPreference is Stop, even though a missing secret is the normal
    # first-run condition for this probe. Capture the exit code explicitly.
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $exists = & $script:Gcloud secrets describe $SecretName "--project=$ProjectId" "--format=value(name)" 2>$null
        $describeExitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    if ($describeExitCode -ne 0) {
        Invoke-Gcloud secrets create $SecretName "--project=$ProjectId" "--replication-policy=automatic" "--labels=application=nova-command-center,environment=shadow"
    }

    $temporary = [System.IO.Path]::GetTempFileName()
    try {
        if ($IsWindows -or $env:OS -eq "Windows_NT") {
            $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
            & icacls.exe $temporary /inheritance:r /grant:r "${identity}:(F)" "*S-1-5-18:(F)" | Out-Null
            if ($LASTEXITCODE -ne 0) {
                throw "Could not restrict the temporary secret file ACL."
            }
        }
        [System.IO.File]::WriteAllText(
            $temporary,
            $Value,
            [System.Text.UTF8Encoding]::new($false)
        )
        Invoke-Gcloud secrets versions add $SecretName "--project=$ProjectId" "--data-file=$temporary"
    }
    finally {
        if (Test-Path -LiteralPath $temporary) {
            Remove-Item -LiteralPath $temporary -Force
        }
    }
}

$clientId = [Environment]::GetEnvironmentVariable("GOOGLE_CLIENT_ID")
$clientSecret = [Environment]::GetEnvironmentVariable("GOOGLE_CLIENT_SECRET")
$allowedEmails = [Environment]::GetEnvironmentVariable("GOOGLE_OAUTH_ALLOWED_EMAILS")

$missing = @()
if ([string]::IsNullOrWhiteSpace($clientId)) { $missing += "GOOGLE_CLIENT_ID" }
if ([string]::IsNullOrWhiteSpace($clientSecret)) { $missing += "GOOGLE_CLIENT_SECRET" }
if ([string]::IsNullOrWhiteSpace($allowedEmails)) { $missing += "GOOGLE_OAUTH_ALLOWED_EMAILS" }
if ($missing.Count -gt 0) {
    throw "Set these process environment variables before running this script: $($missing -join ', '). Values are never printed."
}
if (-not $clientId.Trim().EndsWith(".apps.googleusercontent.com")) {
    throw "GOOGLE_CLIENT_ID is not a Google web application client ID."
}
$emails = @($allowedEmails.Split(",") | ForEach-Object { $_.Trim().ToLowerInvariant() } | Where-Object { $_ })
if ($emails.Count -eq 0 -or @($emails | Where-Object { $_ -notmatch '^[^\s@*]+@[^\s@*]+$' }).Count -gt 0) {
    throw "GOOGLE_OAUTH_ALLOWED_EMAILS must contain exact email addresses without wildcards."
}

$Gcloud = Resolve-Gcloud
if (-not $env:CLOUDSDK_AUTH_ACCESS_TOKEN) {
    $adcToken = (& $Gcloud auth application-default print-access-token --quiet 2>$null)
    if ($LASTEXITCODE -eq 0 -and $adcToken) {
        $env:CLOUDSDK_AUTH_ACCESS_TOKEN = $adcToken.Trim()
    }
}

if (-not $Apply) {
    Write-Host "PLAN ONLY: enable Secret Manager and create or version three Nova Command Center OAuth secrets."
    Write-Host "No secret values were printed and no cloud resources were changed. Re-run with -Apply after review."
    exit 0
}

Invoke-Gcloud services enable secretmanager.googleapis.com "--project=$ProjectId" --quiet
Add-SecretVersion -SecretName $ClientIdSecret -Value $clientId.Trim()
Add-SecretVersion -SecretName $ClientSecretSecret -Value $clientSecret.Trim()
Add-SecretVersion -SecretName $AllowedEmailsSecret -Value ($emails -join ",")

Write-Host "OAuth secret versions were added successfully. Values were not printed."
