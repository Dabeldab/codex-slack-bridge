# AgentChat/coding_agent 2026-07-08T20:02:14Z
param(
    [ValidateSet("status", "registry")]
    [string]$Action = "status",

    [string]$Tool = "all",

    [string]$RegistryPath = "config/tool-fast-paths.json"
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$ResolvedRegistry = if ([System.IO.Path]::IsPathRooted($RegistryPath)) {
    $RegistryPath
} else {
    Join-Path $RepoRoot $RegistryPath
}

function Resolve-AgentPath {
    param([string]$PathValue)
    if ([string]::IsNullOrWhiteSpace($PathValue)) {
        return $PathValue
    }
    $expanded = [Environment]::ExpandEnvironmentVariables($PathValue)
    if ([System.IO.Path]::IsPathRooted($expanded)) {
        return $expanded
    }
    return [System.IO.Path]::GetFullPath((Join-Path $RepoRoot $expanded))
}

function Get-EnvNamesFromFile {
    param([string]$PathValue)
    $resolved = Resolve-AgentPath $PathValue
    if (-not (Test-Path -LiteralPath $resolved)) {
        return @()
    }
    $names = New-Object System.Collections.Generic.List[string]
    foreach ($line in Get-Content -LiteralPath $resolved) {
        if ($line -match '^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=') {
            [void]$names.Add($Matches[1])
        }
    }
    return $names.ToArray()
}

function Get-VaultNames {
    param($Registry)
    $tool = Resolve-AgentPath ([string]$Registry.vault.tool)
    if (-not (Test-Path -LiteralPath $tool)) {
        return @()
    }
    try {
        $output = powershell -ExecutionPolicy Bypass -File $tool -Action list 2>$null
        $names = New-Object System.Collections.Generic.List[string]
        foreach ($line in $output) {
            foreach ($match in [regex]::Matches([string]$line, '\b[A-Z][A-Z0-9_]{2,}\b')) {
                [void]$names.Add($match.Value)
            }
        }
        return $names.ToArray() | Sort-Object -Unique
    } catch {
        return @()
    }
}

function Test-AnyGroup {
    param(
        [object[]]$Group,
        [string[]]$Available
    )
    foreach ($name in $Group) {
        if ($Available -contains [string]$name) {
            return $true
        }
    }
    return $false
}

if (-not (Test-Path -LiteralPath $ResolvedRegistry)) {
    throw "Tool fast-path registry not found: $ResolvedRegistry"
}

$registry = Get-Content -LiteralPath $ResolvedRegistry -Raw | ConvertFrom-Json

if ($Action -eq "registry") {
    $registry | ConvertTo-Json -Depth 12
    exit 0
}

$envFromFiles = New-Object System.Collections.Generic.List[string]
foreach ($envFile in @($registry.env_files)) {
    foreach ($name in Get-EnvNamesFromFile ([string]$envFile)) {
        [void]$envFromFiles.Add($name)
    }
}

$processEnv = [Environment]::GetEnvironmentVariables().Keys | ForEach-Object { [string]$_ }
$vaultNames = @(Get-VaultNames $registry)
$availableNames = @($envFromFiles.ToArray() + $processEnv + $vaultNames) | Sort-Object -Unique

$toolObjects = @()
foreach ($property in $registry.tools.PSObject.Properties) {
    if ($Tool -ne "all" -and $property.Name -ne $Tool) {
        continue
    }
    $toolConfig = $property.Value
    $requiredGroups = @($toolConfig.credentials.required_any)
    $requiredStatus = @()
    foreach ($group in $requiredGroups) {
        $groupNames = @($group | ForEach-Object { [string]$_ })
        $requiredStatus += [PSCustomObject]@{
            any_of = $groupNames
            present = Test-AnyGroup $groupNames $availableNames
        }
    }
    $pathStatus = @()
    foreach ($path in @($toolConfig.paths)) {
        $resolved = Resolve-AgentPath ([string]$path)
        $pathStatus += [PSCustomObject]@{
            path = [string]$path
            exists = Test-Path -LiteralPath $resolved
        }
    }
    $toolObjects += [PSCustomObject]@{
        name = $property.Name
        display_name = $toolConfig.display_name
        safe_actions = @($toolConfig.safe_actions)
        requires_authorization_for = @($toolConfig.requires_authorization_for)
        required_credentials = $requiredStatus
        known_paths = $pathStatus
        fast_start = @($toolConfig.fast_start)
    }
}

[PSCustomObject]@{
    registry = $ResolvedRegistry
    signature = $registry._signature
    env_files_checked = @($registry.env_files | ForEach-Object {
        $path = Resolve-AgentPath ([string]$_)
        [PSCustomObject]@{ path = [string]$_; exists = Test-Path -LiteralPath $path }
    })
    vault = [PSCustomObject]@{
        path = [string]$registry.vault.path
        tool = [string]$registry.vault.tool
        names_visible = $vaultNames.Count
    }
    tools = $toolObjects
} | ConvertTo-Json -Depth 12
