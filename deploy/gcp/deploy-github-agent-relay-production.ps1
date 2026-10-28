[CmdletBinding()]
param([switch]$Apply)

$ErrorActionPreference = "Stop"
$baseScript = Join-Path $PSScriptRoot "deploy-github-agent-relay.ps1"
if (-not $Apply) {
    & $baseScript
    Write-Host "PLAN: production wrapper also sets Cloud Run request timeout to 1900 seconds after deployment."
    exit $LASTEXITCODE
}

& $baseScript -Apply
if ($LASTEXITCODE -ne 0) { throw "Base relay deployment failed." }

gcloud run services update nova-github-agent-relay `
    --project=gen-lang-client-0051653266 `
    --region=us-central1 `
    --timeout=1900 `
    --billing-project=gen-lang-client-0051653266 `
    --quiet
if ($LASTEXITCODE -ne 0) { throw "Could not extend relay request timeout." }

$timeout = gcloud run services describe nova-github-agent-relay `
    --project=gen-lang-client-0051653266 `
    --region=us-central1 `
    --billing-project=gen-lang-client-0051653266 `
    --format='value(spec.template.spec.timeoutSeconds)'
if ($LASTEXITCODE -ne 0 -or [int]$timeout -lt 1900) {
    throw "SECURITY/RELIABILITY READBACK FAILED: relay timeout was not applied."
}
Write-Host "Relay production timeout verified: $timeout seconds."
