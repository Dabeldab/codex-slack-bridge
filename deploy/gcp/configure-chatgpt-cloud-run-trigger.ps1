[CmdletBinding()]
param(
    [string]$ProjectId = "gen-lang-client-0051653266",
    [string]$TriggerRegion = "europe-west1",
    [string]$TriggerId = "0a3f4d1e-0eec-46bb-992e-809d04f08478",
    [string]$RepoOwner = "dariusmakesstuff",
    [string]$RepoName = "codex-slack-bridge",
    [string]$BranchPattern = "^main$",
    [string]$BuildConfig = "deploy/gcp/cloudbuild-cloud-run-chatgpt.yaml",
    [switch]$Apply,
    [switch]$RunAfterApply
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Resolve-Gcloud {
    $command = Get-Command gcloud.ps1 -ErrorAction SilentlyContinue
    if (-not $command) { $command = Get-Command gcloud.cmd -ErrorAction SilentlyContinue }
    if (-not $command) { $command = Get-Command gcloud -ErrorAction SilentlyContinue }
    if (-not $command) { throw "gcloud CLI was not found." }
    return $command.Source
}

function Invoke-Gcloud {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    $output = & $script:Gcloud @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "gcloud command failed with exit code $LASTEXITCODE."
    }
    return $output
}

$script:Gcloud = Resolve-Gcloud

$existing = Invoke-Gcloud builds triggers describe $TriggerId `
    "--project=$ProjectId" `
    "--region=$TriggerRegion" `
    --format=json | ConvertFrom-Json

$existingBranch = ""
if ($existing.github -and $existing.github.push) {
    $existingBranch = [string]$existing.github.push.branch
}
$existingConfig = if ($existing.filename) { [string]$existing.filename } else { "" }

$plan = [ordered]@{
    mode = if ($Apply) { "apply" } else { "plan" }
    project = $ProjectId
    triggerRegion = $TriggerRegion
    triggerId = $TriggerId
    repository = "$RepoOwner/$RepoName"
    currentBranchPattern = $existingBranch
    desiredBranchPattern = $BranchPattern
    currentBuildConfig = $existingConfig
    desiredBuildConfig = $BuildConfig
    serviceAccount = [string]$existing.serviceAccount
    substitutions = $existing.substitutions
    deployTarget = "nova-command-center-shadow"
    deployRegion = "us-central1"
    expectedFlow = @(
        "push main",
        "Cloud Build",
        "docker build",
        "docker push",
        "gcloud run deploy",
        "route traffic to latest"
    )
}

if (-not $Apply) {
    $plan | ConvertTo-Json -Depth 8
    exit 0
}

Invoke-Gcloud builds triggers update github $TriggerId `
    "--project=$ProjectId" `
    "--region=$TriggerRegion" `
    "--repo-owner=$RepoOwner" `
    "--repo-name=$RepoName" `
    "--branch-pattern=$BranchPattern" `
    "--build-config=$BuildConfig" `
    --include-logs-with-status `
    --quiet | Out-Null

$verifiedTrigger = Invoke-Gcloud builds triggers describe $TriggerId `
    "--project=$ProjectId" `
    "--region=$TriggerRegion" `
    --format=json | ConvertFrom-Json

$verified = (
    [string]$verifiedTrigger.github.owner -eq $RepoOwner -and
    [string]$verifiedTrigger.github.name -eq $RepoName -and
    [string]$verifiedTrigger.github.push.branch -eq $BranchPattern -and
    [string]$verifiedTrigger.filename -eq $BuildConfig
)
if (-not $verified) {
    throw "Cloud Build trigger readback did not match the requested main-branch deployment configuration."
}

if ($RunAfterApply) {
    Invoke-Gcloud builds triggers run $TriggerId `
        "--project=$ProjectId" `
        "--region=$TriggerRegion" `
        --branch=main `
        --quiet | Out-Null
}

[ordered]@{
    ok = $true
    verified = $verified
    triggerId = [string]$verifiedTrigger.id
    triggerName = [string]$verifiedTrigger.name
    repository = "$([string]$verifiedTrigger.github.owner)/$([string]$verifiedTrigger.github.name)"
    branchPattern = [string]$verifiedTrigger.github.push.branch
    buildConfig = [string]$verifiedTrigger.filename
    serviceAccount = [string]$verifiedTrigger.serviceAccount
    runAfterApply = [bool]$RunAfterApply
} | ConvertTo-Json -Depth 8
