$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$processes = Get-CimInstance Win32_Process |
  Where-Object {
    $_.Name -in @("py.exe", "python.exe", "python3.exe") -and
    $_.CommandLine -like "*codex_slack_bridge.app*"
  }

if (-not $processes) {
  "Codex Slack Bridge is not running."
  exit 0
}

$processes | ForEach-Object {
  "Running: PID $($_.ProcessId)"
}

$stdout = Join-Path $root "logs\bridge.out.log"
$stderr = Join-Path $root "logs\bridge.err.log"

if (Test-Path $stdout) {
  "Last stdout lines:"
  Get-Content $stdout -Tail 10
}

if (Test-Path $stderr) {
  "Last stderr lines:"
  Get-Content $stderr -Tail 10
}
