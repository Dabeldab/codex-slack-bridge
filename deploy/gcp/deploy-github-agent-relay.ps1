[CmdletBinding()]
param(
    [string]$ProjectId = "gen-lang-client-0051653266",
    [string]$ProjectNumber = "63366976264",
    [string]$Region = "us-central1",
    [string]$Service = "nova-github-agent-relay",
    [string]$Repository = "nova-agent-shadow",
    [string]$RuntimeServiceAccountName = "nova-github-agent-relay",
    [string]$InvokerServiceAccountName = "nova-github-relay-invoker",
    [string]$WorkloadIdentityPool = "nova-github-relay",
    [string]$WorkloadIdentityProvider = "github",
    [string]$GitHubRepository = "dariusmakesstuff/codex-slack-bridge",
    [ValidateSet("private_bearer", "cloud_run_iap", "cloud_run_iap_jwt")]
    [string]$UpstreamAuthMode = "cloud_run_iap_jwt",
    [string]$UpstreamUrl = "https://nova-command-center-shadow-3qcpmfwo7a-uc.a.run.app",
    [string]$IapAudience = "projects/63366976264/iap_web/cloud_run-us-central1/services/nova-command-center-shadow",
    [string]$IapTargetService = "nova-command-center-shadow",
    [string]$UpstreamTokenSecret = "nova-command-center-upstream-token",
    [int]$UpstreamTokenVersion = 0,
    [string]$VPCNetwork = "nova-agent-runtime",
    [string]$VPCSubnet = "nova-agent-us-central1",
    [string]$VPCNetworkTag = "nova-github-agent-relay",
    [switch]$Apply
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path

function Resolve-Gcloud {
    $command = Get-Command gcloud.cmd -ErrorAction SilentlyContinue
    if (-not $command) { $command = Get-Command gcloud -ErrorAction SilentlyContinue }
    if (-not $command) { throw "Google Cloud CLI was not found." }
    return $command.Source
}

function Invoke-Gcloud {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    & $script:Gcloud @Arguments "--billing-project=$ProjectId"
    if ($LASTEXITCODE -ne 0) { throw "gcloud command failed with exit code $LASTEXITCODE." }
}

function Test-GcloudResource {
    param([Parameter(Mandatory = $true)][scriptblock]$Command)
    $oldPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        & $Command *> $null
        $code = $LASTEXITCODE
    }
    finally { $ErrorActionPreference = $oldPreference }
    return $code -eq 0
}

