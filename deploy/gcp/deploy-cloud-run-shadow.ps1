[CmdletBinding()]
param(
    [string]$ProjectId = "gen-lang-client-0051653266",
    [string]$ProjectNumber = "63366976264",
    [string]$Region = "us-central1",
    [string]$Service = "nova-command-center-shadow",
    [string]$Repository = "nova-agent-shadow",
    [string]$ServiceAccountName = "nova-command-center-shadow",
    [string[]]$AllowedUserEmail,
    [string]$ClientIdSecret = "nova-command-center-google-client-id",
    [string]$ClientSecretSecret = "nova-command-center-google-client-secret",
    [string]$AllowedEmailsSecret = "nova-command-center-google-allowed-emails",
    [switch]$EnablePrivateGateway,
    [string]$UpstreamUrl = "http://10.42.0.2:17866",
    [string]$UpstreamTokenSecret = "nova-command-center-upstream-token",
    [int]$UpstreamTokenVersion = 0,
    [string]$VPCNetwork = "nova-agent-runtime",
    [string]$VPCSubnet = "nova-agent-us-central1",
    [string]$VPCNetworkTag = "nova-command-center-proxy",
    [switch]$OAuthRedirectConfigured,
    [switch]$Apply
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path

function Resolve-Gcloud {
    $command = Get-Command gcloud.cmd -ErrorAction SilentlyContinue
    if (-not $command) {
        $command = Get-Command gcloud -ErrorAction SilentlyContinue
    }
    if (-not $command) {
        throw "Google Cloud CLI was not found."
    }
    return $command.Source
}

function Invoke-Gcloud {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    & $script:Gcloud @Arguments "--billing-project=$ProjectId"
    if ($LASTEXITCODE -ne 0) {
        throw "gcloud command failed with exit code $LASTEXITCODE."
    }
}

function Test-GcloudResource {
    param([Parameter(Mandatory = $true)][scriptblock]$Command)
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        & $Command *> $null
        $resourceExitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    return $resourceExitCode -eq 0
}

function Ensure-ServiceIdentity {
    param([Parameter(Mandatory = $true)][string]$ServiceName)

    if ([string]::IsNullOrWhiteSpace($env:CLOUDSDK_AUTH_ACCESS_TOKEN)) {
        throw "A Google Cloud access token is required to generate the service identity."
    }

    $headers = @{ Authorization = "Bearer $env:CLOUDSDK_AUTH_ACCESS_TOKEN" }
    $generateUri = "https://serviceusage.googleapis.com/v1beta1/projects/$ProjectNumber/services/${ServiceName}:generateServiceIdentity"
    $operation = Invoke-RestMethod -Method Post -Uri $generateUri -Headers $headers -ContentType "application/json" -Body "{}"

    for ($attempt = 0; $attempt -lt 60 -and -not $operation.done; $attempt++) {
        Start-Sleep -Seconds 2
        $operationUri = "https://serviceusage.googleapis.com/v1beta1/$($operation.name)"
        $operation = Invoke-RestMethod -Method Get -Uri $operationUri -Headers $headers
    }
    if (-not $operation.done) {
        throw "Timed out while generating the $ServiceName service identity."
    }
    if ($operation.error) {
        throw "Could not generate the $ServiceName service identity: $($operation.error.message)"
    }
}

if ($ProjectNumber -notmatch '^\d+$') {
    throw "ProjectNumber must contain digits only."
}
if ($Service -notmatch '^[a-z][a-z0-9-]{0,61}[a-z0-9]$') {
    throw "Service must be a valid Cloud Run service name."
}
if (-not $AllowedUserEmail -or $AllowedUserEmail.Count -eq 0) {
    throw "At least one exact -AllowedUserEmail is required for IAP access."
}
$AllowedUserEmail = @($AllowedUserEmail | ForEach-Object { $_.Trim().ToLowerInvariant() } | Sort-Object -Unique)
if (@($AllowedUserEmail | Where-Object { $_ -notmatch '^[^\s@*]+@[^\s@*]+$' }).Count -gt 0) {
    throw "AllowedUserEmail must contain exact email addresses without wildcards."
}
if ($EnablePrivateGateway) {
    try {
        $parsedUpstream = [Uri]$UpstreamUrl
        $upstreamAddress = [Net.IPAddress]::Parse($parsedUpstream.Host)
    }
    catch {
        throw "UpstreamUrl must contain one literal private IPv4 address."
    }
    $octets = $upstreamAddress.GetAddressBytes()
    $privateAddress = $upstreamAddress.AddressFamily -eq [Net.Sockets.AddressFamily]::InterNetwork -and (
        $octets[0] -eq 10 -or
        ($octets[0] -eq 172 -and $octets[1] -ge 16 -and $octets[1] -le 31) -or
        ($octets[0] -eq 192 -and $octets[1] -eq 168)
    )
    if ($parsedUpstream.Scheme -ne "http" -or -not $privateAddress -or $parsedUpstream.Port -lt 1 -or $parsedUpstream.AbsolutePath -ne "/") {
        throw "UpstreamUrl must be one private HTTP IPv4 address and port without a path."
    }
    if ($UpstreamTokenVersion -lt 0 -or $VPCNetwork -notmatch '^[a-z][a-z0-9-]+$' -or $VPCSubnet -notmatch '^[a-z][a-z0-9-]+$') {
        throw "Private gateway secret version and VPC identifiers are invalid."
    }
}

$Gcloud = Resolve-Gcloud
if (-not $env:CLOUDSDK_AUTH_ACCESS_TOKEN) {
    $adcToken = (& $Gcloud auth application-default print-access-token --quiet 2>$null)
    if ($LASTEXITCODE -eq 0 -and $adcToken) {
        $env:CLOUDSDK_AUTH_ACCESS_TOKEN = $adcToken.Trim()
    }
}
$commit = (& git -C $repoRoot rev-parse --verify HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $commit -notmatch '^[0-9a-f]{40}$') {
    throw "Could not resolve the deployment commit."
}
$dirty = & git -C $repoRoot status --porcelain
if ($LASTEXITCODE -ne 0 -or $dirty) {
    throw "Refusing to deploy an uncommitted worktree. Commit and verify the branch first."
}

$shortCommit = $commit.Substring(0, 12)
$publicOrigin = "https://$Service-$ProjectNumber.$Region.run.app"
$redirectUri = "$publicOrigin/auth/google/callback"
$image = "$Region-docker.pkg.dev/$ProjectId/$Repository/command-center:$shortCommit"
$serviceAccount = "$ServiceAccountName@$ProjectId.iam.gserviceaccount.com"
$requiredApis = @(
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "iap.googleapis.com",
    "run.googleapis.com",
    "secretmanager.googleapis.com",
    "serviceusage.googleapis.com",
    "compute.googleapis.com"
)

Write-Host "Target service: $Service ($ProjectId / $Region)"
Write-Host "Pinned commit: $commit"
Write-Host "Predicted IAP-protected URL: $publicOrigin"
Write-Host "Required OAuth redirect: $redirectUri"
Write-Host $(if ($EnablePrivateGateway) { "Runtime mode: authenticated private-VM gateway" } else { "Runtime mode: shadow (all operational POST actions disabled)" })

if (-not $Apply) {
    Write-Host "PLAN ONLY: no cloud resources were changed."
    Write-Host "Before -Apply: create secret versions, register the exact redirect URI, and pass -OAuthRedirectConfigured."
    exit 0
}
if (-not $OAuthRedirectConfigured) {
    throw "Refusing deployment until the exact OAuth redirect is registered. Re-run with -OAuthRedirectConfigured only after verification."
}

# Bootstrap Service Usage before pinning quota to a project that has never
# consumed the Service Usage API. Subsequent calls are billed only to ProjectId.
& $Gcloud services enable serviceusage.googleapis.com "--project=$ProjectId" --quiet
if ($LASTEXITCODE -ne 0) {
    throw "Could not enable the Service Usage API in the deployment project."
}
$env:CLOUDSDK_CORE_PROJECT = $ProjectId
$env:GOOGLE_CLOUD_QUOTA_PROJECT = $ProjectId

foreach ($api in $requiredApis) {
    Invoke-Gcloud services enable $api "--project=$ProjectId" --quiet
}

if (-not (Test-GcloudResource { & $Gcloud artifacts repositories describe $Repository "--project=$ProjectId" "--location=$Region" "--billing-project=$ProjectId" })) {
    Invoke-Gcloud artifacts repositories create $Repository "--project=$ProjectId" "--location=$Region" "--repository-format=docker" "--description=Nova Command Center authenticated shadow images"
}
if (-not (Test-GcloudResource { & $Gcloud iam service-accounts describe $serviceAccount "--project=$ProjectId" "--billing-project=$ProjectId" })) {
    Invoke-Gcloud iam service-accounts create $ServiceAccountName "--project=$ProjectId" "--display-name=Nova Command Center shadow"
}

$secretNames = @($ClientIdSecret, $ClientSecretSecret, $AllowedEmailsSecret)
if ($EnablePrivateGateway) {
    $secretNames += $UpstreamTokenSecret
}
foreach ($secretName in $secretNames) {
    $enabledVersion = & $Gcloud secrets versions list $secretName "--project=$ProjectId" "--filter=state=ENABLED" "--limit=1" "--format=value(name)" "--billing-project=$ProjectId" 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $enabledVersion) {
        throw "Required enabled secret version was not found: $secretName"
    }
    Invoke-Gcloud secrets add-iam-policy-binding $secretName "--project=$ProjectId" "--member=serviceAccount:$serviceAccount" "--role=roles/secretmanager.secretAccessor" --quiet
}
if ($EnablePrivateGateway -and $UpstreamTokenVersion -eq 0) {
    $enabledVersion = & $Gcloud secrets versions list $UpstreamTokenSecret `
        "--project=$ProjectId" `
        "--filter=state=ENABLED" `
        "--sort-by=~createTime" `
        "--limit=1" `
        "--format=value(name)" `
        "--billing-project=$ProjectId" 2>$null
    $versionText = ([string]$enabledVersion).Trim()
    if ($LASTEXITCODE -ne 0 -or $versionText -notmatch '(?:^|/)(\d+)$') {
        throw "Could not resolve the latest enabled private gateway token version."
    }
    $UpstreamTokenVersion = [int]$Matches[1]
}
if ($EnablePrivateGateway) {
    $upstreamTokenState = & $Gcloud secrets versions describe $UpstreamTokenVersion `
        "--secret=$UpstreamTokenSecret" `
        "--project=$ProjectId" `
        "--format=value(state)" `
        "--billing-project=$ProjectId" 2>$null
    if (
        $LASTEXITCODE -ne 0 -or
        ([string]$upstreamTokenState).Trim() -ne "ENABLED"
    ) {
        throw "The requested private gateway token version is not enabled: $UpstreamTokenSecret/$UpstreamTokenVersion"
    }
    Write-Host "Pinned private gateway token version: $UpstreamTokenVersion"
}

