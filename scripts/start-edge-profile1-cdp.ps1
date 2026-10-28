# AgentChat/coding_agent 2026-07-09T11:45:00-04:00: non-disruptive Edge Profile 1 CDP launcher.
param(
    [string]$Url = "https://novapointofsale.zoom.us/ai-studio/virtual-agent",
    [int]$Port = 9223,
    [switch]$ForceRestart,
    [switch]$ConfirmCloseBrowser,
    [switch]$Doctor
)

$ErrorActionPreference = "Stop"
$Tool = Join-Path $PSScriptRoot "edge-browser-tool.ps1"

$baseArgs = @(
    "--port", [string]$Port,
    "--profile-mode", "main",
    "--profile-display-name", "Profile 1"
)

if ($Doctor) {
    & powershell -ExecutionPolicy Bypass -File $Tool @baseArgs doctor
    exit $LASTEXITCODE
}

$startArgs = @($baseArgs + @("start", "--url", $Url))
if ($ForceRestart) {
    $startArgs += "--force-restart"
    if ($ConfirmCloseBrowser) {
        $startArgs += "--confirm-close-browser"
    }
}

& powershell -ExecutionPolicy Bypass -File $Tool @startArgs
exit $LASTEXITCODE
