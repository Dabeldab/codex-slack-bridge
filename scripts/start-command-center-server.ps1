# AgentChat/coding_agent 2026-07-09T13:20:00-04:00: start the standalone Nova Ops command center gateway.
param(
  [switch]$Supervised,
  [int]$MaxRestarts = 0,
  [int]$RestartDelaySeconds = 5
)

# AgentChat/direct_codex 2026-07-13T00:16:00-04:00: keep the launcher alive for Task Scheduler supervision.
# AgentChat/coding_agent 2026-07-13T00:55:00-04:00: adopt an existing healthy gateway when supervision starts late.
# AgentChat/direct_codex 2026-07-16T14:36:00-04:00: reclaim only an unhealthy stale gateway tree after a task restart.

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$env:PYTHONPATH = Join-Path $Root "src"
$Port = if ($env:COMMAND_CENTER_PORT) { $env:COMMAND_CENTER_PORT } elseif ($env:AGENT_CHAT_DISPATCH_PORT) { $env:AGENT_CHAT_DISPATCH_PORT } else { "17866" }
$Config = Join-Path $Root "config\agents.yaml"
$HealthUrl = "http://127.0.0.1:$Port/health"
$SessionTokenPath = if ($env:COMMAND_CENTER_SESSION_TOKEN_PATH) {
  [Environment]::ExpandEnvironmentVariables($env:COMMAND_CENTER_SESSION_TOKEN_PATH)
} elseif ($env:LOCALAPPDATA) {
  Join-Path $env:LOCALAPPDATA "NovaOpsCommandCenter\session.token"
} else {
  Join-Path ([IO.Path]::GetTempPath()) "NovaOpsCommandCenter/session.token"
}
$LogDir = Join-Path $Root "logs\command_center"
$StdoutLog = Join-Path $LogDir "gateway-$Port.out.log"
$StderrLog = Join-Path $LogDir "gateway-$Port.err.log"

function Get-CommandCenterHeaders {
  if (-not (Test-Path -LiteralPath $SessionTokenPath -PathType Leaf)) {
    return @{}
  }
  $Token = (Get-Content -LiteralPath $SessionTokenPath -Raw -ErrorAction Stop).Trim()
  if ($Token.Length -lt 32) {
    return @{}
  }
  return @{ Authorization = "Bearer $Token" }
}

function Get-StaleCommandCenterProcesses {
  $PortPattern = "(?i)(?:^|\s)--port\s+" + [regex]::Escape([string]$Port) + "(?:\s|$)"
  return @(
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
      Where-Object {
        $_.Name -in @("py.exe", "python.exe", "python3.exe") -and
        $_.CommandLine -match "(?i)(?:^|\s)-m\s+codex_slack_bridge\.command_center_server(?:\s|$)" -and
        $_.CommandLine -match $PortPattern
      }
  )
}

function Remove-StaleCommandCenterProcesses {
  $Stale = @(Get-StaleCommandCenterProcesses)
  if (-not $Stale) {
    return
  }

  # A threaded health endpoint should answer even while workers are busy. Require
  # repeated failures before reclaiming an exact command-center process tree.
  for ($Attempt = 0; $Attempt -lt 2; $Attempt += 1) {
    try {
      $Health = Invoke-RestMethod -Uri $HealthUrl -Headers (Get-CommandCenterHeaders) -TimeoutSec 2
      if ($Health.ok -and $Health.service -eq "nova-ops-command-center") {
        return
      }
    } catch {
      Start-Sleep -Milliseconds 500
    }
  }

  $ProcessIds = @($Stale | ForEach-Object { [int]$_.ProcessId } | Sort-Object -Unique)
  Write-Warning "Removing unresponsive stale Nova Ops Command Center process tree: $($ProcessIds -join ', ')."
  Stop-Process -Id $ProcessIds -Force -ErrorAction SilentlyContinue

  $Deadline = (Get-Date).AddSeconds(5)
  do {
    Start-Sleep -Milliseconds 250
    $Remaining = @(Get-StaleCommandCenterProcesses)
  } while ($Remaining -and (Get-Date) -lt $Deadline)
  if ($Remaining) {
    throw "Unresponsive stale Nova Ops Command Center process tree could not be stopped."
  }
}

New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
$RestartAttempts = 0
while ($true) {
  try {
    $Process = $null
    try {
      $Existing = Invoke-RestMethod -Uri $HealthUrl -Headers (Get-CommandCenterHeaders) -TimeoutSec 2
      if ($Existing.ok -and $Existing.service -eq "nova-ops-command-center") {
        if (-not $Supervised) {
          Write-Host "Nova Ops Command Center gateway is already healthy on $HealthUrl (PID $($Existing.processId))."
          exit 0
        }
        $Process = Get-Process -Id ([int]$Existing.processId) -ErrorAction Stop
        Write-Host "Supervising existing Nova Ops Command Center gateway on $HealthUrl (PID $($Process.Id))."
      } else {
        throw "Port $Port responded, but it is not the Nova Ops Command Center gateway."
      }
    } catch {
      if ($_.Exception.Message -like "Port $Port responded*") {
        throw
      }
    }

    if ($null -eq $Process) {
      Remove-StaleCommandCenterProcesses
      $Process = Start-Process `
        -FilePath "py" `
        -ArgumentList @("-3", "-m", "codex_slack_bridge.command_center_server", "--config", $Config, "--host", "127.0.0.1", "--port", $Port) `
        -WorkingDirectory $Root `
        -WindowStyle Hidden `
        -RedirectStandardOutput $StdoutLog `
        -RedirectStandardError $StderrLog `
        -PassThru

      $Deadline = (Get-Date).AddSeconds(20)
      $Healthy = $false
      do {
        try {
          $Health = Invoke-RestMethod -Uri $HealthUrl -Headers (Get-CommandCenterHeaders) -TimeoutSec 2
          if ($Health.ok -and $Health.service -eq "nova-ops-command-center") {
            $Healthy = $true
            break
          }
        } catch {
          Start-Sleep -Milliseconds 250
        }
        if ($Process.HasExited) {
          throw "Nova Ops Command Center gateway exited during startup with code $($Process.ExitCode)."
        }
      } while ((Get-Date) -lt $Deadline)
      if (-not $Healthy) {
        throw "Nova Ops Command Center gateway did not become healthy within 20 seconds."
      }
      Write-Host "Nova Ops Command Center gateway is healthy on $HealthUrl (PID $($Process.Id))."
      Write-Host "stdout: $StdoutLog"
      Write-Host "stderr: $StderrLog"
      if (-not $Supervised) {
        exit 0
      }
    }

    $Process.WaitForExit()
    $Process.Refresh()
    $exitCode = if ($null -ne $Process.ExitCode) { [int]$Process.ExitCode } else { 1 }
    Write-Warning "Nova Ops Command Center gateway exited with code $exitCode; the supervised launcher will restart it."
  } catch {
    $exitCode = 1
    if (-not $Supervised) {
      throw
    }
    Write-Warning "Nova Ops Command Center launch failed: $($_.Exception.Message)"
  }

  $RestartAttempts += 1
  if ($MaxRestarts -gt 0 -and $RestartAttempts -ge $MaxRestarts) {
    exit $exitCode
  }
  Start-Sleep -Seconds ([Math]::Max(0, $RestartDelaySeconds))
}