Invoke-Gcloud builds submit $repoRoot "--project=$ProjectId" "--region=$Region" "--config=$repoRoot\deploy\gcp\cloudbuild-shadow.yaml" "--substitutions=_IMAGE=$image" --quiet

Ensure-ServiceIdentity -ServiceName "iap.googleapis.com"
$environmentSettings = "BRIDGE_CONFIG=/app/config/agents.cloud-shadow.yaml,COMMAND_CENTER_HOST=0.0.0.0,COMMAND_CENTER_PORT=8080,COMMAND_CENTER_DISABLE_WATCHERS=1,COMMAND_CENTER_GOOGLE_AUTH_ENABLED=1,NOVA_AGENT_RUNTIME_MODE=shadow,COMMAND_CENTER_PUBLIC_ORIGIN=$publicOrigin,GOOGLE_REDIRECT_URI=$redirectUri"
$secretSettings = "GOOGLE_CLIENT_ID=${ClientIdSecret}:latest,GOOGLE_CLIENT_SECRET=${ClientSecretSecret}:latest,GOOGLE_OAUTH_ALLOWED_EMAILS=${AllowedEmailsSecret}:latest"
$networkArguments = @()
$environmentLabel = "shadow"
if ($EnablePrivateGateway) {
    $environmentSettings += ",COMMAND_CENTER_UPSTREAM_URL=$UpstreamUrl,COMMAND_CENTER_UPSTREAM_TOKEN_PATH=/run/secrets/command-center-upstream-token,COMMAND_CENTER_UPSTREAM_TIMEOUT_SECONDS=15"
    $secretSettings += ",/run/secrets/command-center-upstream-token=${UpstreamTokenSecret}:$UpstreamTokenVersion"
    $networkArguments = @(
        "--network=$VPCNetwork",
        "--subnet=$VPCSubnet",
        "--network-tags=$VPCNetworkTag",
        "--vpc-egress=private-ranges-only"
    )
    $environmentLabel = "private-gateway"
}

