param(
  [string]$Source = "knowledge_sources",
  [string]$Agent = "global",
  [string]$Tags = "nova,moira,oracle",
  [double]$Importance = 2.0
)

$ErrorActionPreference = "Stop"

Set-Location (Split-Path -Parent $PSScriptRoot)

if (-not (Test-Path .packages)) {
  throw "Missing .packages. Run .\scripts\install.ps1 first."
}

$env:PYTHONPATH = ".packages;src"
py -3 -m codex_slack_bridge.knowledge_ingest `
  --config config/agents.yaml `
  --source $Source `
  --agent $Agent `
  --tags $Tags `
  --importance $Importance
