param(
  [string]$Source = "knowledge_sources\zoom_kb",
  [string]$Memory = "data\desktop_chat\memory_vectors.json",
  [string]$Agent = "global",
  [string]$Collection = "zoom_kb",
  [string]$Tags = "nova,zoom,kb",
  [double]$Importance = 2.0
)

$ErrorActionPreference = "Stop"

Set-Location (Split-Path -Parent $PSScriptRoot)

if (-not (Test-Path .packages)) {
  throw "Missing .packages. Run .\scripts\install.ps1 first."
}

$env:PYTHONPATH = ".packages;src"
py -3 -m codex_slack_bridge.desktop_knowledge_ingest `
  --source $Source `
  --memory $Memory `
  --agent $Agent `
  --collection $Collection `
  --tags $Tags `
  --importance $Importance
