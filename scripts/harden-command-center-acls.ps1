param(
  [switch]$Apply
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$CurrentIdentity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
$CurrentSid = $CurrentIdentity.User
$SystemSid = [System.Security.Principal.SecurityIdentifier]::new("S-1-5-18")
$AdministratorsSid = [System.Security.Principal.SecurityIdentifier]::new("S-1-5-32-544")
$AllowedSids = @($CurrentSid.Value, $SystemSid.Value, $AdministratorsSid.Value)
$JournalDir = Join-Path $env:LOCALAPPDATA "NovaOpsSecurity"
$JournalPath = Join-Path $JournalDir "acl-hardening.jsonl"
$OperationKey = "command-center-acl-hardening-v1:2026-07-17"

$Targets = @(
  @{ Path = (Join-Path $Root ".env"); Kind = "File" },
  @{ Path = (Join-Path $Root "data\auth"); Kind = "Directory" },
  @{ Path = (Join-Path $Root "data\command_center"); Kind = "Directory" },
  @{ Path = "C:\Users\redma\Uploader\token.json"; Kind = "File" },
  @{ Path = "C:\Users\redma\.codex\config.toml"; Kind = "File" },
  @{ Path = "C:\Users\redma\AppData\Roaming\gcloud\application_default_credentials.json"; Kind = "File" },
  @{ Path = "C:\Users\redma\Workworkworkworkworkwork\auto-tickets\logmein-connector"; Kind = "Directory" }
)

function Get-ResolvedTarget([string]$Path) {
  if (-not (Test-Path -LiteralPath $Path)) {
    return $null
  }
  return (Resolve-Path -LiteralPath $Path).Path
}

function Get-AclState([string]$Path) {
  $Acl = Get-Acl -LiteralPath $Path
  $Entries = @(
    foreach ($Rule in $Acl.Access) {
      $Sid = try {
        $Rule.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value
      } catch {
        $Rule.IdentityReference.Value
      }
      [ordered]@{
        sid = $Sid
        type = [string]$Rule.AccessControlType
        rights = [string]$Rule.FileSystemRights
        inherited = [bool]$Rule.IsInherited
      }
    }
  )
  $Sddl = $Acl.Sddl
  $Hasher = [Security.Cryptography.SHA256]::Create()
  try {
    $DigestBytes = $Hasher.ComputeHash([Text.Encoding]::UTF8.GetBytes($Sddl))
  } finally {
    $Hasher.Dispose()
  }
  $Digest = ([BitConverter]::ToString($DigestBytes) -replace "-", "").ToLowerInvariant()
  return [ordered]@{
    protected = [bool]$Acl.AreAccessRulesProtected
    aclSha256 = $Digest
    entries = $Entries
  }
}

function Set-PrivateAcl([string]$Path, [bool]$IsDirectory) {
  $Suffix = if ($IsDirectory) {
    "(OI)(CI)(F)"
  } else {
    "(F)"
  }
  $Arguments = @(
    $Path,
    "/inheritance:r",
    "/grant:r",
    "$($CurrentIdentity.Name):$Suffix",
    "*$($SystemSid.Value):$Suffix",
    "*$($AdministratorsSid.Value):$Suffix"
  )
  $Process = Start-Process -FilePath "icacls.exe" -ArgumentList $Arguments -Wait -PassThru -WindowStyle Hidden
  if ($Process.ExitCode -ne 0) {
    throw "icacls failed for one private ACL target."
  }
}

function Test-PrivateAcl([string]$Path) {
  $State = Get-AclState $Path
  $Unexpected = @(
    $State.entries | Where-Object {
      $_.type -ne "Allow" -or $_.sid -notin $AllowedSids
    }
  )
  return [ordered]@{
    ok = [bool]($State.protected -and $Unexpected.Count -eq 0)
    protected = $State.protected
    aclSha256 = $State.aclSha256
    unexpectedSids = @($Unexpected | ForEach-Object { $_.sid } | Sort-Object -Unique)
  }
}

function Write-Journal([System.Collections.IDictionary]$Entry) {
  New-Item -ItemType Directory -Path $JournalDir -Force | Out-Null
  if (-not (Test-Path -LiteralPath $JournalPath)) {
    New-Item -ItemType File -Path $JournalPath -Force | Out-Null
  }
  Set-PrivateAcl -Path $JournalDir -IsDirectory $true
  Set-PrivateAcl -Path $JournalPath -IsDirectory $false
  Add-Content -LiteralPath $JournalPath -Value ($Entry | ConvertTo-Json -Depth 8 -Compress) -Encoding utf8
}

$Resolved = @(
  foreach ($Target in $Targets) {
    $Path = Get-ResolvedTarget $Target.Path
    if ($null -eq $Path) {
      [ordered]@{ path = $Target.Path; kind = $Target.Kind; exists = $false }
      continue
    }
    [ordered]@{
      path = $Path
      kind = $Target.Kind
      exists = $true
      before = Get-AclState $Path
    }
  }
)

if (-not $Apply) {
  [ordered]@{
    ok = $true
    mode = "preview"
    operationKey = $OperationKey
    targets = @(
      $Resolved | ForEach-Object {
        [ordered]@{
          path = $_.path
          kind = $_.kind
          exists = $_.exists
          protected = if ($_.exists) { $_.before.protected } else { $false }
          unauthorizedSids = if ($_.exists) {
            @($_.before.entries | Where-Object { $_.sid -notin $AllowedSids } | ForEach-Object { $_.sid } | Sort-Object -Unique)
          } else { @() }
        }
      }
    )
  } | ConvertTo-Json -Depth 7
  exit 0
}

$Pending = [ordered]@{
  operationKey = $OperationKey
  status = "pending"
  startedAtUtc = [DateTimeOffset]::UtcNow.ToString("o")
  targets = @($Resolved | Where-Object { $_.exists } | ForEach-Object {
    [ordered]@{ path = $_.path; kind = $_.kind; beforeAclSha256 = $_.before.aclSha256 }
  })
}
Write-Journal $Pending

try {
  foreach ($Target in $Resolved | Where-Object { $_.exists }) {
    Set-PrivateAcl -Path $Target.path -IsDirectory ($Target.kind -eq "Directory")
  }
  $Verification = @(
    foreach ($Target in $Resolved | Where-Object { $_.exists }) {
      $Result = Test-PrivateAcl $Target.path
      [ordered]@{ path = $Target.path; ok = $Result.ok; protected = $Result.protected; aclSha256 = $Result.aclSha256; unexpectedSids = $Result.unexpectedSids }
    }
  )
  if (@($Verification | Where-Object { -not $_.ok }).Count -gt 0) {
    throw "One or more ACL targets failed authoritative readback."
  }
  $Completed = [ordered]@{
    operationKey = $OperationKey
    status = "completed"
    completedAtUtc = [DateTimeOffset]::UtcNow.ToString("o")
    verification = $Verification
  }
  Write-Journal $Completed
  [ordered]@{ ok = $true; status = "completed"; operationKey = $OperationKey; verification = $Verification } |
    ConvertTo-Json -Depth 7
} catch {
  Write-Journal ([ordered]@{
    operationKey = $OperationKey
    status = "failed"
    completedAtUtc = [DateTimeOffset]::UtcNow.ToString("o")
    error = $_.Exception.Message
  })
  throw
}
