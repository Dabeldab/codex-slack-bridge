param(
    [string]$ProjectId = "gen-lang-client-0051653266",
    [string]$Region = "global",
    [string]$LegacyTriggerId = "bc4dba46-f1b0-4441-ae00-13ed3c6c6a59",
    [string]$TriggerName = "nova-agent-runtime-main",
    [string]$RepoOwner = "dariusmakesstuff",
    [string]$RepoName = "codex-slack-bridge",
    [string]$BranchPattern = "^main$",
    [string]$ServiceAccountId = "nova-agent-build",
    [string]$BuildInvokerRoleId = "novaAgentRuntimeBuild",
    [switch]$Apply
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Find-Gcloud {
    $command = Get-Command gcloud.ps1 -ErrorAction SilentlyContinue
    if (-not $command) { $command = Get-Command gcloud.cmd -ErrorAction SilentlyContinue }
    if (-not $command) { $command = Get-Command gcloud -ErrorAction SilentlyContinue }
    if (-not $command) { throw "gcloud CLI was not found." }
    return $command.Source
}

$script:Gcloud = Find-Gcloud

function Enable-ApplicationDefaultToken {
    if ($env:CLOUDSDK_AUTH_ACCESS_TOKEN) { return }
    $token = & $script:Gcloud auth application-default print-access-token --quiet 2>$null | Select-Object -First 1
    if (-not $token) { throw "Application Default Credentials could not provide a Google Cloud access token." }
    $env:CLOUDSDK_AUTH_ACCESS_TOKEN = [string]$token
}

function Invoke-Gcloud {
    $errorFile = Join-Path ([IO.Path]::GetTempPath()) ("gcloud-error-" + [guid]::NewGuid().ToString("N") + ".log")
    $priorPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $output = & $script:Gcloud @args 2> $errorFile
        $exitCode = $LASTEXITCODE
        if ($exitCode -ne 0) {
            $details = (($output | Out-String) + (Get-Content -LiteralPath $errorFile -Raw -ErrorAction SilentlyContinue)).Trim()
            throw $details
        }
        return $output
    }
    finally {
        $ErrorActionPreference = $priorPreference
        Remove-Item -LiteralPath $errorFile -Force -ErrorAction SilentlyContinue
    }
}

function Test-GcloudResource([string[]]$Arguments) {
    $priorPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        & $script:Gcloud @Arguments 1>$null 2>$null
        return $LASTEXITCODE -eq 0
    }
    finally { $ErrorActionPreference = $priorPreference }
}

function Convert-TriggerSummary($Trigger) {
    if (-not $Trigger) { return $null }
    $buildConfig = if ($Trigger.PSObject.Properties["filename"]) {
        [string]$Trigger.filename
    }
    elseif ($Trigger.PSObject.Properties["build"]) {
        "<inline-build>"
    }
    else {
        "<unspecified>"
    }
    return [ordered]@{
        id = [string]$Trigger.id
        name = [string]$Trigger.name
        repository = "$([string]$Trigger.github.owner)/$([string]$Trigger.github.name)"
        branch = [string]$Trigger.github.push.branch
        buildConfig = $buildConfig
        serviceAccount = [string]$Trigger.serviceAccount
    }
}

function Get-TriggerByName(
    [string]$Name,
    [string]$Project,
    [string]$Location,
    [int]$Attempts = 1
) {
    for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
        if (Test-GcloudResource @("builds", "triggers", "describe", $Name, "--project=$Project", "--region=$Location")) {
            return Invoke-Gcloud builds triggers describe $Name "--project=$Project" "--region=$Location" --format=json | ConvertFrom-Json
        }
        if ($attempt -lt $Attempts) { Start-Sleep -Seconds 2 }
    }
    return $null
}