if ($ProjectNumber -notmatch '^\d+$') { throw "ProjectNumber must contain digits only." }
if ($GitHubRepository -notmatch '^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$') { throw "GitHubRepository is invalid." }
foreach ($name in @($Service, $RuntimeServiceAccountName, $InvokerServiceAccountName, $WorkloadIdentityPool, $WorkloadIdentityProvider, $VPCNetwork, $VPCSubnet, $VPCNetworkTag)) {
    if ($name -notmatch '^[a-z][a-z0-9-]{1,62}$') { throw "Invalid Google resource name: $name" }
}
<#
# Corrupted duplicate retained by the #197 merge.  The complete deployment
# body begins after this comment block.
# Service-account IDs must be 6-30 characters (stricter than generic Google resource names).
foreach ($name in @($RuntimeServiceAccountName, $InvokerServiceAccountName)) {
    if ($name -notmatch '^[a-z][a-z0-9-]{4,28}[a-z0-9]
    $upstreamAddress = [Net.IPAddress]::Parse($parsedUpstream.Host)
}
catch { throw "UpstreamUrl must contain one literal private IPv4 address." }
$octets = $upstreamAddress.GetAddressBytes()
$privateAddress = $upstreamAddress.AddressFamily -eq [Net.Sockets.AddressFamily]::InterNetwork -and (
    $octets[0] -eq 10 -or
    ($octets[0] -eq 172 -and $octets[1] -ge 16 -and $octets[1] -le 31) -or
    ($octets[0] -eq 192 -and $octets[1] -eq 168)
)
if ($parsedUpstream.Scheme -ne "http" -or -not $privateAddress -or $parsedUpstream.Port -lt 1 -or $parsedUpstream.AbsolutePath -ne "/") {
    throw "UpstreamUrl must be one private HTTP IPv4 address and port without a path."
}

$Gcloud = Resolve-Gcloud
$runtimeServiceAccount = "$RuntimeServiceAccountName@$ProjectId.iam.gserviceaccount.com"
$invokerServiceAccount = "$InvokerServiceAccountName@$ProjectId.iam.gserviceaccount.com"
$providerResource = "projects/$ProjectNumber/locations/global/workloadIdentityPools/$WorkloadIdentityPool/providers/$WorkloadIdentityProvider"
$relayUrl = "https://$Service-$ProjectNumber.$Region.run.app"
$principalSet = "principalSet://iam.googleapis.com/projects/$ProjectNumber/locations/global/workloadIdentityPools/$WorkloadIdentityPool/attribute.repository/$GitHubRepository"
$attributeCondition = "assertion.repository == '$GitHubRepository' && assertion.ref == 'refs/heads/main'"

$commit = (& git -C $repoRoot rev-parse --verify HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $commit -notmatch '^[0-9a-f]{40}$') { throw "Could not resolve deployment commit." }
$dirty = & git -C $repoRoot status --porcelain
if ($LASTEXITCODE -ne 0 -or $dirty) { throw "Refusing to deploy an uncommitted worktree." }
$shortCommit = $commit.Substring(0, 12)
$image = "$Region-docker.pkg.dev/$ProjectId/$Repository/github-agent-relay:$shortCommit"

Write-Host "GitHub Agent Relay deployment"
Write-Host "  Project/region: $ProjectId / $Region"
Write-Host "  Service:        $Service"
Write-Host "  Relay URL:      $relayUrl"
Write-Host "  Runtime SA:     $runtimeServiceAccount"
Write-Host "  Invoker SA:     $invokerServiceAccount"
Write-Host "  WIF provider:   $providerResource"
Write-Host "  GitHub scope:   $GitHubRepository @ refs/heads/main"
Write-Host "  Upstream:       $UpstreamUrl"
Write-Host "  VPC:            $VPCNetwork / $VPCSubnet"
Write-Host "  Commit:         $commit"

if (-not $Apply) {
    Write-Host "PLAN ONLY: no Google Cloud resources were changed."
    exit 0
}

$requiredApis = @(
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
    "compute.googleapis.com",
    "iamcredentials.googleapis.com",
    "run.googleapis.com",
    "secretmanager.googleapis.com",
    "sts.googleapis.com"
)
foreach ($api in $requiredApis) { Invoke-Gcloud services enable $api "--project=$ProjectId" --quiet }

if (-not (Test-GcloudResource { & $Gcloud artifacts repositories describe $Repository "--project=$ProjectId" "--location=$Region" "--billing-project=$ProjectId" })) {
    Invoke-Gcloud artifacts repositories create $Repository `
        "--project=$ProjectId" `
        "--location=$Region" `
        --repository-format=docker `
        "--description=Nova agent relay images"
}

if (-not (Test-GcloudResource { & $Gcloud iam service-accounts describe $runtimeServiceAccount "--project=$ProjectId" "--billing-project=$ProjectId" })) {
    Invoke-Gcloud iam service-accounts create $RuntimeServiceAccountName "--project=$ProjectId" "--display-name=Nova GitHub agent relay runtime"
}
if (-not (Test-GcloudResource { & $Gcloud iam service-accounts describe $invokerServiceAccount "--project=$ProjectId" "--billing-project=$ProjectId" })) {
    Invoke-Gcloud iam service-accounts create $InvokerServiceAccountName "--project=$ProjectId" "--display-name=Nova GitHub agent relay invoker"
}
if (-not (Test-GcloudResource { & $Gcloud iam workload-identity-pools describe $WorkloadIdentityPool "--project=$ProjectId" --location=global "--billing-project=$ProjectId" })) {
    Invoke-Gcloud iam workload-identity-pools create $WorkloadIdentityPool "--project=$ProjectId" --location=global "--display-name=Nova GitHub Relay"
}
if (-not (Test-GcloudResource { & $Gcloud iam workload-identity-pools providers describe $WorkloadIdentityProvider "--project=$ProjectId" --location=global "--workload-identity-pool=$WorkloadIdentityPool" "--billing-project=$ProjectId" })) {
    Invoke-Gcloud iam workload-identity-pools providers create-oidc $WorkloadIdentityProvider `
        "--project=$ProjectId" `
        --location=global `
        "--workload-identity-pool=$WorkloadIdentityPool" `
        "--display-name=GitHub Actions" `
        "--issuer-uri=https://token.actions.githubusercontent.com" `
        "--attribute-mapping=google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.ref=assertion.ref,attribute.actor=assertion.actor" `
        "--attribute-condition=$attributeCondition"
}
else {
    Invoke-Gcloud iam workload-identity-pools providers update-oidc $WorkloadIdentityProvider `
        "--project=$ProjectId" `
        --location=global `
        "--workload-identity-pool=$WorkloadIdentityPool" `
        "--issuer-uri=https://token.actions.githubusercontent.com" `
        "--attribute-mapping=google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.ref=assertion.ref,attribute.actor=assertion.actor" `
        "--attribute-condition=$attributeCondition"
}

Invoke-Gcloud iam service-accounts add-iam-policy-binding $invokerServiceAccount `
    "--project=$ProjectId" `
    "--member=$principalSet" `
    "--role=roles/iam.workloadIdentityUser" `
    --quiet

$enabledVersion = & $Gcloud secrets versions list $UpstreamTokenSecret `
    "--project=$ProjectId" `
    "--filter=state=ENABLED" `
    "--sort-by=~createTime" `
    "--limit=1" `
    "--format=value(name)" `
    "--billing-project=$ProjectId" 2>$null
if ($LASTEXITCODE -ne 0 -or -not $enabledVersion) { throw "No enabled version of $UpstreamTokenSecret exists." }
if ($UpstreamTokenVersion -eq 0) {
    $versionText = ([string]$enabledVersion).Trim()
    if ($versionText -notmatch '(?:^|/)(\d+)$') { throw "Could not resolve upstream token version." }
    $UpstreamTokenVersion = [int]$Matches[1]
}
$secretState = & $Gcloud secrets versions describe $UpstreamTokenVersion `
    "--secret=$UpstreamTokenSecret" `
    "--project=$ProjectId" `
    "--format=value(state)" `
    "--billing-project=$ProjectId"
if ($LASTEXITCODE -ne 0 -or ([string]$secretState).Trim() -ne "ENABLED") {
    throw "Pinned upstream token version is not enabled: $UpstreamTokenSecret/$UpstreamTokenVersion"
}
Invoke-Gcloud secrets add-iam-policy-binding $UpstreamTokenSecret `
    "--project=$ProjectId" `
    "--member=serviceAccount:$runtimeServiceAccount" `
    "--role=roles/secretmanager.secretAccessor" `
    --quiet

Invoke-Gcloud builds submit $repoRoot `
    "--project=$ProjectId" `
    "--region=$Region" `
    "--config=$repoRoot\deploy\gcp\cloudbuild-github-agent-relay.yaml" `
    "--substitutions=_IMAGE=$image" `
    --quiet

$envSettings = "COMMAND_CENTER_UPSTREAM_URL=$UpstreamUrl,COMMAND_CENTER_UPSTREAM_TOKEN_PATH=/run/secrets/command-center-upstream-token,COMMAND_CENTER_UPSTREAM_TIMEOUT_SECONDS=15"
$secretSettings = "/run/secrets/command-center-upstream-token=${UpstreamTokenSecret}:$UpstreamTokenVersion"
Invoke-Gcloud run deploy $Service `
    "--project=$ProjectId" `
    "--region=$Region" `
    "--image=$image" `
    "--service-account=$runtimeServiceAccount" `
    --no-allow-unauthenticated `
    --no-iap `
    "--ingress=all" `
    "--port=8080" `
    "--concurrency=16" `
    "--min=0" `
    "--max=2" `
    "--cpu=1" `
    "--memory=512Mi" `
    "--timeout=60" `
    "--execution-environment=gen2" `
    "--set-env-vars=$envSettings" `
    "--set-secrets=$secretSettings" `
    "--network=$VPCNetwork" `
    "--subnet=$VPCSubnet" `
    "--network-tags=$VPCNetworkTag" `
    "--vpc-egress=private-ranges-only" `
    "--labels=application=nova-github-agent-relay,environment=production,commit=$shortCommit" `
    --quiet

Invoke-Gcloud run services add-iam-policy-binding $Service `
    "--project=$ProjectId" `
    "--region=$Region" `
    "--member=serviceAccount:$invokerServiceAccount" `
    "--role=roles/run.invoker" `
    --quiet

$description = (& $Gcloud run services describe $Service "--project=$ProjectId" "--region=$Region" "--billing-project=$ProjectId" --format=json) | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw "Could not read back deployed relay service." }
$providerReadback = (& $Gcloud iam workload-identity-pools providers describe $WorkloadIdentityProvider "--project=$ProjectId" --location=global "--workload-identity-pool=$WorkloadIdentityPool" "--billing-project=$ProjectId" --format=json) | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw "Could not read back relay Workload Identity provider." }
if ([string]$providerReadback.oidc.issuerUri -ne "https://token.actions.githubusercontent.com") {
    throw "SECURITY READBACK FAILED: GitHub OIDC issuer mismatch."
}
if ([string]$providerReadback.attributeCondition -ne $attributeCondition) {
    throw "SECURITY READBACK FAILED: GitHub WIF repository/branch condition mismatch."
}
$policy = (& $Gcloud run services get-iam-policy $Service "--project=$ProjectId" "--region=$Region" "--billing-project=$ProjectId" --format=json) | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw "Could not read back relay IAM policy." }
$members = @($policy.bindings | ForEach-Object { $_.members } | Where-Object { $_ })
if ($members -contains "allUsers" -or $members -contains "allAuthenticatedUsers") {
    throw "SECURITY READBACK FAILED: relay service is broader than the dedicated invoker identity."
}
$invokerBinding = @(
    $policy.bindings |
        Where-Object { $_.role -eq "roles/run.invoker" } |
        ForEach-Object { $_.members } |
        Where-Object { $_ -eq "serviceAccount:$invokerServiceAccount" }
)
if ($invokerBinding.Count -ne 1) { throw "SECURITY READBACK FAILED: dedicated relay invoker binding is missing." }
$readbackServiceAccount = [string]$description.spec.template.spec.serviceAccountName
if (-not $readbackServiceAccount) { $readbackServiceAccount = [string]$description.template.serviceAccount }
if ($readbackServiceAccount -ne $runtimeServiceAccount) {
    throw "SECURITY READBACK FAILED: runtime service account mismatch."
}

