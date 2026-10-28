param(
  [string]$TaskName = "NovaOpsCommandCenterGateway",
  [string]$RegistryValueName = "CodexCommandCenter",
  [switch]$StartNow
)

# AgentChat/direct_codex 2026-07-13T00:16:00-04:00: install restart-on-failure supervision.
# AgentChat/coding_agent 2026-07-13T00:55:00-04:00: preserve a supervised non-admin fallback until task verification succeeds.

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$startScript = Join-Path $root "scripts\start-command-center-server.ps1"

if (-not (Test-Path $startScript)) {
  throw "Start script not found: $startScript"
}

$runKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
$startup = [Environment]::GetFolderPath("Startup")
$legacyLauncher = Join-Path $startup "$TaskName.cmd"
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$supervisedArguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$startScript`" -Supervised"
$action = New-ScheduledTaskAction `
  -Execute "powershell.exe" `
  -Argument $supervisedArguments
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $identity
$principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet `
  -AllowStartIfOnBatteries `
  -DontStopIfGoingOnBatteries `
  -StartWhenAvailable `
  -MultipleInstances IgnoreNew `
  -RestartCount 999 `
  -RestartInterval (New-TimeSpan -Minutes 1) `
  -ExecutionTimeLimit (New-TimeSpan -Seconds 0)

function Test-SupervisedScheduledTask {
  param([object]$Task)

  $taskAction = @($Task.Actions) | Select-Object -First 1
  return (
    $null -ne $taskAction -and
    [int]$Task.Settings.RestartCount -ge 1 -and
    [string]$Task.Settings.ExecutionTimeLimit -eq "PT0S" -and
    [string]$taskAction.Execute -match "(?i)powershell" -and
    [string]$taskAction.Arguments -match [regex]::Escape($startScript) -and
    [string]$taskAction.Arguments -match "(?i)(^|\s)-Supervised(\s|$)"
  )
}

$installed = $null
$registrationError = ""
$scheduledVerified = $false
try {
  Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Force | Out-Null
  $installed = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
  $scheduledVerified = Test-SupervisedScheduledTask $installed
  if (-not $scheduledVerified) {
    throw "Scheduled task '$TaskName' failed supervised-policy readback."
  }
} catch {
  $registrationError = $_.Exception.Message
  try {
    $installed = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    $scheduledVerified = Test-SupervisedScheduledTask $installed
  } catch {
    $scheduledVerified = $false
  }
}

if ($scheduledVerified -and $StartNow) {
  try {
    if ([string]$installed.State -ne "Running") {
      Start-ScheduledTask -TaskName $TaskName
    }
    $startDeadline = (Get-Date).AddSeconds(10)
    do {
      Start-Sleep -Milliseconds 250
      $installed = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    } while ([string]$installed.State -ne "Running" -and (Get-Date) -lt $startDeadline)
    if ([string]$installed.State -ne "Running") {
      throw "Scheduled task '$TaskName' did not enter Running state."
    }
  } catch {
    $registrationError = $_.Exception.Message
    $scheduledVerified = $false
  }
}

if ($scheduledVerified) {
  if (Test-Path -LiteralPath $legacyLauncher) {
    Remove-Item -LiteralPath $legacyLauncher -Force
  }
  if (Test-Path -LiteralPath $legacyLauncher) {
    throw "Legacy Startup folder launcher is still present: $legacyLauncher"
  }

  Remove-ItemProperty -Path $runKey -Name $RegistryValueName -ErrorAction SilentlyContinue
  Remove-ItemProperty -Path $runKey -Name $TaskName -ErrorAction SilentlyContinue

  "Installed and verified supervised scheduled task '$TaskName' for $identity."
  "Target: $startScript"
  "Restart-on-failure: $($installed.Settings.RestartCount) attempts at $($installed.Settings.RestartInterval)."
  "Legacy HKCU Run and Startup folder entries are absent."
  return
}

$launcherBody = @"
@echo off
:supervise
powershell.exe $supervisedArguments
timeout /t 5 /nobreak >nul
goto supervise
"@
$launcherTemp = "$legacyLauncher.tmp"
$launcherBody | Set-Content -LiteralPath $launcherTemp -Encoding ASCII
Move-Item -LiteralPath $launcherTemp -Destination $legacyLauncher -Force
$verifiedLauncher = Get-Content -LiteralPath $legacyLauncher -Raw
if ($verifiedLauncher -notmatch "(?i)(^|\s)-Supervised(\s|$)") {
  throw "Supervised Startup folder fallback verification failed: $legacyLauncher"
}

if ($StartNow) {
  Start-Process `
    -FilePath $env:ComSpec `
    -ArgumentList @("/d", "/c", "`"$legacyLauncher`"") `
    -WindowStyle Hidden
}

"Scheduled task install was unavailable: $registrationError"
"Installed and verified supervised Startup folder fallback: $legacyLauncher"
"Target: $startScript"