Enable-ApplicationDefaultToken
try {
    $projectNumber = (Invoke-Gcloud projects describe $ProjectId "--format=value(projectNumber)" "--billing-project=$ProjectId" | Select-Object -First 1).Trim()
    if (-not $projectNumber) { throw "Could not resolve the GCP project number." }
    $serviceAccount = "$ServiceAccountId@$ProjectId.iam.gserviceaccount.com"
    $serviceAccountResource = "projects/$ProjectId/serviceAccounts/$serviceAccount"
    $buildInvokerRole = "projects/$ProjectId/roles/$BuildInvokerRoleId"
    $bucket = "gs://nova-agent-runtime-source-$projectNumber"
    $buildConfig = "deploy/gcp/cloudbuild-agent-runtime.yaml"

    $legacy = $null
    if (Test-GcloudResource @("builds", "triggers", "describe", $LegacyTriggerId, "--project=$ProjectId", "--region=$Region")) {
        $legacy = Invoke-Gcloud builds triggers describe $LegacyTriggerId "--project=$ProjectId" "--region=$Region" --format=json | ConvertFrom-Json
    }
    $existingDesired = Get-TriggerByName $TriggerName $ProjectId $Region
    $replacesLegacyTrigger = $null -ne $legacy
    if ($existingDesired -and $legacy) {
        $replacesLegacyTrigger = $replacesLegacyTrigger -and [string]$legacy.id -ne [string]$existingDesired.id
    }
    $plan = [ordered]@{
        operationId = "cloud-build-github-link:${ProjectId}:${LegacyTriggerId}:main"
        mode = if ($Apply) { "apply" } else { "plan" }
        project = $ProjectId
        legacyGitHubTrigger = (Convert-TriggerSummary $legacy)
        existingDedicatedTrigger = (Convert-TriggerSummary $existingDesired)
        desired = [ordered]@{
            name = $TriggerName
            repository = "$RepoOwner/$RepoName"
            branch = $BranchPattern
            buildConfig = $buildConfig
            serviceAccount = $serviceAccountResource
            buildInvokerRole = $buildInvokerRole
            sourceBucket = $bucket
            automaticProductionPromotion = $false
            replacesLegacyTrigger = $replacesLegacyTrigger
        }
    }
    if (-not $Apply) {
        $plan | ConvertTo-Json -Depth 8
        exit 0
    }

    Invoke-Gcloud services enable cloudbuild.googleapis.com storage.googleapis.com iam.googleapis.com `
        "--project=$ProjectId" --quiet | Out-Null
    if (-not (Test-GcloudResource @("iam", "service-accounts", "describe", $serviceAccount, "--project=$ProjectId"))) {
        Invoke-Gcloud iam service-accounts create $ServiceAccountId "--project=$ProjectId" `
            --display-name="Nova agent runtime Cloud Build" --quiet | Out-Null
    }
    if (-not (Test-GcloudResource @("iam", "roles", "describe", $BuildInvokerRoleId, "--project=$ProjectId"))) {
        Invoke-Gcloud iam roles create $BuildInvokerRoleId "--project=$ProjectId" `
            --title="Nova agent runtime build invoker" `
            --description="Create only the GitHub-triggered Nova runtime validation build" `
            --permissions=cloudbuild.builds.create --stage=GA "--billing-project=$ProjectId" --quiet | Out-Null
    }
    else {
        Invoke-Gcloud iam roles update $BuildInvokerRoleId "--project=$ProjectId" `
            --title="Nova agent runtime build invoker" `
            --description="Create only the GitHub-triggered Nova runtime validation build" `
            --permissions=cloudbuild.builds.create --stage=GA "--billing-project=$ProjectId" --quiet | Out-Null
    }
    if (-not (Test-GcloudResource @("storage", "buckets", "describe", $bucket, "--project=$ProjectId"))) {
        Invoke-Gcloud storage buckets create $bucket "--project=$ProjectId" --location=us-central1 `
            --uniform-bucket-level-access --public-access-prevention --quiet | Out-Null
    }
    foreach ($role in @("roles/storage.objectCreator", "roles/storage.objectViewer")) {
        Invoke-Gcloud storage buckets add-iam-policy-binding $bucket `
            "--member=serviceAccount:$serviceAccount" "--role=$role" --quiet | Out-Null
    }
    Invoke-Gcloud projects add-iam-policy-binding $ProjectId `
        "--member=serviceAccount:$serviceAccount" --role=roles/logging.logWriter --condition=None `
        "--billing-project=$ProjectId" --quiet | Out-Null
    Invoke-Gcloud projects add-iam-policy-binding $ProjectId `
        "--member=serviceAccount:$serviceAccount" "--role=$buildInvokerRole" --condition=None `
        "--billing-project=$ProjectId" --quiet | Out-Null

    if (-not $existingDesired) {
        Invoke-Gcloud builds triggers create github `
            "--project=$ProjectId" "--region=$Region" "--name=$TriggerName" `
            "--repo-owner=$RepoOwner" "--repo-name=$RepoName" "--branch-pattern=$BranchPattern" `
            "--build-config=$buildConfig" "--service-account=$serviceAccountResource" `
            "--description=Validate and publish immutable Nova private agent runtime artifacts from main" `
            "--substitutions=_SOURCE_BUCKET=nova-agent-runtime-source-$projectNumber,_SOURCE_PREFIX=releases" `
            --include-logs-with-status --quiet | Out-Null
        $existingDesired = Get-TriggerByName $TriggerName $ProjectId $Region -Attempts 10
        if (-not $existingDesired) { throw "Dedicated Cloud Build trigger creation did not produce a readback." }
    }
    else {
        Invoke-Gcloud builds triggers update github ([string]$existingDesired.id) `
            "--project=$ProjectId" "--region=$Region" `
            "--repo-owner=$RepoOwner" "--repo-name=$RepoName" "--branch-pattern=$BranchPattern" `
            "--build-config=$buildConfig" "--service-account=$serviceAccountResource" `
            "--description=Validate and publish immutable Nova private agent runtime artifacts from main" `
            "--update-substitutions=_SOURCE_BUCKET=nova-agent-runtime-source-$projectNumber,_SOURCE_PREFIX=releases" `
            --include-logs-with-status --quiet | Out-Null
    }

    $readback = Invoke-Gcloud builds triggers describe ([string]$existingDesired.id) "--project=$ProjectId" "--region=$Region" --format=json | ConvertFrom-Json
    $verified = (
        [string]$readback.name -eq $TriggerName -and
        [string]$readback.github.owner -eq $RepoOwner -and
        [string]$readback.github.name -eq $RepoName -and
        [string]$readback.github.push.branch -eq $BranchPattern -and
        [string]$readback.filename -eq $buildConfig -and
        [string]$readback.serviceAccount -eq $serviceAccountResource
    )
    if (-not $verified) { throw "Cloud Build GitHub trigger readback did not match the requested configuration." }

    $legacyRemoved = $true
    if ($legacy -and [string]$legacy.id -ne [string]$readback.id) {
        Invoke-Gcloud builds triggers delete ([string]$legacy.id) "--project=$ProjectId" "--region=$Region" --quiet | Out-Null
        $legacyRemoved = -not (Test-GcloudResource @("builds", "triggers", "describe", ([string]$legacy.id), "--project=$ProjectId", "--region=$Region"))
        if (-not $legacyRemoved) { throw "The verified dedicated trigger exists, but the obsolete legacy deploy trigger was not removed." }
    }

    [ordered]@{
        ok = $true
        operationId = $plan.operationId
        triggerId = [string]$readback.id
        triggerName = [string]$readback.name
        repository = "$([string]$readback.github.owner)/$([string]$readback.github.name)"
        branch = [string]$readback.github.push.branch
        buildConfig = [string]$readback.filename
        serviceAccount = [string]$readback.serviceAccount
        buildInvokerRole = $buildInvokerRole
        sourceBucket = $bucket
        automaticProductionPromotion = $false
        legacyTriggerId = $LegacyTriggerId
        legacyTriggerRemoved = $legacyRemoved
        verified = $true
    } | ConvertTo-Json -Depth 8
}
finally {
    Remove-Item Env:CLOUDSDK_AUTH_ACCESS_TOKEN -ErrorAction SilentlyContinue
}
