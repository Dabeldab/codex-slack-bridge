# AgentChat/coding_agent 2026-07-08T16:12:51Z: wrapper for the read-only Google Drive agent tool.
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Args
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$SrcPath = Join-Path $RepoRoot "src"
$ExistingPythonPath = [Environment]::GetEnvironmentVariable("PYTHONPATH", "Process")
if ([string]::IsNullOrWhiteSpace($ExistingPythonPath)) {
    $env:PYTHONPATH = $SrcPath
} else {
    $env:PYTHONPATH = "$SrcPath;$ExistingPythonPath"
}

& py -3 -m codex_slack_bridge.google_drive_tool @Args
exit $LASTEXITCODE
