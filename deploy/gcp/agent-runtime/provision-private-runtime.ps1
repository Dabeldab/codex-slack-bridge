# AgentChat/direct_codex 2026-08-04T15:00:00Z: quiesce support reminder timer during promotion.
param(
    [string]$ProjectId = "gen-lang-client-0051653266",
    [string]$Region = "us-central1",
    [string]$Zone = "us-central1-a",
    [string]$Instance = "nova-agent-runtime-staging",
    [string]$Network = "nova-agent-runtime",
    [string]$Subnet = "nova-agent-us-central1",
    [string]$SubnetRange = "10.42.0.0/24",
    [string]$Router = "nova-agent-router",
    [string]$Nat = "nova-agent-nat",
    [string]$EgressAddress = "nova-agent-egress",
    [string]$ServiceAccountId = "nova-agent-runtime",
    [string]$RoryServiceAccountId = "nova-rory-cloud-ops",
    [string]$MachineType = "e2-standard-4",
    [int]$BootDiskGb = 100,
    [string]$StateDisk = "nova-agent-runtime-state",
    [int]$StateDiskGb = 50,
    [string]$CodexVersion = "0.144.4",
    [string]$SingaporeSourceCommit = "dea78b3ef16eca55323f87912e73060d6b8e1b4e",
    [ValidateSet("access-token", "device")]
    [string]$CodexAuthMode = "access-token",
    [ValidateRange(120, 3600)]
    [int]$PromotionWatchdogHoldSeconds = 900,
    [switch]$UpdateExisting,
    [switch]$Apply
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path

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

function Test-GcloudResource([string[]]$Arguments) {
    $priorPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        & $script:Gcloud @Arguments 1>$null 2>$null
        return $LASTEXITCODE -eq 0
    }
    finally { $ErrorActionPreference = $priorPreference }
}

function Get-PrivateRuntimeInstanceStatus {
    $status = Invoke-Gcloud compute instances describe $Instance `
        "--project=$ProjectId" "--zone=$Zone" "--format=value(status)" |
        Select-Object -First 1
    if (-not $status) {
        throw "Could not read the private runtime instance status."
    }
    return ([string]$status).Trim().ToUpperInvariant()
}

function Start-PrivateRuntimeInstanceWithRetry(
    [int]$Attempts = 8,
    [int]$MaximumDelaySeconds = 30
) {
    $lastStartError = ""
    for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
        $status = Get-PrivateRuntimeInstanceStatus
        if ($status -eq "RUNNING") {
            return $status
        }
        if ($status -eq "TERMINATED") {
            try {
                Invoke-Gcloud compute instances start $Instance `
                    "--project=$ProjectId" "--zone=$Zone" --quiet | Out-Null
            }
            catch {
                $lastStartError = $_.Exception.Message
            }
        }
        elseif ($status -notin @("PROVISIONING", "STAGING", "STOPPING", "REPAIRING")) {
            throw "Refusing automatic start from unsupported instance state: $status"
        }

        if ($attempt -lt $Attempts) {
            $delaySeconds = [Math]::Min($MaximumDelaySeconds, 5 * $attempt)
            Start-Sleep -Seconds $delaySeconds
        }
    }

    $finalStatus = Get-PrivateRuntimeInstanceStatus
    $details = if ($lastStartError) { " Last start error: $lastStartError" } else { "" }
    throw "Private runtime did not reach RUNNING after $Attempts attempts; final state is $finalStatus.$details"
}

function Set-PrivateRuntimeWatchdogHold([int]$HoldSeconds) {
    $holdUntil = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds() + $HoldSeconds
    Invoke-Gcloud compute instances add-labels $Instance `
        "--project=$ProjectId" "--zone=$Zone" `
        "--labels=nova-watchdog-hold-until=$holdUntil" --quiet | Out-Null
    return $holdUntil
}

function Clear-PrivateRuntimeWatchdogHold {
    Invoke-Gcloud compute instances remove-labels $Instance `
        "--project=$ProjectId" "--zone=$Zone" `
        --labels=nova-watchdog-hold-until --quiet | Out-Null
}