Invoke-Gcloud run deploy $Service `
    "--project=$ProjectId" `
    "--region=$Region" `
    "--image=$image" `
    "--service-account=$serviceAccount" `
    --no-allow-unauthenticated `
    --iap `
    "--ingress=all" `
    "--port=8080" `
    "--concurrency=16" `
    "--min=0" `
    "--max=1" `
    "--cpu=1" `
    "--memory=1Gi" `
    "--timeout=300" `
    "--execution-environment=gen2" `
    "--set-env-vars=$environmentSettings" `
    "--set-secrets=$secretSettings" `
    "--labels=application=nova-command-center,environment=$environmentLabel,commit=$shortCommit" `
    @networkArguments `
    --quiet
Invoke-Gcloud run services update-traffic $Service `
    "--project=$ProjectId" `
    "--region=$Region" `
    --to-latest `
    --quiet

$iapServiceAgent = "service-$ProjectNumber@gcp-sa-iap.iam.gserviceaccount.com"
Invoke-Gcloud run services add-iam-policy-binding $Service "--project=$ProjectId" "--region=$Region" "--member=serviceAccount:$iapServiceAgent" "--role=roles/run.invoker" --quiet
foreach ($email in $AllowedUserEmail) {
    Invoke-Gcloud iap web add-iam-policy-binding "--project=$ProjectId" "--region=$Region" "--resource-type=cloud-run" "--service=$Service" "--member=user:$email" "--role=roles/iap.httpsResourceAccessor" --quiet
}

