$ErrorActionPreference = "Stop"

Set-Location (Split-Path -Parent $PSScriptRoot)

if (-not (Test-Path .packages)) {
  throw "Missing .packages. Run .\scripts\install.ps1 first."
}

py -3 -m pip install `
  --disable-pip-version-check `
  --progress-bar off `
  --timeout 120 `
  --retries 2 `
  --target .packages `
  -r requirements-memory.txt