Write-Host "Relay deployment verified."
Write-Host "Workflow WIF provider: $providerResource"
Write-Host "Workflow service account: $invokerServiceAccount"
Write-Host "Relay URL: $relayUrl"
Write-Host "Pinned upstream token version: $UpstreamTokenVersion"
) {
        throw "Invalid Google service-account ID (6-30 lowercase letters, digits, hyphens): $name"
    }
}
#>
# Service-account IDs are stricter than generic Google resource names.
foreach ($name in @($RuntimeServiceAccountName, $InvokerServiceAccountName)) {
    if ($name -notmatch '^[a-z](?:[a-z0-9-]{4,28}[a-z0-9])$') {
        throw "Invalid Google service-account ID (6-30 lowercase letters, digits, hyphens): $name"
    }
}
if ($UpstreamAuthMode -eq "private_bearer") {
    try {
        $parsedUpstream = [Uri]$UpstreamUrl
        $upstreamAddress = [Net.IPAddress]::Parse($parsedUpstream.Host)
    }
    catch { throw "UpstreamUrl must contain one literal private IPv4 address." }
    $octets = $upstreamAddress.GetAddressBytes()
    $privateAddress = $upstreamAddress.AddressFamily -eq [Net.Sockets.AddressFamily]::InterNetwork -and (
        $octets[0] -eq 10 -or
        ($octets[0] -eq 172 -and $octets[1] -ge 16 -and $octets[1] -le 31) -or
        ($octets[0] -eq 192 -and $octets[1] -eq 168)
    )
    if ($parsedUpstream.Scheme -ne "http" -or -not $privateAddress -or $parsedUpstream.Port -lt 1 -or $parsedUpstream.AbsolutePath -ne "/") {
        throw "UpstreamUrl must be one private HTTP IPv4 address and port without a path."
    }
}
else {
    try { $parsedUpstream = [Uri]$UpstreamUrl }
    catch { throw "UpstreamUrl must be a Cloud Run HTTPS origin." }
    if ($parsedUpstream.Scheme -ne "https" -or -not $parsedUpstream.Host.EndsWith(".run.app") -or $parsedUpstream.Port -notin -1, 443 -or $parsedUpstream.AbsolutePath -ne "/" -or $IapAudience -notmatch "^projects/$ProjectNumber/iap_web/cloud_run-$Region/services/$IapTargetService$") {
        throw "Cloud Run IAP upstream settings are invalid."
    }
}