$description = (& $Gcloud run services describe $Service "--project=$ProjectId" "--region=$Region" "--billing-project=$ProjectId" --format=json) | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw "Could not read back the deployed Cloud Run service." }
$runPolicy = (& $Gcloud run services get-iam-policy $Service "--project=$ProjectId" "--region=$Region" "--billing-project=$ProjectId" --format=json) | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw "Could not read back the Cloud Run IAM policy." }
$iapPolicy = (& $Gcloud iap web get-iam-policy "--project=$ProjectId" "--region=$Region" "--resource-type=cloud-run" "--service=$Service" "--billing-project=$ProjectId" --format=json) | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw "Could not read back the IAP policy." }

$runMembers = @($runPolicy.bindings | ForEach-Object { $_.members } | Where-Object { $_ })
$iapMembers = @($iapPolicy.bindings | Where-Object { $_.role -eq "roles/iap.httpsResourceAccessor" } | ForEach-Object { $_.members } | Where-Object { $_ })
$expectedIapMembers = @($AllowedUserEmail | ForEach-Object { "user:$_" } | Sort-Object -Unique)
$readbackServiceAccount = [string]$description.spec.template.spec.serviceAccountName
if (-not $readbackServiceAccount) { $readbackServiceAccount = [string]$description.template.serviceAccount }
$readbackIap = $description.iapEnabled -eq $true -or [string]$description.metadata.annotations.'run.googleapis.com/iap-enabled' -eq "true"
$readbackMaxScale = [string]$description.metadata.annotations.'run.googleapis.com/maxScale'
$readbackConcurrency = [int]$description.spec.template.spec.containerConcurrency
$readbackCommit = [string]$description.metadata.labels.commit
$latestReadyRevision = [string]$description.status.latestReadyRevisionName
$latestTrafficPercent = @($description.status.traffic | Where-Object {
    $_.latestRevision -eq $true -or [string]$_.revisionName -eq $latestReadyRevision
} | ForEach-Object { [int]$_.percent } | Measure-Object -Sum).Sum
$otherTrafficPercent = @($description.status.traffic | Where-Object {
    $_.latestRevision -ne $true -and [string]$_.revisionName -ne $latestReadyRevision
} | ForEach-Object { [int]$_.percent } | Measure-Object -Sum).Sum
$container = @($description.spec.template.spec.containers)[0]
$readbackImage = [string]$container.image
$upstreamVolumeVersions = @(
    foreach ($volume in @($description.spec.template.spec.volumes)) {
        if ([string]$volume.secret.secretName -ne $UpstreamTokenSecret) {
            continue
        }
        foreach ($item in @($volume.secret.items)) {
            [string]$item.key
        }
    }
)
$environment = @{}
$secretReferences = @{}
foreach ($entry in @($container.env)) {
    if ($null -ne $entry.value) {
        $environment[[string]$entry.name] = [string]$entry.value
    }
    if ($entry.valueFrom.secretKeyRef) {
        $secretReferences[[string]$entry.name] = @{
            name = [string]$entry.valueFrom.secretKeyRef.name
            version = [string]$entry.valueFrom.secretKeyRef.key
        }
    }
}

