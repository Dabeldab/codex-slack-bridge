$ErrorActionPreference = "Stop"

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
  Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
  "Stopped: PID $($_.ProcessId)"
}