$Gcloud = Resolve-Gcloud
$runtimeServiceAccount = "$RuntimeServiceAccountName@$ProjectId.iam.gserviceaccount.com"
$invokerServiceAccount = "$InvokerServiceAccountName@$ProjectId.iam.gserviceaccount.com"
$providerResource = "projects/$ProjectNumber/locations/global/workloadIdentityPools/$WorkloadIdentityPool/providers/$WorkloadIdentityProvider"
$relayUrl = "https://$Service-$ProjectNumber.$Region.run.app"
$principalSet = "principalSet://iam.googleapis.com/projects/$ProjectNumber/locations/global/workloadIdentityPools/$WorkloadIdentityPool/attribute.repository/$GitHubRepository"
# A single-quoted format string avoids PowerShell parsing the embedded CEL
# quote boundaries as a second expression during script compilation.
$attributeCondition = 'assertion.repository == ''{0}'' && assertion.ref == ''refs/heads/main''' -f $GitHubRepository

$commit = (& git -C $repoRoot rev-parse --verify HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $commit -notmatch '^[0-9a-f]{40}$') { throw "Could not resolve deployment commit." }
$dirty = & git -C $repoRoot status --porcelain
if ($LASTEXITCODE -ne 0 -or $dirty) { throw "Refusing to deploy an uncommitted worktree." }
$shortCommit = $commit.Substring(0, 12)
$image = "$Region-docker.pkg.dev/$ProjectId/$Repository/github-agent-relay:$shortCommit"

