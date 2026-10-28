param(
  [switch]$Supervised,
  [int]$MaxRestarts = 0,
  [int]$RestartDelaySeconds = 5
)

# AgentChat/direct_codex 2026-07-13T00:16:00-04:00: keep the launcher alive for Task Scheduler supervision.
# AgentChat/coding_agent 2026-07-13T00:55:00-04:00: adopt an existing bridge process when supervision starts late.

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

New-Item -ItemType Directory -Force logs | Out-Null

$stdout = Join-Path $root "logs\bridge.out.log"
$stderr = Join-Path $root "logs\bridge.err.log"
$RestartAttempts = 0
while ($true) {
  try {
    $existing = Get-CimInstance Win32_Process |
      Where-Object {
        $_.Name -in @("py.exe", "python.exe", "python3.exe") -and
        $_.CommandLine -like "*codex_slack_bridge.app*"
      }

    if ($existing) {
      if (-not $Supervised) {
        $existing | ForEach-Object { "Already running: PID $($_.ProcessId)" }
        exit 0
      }
      $owner = $existing | Sort-Object ProcessId | Select-Object -First 1
      $process = Get-Process -Id ([int]$owner.ProcessId) -ErrorAction Stop
      "Supervising existing Codex Slack Bridge: PID $($process.Id)"
    } else {
      # Only require the local Python environment when we actually need to launch
      # a new bridge. A supervised launcher starting late must be able to adopt an
      # already-running process even if installation files are temporarily absent.
      if (-not (Test-Path .packages)) {
        throw "Missing .packages. Run .\scripts\install.ps1 first."
      }
      $env:PYTHONPATH = ".packages;src"
      $python = (Get-Command py).Source

      $process = Start-Process `
        -FilePath $python `
        -ArgumentList "-3 -m codex_slack_bridge.app" `
        -WorkingDirectory $root `
        -WindowStyle Hidden `
        -RedirectStandardOutput $stdout `
        -RedirectStandardError $stderr `
        -PassThru

      "Started Codex Slack Bridge: PID $($process.Id)"
      "stdout: $stdout"
      "stderr: $stderr"
      if (-not $Supervised) {
        exit 0
      }
    }

    $process.WaitForExit()
    $process.Refresh()
    $exitCode = if ($null -ne $process.ExitCode) { [int]$process.ExitCode } else { 1 }
    Write-Warning "Codex Slack Bridge exited with code $exitCode; the supervised launcher will restart it."
  } catch {
    $exitCode = 1
    if (-not $Supervised) {
      throw
    }
    Write-Warning "Codex Slack Bridge launch failed: $($_.Exception.Message)"
  }

  $RestartAttempts += 1
  if ($MaxRestarts -gt 0 -and $RestartAttempts -ge $MaxRestarts) {
    exit $exitCode
  }
  Start-Sleep -Seconds ([Math]::Max(0, $RestartDelaySeconds))
}
