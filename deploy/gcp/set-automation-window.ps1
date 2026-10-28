[CmdletBinding()]
param(
    [string]$ProjectId = "gen-lang-client-0051653266",
    [string]$Location = "us-central1",
    [string]$TimeZone = "America/New_York",
    [string]$LogMeInSchedule = "*/15 8-18 * * *",
    [string]$QualitySchedule = "30 8 * * *",
    [string]$JournalPath = "",
    [switch]$Apply
)

$ErrorActionPreference = "Stop"

$targets = @(
    [ordered]@{
        name = "logmein-connector-scheduler-trigger"
        desiredSchedule = $LogMeInSchedule
        purpose = "LogMeIn ticket intake every 15 minutes while automation is open"
    },
    [ordered]@{
        name = "quality-emailer-logmein-connector-scheduler-trigger"
        desiredSchedule = $QualitySchedule
        purpose = "Daily quality email after the first morning intake cycles"
    }
)
$watchdogName = "nova-command-center-runtime-watchdog"

function Invoke-GcloudText {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)
    $output = & gcloud.cmd @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "gcloud failed: $($output -join [Environment]::NewLine)"
    }
    return ($output -join [Environment]::NewLine)
}

function Read-SchedulerJob {
    param([Parameter(Mandatory = $true)][string]$Name)
    $raw = Invoke-GcloudText -Arguments @(
        "scheduler", "jobs", "describe", $Name,
        "--project=$ProjectId",
        "--location=$Location",
        "--format=json"
    )
    return ($raw | ConvertFrom-Json)
}

function Scheduler-Snapshot {
    param([Parameter(Mandatory = $true)]$Job)
    return [ordered]@{
        name = [string]$Job.name
        schedule = [string]$Job.schedule
        timeZone = [string]$Job.timeZone
        state = [string]$Job.state
        uri = [string]$Job.httpTarget.uri
    }
}

$before = @()
foreach ($target in $targets) {
    $job = Read-SchedulerJob -Name $target.name
    $before += Scheduler-Snapshot -Job $job
}
$watchdogBefore = Scheduler-Snapshot -Job (Read-SchedulerJob -Name $watchdogName)

$operationId = "automation-window:8-19:${TimeZone}:$($targets.name -join ',')"
$journal = [ordered]@{
    operationId = $operationId
    state = if ($Apply) { "pending" } else { "plan_only" }
    capturedAtUtc = [DateTime]::UtcNow.ToString("o")
    projectId = $ProjectId
    location = $Location
    timeZone = $TimeZone
    before = $before
    desired = @($targets | ForEach-Object {
        [ordered]@{ name = $_.name; schedule = $_.desiredSchedule; timeZone = $TimeZone }
    })
    watchdog = $watchdogBefore
    verified = @()
}

if (-not $JournalPath) {
    $JournalPath = Join-Path ([IO.Path]::GetTempPath()) "nova-automation-window-journal.json"
}
$journalDirectory = Split-Path -Parent $JournalPath
if ($journalDirectory) {
    [IO.Directory]::CreateDirectory($journalDirectory) | Out-Null
}
[IO.File]::WriteAllText(
    $JournalPath,
    ($journal | ConvertTo-Json -Depth 8),
    [Text.UTF8Encoding]::new($false)
)

if (-not $Apply) {
    $journal | ConvertTo-Json -Depth 8
    Write-Host "PLAN ONLY: rerun with -Apply to update the two background scheduler jobs."
    exit 0
}

$verified = @()
foreach ($target in $targets) {
    $current = Read-SchedulerJob -Name $target.name
    $currentSnapshot = Scheduler-Snapshot -Job $current
    if (
        $currentSnapshot.schedule -ne $target.desiredSchedule -or
        $currentSnapshot.timeZone -ne $TimeZone
    ) {
        Invoke-GcloudText -Arguments @(
            "scheduler", "jobs", "update", "http", $target.name,
            "--project=$ProjectId",
            "--location=$Location",
            "--schedule=$($target.desiredSchedule)",
            "--time-zone=$TimeZone",
            "--quiet"
        ) | Out-Null
    }
    $readback = Scheduler-Snapshot -Job (Read-SchedulerJob -Name $target.name)
    if (
        $readback.schedule -ne $target.desiredSchedule -or
        $readback.timeZone -ne $TimeZone -or
        $readback.uri -ne $currentSnapshot.uri -or
        $readback.state -ne $currentSnapshot.state
    ) {
        throw "Scheduler readback failed for $($target.name)."
    }
    $verified += $readback
}

$watchdogAfter = Scheduler-Snapshot -Job (Read-SchedulerJob -Name $watchdogName)
if (
    $watchdogAfter.schedule -ne $watchdogBefore.schedule -or
    $watchdogAfter.timeZone -ne $watchdogBefore.timeZone -or
    $watchdogAfter.uri -ne $watchdogBefore.uri -or
    $watchdogAfter.state -ne $watchdogBefore.state
) {
    throw "The always-on runtime watchdog changed unexpectedly."
}

$journal.state = "verified"
$journal.completedAtUtc = [DateTime]::UtcNow.ToString("o")
$journal.verified = $verified
$journal.watchdog = $watchdogAfter
[IO.File]::WriteAllText(
    $JournalPath,
    ($journal | ConvertTo-Json -Depth 8),
    [Text.UTF8Encoding]::new($false)
)
$journal | ConvertTo-Json -Depth 8