Write-Host "GitHub Agent Relay deployment"
Write-Host "  Project/region: $ProjectId / $Region"
Write-Host "  Service:        $Service"
Write-Host "  Relay URL:      $relayUrl"
Write-Host "  Runtime SA:     $runtimeServiceAccount"
Write-Host "  Invoker SA:     $invokerServiceAccount"
Write-Host "  WIF provider:   $providerResource"
Write-Host "  GitHub scope:   $GitHubRepository @ refs/heads/main"
Write-Host "  Upstream:       $UpstreamUrl"
Write-Host "  Upstream auth:  $UpstreamAuthMode"
Write-Host "  VPC:            $VPCNetwork / $VPCSubnet"
Write-Host "  Commit:         $commit"

if (-not $Apply) {
    Write-Host "PLAN ONLY: no Google Cloud resources were changed."
    exit 0
}

$requiredApis = @(
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
    "compute.googleapis.com",
    "iamcredentials.googleapis.com",
    "run.googleapis.com",
    "secretmanager.googleapis.com",
    "sts.googleapis.com"
)
foreach ($api in $requiredApis) { Invoke-Gcloud services enable $api "--project=$ProjectId" --quiet }

if (-not (Test-GcloudResource { & $Gcloud artifacts repositories describe $Repository "--project=$ProjectId" "--location=$Region" "--billing-project=$ProjectId" })) {
    Invoke-Gcloud artifacts repositories create $Repository `
        "--project=$ProjectId" `
        "--location=$Region" `
        --repository-format=docker `
        "--description=Nova agent relay images"
}

