param(
  [string]$TaskName = "CodexSlackBridge",
  [string]$RegistryValueName = "CodexSlackBridge"
)

$ErrorActionPreference = "Stop"

$removed = $false
$runKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
$registryNames = @($RegistryValueName, $TaskName) | Select-Object -Unique
foreach ($name in $registryNames) {
  if (Get-ItemProperty -Path $runKey -Name $name -ErrorAction SilentlyContinue) {
    Remove-ItemProperty -Path $runKey -Name $name -ErrorAction Stop
    "Removed per-user startup registry entry '$name'."
    $removed = $true
  }
}

foreach ($task in @(Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue)) {
  $task | Unregister-ScheduledTask -Confirm:$false -ErrorAction Stop
  "Removed startup task '$TaskName'."
  $removed = $true
}

$startup = [Environment]::GetFolderPath("Startup")
$launcher = Join-Path $startup "$TaskName.cmd"
if (Test-Path -LiteralPath $launcher) {
  Remove-Item -LiteralPath $launcher -Force
  "Removed Startup folder launcher '$launcher'."
  $removed = $true
}

if (-not $removed) {
  "Startup entry '$TaskName' is not installed."
}
