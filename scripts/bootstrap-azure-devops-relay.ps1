param(
  [Parameter(Mandatory = $true)][string]$Organization,
  [string]$Project = "",
  [string]$AppDisplayName = "nova-chatgpt-relay",
  [ValidateSet("stakeholder", "express")][string]$AccessLevel = "express",
  [ValidateSet("projectReader", "projectContributor")][string]$ProjectGroup = "projectContributor",
  [switch]$Apply
)

$ErrorActionPreference = "Stop"
$Repo = "dariusmakesstuff/codex-slack-bridge"
$EnvironmentName = "azure-relay"
$DevOpsResource = "499b84ac-1321-427f-aa17-267ca6975798"

function Invoke-AzCli([string[]]$Arguments) {
  $output = & az @Arguments 2>&1
  if ($LASTEXITCODE -ne 0) { throw "az failed: $($output -join [Environment]::NewLine)" }
  return ($output -join "`n").Trim()
}

Write-Host "Azure DevOps relay plan"
Write-Host "  Organization : $Organization"
Write-Host "  Project      : $Project"
Write-Host "  Entra app    : $AppDisplayName"
Write-Host "  GitHub trust : repo:$Repo:environment:$EnvironmentName"
Write-Host "  License      : $AccessLevel"
Write-Host "  Project role : $ProjectGroup"
Write-Host "  Secrets      : none (GitHub OIDC only)"

if (-not $Apply) {
  Write-Host ""
  Write-Host "Plan only. Re-run with -Apply after reviewing the values."
  exit 0
}

if (-not (Get-Command az -ErrorAction SilentlyContinue)) { throw "Azure CLI (az) is required." }
$tenantId = Invoke-AzCli @("account", "show", "--query", "tenantId", "-o", "tsv")
if (-not $tenantId) { throw "No Azure CLI login is active. Run 'az login --allow-no-subscriptions' first." }

$appId = Invoke-AzCli @("ad", "app", "list", "--display-name", $AppDisplayName, "--query", "[0].appId", "-o", "tsv")
if (-not $appId) { $appId = Invoke-AzCli @("ad", "app", "create", "--display-name", $AppDisplayName, "--query", "appId", "-o", "tsv") }
$appObjectId = Invoke-AzCli @("ad", "app", "show", "--id", $appId, "--query", "id", "-o", "tsv")
$spObjectId = Invoke-AzCli @("ad", "sp", "show", "--id", $appId, "--query", "id", "-o", "tsv")
if (-not $spObjectId) { $spObjectId = Invoke-AzCli @("ad", "sp", "create", "--id", $appId, "--query", "id", "-o", "tsv") }

$credentialName = "github-azure-relay"
$existingCredential = Invoke-AzCli @("ad", "app", "federated-credential", "list", "--id", $appObjectId, "--query", "[?name=='$credentialName'].name | [0]", "-o", "tsv")
if (-not $existingCredential) {
  $credential = @{
    name = $credentialName
    issuer = "https://token.actions.githubusercontent.com"
    subject = "repo:$Repo:environment:$EnvironmentName"
    description = "Nova Azure DevOps relay from protected GitHub environment"
    audiences = @("api://AzureADTokenExchange")
  } | ConvertTo-Json -Depth 5
  $temp = Join-Path $env:TEMP "nova-azure-relay-federated.json"
  Set-Content -Path $temp -Value $credential -Encoding utf8
  try { Invoke-AzCli @("ad", "app", "federated-credential", "create", "--id", $appObjectId, "--parameters", "@$temp") | Out-Null }
  finally { Remove-Item -Force $temp -ErrorAction SilentlyContinue }
}

$devOpsToken = Invoke-AzCli @("account", "get-access-token", "--resource", $DevOpsResource, "--query", "accessToken", "-o", "tsv")
$headers = @{ Authorization = "Bearer $devOpsToken"; "Content-Type" = "application/json" }
$projectEntitlements = @()
if ($Project) {
  $encodedProject = [uri]::EscapeDataString($Project)
  $projectInfo = Invoke-RestMethod -Method Get -Headers $headers -Uri "https://dev.azure.com/$Organization/_apis/projects/$encodedProject?api-version=7.1"
  if (-not $projectInfo.id) { throw "Azure DevOps project could not be resolved." }
  $projectEntitlements += @{ group = @{ groupType = $ProjectGroup }; projectRef = @{ id = [string]$projectInfo.id } }
}

$entitlementBody = @{
  accessLevel = @{ accountLicenseType = $AccessLevel; licensingSource = "account" }
  projectEntitlements = $projectEntitlements
  servicePrincipal = @{ origin = "aad"; originId = $spObjectId; subjectKind = "servicePrincipal" }
} | ConvertTo-Json -Depth 8

try {
  $result = Invoke-RestMethod -Method Post -Headers $headers -Body $entitlementBody -Uri "https://vsaex.dev.azure.com/$Organization/_apis/serviceprincipalentitlements?api-version=7.1-preview.1"
  if ($result.operationResult -and -not $result.operationResult.isSuccess) { throw "Azure DevOps rejected the service-principal entitlement." }
} catch {
  if ($_.Exception.Response -and [int]$_.Exception.Response.StatusCode -in @(400, 409)) { Write-Host "Azure DevOps principal may already exist; continuing to readback." }
  else { throw }
}

Write-Host ""
Write-Host "Created/verified passwordless relay identity."
Write-Host "Set these GitHub repository/environment variables (not secrets):"
Write-Host "  AZURE_CLIENT_ID=$appId"
Write-Host "  AZURE_TENANT_ID=$tenantId"
Write-Host "  AZURE_DEVOPS_ORGANIZATION=$Organization"
if ($Project) { Write-Host "  AZURE_DEVOPS_PROJECT=$Project" }
Write-Host ""
Write-Host "GitHub environment required: $EnvironmentName"
Write-Host "Service principal object id: $spObjectId"