if (-not $readbackIap) { throw "Readback failed: IAP is not enabled." }
if ($readbackServiceAccount -ne $serviceAccount) { throw "Readback failed: the dedicated service account is not attached." }
if ($runMembers -contains "allUsers" -or $runMembers -contains "allAuthenticatedUsers") { throw "Readback failed: public Cloud Run IAM access is present." }
if ($runMembers -notcontains "serviceAccount:$iapServiceAgent") { throw "Readback failed: the IAP service agent cannot invoke Cloud Run." }
if (@(Compare-Object -ReferenceObject $expectedIapMembers -DifferenceObject @($iapMembers)).Count -ne 0) {
    throw "Readback failed: the IAP accessor set does not exactly match the intended users."
}
if ($readbackMaxScale -ne "1") { throw "Readback failed: the effective service maximum is not one instance." }
if ($readbackConcurrency -ne 16) { throw "Readback failed: the private gateway concurrency is not 16." }
if ($latestTrafficPercent -ne 100 -or $otherTrafficPercent -ne 0) { throw "Readback failed: the latest ready revision is not serving 100 percent of traffic." }
if ($readbackCommit -ne $shortCommit -or $readbackImage -ne $image) { throw "Readback failed: the deployed image is not pinned to the intended commit." }
if ($environment.NOVA_AGENT_RUNTIME_MODE -ne "shadow") { throw "Readback failed: the runtime is not in shadow mode." }
if ($environment.COMMAND_CENTER_DISABLE_WATCHERS -ne "1") { throw "Readback failed: background watchers are not disabled." }
if ($environment.COMMAND_CENTER_GOOGLE_AUTH_ENABLED -ne "1") { throw "Readback failed: Google authentication is not enabled." }
if ($environment.COMMAND_CENTER_PUBLIC_ORIGIN -ne $publicOrigin -or $environment.GOOGLE_REDIRECT_URI -ne $redirectUri) {
    throw "Readback failed: the public origin or OAuth redirect differs from the registered values."
}
if ($EnablePrivateGateway) {
    if (
        $environment.COMMAND_CENTER_UPSTREAM_URL -ne $UpstreamUrl -or
        $environment.COMMAND_CENTER_UPSTREAM_TOKEN_PATH -ne "/run/secrets/command-center-upstream-token" -or
        $environment.COMMAND_CENTER_UPSTREAM_TIMEOUT_SECONDS -ne "15"
    ) {
        throw "Readback failed: the private runtime upstream is not configured exactly."
    }
    $revisionJson = $description | ConvertTo-Json -Depth 24 -Compress
    if ($revisionJson -notmatch [regex]::Escape($UpstreamTokenSecret) -or $revisionJson -notmatch [regex]::Escape("/run/secrets")) {
        throw "Readback failed: the private gateway bearer is not mounted from Secret Manager."
    }
    if (
        $upstreamVolumeVersions.Count -lt 1 -or
        @($upstreamVolumeVersions | Where-Object { $_ -ne [string]$UpstreamTokenVersion }).Count -ne 0
    ) {
        throw "Readback failed: a private gateway token volume is missing or references a different version."
    }
    $readbackUpstreamTokenState = & $Gcloud secrets versions describe $UpstreamTokenVersion `
        "--secret=$UpstreamTokenSecret" `
        "--project=$ProjectId" `
        "--format=value(state)" `
        "--billing-project=$ProjectId" 2>$null
    if (
        $LASTEXITCODE -ne 0 -or
        ([string]$readbackUpstreamTokenState).Trim() -ne "ENABLED"
    ) {
        throw "Readback failed: the deployed private gateway token version is not enabled."
    }
    $networkInterfaces = [string]$description.spec.template.metadata.annotations.'run.googleapis.com/network-interfaces'
    $vpcEgress = [string]$description.spec.template.metadata.annotations.'run.googleapis.com/vpc-access-egress'
    if ($networkInterfaces -notmatch [regex]::Escape($VPCNetwork) -or $networkInterfaces -notmatch [regex]::Escape($VPCSubnet) -or $networkInterfaces -notmatch [regex]::Escape($VPCNetworkTag)) {
        throw "Readback failed: the intended Direct VPC network, subnet, or source tag is missing."
    }
    if ($vpcEgress -ne "private-ranges-only") {
        throw "Readback failed: private-only VPC egress is not enforced."
    }
}
$expectedSecrets = @{
    GOOGLE_CLIENT_ID = $ClientIdSecret
    GOOGLE_CLIENT_SECRET = $ClientSecretSecret
    GOOGLE_OAUTH_ALLOWED_EMAILS = $AllowedEmailsSecret
}
foreach ($environmentName in $expectedSecrets.Keys) {
    $reference = $secretReferences[$environmentName]
    if (-not $reference -or $reference.name -ne $expectedSecrets[$environmentName] -or $reference.version -ne "latest") {
        throw "Readback failed: $environmentName is not attached through the intended latest Secret Manager reference."
    }
}

[pscustomobject]@{
    ok = $true
    service = $Service
    region = $Region
    url = [string]$description.status.url
    iapEnabled = $readbackIap
    iapAccessorMembers = $iapMembers
    publicIamMemberPresent = $false
    serviceAccount = $readbackServiceAccount
    maxScale = [int]$readbackMaxScale
    concurrency = $readbackConcurrency
    revision = $latestReadyRevision
    latestTrafficPercent = $latestTrafficPercent
    image = $readbackImage
    commit = $commit
    upstreamTokenVersion = $(if ($EnablePrivateGateway) { $UpstreamTokenVersion } else { $null })
    runtimeMode = $environment.NOVA_AGENT_RUNTIME_MODE
    externalWritesEnabled = [bool]$EnablePrivateGateway
} | ConvertTo-Json -Depth 4
