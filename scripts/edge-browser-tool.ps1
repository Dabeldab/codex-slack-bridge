# AgentChat/coding_agent 2026-07-08T18:30:00Z: wrapper for Edge CDP browser control.
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Args
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$SrcPath = Join-Path $RepoRoot "src"
$PackagesPath = Join-Path $RepoRoot ".packages"
$ExistingPythonPath = [Environment]::GetEnvironmentVariable("PYTHONPATH", "Process")
$parts = @($PackagesPath, $SrcPath)
if (-not [string]::IsNullOrWhiteSpace($ExistingPythonPath)) {
    $parts += $ExistingPythonPath
}
$env:PYTHONPATH = ($parts -join ";")

& py -3 -m codex_slack_bridge.edge_browser_tool @Args
exit $LASTEXITCODE
