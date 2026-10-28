$ErrorActionPreference = "Stop"

Set-Location (Split-Path -Parent $PSScriptRoot)

if (-not (Test-Path .packages)) {
  throw "Missing .packages. Run .\scripts\install.ps1 first."
}

$env:PYTHONPATH = ".packages;src"
py -3 -m codex_slack_bridge.app
