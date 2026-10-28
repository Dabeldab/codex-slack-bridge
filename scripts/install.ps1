$ErrorActionPreference = "Stop"

Set-Location (Split-Path -Parent $PSScriptRoot)

if (Test-Path .packages) {
  Remove-Item -Recurse -Force .packages
}

py -3 -m pip install `
  --disable-pip-version-check `
  --progress-bar off `
  --timeout 60 `
  --retries 2 `
  --target .packages `
  -r requirements.txt
