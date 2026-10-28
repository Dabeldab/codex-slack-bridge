param(
  [string]$Output = "knowledge_sources\zoom_kb",
  [string]$Memory = "data\desktop_chat\memory_vectors.json",
  [string]$Agent = "global",
  [string]$Collection = "zoom_kb",
  [string]$Tags = "nova,zoom,kb",
  [double]$Importance = 2.0,
  [switch]$IncludeSamples
)

$ErrorActionPreference = "Stop"

Set-Location (Split-Path -Parent $PSScriptRoot)

if (-not (Test-Path .packages)) {
  throw "Missing .packages. Run .\scripts\install.ps1 first."
}

$env:PYTHONPATH = ".packages;src"
$argsList = @(
  "-3", "-m", "codex_slack_bridge.zoom_kb_sync",
  "--output", $Output,
  "--memory", $Memory,
  "--agent", $Agent,
  "--collection", $Collection,
  "--tags", $Tags,
  "--importance", $Importance
)

if ($IncludeSamples) {
  $argsList += "--include-samples"
}

py @argsList
