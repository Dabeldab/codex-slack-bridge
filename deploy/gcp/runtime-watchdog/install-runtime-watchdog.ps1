param(
    [string]$ProjectId = "gen-lang-client-0051653266",
    [string]$Region = "us-central1",
    [string]$Zone = "us-central1-a",
    [string]$Instance = "nova-agent-runtime-staging",
    [string]$GatewayService = "nova-command-center-shadow",
    [string]$UpstreamTokenSecret = "nova-command-center-upstream-token",
    [string]$WorkflowName = "nova-command-center-runtime-watchdog",
    [string]$SchedulerJob = "nova-command-center-runtime-watchdog",
    [string]$RuntimeServiceAccountId = "nova-runtime-watchdog",
    [string]$TriggerServiceAccountId = "nova-runtime-watchdog-trigger",
    [string]$CustomRoleId = "NovaRuntimeWatchdog",
    [string]$Schedule = "*/2 * * * *",
    [string]$TimeZone = "Etc/UTC",
    [switch]$Apply
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$WorkflowSource = (Resolve-Path (Join-Path $PSScriptRoot "command-center-runtime-watchdog.yaml")).Path
$HoldLabel = "nova-watchdog-hold-until"

function Find-Gcloud {
    $command = Get-Command gcloud.cmd -ErrorAction SilentlyContinue
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

function Invoke-GcloudWithRetry(
    [int]$Attempts,
    [int]$DelaySeconds,
    [string[]]$Arguments
) {
    $lastFailure = $null
    for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
        try {
            return Invoke-Gcloud @Arguments
        }
        catch {
            $lastFailure = $_
            $retryable = $_.Exception.Message -match (
                "SERVICE_DISABLED|IAM permission denied|RESOURCE_EXHAUSTED|" +
                "UNAVAILABLE|temporar|propagat|HTTP 429|HTTP 503"
            )
            if (-not $retryable) {
                throw
            }
            if ($attempt -lt $Attempts) {
                Start-Sleep -Seconds $DelaySeconds
            }
        }
    }
    throw $lastFailure
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

function Get-ManifestUpstreamTokenVersion(
    [object]$InstanceDescription,
    [string]$ExpectedProjectId,
    [string]$SecretName
) {
    $manifestItems = @(
        $InstanceDescription.metadata.items | Where-Object {
            [string]$_.key -eq "nova-secret-manifest"
        }
    )
    if ($manifestItems.Count -ne 1 -or -not [string]$manifestItems[0].value) {
        throw "The VM must contain exactly one non-empty nova-secret-manifest metadata item."
    }
    try {
        $manifest = [string]$manifestItems[0].value | ConvertFrom-Json
    }
    catch {
        throw "The VM nova-secret-manifest is not valid JSON."
    }
    if ([string]$manifest.project_id -ne $ExpectedProjectId) {
        throw "The VM nova-secret-manifest project does not match the watchdog project."
    }
    $entries = @(
        $manifest.secrets | Where-Object { [string]$_.id -eq $SecretName }
    )
    if ($entries.Count -ne 1) {
        throw "The VM manifest must contain exactly one upstream-token entry."
    }
    $version = [string]$entries[0].version
    if ($version -notmatch '^[1-9][0-9]*$') {
        throw "The VM manifest upstream-token version must be numeric."
    }
    return $version
}

function Get-GatewayMountedVersions(
    [object]$GatewayDescription,
    [string]$SecretName
) {
    return @(
        foreach ($volume in @($GatewayDescription.spec.template.spec.volumes)) {
            if ([string]$volume.secret.secretName -ne $SecretName) {
                continue
            }
            foreach ($item in @($volume.secret.items)) {
                [string]$item.key
            }
        }
    )
}

function Test-PolicyBinding(
    [object]$Policy,
    [string]$Role,
    [string]$Member
) {
    return @(
        $Policy.bindings | Where-Object {
            [string]$_.role -eq $Role -and
            @($_.members) -contains $Member
        }
    ).Count -ge 1
}

function Test-ConditionalPolicyBinding(
    [object]$Policy,
    [string]$Role,
    [string]$Member,
    [string]$Title,
    [string]$Expression
) {
    return @(
        $Policy.bindings | Where-Object {
            [string]$_.role -eq $Role -and
            @($_.members) -contains $Member -and
            [string]$_.condition.title -eq $Title -and
            [string]$_.condition.expression -eq $Expression
        }
    ).Count -eq 1
}

Enable-ApplicationDefaultToken
try {
    $ProjectNumber = (Invoke-Gcloud projects describe $ProjectId `
        "--format=value(projectNumber)" "--billing-project=$ProjectId" | Select-Object -First 1).Trim()
    if (-not $ProjectNumber) { throw "Could not resolve the GCP project number." }

    $RuntimeServiceAccount = "$RuntimeServiceAccountId@$ProjectId.iam.gserviceaccount.com"
    $TriggerServiceAccount = "$TriggerServiceAccountId@$ProjectId.iam.gserviceaccount.com"
    $CustomRole = "projects/$ProjectId/roles/$CustomRoleId"
    $WorkflowUri = "https://workflowexecutions.googleapis.com/v1/projects/$ProjectId/locations/$Region/workflows/$WorkflowName/executions"
    $SchedulerMessageBody = '{"argument":"{}"}'
    $InstanceResource = "projects/$ProjectId/zones/$Zone/instances/$Instance"
    $GatewayResource = "projects/$ProjectId/locations/$Region/services/$GatewayService"
    $GatewayResourceByNumber = "projects/$ProjectNumber/locations/$Region/services/$GatewayService"
    $IapResource = "projects/$ProjectNumber/iap_web/cloud_run-$Region/services/$GatewayService"
    $RunConditionTitle = "nova-watchdog-run-$GatewayService"
    $RunConditionExpression = (
        "resource.name == '$GatewayResource' || " +
        "resource.name == '$GatewayResourceByNumber' || " +
        "resource.name.startsWith('projects/$ProjectId/locations/$Region/operations/') || " +
        "resource.name.startsWith('projects/$ProjectNumber/locations/$Region/operations/')"
    )
    $IapConditionTitle = "nova-watchdog-iap-$GatewayService"
    $IapConditionExpression = "resource.name == '$IapResource'"
    $OperationId = "gcp-runtime-watchdog:${ProjectId}:${Zone}:${Instance}"
    $CustomRolePermissions = @(
        "compute.instances.get",
        "compute.instances.start",
        "run.operations.get",
        "run.services.get",
        "run.services.update",
        "secretmanager.versions.get"
    )

    $InstanceExists = Test-GcloudResource @(
        "compute", "instances", "describe", $Instance,
        "--project=$ProjectId", "--zone=$Zone"
    )
    $RuntimeServiceAccountExists = Test-GcloudResource @(
        "iam", "service-accounts", "describe", $RuntimeServiceAccount,
        "--project=$ProjectId"
    )
    $TriggerServiceAccountExists = Test-GcloudResource @(
        "iam", "service-accounts", "describe", $TriggerServiceAccount,
        "--project=$ProjectId"
    )
    $CustomRoleExists = Test-GcloudResource @(
        "iam", "roles", "describe", $CustomRoleId,
        "--project=$ProjectId"
    )
    $WorkflowExists = Test-GcloudResource @(
        "workflows", "describe", $WorkflowName,
        "--project=$ProjectId", "--location=$Region"
    )
    $SchedulerExists = Test-GcloudResource @(
        "scheduler", "jobs", "describe", $SchedulerJob,
        "--project=$ProjectId", "--location=$Region"
    )
    $GatewayExists = Test-GcloudResource @(
        "run", "services", "describe", $GatewayService,
        "--project=$ProjectId", "--region=$Region"
    )
    $UpstreamTokenSecretExists = Test-GcloudResource @(
        "secrets", "describe", $UpstreamTokenSecret,
        "--project=$ProjectId"
    )

    $ManifestUpstreamTokenVersion = ""
    $ManifestUpstreamTokenState = ""
    $GatewayMountedVersions = @()
    $GatewayRuntimeServiceAccount = ""
    $GatewayImageBefore = ""
    $GatewayIapEnabled = $false
    if ($InstanceExists) {
        $instanceDescription = Invoke-Gcloud compute instances describe $Instance `
            "--project=$ProjectId" "--zone=$Zone" --format=json | ConvertFrom-Json
        $ManifestUpstreamTokenVersion = Get-ManifestUpstreamTokenVersion `
            -InstanceDescription $instanceDescription `
            -ExpectedProjectId $ProjectId `
            -SecretName $UpstreamTokenSecret
    }
    if ($UpstreamTokenSecretExists -and $ManifestUpstreamTokenVersion) {
        $ManifestUpstreamTokenState = [string](
            Invoke-Gcloud secrets versions describe $ManifestUpstreamTokenVersion `
                "--secret=$UpstreamTokenSecret" `
                "--project=$ProjectId" `
                "--format=value(state)" | Select-Object -First 1
        ).Trim()
    }
    if ($GatewayExists) {
        $gatewayDescription = Invoke-Gcloud run services describe $GatewayService `
            "--project=$ProjectId" "--region=$Region" --format=json | ConvertFrom-Json
        $GatewayMountedVersions = @(
            Get-GatewayMountedVersions `
                -GatewayDescription $gatewayDescription `
                -SecretName $UpstreamTokenSecret
        )
        $GatewayRuntimeServiceAccount = [string]$gatewayDescription.spec.template.spec.serviceAccountName
        if (-not $GatewayRuntimeServiceAccount) {
            $GatewayRuntimeServiceAccount = [string]$gatewayDescription.template.serviceAccount
        }
        $GatewayImageBefore = [string]@($gatewayDescription.spec.template.spec.containers)[0].image
        $iapEnabledProperty = $gatewayDescription.PSObject.Properties["iapEnabled"]
        if ($iapEnabledProperty -and $iapEnabledProperty.Value -eq $true) {
            $GatewayIapEnabled = $true
        }
        $metadataProperty = $gatewayDescription.PSObject.Properties["metadata"]
        if ($metadataProperty -and $metadataProperty.Value) {
            $annotationsProperty = $metadataProperty.Value.PSObject.Properties["annotations"]
            if ($annotationsProperty -and $annotationsProperty.Value) {
                $iapAnnotation = $annotationsProperty.Value.PSObject.Properties[
                    "run.googleapis.com/iap-enabled"
                ]
                if ($iapAnnotation -and [string]$iapAnnotation.Value -eq "true") {
                    $GatewayIapEnabled = $true
                }
            }
        }
    }

    $plan = [ordered]@{
        operationId = $OperationId
        mode = if ($Apply) { "apply" } else { "plan" }
        project = $ProjectId
        projectNumber = $ProjectNumber
        region = $Region
        zone = $Zone
        instance = $Instance
        instanceResource = $InstanceResource
        instanceExists = $InstanceExists
        gatewayService = $GatewayService
        gatewayResource = $GatewayResource
        gatewayExists = $GatewayExists
        gatewayRuntimeServiceAccount = $GatewayRuntimeServiceAccount
        gatewayImage = $GatewayImageBefore
        gatewayIapEnabled = $GatewayIapEnabled
        gatewayMountedVersions = $GatewayMountedVersions
        upstreamTokenSecret = $UpstreamTokenSecret
        upstreamTokenSecretExists = $UpstreamTokenSecretExists
        manifestUpstreamTokenVersion = $ManifestUpstreamTokenVersion
        manifestUpstreamTokenState = $ManifestUpstreamTokenState
        workflow = $WorkflowName
        workflowExists = $WorkflowExists
        workflowSource = $WorkflowSource
        schedulerJob = $SchedulerJob
        schedulerExists = $SchedulerExists
        schedule = $Schedule
        timeZone = $TimeZone
        runtimeServiceAccount = $RuntimeServiceAccount
        runtimeServiceAccountExists = $RuntimeServiceAccountExists
        triggerServiceAccount = $TriggerServiceAccount
        triggerServiceAccountExists = $TriggerServiceAccountExists
        customRole = $CustomRole
        customRoleExists = $CustomRoleExists
        customRolePermissions = $CustomRolePermissions
        exactInstanceBinding = $true
        exactGatewayCondition = $RunConditionExpression
        exactIapCondition = $IapConditionExpression
        maintenanceHoldLabel = $HoldLabel
        workflowUri = $WorkflowUri
    }

    if (-not $Apply) {
        $plan | ConvertTo-Json -Depth 6
        exit 0
    }
    if (-not $InstanceExists) {
        throw "Refusing watchdog deployment because the exact VM does not exist: $InstanceResource"
    }
    if (-not $GatewayExists) {
        throw "Refusing watchdog deployment because the exact Cloud Run service does not exist: $GatewayResource"
    }
    if (-not $UpstreamTokenSecretExists) {
        throw "Refusing watchdog deployment because the exact upstream-token secret does not exist: $UpstreamTokenSecret"
    }
    if ($ManifestUpstreamTokenState -ne "ENABLED") {
        throw "Refusing watchdog deployment because the VM-manifest exact upstream-token version is not ENABLED."
    }
    if (-not $GatewayRuntimeServiceAccount) {
        throw "Refusing watchdog deployment because the Cloud Run service identity could not be resolved."
    }
    if (-not $GatewayIapEnabled) {
        throw "Refusing watchdog deployment because direct Cloud Run IAP is not enabled."
    }
    if ($GatewayMountedVersions.Count -lt 1) {
        throw "Refusing watchdog deployment because the exact upstream-token mount is absent."
    }

    Invoke-Gcloud services enable compute.googleapis.com iam.googleapis.com `
        workflows.googleapis.com `
        cloudscheduler.googleapis.com `
        iamcredentials.googleapis.com `
        iap.googleapis.com `
        run.googleapis.com `
        secretmanager.googleapis.com `
        "--project=$ProjectId" --quiet | Out-Null

    if (-not $RuntimeServiceAccountExists) {
        Invoke-Gcloud iam service-accounts create $RuntimeServiceAccountId `
            "--project=$ProjectId" `
            --display-name="Nova runtime watchdog executor" --quiet | Out-Null
    }
    if (-not $TriggerServiceAccountExists) {
        Invoke-Gcloud iam service-accounts create $TriggerServiceAccountId `
            "--project=$ProjectId" `
            --display-name="Nova runtime watchdog scheduler trigger" --quiet | Out-Null
    }

    $roleArguments = @(
        $CustomRoleId,
        "--project=$ProjectId",
        "--title=Nova Runtime Watchdog",
        "--description=Repair only the bound Nova VM and exact Command Center gateway secret pin.",
        ("--permissions=" + ($CustomRolePermissions -join ",")),
        "--stage=GA",
        "--quiet"
    )
    if ($CustomRoleExists) {
        Invoke-Gcloud iam roles update @roleArguments | Out-Null
    }
    else {
        Invoke-Gcloud iam roles create @roleArguments | Out-Null
    }

    Invoke-Gcloud compute instances add-iam-policy-binding $Instance `
        "--project=$ProjectId" "--zone=$Zone" `
        "--member=serviceAccount:$RuntimeServiceAccount" `
        "--role=$CustomRole" --condition=None --quiet | Out-Null

    $RuntimeMember = "serviceAccount:$RuntimeServiceAccount"
    $runConditionArgument = (
        "--condition=expression=$RunConditionExpression,title=$RunConditionTitle," +
        "description=Exact Command Center gateway and regional operations only"
    )
    Invoke-Gcloud projects add-iam-policy-binding $ProjectId `
        "--member=$RuntimeMember" `
        "--role=$CustomRole" `
        $runConditionArgument `
        "--billing-project=$ProjectId" --quiet | Out-Null

    Invoke-Gcloud secrets add-iam-policy-binding $UpstreamTokenSecret `
        "--project=$ProjectId" `
        "--member=$RuntimeMember" `
        "--role=$CustomRole" --condition=None --quiet | Out-Null

    Invoke-Gcloud iam service-accounts add-iam-policy-binding $RuntimeServiceAccount `
        "--project=$ProjectId" `
        "--member=$RuntimeMember" `
        --role=roles/iam.serviceAccountTokenCreator `
        --condition=None --quiet | Out-Null

    Invoke-Gcloud iam service-accounts add-iam-policy-binding $GatewayRuntimeServiceAccount `
        "--project=$ProjectId" `
        "--member=$RuntimeMember" `
        --role=roles/iam.serviceAccountUser `
        --condition=None --quiet | Out-Null

    $iapConditionArgument = (
        "--condition=expression=$IapConditionExpression,title=$IapConditionTitle," +
        "description=Exact Command Center IAP resource only"
    )
    Invoke-Gcloud projects add-iam-policy-binding $ProjectId `
        "--member=$RuntimeMember" `
        --role=roles/iap.httpsResourceAccessor `
        $iapConditionArgument `
        "--billing-project=$ProjectId" --quiet | Out-Null

    Invoke-Gcloud projects add-iam-policy-binding $ProjectId `
        "--member=serviceAccount:$TriggerServiceAccount" `
        --role=roles/workflows.invoker --condition=None `
        "--billing-project=$ProjectId" --quiet | Out-Null

    $workflowDeployArguments = @(
        "workflows",
        "deploy",
        $WorkflowName,
        "--project=$ProjectId",
        "--location=$Region",
        "--source=$WorkflowSource",
        "--service-account=$RuntimeServiceAccount",
        "--set-env-vars=NOVA_WATCHDOG_PROJECT_ID=$ProjectId,NOVA_WATCHDOG_REGION=$Region,NOVA_WATCHDOG_ZONE=$Zone,NOVA_WATCHDOG_INSTANCE=$Instance,NOVA_WATCHDOG_HOLD_LABEL=$HoldLabel,NOVA_WATCHDOG_GATEWAY_SERVICE=$GatewayService,NOVA_WATCHDOG_UPSTREAM_SECRET=$UpstreamTokenSecret,NOVA_WATCHDOG_SERVICE_ACCOUNT=$RuntimeServiceAccount",
        "--call-log-level=log-errors-only",
        "--labels=application=nova-agent-runtime,component=watchdog",
        "--quiet"
    )
    Invoke-GcloudWithRetry -Attempts 12 -DelaySeconds 10 `
        -Arguments $workflowDeployArguments | Out-Null

    $schedulerMessagePath = Join-Path ([IO.Path]::GetTempPath()) `
        ("nova-runtime-watchdog-scheduler-" + [guid]::NewGuid().ToString("N") + ".json")
    try {
        [IO.File]::WriteAllText(
            $schedulerMessagePath,
            $SchedulerMessageBody,
            [Text.UTF8Encoding]::new($false)
        )
        $schedulerHeaderArgument = if ($SchedulerExists) {
            "--update-headers=Content-Type=application/json"
        }
        else {
            "--headers=Content-Type=application/json"
        }
        $schedulerArguments = @(
            "http",
            $SchedulerJob,
            "--project=$ProjectId",
            "--location=$Region",
            "--schedule=$Schedule",
            "--time-zone=$TimeZone",
            "--uri=$WorkflowUri",
            "--http-method=POST",
            "--message-body-from-file=$schedulerMessagePath",
            $schedulerHeaderArgument,
            "--oauth-service-account-email=$TriggerServiceAccount",
            "--oauth-token-scope=https://www.googleapis.com/auth/cloud-platform",
            "--attempt-deadline=30s",
            "--description=Repair the private Command Center VM and exact Cloud Run gateway secret pin.",
            "--quiet"
        )
        if ($SchedulerExists) {
            $schedulerCommand = @("scheduler", "jobs", "update") + $schedulerArguments
        }
        else {
            $schedulerCommand = @("scheduler", "jobs", "create") + $schedulerArguments
        }
        Invoke-GcloudWithRetry -Attempts 12 -DelaySeconds 10 `
            -Arguments $schedulerCommand | Out-Null
    }
    finally {
        Remove-Item -LiteralPath $schedulerMessagePath -Force -ErrorAction SilentlyContinue
    }

    $workflowReadback = Invoke-Gcloud workflows describe $WorkflowName `
        "--project=$ProjectId" "--location=$Region" --format=json | ConvertFrom-Json
    $schedulerReadback = Invoke-Gcloud scheduler jobs describe $SchedulerJob `
        "--project=$ProjectId" "--location=$Region" --format=json | ConvertFrom-Json
    $instancePolicy = Invoke-Gcloud compute instances get-iam-policy $Instance `
        "--project=$ProjectId" "--zone=$Zone" --format=json | ConvertFrom-Json
    $projectPolicy = Invoke-Gcloud projects get-iam-policy $ProjectId `
        "--billing-project=$ProjectId" --format=json | ConvertFrom-Json
    $secretPolicy = Invoke-Gcloud secrets get-iam-policy $UpstreamTokenSecret `
        "--project=$ProjectId" --format=json | ConvertFrom-Json
    $runtimeServiceAccountPolicy = Invoke-Gcloud iam service-accounts get-iam-policy `
        $RuntimeServiceAccount "--project=$ProjectId" --format=json | ConvertFrom-Json
    $gatewayServiceAccountPolicy = Invoke-Gcloud iam service-accounts get-iam-policy `
        $GatewayRuntimeServiceAccount "--project=$ProjectId" --format=json | ConvertFrom-Json
    $customRoleReadback = Invoke-Gcloud iam roles describe $CustomRoleId `
        "--project=$ProjectId" --format=json | ConvertFrom-Json

    $runtimeMember = "serviceAccount:$RuntimeServiceAccount"
    $instanceBindingVerified = Test-PolicyBinding `
        -Policy $instancePolicy -Role $CustomRole -Member $runtimeMember
    $runBindingVerified = Test-ConditionalPolicyBinding `
        -Policy $projectPolicy `
        -Role $CustomRole `
        -Member $runtimeMember `
        -Title $RunConditionTitle `
        -Expression $RunConditionExpression
    $iapBindingVerified = Test-ConditionalPolicyBinding `
        -Policy $projectPolicy `
        -Role "roles/iap.httpsResourceAccessor" `
        -Member $runtimeMember `
        -Title $IapConditionTitle `
        -Expression $IapConditionExpression
    $secretBindingVerified = Test-PolicyBinding `
        -Policy $secretPolicy -Role $CustomRole -Member $runtimeMember
    $selfSignerBindingVerified = Test-PolicyBinding `
        -Policy $runtimeServiceAccountPolicy `
        -Role "roles/iam.serviceAccountTokenCreator" `
        -Member $runtimeMember
    $gatewayActAsBindingVerified = Test-PolicyBinding `
        -Policy $gatewayServiceAccountPolicy `
        -Role "roles/iam.serviceAccountUser" `
        -Member $runtimeMember
    $customRolePermissionsVerified = @(
        Compare-Object `
            -ReferenceObject @($CustomRolePermissions | Sort-Object) `
            -DifferenceObject @($customRoleReadback.includedPermissions | Sort-Object)
    ).Count -eq 0
    $workflowServiceAccountReadback = [string]$workflowReadback.serviceAccount
    $workflowIdentityVerified = (
        $workflowServiceAccountReadback -eq $RuntimeServiceAccount -or
        $workflowServiceAccountReadback.EndsWith("/serviceAccounts/$RuntimeServiceAccount")
    )
    $schedulerIdentityVerified = [string]$schedulerReadback.httpTarget.oauthToken.serviceAccountEmail -eq $TriggerServiceAccount
    $schedulerUriVerified = [string]$schedulerReadback.httpTarget.uri -eq $WorkflowUri
    $schedulerBodyReadback = [Text.Encoding]::UTF8.GetString(
        [Convert]::FromBase64String([string]$schedulerReadback.httpTarget.body)
    )
    $schedulerBodyVerified = $schedulerBodyReadback -eq $SchedulerMessageBody
    $schedulerContentTypeVerified = (
        [string]$schedulerReadback.httpTarget.headers.'Content-Type' -eq "application/json"
    )

    if (-not $instanceBindingVerified) {
        throw "Watchdog readback failed: the exact-instance custom-role binding is missing."
    }
    if (-not $customRolePermissionsVerified) {
        throw "Watchdog readback failed: the custom-role permission set differs."
    }
    if (
        -not $runBindingVerified -or
        -not $iapBindingVerified -or
        -not $secretBindingVerified -or
        -not $selfSignerBindingVerified -or
        -not $gatewayActAsBindingVerified
    ) {
        throw "Watchdog readback failed: one or more exact gateway IAM bindings are missing."
    }
    if (-not $workflowIdentityVerified) {
        throw "Watchdog readback failed: the workflow service account does not match."
    }
    if (
        -not $schedulerIdentityVerified -or
        -not $schedulerUriVerified -or
        -not $schedulerBodyVerified -or
        -not $schedulerContentTypeVerified
    ) {
        throw "Watchdog readback failed: the scheduler target, identity, body, or content type does not match."
    }

    $testArguments = @(
        "workflows",
        "run",
        $WorkflowName,
        "--project=$ProjectId",
        "--location=$Region",
        "--data={}",
        "--format=json"
    )
    $testExecution = $null
    for ($testAttempt = 1; $testAttempt -le 9; $testAttempt++) {
        $testExecution = Invoke-GcloudWithRetry -Attempts 3 -DelaySeconds 5 `
            -Arguments $testArguments | ConvertFrom-Json
        if ([string]$testExecution.state -eq "SUCCEEDED") {
            break
        }
        if ($testAttempt -lt 9) {
            Start-Sleep -Seconds 10
        }
    }
    $testSucceeded = [string]$testExecution.state -eq "SUCCEEDED"
    if (-not $testSucceeded) {
        $testError = if ($testExecution.PSObject.Properties["error"]) {
            [string]$testExecution.error.context
        }
        else {
            ""
        }
        throw "Watchdog test execution did not succeed. $testError"
    }
    try {
        $testResult = [string]$testExecution.result | ConvertFrom-Json
    }
    catch {
        throw "Watchdog test execution did not return valid JSON."
    }
    if (
        $testResult.ok -ne $true -or
        [int]$testResult.healthStatus -ne 200 -or
        [string]$testResult.targetVersion -ne $ManifestUpstreamTokenVersion
    ) {
        throw "Watchdog test execution did not verify the exact gateway version and end-to-end health."
    }

    $gatewayAfterTest = Invoke-Gcloud run services describe $GatewayService `
        "--project=$ProjectId" "--region=$Region" --format=json | ConvertFrom-Json
    $gatewayMountedVersionsAfter = @(
        Get-GatewayMountedVersions `
            -GatewayDescription $gatewayAfterTest `
            -SecretName $UpstreamTokenSecret
    )
    $gatewayImageAfter = [string]@($gatewayAfterTest.spec.template.spec.containers)[0].image
    $gatewayServiceAccountAfter = [string]$gatewayAfterTest.spec.template.spec.serviceAccountName
    if (-not $gatewayServiceAccountAfter) {
        $gatewayServiceAccountAfter = [string]$gatewayAfterTest.template.serviceAccount
    }
    $latestReadyRevision = [string]$gatewayAfterTest.status.latestReadyRevisionName
    $latestTrafficPercent = @(
        $gatewayAfterTest.status.traffic | Where-Object {
            $_.latestRevision -eq $true -or
            [string]$_.revisionName -eq $latestReadyRevision
        } | ForEach-Object { [int]$_.percent } | Measure-Object -Sum
    ).Sum
    $otherTrafficPercent = @(
        $gatewayAfterTest.status.traffic | Where-Object {
            $_.latestRevision -ne $true -and
            [string]$_.revisionName -ne $latestReadyRevision
        } | ForEach-Object { [int]$_.percent } | Measure-Object -Sum
    ).Sum
    $gatewayReadbackVerified = (
        $gatewayMountedVersionsAfter.Count -ge 1 -and
        @(
            $gatewayMountedVersionsAfter | Where-Object {
                $_ -ne $ManifestUpstreamTokenVersion
            }
        ).Count -eq 0 -and
        $gatewayImageAfter -eq $GatewayImageBefore -and
        $gatewayServiceAccountAfter -eq $GatewayRuntimeServiceAccount -and
        $latestReadyRevision -and
        [int]$latestTrafficPercent -eq 100 -and
        [int]$otherTrafficPercent -eq 0
    )
    if (-not $gatewayReadbackVerified) {
        throw "Watchdog readback failed: Cloud Run did not preserve identity/image while serving the exact version at 100 percent traffic."
    }

    [ordered]@{
        ok = $true
        operationId = $OperationId
        project = $ProjectId
        instance = $Instance
        zone = $Zone
        workflow = $WorkflowName
        workflowRevision = [string]$workflowReadback.revisionId
        workflowServiceAccount = $RuntimeServiceAccount
        schedulerJob = $SchedulerJob
        schedule = $Schedule
        triggerServiceAccount = $TriggerServiceAccount
        exactInstanceBindingVerified = $instanceBindingVerified
        runBindingVerified = $runBindingVerified
        iapBindingVerified = $iapBindingVerified
        secretBindingVerified = $secretBindingVerified
        selfSignerBindingVerified = $selfSignerBindingVerified
        gatewayActAsBindingVerified = $gatewayActAsBindingVerified
        customRolePermissionsVerified = $customRolePermissionsVerified
        gatewayReadbackVerified = $gatewayReadbackVerified
        gatewayService = $GatewayService
        gatewayRevision = $latestReadyRevision
        gatewayMountedVersions = $gatewayMountedVersionsAfter
        manifestUpstreamTokenVersion = $ManifestUpstreamTokenVersion
        workflowIdentityVerified = $workflowIdentityVerified
        schedulerIdentityVerified = $schedulerIdentityVerified
        schedulerUriVerified = $schedulerUriVerified
        schedulerBodyVerified = $schedulerBodyVerified
        schedulerContentTypeVerified = $schedulerContentTypeVerified
        testExecution = [string]$testExecution.name
        testExecutionState = [string]$testExecution.state
        testExecutionResult = [string]$testExecution.result
    } | ConvertTo-Json -Depth 6
}
finally {
    Remove-Item Env:CLOUDSDK_AUTH_ACCESS_TOKEN -ErrorAction SilentlyContinue
}
