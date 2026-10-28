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
    [string]$SingaporeSourceCommit = "dea78b3ef16eca55323f87912e73060d6b8e1b4e",
    [ValidateRange(120, 3600)]
    [int]$PromotionWatchdogHoldSeconds = 900,
    [switch]$UpdateExisting,
    [switch]$Apply
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path
$LegacyProvisioner = Join-Path $PSScriptRoot "provision-private-runtime.ps1"
$LegacyBootstrap = Join-Path $PSScriptRoot "bootstrap-private-runtime.sh"
$Transformer = Join-Path $RepoRoot "scripts\runtime_cutover_transform.py"
$Python = (Get-Command python -ErrorAction Stop).Source
$TempRoot = Join-Path ([IO.Path]::GetTempPath()) ("nova-chatgpt-runtime-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $TempRoot | Out-Null
try {
    $GeneratedProvisioner = Join-Path $TempRoot "provision-private-runtime.ps1"
    $GeneratedBootstrap = Join-Path $TempRoot "bootstrap-private-runtime.sh"
    & $Python $Transformer provisioner $LegacyProvisioner $GeneratedProvisioner
    if ($LASTEXITCODE -ne 0) { throw "ChatGPT provisioner transform failed." }
    & $Python $Transformer bootstrap $LegacyBootstrap $GeneratedBootstrap
    if ($LASTEXITCODE -ne 0) { throw "ChatGPT bootstrap transform failed." }

    $env:NOVA_RUNTIME_REPO_ROOT = $RepoRoot
    $arguments = @(
        "-ProjectId", $ProjectId,
        "-Region", $Region,
        "-Zone", $Zone,
        "-Instance", $Instance,
        "-Network", $Network,
        "-Subnet", $Subnet,
        "-SubnetRange", $SubnetRange,
        "-Router", $Router,
        "-Nat", $Nat,
        "-EgressAddress", $EgressAddress,
        "-ServiceAccountId", $ServiceAccountId,
        "-RoryServiceAccountId", $RoryServiceAccountId,
        "-MachineType", $MachineType,
        "-BootDiskGb", $BootDiskGb,
        "-StateDisk", $StateDisk,
        "-StateDiskGb", $StateDiskGb,
        "-SingaporeSourceCommit", $SingaporeSourceCommit,
        "-PromotionWatchdogHoldSeconds", $PromotionWatchdogHoldSeconds
    )
    if ($UpdateExisting) { $arguments += "-UpdateExisting" }
    if ($Apply) { $arguments += "-Apply" }
    & $GeneratedProvisioner @arguments
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
finally {
    Remove-Item Env:NOVA_RUNTIME_REPO_ROOT -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $TempRoot -Recurse -Force -ErrorAction SilentlyContinue
}