function Resolve-SecretVersion([string]$SecretId) {
    if (-not (Test-GcloudResource @("secrets", "describe", $SecretId, "--project=$ProjectId", "--billing-project=$ProjectId"))) {
        return ""
    }
    try {
        $version = Invoke-Gcloud secrets versions describe latest "--secret=$SecretId" `
            "--project=$ProjectId" "--format=value(name)" "--billing-project=$ProjectId" | Select-Object -First 1
        if (-not $version) { return "" }
        return ([string]$version).Trim().Split('/')[-1]
    }
    catch { return "" }
}

function Get-PrivateRuntimeInvariantFailures(
    $InstanceReadback,
    [string]$ExpectedServiceAccount,
    [string]$ExpectedStateDisk
) {
    $failures = [System.Collections.Generic.List[string]]::new()
    $accessConfigs = @(
        foreach ($interface in @($InstanceReadback.networkInterfaces)) {
            if ($interface.PSObject.Properties["accessConfigs"]) {
                @($interface.accessConfigs)
            }
        }
    )
    if ($accessConfigs.Count -ne 0) {
        $failures.Add("the agent VM has a public address")
    }

    $serviceAccounts = @($InstanceReadback.serviceAccounts)
    if ($serviceAccounts.Count -ne 1 -or [string]$serviceAccounts[0].email -ne $ExpectedServiceAccount) {
        $failures.Add("the dedicated runtime service account is not attached exactly once")
    }
    if (-not $InstanceReadback.PSObject.Properties["shieldedInstanceConfig"] -or
        $InstanceReadback.shieldedInstanceConfig.enableSecureBoot -ne $true) {
        $failures.Add("Shielded VM Secure Boot is not enabled")
    }

    $stateAttachments = @(
        $InstanceReadback.disks | Where-Object {
            [string]$_.source -match ("/disks/" + [regex]::Escape($ExpectedStateDisk) + "$")
        }
    )
    if ($stateAttachments.Count -ne 1 -or $stateAttachments[0].autoDelete -eq $true) {
        $failures.Add("the non-auto-delete persistent state disk is not attached exactly once")
    }
    return @($failures)
}

Enable-ApplicationDefaultToken
try {
    $ProjectNumber = (Invoke-Gcloud projects describe $ProjectId "--format=value(projectNumber)" "--billing-project=$ProjectId" | Select-Object -First 1).Trim()
    if (-not $ProjectNumber) { throw "Could not resolve the GCP project number." }
    $ServiceAccount = "$ServiceAccountId@$ProjectId.iam.gserviceaccount.com"
    $RoryServiceAccount = "$RoryServiceAccountId@$ProjectId.iam.gserviceaccount.com"
    $SourceBucket = "nova-agent-runtime-source-$ProjectNumber"
    $Commit = (git -C $RepoRoot rev-parse HEAD).Trim()
    if (-not $Commit) { throw "Could not resolve the source commit." }
    $remoteMainLines = @(git -C $RepoRoot ls-remote --exit-code origin refs/heads/main)
    $remoteMainExitCode = $LASTEXITCODE
    $remoteMainLine = $remoteMainLines | Select-Object -First 1
    if ($remoteMainExitCode -ne 0 -or -not $remoteMainLine) {
        throw "Could not resolve the GitHub origin/main commit."
    }
    $GitHubMainCommit = ([string]$remoteMainLine).Split()[0]
    $SourceObject = "releases/$Commit.tar.gz"
    $SourceUri = "gs://$SourceBucket/$SourceObject"
    if ($SingaporeSourceCommit -notmatch '^[0-9a-f]{40}$') { throw "SingaporeSourceCommit must be a full Git commit." }
    $SingaporeSourceObject = "components/singapore/$SingaporeSourceCommit.tar.gz"
    $SingaporeSourceUri = "gs://$SourceBucket/$SingaporeSourceObject"
    $SourceArtifactReady = Test-GcloudResource @(
        "storage", "objects", "describe", $SourceUri, "--project=$ProjectId"
    )
    $SingaporeSourceArtifactReady = Test-GcloudResource @(
        "storage", "objects", "describe", $SingaporeSourceUri, "--project=$ProjectId"
    )
    $OperationId = "gcp-agent-runtime:${ProjectId}:${Instance}:${Commit}"
    $InstanceExists = Test-GcloudResource @(
        "compute", "instances", "describe", $Instance, "--project=$ProjectId", "--zone=$Zone"
    )
    $CurrentSourceCommit = ""
    $ExistingRuntimeInvariantFailures = @()
    if ($InstanceExists) {
        $existingInstance = Invoke-Gcloud compute instances describe $Instance `
            "--project=$ProjectId" "--zone=$Zone" --format=json | ConvertFrom-Json
        foreach ($item in @($existingInstance.metadata.items)) {
            if ([string]$item.key -eq "nova-source-commit") {
                $CurrentSourceCommit = [string]$item.value
                break
            }
        }
        $ExistingRuntimeInvariantFailures = @(
            Get-PrivateRuntimeInvariantFailures $existingInstance $ServiceAccount $StateDisk
        )
    }

    $secretDefinitions = @(
        @{ id = "nova-agents-slack-app-token"; path = "/run/nova-secrets/slack-app-token"; owner = "root"; group = "root"; required = $true },
        @{ id = "nova-agents-slack-bot-token"; path = "/run/nova-secrets/slack-bot-token"; owner = "root"; group = "root"; required = $true },
        @{ id = "nova-agents-gmail-oauth-token"; path = "/run/nova-secrets/gmail-oauth-token"; owner = "root"; group = "root"; required = $true },
        @{ id = "nova-agents-salesforce-client-id"; path = "/run/nova-secrets/salesforce-client-id"; owner = "nova-salesforce-broker"; group = "nova-salesforce-broker"; required = $true },
        @{ id = "nova-agents-salesforce-client-secret"; path = "/run/nova-secrets/salesforce-client-secret"; owner = "nova-salesforce-broker"; group = "nova-salesforce-broker"; required = $true },
        @{ id = "nova-agents-salesforce-login-url"; path = "/run/nova-secrets/salesforce-login-url"; owner = "nova-salesforce-broker"; group = "nova-salesforce-broker"; required = $true },
        @{ id = "nova-agents-salesforce-instance-url"; path = "/run/nova-secrets/salesforce-instance-url"; owner = "nova-salesforce-broker"; group = "nova-salesforce-broker"; required = $true },
        @{ id = "nova-agents-pos-main-api-cohort-ro"; path = "/run/nova-secrets/pos-main-api-cohort-ro"; owner = "nova-salesforce-broker"; group = "nova-salesforce-broker"; required = $true },
        @{ id = "nova-agents-novapos-developer-username"; path = "/run/nova-secrets/novapos-developer-username"; owner = "nova-salesforce-broker"; group = "nova-salesforce-broker"; required = $true },
        @{ id = "nova-agents-novapos-developer-password"; path = "/run/nova-secrets/novapos-developer-password"; owner = "nova-salesforce-broker"; group = "nova-salesforce-broker"; required = $true },
        @{ id = "nova-agents-chargify-api-key"; path = "/run/nova-secrets/chargify-api-key"; owner = "nova-maxio-broker"; group = "nova-maxio-broker"; required = $true },
        @{ id = "nova-agents-chargify-base-url"; path = "/run/nova-secrets/chargify-base-url"; owner = "nova-maxio-broker"; group = "nova-maxio-broker"; required = $true },
        @{ id = "nova-agents-rescue-user"; path = "/run/nova-secrets/rescue-user"; owner = "nova-rescue-broker"; group = "nova-rescue-broker"; required = $true },
        @{ id = "nova-agents-rescue-password"; path = "/run/nova-secrets/rescue-password"; owner = "nova-rescue-broker"; group = "nova-rescue-broker"; required = $true },
        @{ id = "nova-agents-rescue-base"; path = "/run/nova-secrets/rescue-base"; owner = "nova-rescue-broker"; group = "nova-rescue-broker"; required = $true },
        @{ id = "nova-agents-rescue-node-id"; path = "/run/nova-secrets/rescue-node-id"; owner = "nova-rescue-broker"; group = "nova-rescue-broker"; required = $true },
        @{ id = "nova-agents-zoom-oauth-client-id"; path = "/run/nova-secrets/zoom-oauth-client-id"; owner = "root"; group = "nova-zoom-credentials"; mode = "0440"; required = $true },
        @{ id = "nova-agents-zoom-oauth-client-secret"; path = "/run/nova-secrets/zoom-oauth-client-secret"; owner = "root"; group = "nova-zoom-credentials"; mode = "0440"; required = $true },
        @{ id = "nova-agents-zoom-oauth-refresh-token"; path = "/run/nova-secrets/zoom-oauth-refresh-token"; owner = "root"; group = "nova-zoom-credentials"; mode = "0440"; required = $true },
        @{ id = "nova-agents-zoom-s2s-account-id"; path = "/run/nova-secrets/zoom-s2s-account-id"; owner = "root"; group = "nova-zoom-credentials"; mode = "0440"; required = $true },
        @{ id = "nova-agents-zoom-s2s-client-id"; path = "/run/nova-secrets/zoom-s2s-client-id"; owner = "root"; group = "nova-zoom-credentials"; mode = "0440"; required = $true },
        @{ id = "nova-agents-zoom-s2s-client-secret"; path = "/run/nova-secrets/zoom-s2s-client-secret"; owner = "root"; group = "nova-zoom-credentials"; mode = "0440"; required = $true },
        @{ id = "nova-agents-zoom-team-chat-sender-user-id"; path = "/run/nova-secrets/zoom-team-chat-sender-user-id"; owner = "root"; group = "nova-zoom-credentials"; mode = "0440"; required = $true },
        @{ id = "nova-agents-zoom-singapore-julio-contact"; path = "/run/nova-secrets/zoom-singapore-julio-contact"; owner = "root"; group = "nova-zoom-credentials"; mode = "0440"; required = $true },
        @{ id = "nova-agents-zoom-internal-wiko-contact"; path = "/run/nova-secrets/zoom-internal-wiko-contact"; owner = "root"; group = "nova-zoom-credentials"; mode = "0440"; required = $true },
        @{ id = "nova-agents-singapore-gmail-client"; path = "/run/nova-secrets/singapore-gmail-client"; owner = "nova-singapore-broker"; group = "nova-singapore-broker"; required = $true },
        @{ id = "nova-agents-singapore-gmail-token"; path = "/run/nova-secrets/singapore-gmail-token"; owner = "nova-singapore-broker"; group = "nova-singapore-broker"; required = $true },
        @{ id = "nova-agents-singapore-server-catalog"; path = "/run/nova-secrets/singapore-server-catalog"; owner = "nova-singapore-broker"; group = "nova-singapore-broker"; required = $true },
        @{ id = "nova-agents-singapore-salesforce-identity-map"; path = "/run/nova-secrets/singapore-salesforce-identity-map"; owner = "nova-singapore-broker"; group = "nova-singapore-broker"; required = $true },
        @{ id = "nova-agents-github-app-id"; path = "/run/nova-secrets/github-app-id"; owner = "nova-cloud-broker"; group = "nova-cloud-broker"; required = $true },
        @{ id = "nova-agents-github-app-installation-id"; path = "/run/nova-secrets/github-app-installation-id"; owner = "nova-cloud-broker"; group = "nova-cloud-broker"; required = $true },
        @{ id = "nova-agents-github-app-private-key"; path = "/run/nova-secrets/github-app-private-key"; owner = "nova-cloud-broker"; group = "nova-cloud-broker"; required = $true },
        @{ id = "nova-agents-github-user-token"; path = "/run/nova-secrets/github-user-token"; owner = "nova-cloud-broker"; group = "nova-cloud-broker"; required = $true },
        @{ id = "nova-agents-google-workspace-adc"; path = "/run/nova-secrets/google-workspace-adc"; owner = "nova-cloud-broker"; group = "nova-cloud-broker"; required = $true },
        @{ id = "nova-agents-operator-signing-key"; path = "/run/nova-secrets/operator-message-key"; owner = "root"; group = "root"; required = $true },
        @{ id = "nova-command-center-upstream-token"; path = "/run/nova-secrets/command-center-proxy-token"; owner = "root"; group = "root"; required = $true },
        @{ id = "nova-agents-openai-api-key"; path = "/run/nova-secrets/openai-api-key"; owner = "nova-runtime"; group = "nova-runtime"; mode = "0440"; required = $false }
    )
    if ($CodexAuthMode -eq "access-token") {
        $secretDefinitions += @{
            id = "nova-agents-codex-access-token"
            path = "/run/nova-secrets/codex-access-token"
            owner = "root"
            group = "root"
            required = $true
        }
    }

    $resolvedSecrets = @()
    $missingRequired = @()
    $missingOptional = @()
    foreach ($definition in $secretDefinitions) {
        $version = Resolve-SecretVersion ([string]$definition.id)
        if (-not $version) {
            if ([bool]$definition.required) { $missingRequired += [string]$definition.id }
            else { $missingOptional += [string]$definition.id }
            continue
        }
        $resolvedSecrets += [ordered]@{
            id = [string]$definition.id
            version = $version
            path = [string]$definition.path
            owner = [string]$definition.owner
            group = [string]$definition.group
            mode = if ($definition.ContainsKey("mode")) { [string]$definition["mode"] } else { "0400" }
            required = [bool]$definition.required
        }
    }

    $plan = [ordered]@{
        operationId = $OperationId
        mode = if ($Apply) { "apply" } else { "plan" }
        project = $ProjectId
        region = $Region
        zone = $Zone
        instance = $Instance
        instanceExists = $InstanceExists
        updateExistingRequested = [bool]$UpdateExisting
        deploymentAction = if ($UpdateExisting) { "guarded_in_place_promotion" } else { "create_new_private_vm" }
        currentSourceCommit = $CurrentSourceCommit
        existingRuntimeInvariantReady = $InstanceExists -and $ExistingRuntimeInvariantFailures.Count -eq 0
        existingRuntimeInvariantFailures = $ExistingRuntimeInvariantFailures
        machineType = $MachineType
        bootDiskGb = $BootDiskGb
        stateDisk = $StateDisk
        stateDiskGb = $StateDiskGb
        stateDiskAutoDelete = $false
        privateAddressOnly = $true
        network = $Network
        subnet = $Subnet
        subnetRange = $SubnetRange
        staticEgressAddress = $EgressAddress
        serviceAccount = $ServiceAccount
        roryCloudServiceAccount = $RoryServiceAccount
        sourceCommit = $Commit
        githubMainCommit = $GitHubMainCommit
        sourceMatchesGitHubMain = $Commit -eq $GitHubMainCommit
        sourceBucket = $SourceBucket
        sourceObject = $SourceObject
        sourceArtifactReady = $SourceArtifactReady
        singaporeSourceCommit = $SingaporeSourceCommit
        singaporeSourceObject = $SingaporeSourceObject
        singaporeSourceArtifactReady = $SingaporeSourceArtifactReady
        codexVersion = $CodexVersion
        codexAuthMode = $CodexAuthMode
        codexAuth = if ($CodexAuthMode -eq "device") {
            "Interactive ChatGPT device-code login on the private VM; no Platform API key"
        } else {
            "ChatGPT workspace access token through Codex CLI; no Platform API key"
        }
        interactiveCodexAuthRequired = $CodexAuthMode -eq "device"
        promotionWatchdogHoldSeconds = $PromotionWatchdogHoldSeconds
        unintendedStopRecovery = "external_workflow_after_expiring_maintenance_hold"
        requiredSecretsReady = $missingRequired.Count -eq 0
        missingRequiredSecrets = $missingRequired
        missingOptionalSecrets = $missingOptional
        startsSlackOrWriters = if ($UpdateExisting) { "only_after_bootstrap_preflight" } else { $false }
    }

    if (-not $Apply) {
        $plan | ConvertTo-Json -Depth 8
        exit 0
    }
    if ($missingRequired.Count -gt 0) {
        throw "Required Secret Manager versions are missing: $($missingRequired -join ', ')"
    }
    if ($Commit -ne $GitHubMainCommit) {
        throw "Refusing deployment: local HEAD $Commit is not the GitHub origin/main commit $GitHubMainCommit."
    }
    if (-not $SourceArtifactReady) {
        throw "Refusing deployment: the tested Cloud Build artifact does not exist at $SourceUri."
    }
    if (-not $SingaporeSourceArtifactReady) {
        throw "Refusing deployment: the pinned Singapore component artifact does not exist at $SingaporeSourceUri."
    }
    if (git -C $RepoRoot status --porcelain) {
        throw "The GCP runtime source worktree must be clean before deployment."
    }
    if ($UpdateExisting -and -not $InstanceExists) {
        throw "UpdateExisting requires the private runtime instance to already exist: $Instance"
    }
    if ($UpdateExisting -and $ExistingRuntimeInvariantFailures.Count -gt 0) {
        throw "Refusing promotion because the existing private runtime failed invariant checks: $($ExistingRuntimeInvariantFailures -join '; ')"
    }
    if (-not $UpdateExisting -and $InstanceExists) {
        throw "Instance already exists; use -UpdateExisting for a guarded immutable promotion: $Instance"
    }

    $apis = @(
        "compute.googleapis.com",
        "iam.googleapis.com",
        "iamcredentials.googleapis.com",
        "cloudasset.googleapis.com",
        "cloudresourcemanager.googleapis.com",
        "serviceusage.googleapis.com",
        "secretmanager.googleapis.com",
        "storage.googleapis.com",
        "iap.googleapis.com",
        "oslogin.googleapis.com",
        "logging.googleapis.com",
        "monitoring.googleapis.com"
    )
    Invoke-Gcloud services enable @apis "--project=$ProjectId" --quiet | Out-Null

    if (-not (Test-GcloudResource @("iam", "service-accounts", "describe", $ServiceAccount, "--project=$ProjectId"))) {
        Invoke-Gcloud iam service-accounts create $ServiceAccountId "--project=$ProjectId" `
            --display-name="Nova private agent runtime" --quiet | Out-Null
    }
    if (-not (Test-GcloudResource @("iam", "service-accounts", "describe", $RoryServiceAccount, "--project=$ProjectId"))) {
        Invoke-Gcloud iam service-accounts create $RoryServiceAccountId "--project=$ProjectId" `
            --display-name="Rory operator cloud access" --quiet | Out-Null
    }

    foreach ($role in @(
        "roles/owner",
        "roles/viewer",
        "roles/cloudasset.viewer",
        "roles/iam.serviceAccountTokenCreator",
        "roles/serviceusage.serviceUsageViewer",
        "roles/logging.viewer",
        "roles/monitoring.viewer",
        "roles/secretmanager.secretAccessor",
        "roles/secretmanager.viewer"
    )) {
        Invoke-Gcloud projects add-iam-policy-binding $ProjectId "--member=serviceAccount:$RoryServiceAccount" `
            "--role=$role" --condition=None "--billing-project=$ProjectId" --quiet | Out-Null
    }
    Invoke-Gcloud iam service-accounts add-iam-policy-binding $RoryServiceAccount `
        "--project=$ProjectId" "--member=serviceAccount:$ServiceAccount" `
        --role=roles/iam.serviceAccountTokenCreator --quiet | Out-Null

    foreach ($definition in $resolvedSecrets) {
        Invoke-Gcloud secrets add-iam-policy-binding $definition.id "--project=$ProjectId" `
            "--member=serviceAccount:$ServiceAccount" --role=roles/secretmanager.secretAccessor --quiet | Out-Null
    }
    foreach ($role in @("roles/logging.logWriter", "roles/monitoring.metricWriter")) {
        Invoke-Gcloud projects add-iam-policy-binding $ProjectId "--member=serviceAccount:$ServiceAccount" `
            "--role=$role" --condition=None "--billing-project=$ProjectId" --quiet | Out-Null
    }

    if (-not (Test-GcloudResource @("compute", "networks", "describe", $Network, "--project=$ProjectId"))) {
        Invoke-Gcloud compute networks create $Network "--project=$ProjectId" --subnet-mode=custom --quiet | Out-Null
    }
    if (-not (Test-GcloudResource @("compute", "networks", "subnets", "describe", $Subnet, "--project=$ProjectId", "--region=$Region"))) {
        Invoke-Gcloud compute networks subnets create $Subnet "--project=$ProjectId" "--region=$Region" `
            "--network=$Network" "--range=$SubnetRange" --enable-private-ip-google-access --quiet | Out-Null
    }
    if (-not (Test-GcloudResource @("compute", "addresses", "describe", $EgressAddress, "--project=$ProjectId", "--region=$Region"))) {
        Invoke-Gcloud compute addresses create $EgressAddress "--project=$ProjectId" "--region=$Region" --quiet | Out-Null
    }
    if (-not (Test-GcloudResource @("compute", "routers", "describe", $Router, "--project=$ProjectId", "--region=$Region"))) {
        Invoke-Gcloud compute routers create $Router "--project=$ProjectId" "--region=$Region" "--network=$Network" --quiet | Out-Null
    }
    if (-not (Test-GcloudResource @("compute", "routers", "nats", "describe", $Nat, "--project=$ProjectId", "--region=$Region", "--router=$Router"))) {
        Invoke-Gcloud compute routers nats create $Nat "--project=$ProjectId" "--region=$Region" "--router=$Router" `
            --nat-all-subnet-ip-ranges "--nat-external-ip-pool=$EgressAddress" --enable-endpoint-independent-mapping --quiet | Out-Null
    }
    else {
        Invoke-Gcloud compute routers nats update $Nat "--project=$ProjectId" "--region=$Region" "--router=$Router" `
            --nat-all-subnet-ip-ranges "--nat-external-ip-pool=$EgressAddress" --enable-endpoint-independent-mapping --quiet | Out-Null
    }
    if (-not (Test-GcloudResource @("compute", "firewall-rules", "describe", "nova-agent-allow-iap-ssh", "--project=$ProjectId"))) {
        Invoke-Gcloud compute firewall-rules create nova-agent-allow-iap-ssh "--project=$ProjectId" `
            "--network=$Network" --direction=INGRESS --action=ALLOW --rules=tcp:22 `
            --source-ranges=35.235.240.0/20 --target-tags=nova-agent-runtime --quiet | Out-Null
    }

    if (-not (Test-GcloudResource @("compute", "disks", "describe", $StateDisk, "--project=$ProjectId", "--zone=$Zone"))) {
        Invoke-Gcloud compute disks create $StateDisk "--project=$ProjectId" "--zone=$Zone" `
            "--size=${StateDiskGb}GB" --type=pd-balanced `
            "--labels=application=nova-agent-runtime,environment=staging,data=state" --quiet | Out-Null
    }

    $bucketUri = "gs://$SourceBucket"
    if (-not (Test-GcloudResource @("storage", "buckets", "describe", $bucketUri, "--project=$ProjectId"))) {
        Invoke-Gcloud storage buckets create $bucketUri "--project=$ProjectId" "--location=$Region" `
            --uniform-bucket-level-access --public-access-prevention --quiet | Out-Null
    }
    Invoke-Gcloud storage buckets add-iam-policy-binding $bucketUri `
        "--member=serviceAccount:$ServiceAccount" --role=roles/storage.objectViewer --quiet | Out-Null

    $manifestPath = Join-Path ([IO.Path]::GetTempPath()) ("nova-agent-secret-manifest-" + [guid]::NewGuid().ToString("N") + ".json")
    try {
        $manifestJson = [ordered]@{ project_id = $ProjectId; secrets = $resolvedSecrets } | ConvertTo-Json -Depth 8
        $utf8WithoutBom = [Text.UTF8Encoding]::new($false)
        [IO.File]::WriteAllText($manifestPath, $manifestJson, $utf8WithoutBom)

        $metadata = "enable-oslogin=TRUE,block-project-ssh-keys=TRUE,serial-port-enable=FALSE,nova-source-bucket=$SourceBucket,nova-source-object=$SourceObject,nova-source-commit=$Commit,nova-singapore-source-object=$SingaporeSourceObject,nova-singapore-source-commit=$SingaporeSourceCommit,nova-codex-version=$CodexVersion,nova-codex-auth-mode=$CodexAuthMode,nova-state-disk=$StateDisk"
        $metadataFiles = "startup-script=$(Join-Path $PSScriptRoot 'bootstrap-private-runtime.sh'),nova-secret-manifest=$manifestPath"
        if ($UpdateExisting) {
            Invoke-Gcloud compute instances add-metadata $Instance "--project=$ProjectId" "--zone=$Zone" `
                "--metadata=$metadata" "--metadata-from-file=$metadataFiles" --quiet | Out-Null
            # Older releases do not have the local health-repair timer. Stop it
            # when present so a deliberate promotion shutdown is never treated
            # as a service failure.
            try {
                Invoke-Gcloud compute ssh $Instance "--project=$ProjectId" "--zone=$Zone" `
                    "--billing-project=$ProjectId" --tunnel-through-iap --quiet `
                    "--command=sudo -n /bin/systemctl disable --now nova-command-center-healthcheck.timer" | Out-Null
            }
            catch { }
            try {
                Invoke-Gcloud compute ssh $Instance "--project=$ProjectId" "--zone=$Zone" `
                    "--billing-project=$ProjectId" --tunnel-through-iap --quiet `
                    "--command=sudo -n /bin/systemctl disable --now nova-runtime-recovery.timer" | Out-Null
            }
            catch { }
            # Disable the currently verified consumers before reboot. This
            # closes the systemd boot race while the new startup script is
            # installing its transient preflight gate.
            Invoke-Gcloud compute ssh $Instance "--project=$ProjectId" "--zone=$Zone" `
                "--billing-project=$ProjectId" --tunnel-through-iap --quiet `
                "--command=sudo -n /bin/systemctl disable --now nova-command-center.service nova-slack-bridge.service" | Out-Null
            # The release being upgraded may predate the read-only Zoom timer.
            # Quiesce it when present without turning an absent optional unit
            # into a failed promotion after the primary consumers are stopped.
            try {
                Invoke-Gcloud compute ssh $Instance "--project=$ProjectId" "--zone=$Zone" `
                    "--billing-project=$ProjectId" --tunnel-through-iap --quiet `
                    "--command=sudo -n /bin/systemctl disable --now nova-zoom-monitor.timer nova-support-shift-reminders.timer" | Out-Null
            }
            catch { }
            # A graceful stop lets systemd flush SQLite and service journals.
            # The persistent activation marker then requires the new bootstrap
            # to pass provider/MCP preflight before it restarts production.
            # The expiring label prevents the external watchdog from racing an
            # intentional reboot, but cannot suppress recovery indefinitely if
            # this promotion process is interrupted after the stop.
            $maintenanceHoldUntil = Set-PrivateRuntimeWatchdogHold $PromotionWatchdogHoldSeconds
            $promotionRestartVerified = $false
            $promotionFailure = $null
            $compensatingStartFailure = $null
            try {
                Invoke-Gcloud compute instances stop $Instance `
                    "--project=$ProjectId" "--zone=$Zone" --quiet | Out-Null
                Start-PrivateRuntimeInstanceWithRetry | Out-Null
                $promotionRestartVerified = $true
            }
            catch {
                $promotionFailure = $_
            }
            finally {
                if (-not $promotionRestartVerified) {
                    try {
                        Start-PrivateRuntimeInstanceWithRetry | Out-Null
                        $promotionRestartVerified = $true
                    }
                    catch {
                        $compensatingStartFailure = $_
                    }
                }
                if ($promotionRestartVerified) {
                    try {
                        Clear-PrivateRuntimeWatchdogHold
                    }
                    catch {
                        Write-Warning "The runtime is RUNNING, but the watchdog hold label could not be cleared. It will expire automatically."
                    }
                }
            }
            if ($promotionFailure) {
                if ($promotionRestartVerified) {
                    throw "Promotion aborted after a restart failure, but the compensating start restored the VM to RUNNING: $($promotionFailure.Exception.Message)"
                }
                $compensationDetails = if ($compensatingStartFailure) {
                    $compensatingStartFailure.Exception.Message
                }
                else {
                    "no compensating-start error was captured"
                }
                throw "Promotion stopped the runtime and could not verify recovery. The external watchdog may restart it after hold epoch $maintenanceHoldUntil. Promotion error: $($promotionFailure.Exception.Message) Compensating start: $compensationDetails"
            }
        }
        else {
            Invoke-Gcloud compute instances create $Instance "--project=$ProjectId" "--zone=$Zone" `
                "--machine-type=$MachineType" "--subnet=$Subnet" --no-address `
                "--service-account=$ServiceAccount" --scopes=https://www.googleapis.com/auth/cloud-platform `
                --image-family=debian-12 --image-project=debian-cloud `
                "--boot-disk-size=${BootDiskGb}GB" --boot-disk-type=pd-balanced `
                "--disk=name=$StateDisk,device-name=$StateDisk,mode=rw,boot=no,auto-delete=no" `
                --shielded-secure-boot --shielded-vtpm --shielded-integrity-monitoring `
                --tags=nova-agent-runtime `
                "--metadata=$metadata" "--metadata-from-file=$metadataFiles" `
                "--labels=application=nova-agent-runtime,environment=staging" --quiet | Out-Null
        }
    }
    finally {
        Remove-Item -LiteralPath $manifestPath -Force -ErrorAction SilentlyContinue
    }

    $instanceReadback = Invoke-Gcloud compute instances describe $Instance "--project=$ProjectId" "--zone=$Zone" --format=json | ConvertFrom-Json
    $readbackFailures = @(
        Get-PrivateRuntimeInvariantFailures $instanceReadback $ServiceAccount $StateDisk
    )
    if ($readbackFailures.Count -gt 0) {
        throw "Readback failed: $($readbackFailures -join '; ')"
    }

    $egressIp = (Invoke-Gcloud compute addresses describe $EgressAddress "--project=$ProjectId" "--region=$Region" "--format=value(address)" | Select-Object -First 1).Trim()
    [ordered]@{
        ok = $true
        operationId = $OperationId
        project = $ProjectId
        instance = $Instance
        zone = $Zone
        internalIp = [string]$instanceReadback.networkInterfaces[0].networkIP
        publicAddressAttached = $false
        staticEgressIp = $egressIp
        stateDisk = $StateDisk
        stateDiskAutoDelete = $false
        serviceAccount = $ServiceAccount
        sourceCommit = $Commit
        githubMainCommit = $GitHubMainCommit
        sourceArtifact = $SourceUri
        sourceArtifactVerified = $true
        deploymentAction = if ($UpdateExisting) { "guarded_in_place_promotion" } else { "create_new_private_vm" }
        previousSourceCommit = $CurrentSourceCommit
        codexAuthMode = $CodexAuthMode
        interactiveCodexAuthRequired = $CodexAuthMode -eq "device"
        secrets = @($resolvedSecrets | ForEach-Object { @{ id = $_.id; version = $_.version } })
        missingOptionalSecrets = $missingOptional
        slackAndWritersStarted = if ($UpdateExisting) { "only_after_bootstrap_preflight" } else { $false }
    } | ConvertTo-Json -Depth 8
}
finally {
    Remove-Item Env:CLOUDSDK_AUTH_ACCESS_TOKEN -ErrorAction SilentlyContinue
}