if (-not (Test-GcloudResource { & $Gcloud iam service-accounts describe $runtimeServiceAccount "--project=$ProjectId" "--billing-project=$ProjectId" })) {
    Invoke-Gcloud iam service-accounts create $RuntimeServiceAccountName "--project=$ProjectId" "--display-name=Nova GitHub agent relay runtime"
}
if (-not (Test-GcloudResource { & $Gcloud iam service-accounts describe $invokerServiceAccount "--project=$ProjectId" "--billing-project=$ProjectId" })) {
    Invoke-Gcloud iam service-accounts create $InvokerServiceAccountName "--project=$ProjectId" "--display-name=Nova GitHub agent relay invoker"
}
if (-not (Test-GcloudResource { & $Gcloud iam workload-identity-pools describe $WorkloadIdentityPool "--project=$ProjectId" --location=global "--billing-project=$ProjectId" })) {
    Invoke-Gcloud iam workload-identity-pools create $WorkloadIdentityPool "--project=$ProjectId" --location=global "--display-name=Nova GitHub Relay"
}
if (-not (Test-GcloudResource { & $Gcloud iam workload-identity-pools providers describe $WorkloadIdentityProvider "--project=$ProjectId" --location=global "--workload-identity-pool=$WorkloadIdentityPool" "--billing-project=$ProjectId" })) {
    Invoke-Gcloud iam workload-identity-pools providers create-oidc $WorkloadIdentityProvider `
        "--project=$ProjectId" `
        --location=global `
        "--workload-identity-pool=$WorkloadIdentityPool" `
        "--display-name=GitHub Actions" `
        "--issuer-uri=https://token.actions.githubusercontent.com" `
        "--attribute-mapping=google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.ref=assertion.ref,attribute.actor=assertion.actor" `
        "--attribute-condition=$attributeCondition"
}
else {
    Invoke-Gcloud iam workload-identity-pools providers update-oidc $WorkloadIdentityProvider `
        "--project=$ProjectId" `
        --location=global `
        "--workload-identity-pool=$WorkloadIdentityPool" `
        "--issuer-uri=https://token.actions.githubusercontent.com" `
        "--attribute-mapping=google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.ref=assertion.ref,attribute.actor=assertion.actor" `
        "--attribute-condition=$attributeCondition"
}

Invoke-Gcloud iam service-accounts add-iam-policy-binding $invokerServiceAccount `
    "--project=$ProjectId" `
    "--member=$principalSet" `
    "--role=roles/iam.workloadIdentityUser" `
    --quiet

$enabledVersion = & $Gcloud secrets versions list $UpstreamTokenSecret `
    "--project=$ProjectId" `
    "--filter=state=ENABLED" `
    "--sort-by=~createTime" `
    "--limit=1" `
    "--format=value(name)" `
    "--billing-project=$ProjectId" 2>$null
if ($LASTEXITCODE -ne 0 -or -not $enabledVersion) { throw "No enabled version of $UpstreamTokenSecret exists." }
if ($UpstreamTokenVersion -eq 0) {
    $versionText = ([string]$enabledVersion).Trim()
    if ($versionText -notmatch '(?:^|/)(\d+)$') { throw "Could not resolve upstream token version." }
    $UpstreamTokenVersion = [int]$Matches[1]
}
$secretState = & $Gcloud secrets versions describe $UpstreamTokenVersion `
    "--secret=$UpstreamTokenSecret" `
    "--project=$ProjectId" `
    "--format=value(state)" `
    "--billing-project=$ProjectId"
if ($LASTEXITCODE -ne 0 -or ([string]$secretState).Trim() -ne "ENABLED") {
    throw "Pinned upstream token version is not enabled: $UpstreamTokenSecret/$UpstreamTokenVersion"
}
Invoke-Gcloud secrets add-iam-policy-binding $UpstreamTokenSecret `
    "--project=$ProjectId" `
    "--member=serviceAccount:$runtimeServiceAccount" `
    "--role=roles/secretmanager.secretAccessor" `
    --quiet

if ($UpstreamAuthMode -in @("cloud_run_iap", "cloud_run_iap_jwt")) {
    Invoke-Gcloud iap web add-iam-policy-binding `
        "--resource-type=cloud-run" `
        "--service=$IapTargetService" `
        "--region=$Region" `
        "--project=$ProjectId" `
        "--member=serviceAccount:$runtimeServiceAccount" `
        "--role=roles/iap.httpsResourceAccessor" `
        --quiet
    if ($UpstreamAuthMode -eq "cloud_run_iap_jwt") {
        Invoke-Gcloud iam service-accounts add-iam-policy-binding $runtimeServiceAccount `
            "--project=$ProjectId" `
            "--member=serviceAccount:$runtimeServiceAccount" `
            "--role=roles/iam.serviceAccountTokenCreator" `
            --quiet
    }
    Invoke-Gcloud run services update $IapTargetService `
        "--project=$ProjectId" `
        "--region=$Region" `
        "--update-env-vars=COMMAND_CENTER_TRUSTED_BEARER_PATH=/run/nova-relay-secrets/command-center-upstream-token" `
        "--update-secrets=/run/nova-relay-secrets/command-center-upstream-token=${UpstreamTokenSecret}:$UpstreamTokenVersion" `
        --quiet
}

Invoke-Gcloud builds submit $repoRoot `
    "--project=$ProjectId" `
    "--region=$Region" `
    "--config=$repoRoot\deploy\gcp\cloudbuild-github-agent-relay.yaml" `
    "--substitutions=_IMAGE=$image" `
    --quiet

$envSettings = "COMMAND_CENTER_UPSTREAM_URL=$UpstreamUrl,COMMAND_CENTER_UPSTREAM_AUTH_MODE=$UpstreamAuthMode,COMMAND_CENTER_IAP_AUDIENCE=$IapAudience,COMMAND_CENTER_UPSTREAM_TOKEN_PATH=/run/secrets/command-center-upstream-token,COMMAND_CENTER_UPSTREAM_TIMEOUT_SECONDS=15"
$secretSettings = "/run/secrets/command-center-upstream-token=${UpstreamTokenSecret}:$UpstreamTokenVersion"
Invoke-Gcloud run deploy $Service `
    "--project=$ProjectId" `
    "--region=$Region" `
    "--image=$image" `
    "--service-account=$runtimeServiceAccount" `
    --no-allow-unauthenticated `
    --no-iap `
    "--ingress=all" `
    "--port=8080" `
    "--concurrency=16" `
    "--min=0" `
    "--max=2" `
    "--cpu=1" `
    "--memory=512Mi" `
    "--timeout=60" `
    "--execution-environment=gen2" `
    "--set-env-vars=$envSettings" `
    "--set-secrets=$secretSettings" `
    "--network=$VPCNetwork" `
    "--subnet=$VPCSubnet" `
    "--network-tags=$VPCNetworkTag" `
    "--vpc-egress=private-ranges-only" `
    "--labels=application=nova-github-agent-relay,environment=production,commit=$shortCommit" `
    --quiet

Invoke-Gcloud run services add-iam-policy-binding $Service `
    "--project=$ProjectId" `
    "--region=$Region" `
    "--member=serviceAccount:$invokerServiceAccount" `
    "--role=roles/run.invoker" `
    --quiet

$description = (& $Gcloud run services describe $Service "--project=$ProjectId" "--region=$Region" "--billing-project=$ProjectId" --format=json) | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw "Could not read back deployed relay service." }
$providerReadback = (& $Gcloud iam workload-identity-pools providers describe $WorkloadIdentityProvider "--project=$ProjectId" --location=global "--workload-identity-pool=$WorkloadIdentityPool" "--billing-project=$ProjectId" --format=json) | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw "Could not read back relay Workload Identity provider." }
if ([string]$providerReadback.oidc.issuerUri -ne "https://token.actions.githubusercontent.com") {
    throw "SECURITY READBACK FAILED: GitHub OIDC issuer mismatch."
}
if ([string]$providerReadback.attributeCondition -ne $attributeCondition) {
    throw "SECURITY READBACK FAILED: GitHub WIF repository/branch condition mismatch."
}
$policy = (& $Gcloud run services get-iam-policy $Service "--project=$ProjectId" "--region=$Region" "--billing-project=$ProjectId" --format=json) | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw "Could not read back relay IAM policy." }
$members = @($policy.bindings | ForEach-Object { $_.members } | Where-Object { $_ })
if ($members -contains "allUsers" -or $members -contains "allAuthenticatedUsers") {
    throw "SECURITY READBACK FAILED: relay service is broader than the dedicated invoker identity."
}
$invokerBinding = @(
    $policy.bindings |
        Where-Object { $_.role -eq "roles/run.invoker" } |
        ForEach-Object { $_.members } |
        Where-Object { $_ -eq "serviceAccount:$invokerServiceAccount" }
)
if ($invokerBinding.Count -ne 1) { throw "SECURITY READBACK FAILED: dedicated relay invoker binding is missing." }
$readbackServiceAccount = [string]$description.spec.template.spec.serviceAccountName
if (-not $readbackServiceAccount) { $readbackServiceAccount = [string]$description.template.serviceAccount }
if ($readbackServiceAccount -ne $runtimeServiceAccount) {
    throw "SECURITY READBACK FAILED: runtime service account mismatch."
}

Write-Host "Relay deployment verified."
Write-Host "Workflow WIF provider: $providerResource"
Write-Host "Workflow service account: $invokerServiceAccount"
Write-Host "Relay URL: $relayUrl"
Write-Host "Pinned upstream token version: $UpstreamTokenVersion"
