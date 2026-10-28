param(
    [string]$ProjectId = "gen-lang-client-0051653266",
    [string]$BridgeEnvPath = "C:\Users\redma\Workworkworkworkworkwork\codex-slack-bridge\.env",
    [string]$SalesforceEnvPath = "C:\Users\redma\Workworkworkworkworkwork\auto-tickets\logmein-connector\.env",
    [string]$GmailTokenPath = "C:\Users\redma\Uploader\token.json",
    [string]$OpsEnvPath = "C:\Users\redma\Workworkworkworkworkwork\codex-slack-bridge\config\ops.env",
    [string]$RescueEnvPath = "C:\Users\redma\Workworkworkworkworkwork\auto-tickets\logmein-connector\.env",
    [string]$SingaporeGmailClientPath = "C:\Users\redma\Uploader\credentials.json",
    [string]$SingaporeServerCatalogPath = "C:\Users\redma\Uploader\servers.json",
    [string]$SingaporeIdentityMapPath = "C:\Users\redma\Uploader\salesforce-identity-map.json",
    [string]$GitHubAppIdPath = "C:\Users\redma\AppData\Local\NovaAgentRuntime\github-app\app-id.txt",
    [string]$GitHubAppInstallationIdPath = "C:\Users\redma\AppData\Local\NovaAgentRuntime\github-app\installation-id.txt",
    [string]$GitHubAppPrivateKeyPath = "C:\Users\redma\AppData\Local\NovaAgentRuntime\github-app\private-key.pem",
    [string]$GoogleWorkspaceAdcPath = "$env:APPDATA\gcloud\application_default_credentials.json",
    [string]$VaultToolPath = "C:\Users\redma\AppData\Local\CodexBillingAgent\secure_secret_store.ps1",
    [string]$CodexAccessTokenPath = "",
    [switch]$OnlyCodexAccessToken,
    [switch]$OnlyRoryOperatorSecrets,
    [switch]$AllowMissingCodexAccessToken,
    [switch]$AllowMissingGitHubApp,
    [switch]$VerifyExisting,
    [switch]$Apply
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

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

function Read-DotEnvValue([string]$Path, [string]$Name) {
    if (-not (Test-Path -LiteralPath $Path)) { throw "Credential source file was not found: $Path" }
    foreach ($line in Get-Content -LiteralPath $Path) {
        if ($line -match ('^\s*' + [regex]::Escape($Name) + '\s*=\s*(.*)$')) {
            $value = [string]$Matches[1]
            if ($value.Length -ge 2 -and (($value[0] -eq '"' -and $value[-1] -eq '"') -or ($value[0] -eq "'" -and $value[-1] -eq "'"))) {
                $value = $value.Substring(1, $value.Length - 2)
            }
            return $value
        }
    }
    return ""
}

function Read-VaultSecret([string]$Name) {
    if (-not (Test-Path -LiteralPath $VaultToolPath)) { throw "Credential vault tool was not found." }
    if (-not (Get-Command Get-SecretValue -ErrorAction SilentlyContinue)) {
        . $VaultToolPath -Action list | Out-Null
    }
    return Get-SecretValue $Name
}

function Read-CodexAccessToken {
    if ($CodexAccessTokenPath) {
        if (-not (Test-Path -LiteralPath $CodexAccessTokenPath)) { return "" }
        return [IO.File]::ReadAllText((Resolve-Path -LiteralPath $CodexAccessTokenPath).Path).Trim()
    }
    return [string][Environment]::GetEnvironmentVariable("CODEX_ACCESS_TOKEN", "Process")
}

function Read-GitHubUserToken {
    $gh = Get-Command gh.exe -ErrorAction SilentlyContinue
    if (-not $gh) { $gh = Get-Command gh -ErrorAction SilentlyContinue }
    if (-not $gh) { throw "GitHub CLI was not found." }
    $token = & $gh.Source auth token 2>$null | Select-Object -First 1
    if ($LASTEXITCODE -ne 0 -or -not $token) { throw "GitHub CLI could not provide the authenticated operator token." }
    return ([string]$token).Trim()
}

function Test-SecretExists([string]$SecretId) {
    $priorPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        & $script:Gcloud secrets describe $SecretId "--project=$ProjectId" "--format=value(name)" "--billing-project=$ProjectId" 1>$null 2>$null
        return $LASTEXITCODE -eq 0
    }
    finally { $ErrorActionPreference = $priorPreference }
}

function Add-SecretVersion([string]$SecretId, [string]$Value) {
    if ([string]::IsNullOrEmpty($Value)) { throw "Refusing to store an empty value for $SecretId." }
    if (-not (Test-SecretExists $SecretId)) {
        Invoke-Gcloud secrets create $SecretId "--project=$ProjectId" --replication-policy=automatic `
            "--labels=application=nova-agent-runtime,environment=staging" --quiet | Out-Null
    }

    $temporary = Join-Path ([IO.Path]::GetTempPath()) ("nova-secret-" + [guid]::NewGuid().ToString("N") + ".tmp")
    try {
        [IO.File]::WriteAllText($temporary, $Value, [Text.UTF8Encoding]::new($false))
        $aclOutput = & icacls $temporary /inheritance:r /grant:r "${env:USERNAME}:(R,W)" 2>&1
        if ($LASTEXITCODE -ne 0) { throw "Could not restrict the temporary secret file ACL." }
        $version = Invoke-Gcloud secrets versions add $SecretId "--project=$ProjectId" "--data-file=$temporary" `
            "--format=value(name)" "--billing-project=$ProjectId" --quiet | Select-Object -First 1
        return ([string]$version).Trim().Split('/')[-1]
    }
    finally {
        if (Test-Path -LiteralPath $temporary) {
            [IO.File]::WriteAllBytes($temporary, [byte[]]::new(0))
            Remove-Item -LiteralPath $temporary -Force
        }
    }
}

function Resolve-LatestSecretVersion([string]$SecretId) {
    if (-not (Test-SecretExists $SecretId)) { return "" }
    try {
        $version = Invoke-Gcloud secrets versions describe latest "--secret=$SecretId" `
            "--project=$ProjectId" "--format=value(name)" "--billing-project=$ProjectId" | Select-Object -First 1
        if (-not $version) { return "" }
        return ([string]$version).Trim().Split('/')[-1]
    }
    catch { return "" }
}

function Test-FixedTimeByteEquality([byte[]]$Left, [byte[]]$Right) {
    if ($Left.Length -ne $Right.Length) { return $false }
    $difference = 0
    for ($index = 0; $index -lt $Left.Length; $index++) {
        $difference = $difference -bor ($Left[$index] -bxor $Right[$index])
    }
    return $difference -eq 0
}

function Test-SecretVersionValue([string]$SecretId, [string]$Version, [string]$Expected) {
    $temporary = Join-Path ([IO.Path]::GetTempPath()) ("nova-secret-readback-" + [guid]::NewGuid().ToString("N") + ".tmp")
    try {
        Invoke-Gcloud secrets versions access $Version "--secret=$SecretId" "--project=$ProjectId" `
            "--out-file=$temporary" "--billing-project=$ProjectId" --quiet | Out-Null
        $actual = [IO.File]::ReadAllText($temporary, [Text.UTF8Encoding]::new($false))
        $expectedBytes = [Text.Encoding]::UTF8.GetBytes($Expected)
        $actualBytes = [Text.Encoding]::UTF8.GetBytes($actual)
        try { return Test-FixedTimeByteEquality $expectedBytes $actualBytes }
        finally {
            [Array]::Clear($expectedBytes, 0, $expectedBytes.Length)
            [Array]::Clear($actualBytes, 0, $actualBytes.Length)
        }
    }
    finally {
        if (Test-Path -LiteralPath $temporary) {
            [IO.File]::WriteAllBytes($temporary, [byte[]]::new(0))
            Remove-Item -LiteralPath $temporary -Force
        }
    }
}

Enable-ApplicationDefaultToken
try {
    $selectionCount = @($OnlyCodexAccessToken, $OnlyRoryOperatorSecrets).Where({ $_ }).Count
    if ($selectionCount -gt 1) {
        throw "OnlyCodexAccessToken and OnlyRoryOperatorSecrets are mutually exclusive."
    }
    $sources = @(
        @{ id = "nova-agents-slack-app-token"; value = { Read-DotEnvValue $BridgeEnvPath "SLACK_APP_TOKEN" }; required = $true },
        @{ id = "nova-agents-slack-bot-token"; value = { Read-DotEnvValue $BridgeEnvPath "SLACK_BOT_TOKEN" }; required = $true },
        @{ id = "nova-agents-gmail-oauth-token"; value = { if (Test-Path -LiteralPath $GmailTokenPath) { [IO.File]::ReadAllText((Resolve-Path -LiteralPath $GmailTokenPath).Path) } else { "" } }; required = $true },
        @{ id = "nova-agents-salesforce-client-id"; value = { Read-DotEnvValue $SalesforceEnvPath "SALESFORCE_CLIENT_ID" }; required = $true },
        @{ id = "nova-agents-salesforce-client-secret"; value = { Read-DotEnvValue $SalesforceEnvPath "SALESFORCE_CLIENT_SECRET" }; required = $true },
        @{ id = "nova-agents-salesforce-login-url"; value = { Read-DotEnvValue $SalesforceEnvPath "SALESFORCE_LOGIN_URL" }; required = $true },
        @{ id = "nova-agents-salesforce-instance-url"; value = { Read-DotEnvValue $SalesforceEnvPath "SALESFORCE_INSTANCE_URL" }; required = $true },
        @{ id = "nova-agents-chargify-api-key"; value = { Read-VaultSecret "CHARGIFY_API_KEY" }; required = $true },
        @{ id = "nova-agents-chargify-base-url"; value = { Read-VaultSecret "CHARGIFY_BASE_URL" }; required = $true },
        @{ id = "nova-agents-rescue-user"; value = { Read-DotEnvValue $RescueEnvPath "RESCUE_USER" }; required = $true },
        @{ id = "nova-agents-rescue-password"; value = { Read-DotEnvValue $RescueEnvPath "RESCUE_PASS" }; required = $true },
        @{ id = "nova-agents-rescue-base"; value = { Read-DotEnvValue $RescueEnvPath "RESCUE_BASE" }; required = $true },
        @{ id = "nova-agents-rescue-node-id"; value = { Read-DotEnvValue $RescueEnvPath "RESCUE_GROUP_NODE_ID" }; required = $true },
        @{ id = "nova-agents-zoom-oauth-client-id"; value = { Read-DotEnvValue $OpsEnvPath "ZOOM_OAUTH_CLIENT_ID" }; required = $true },
        @{ id = "nova-agents-zoom-oauth-client-secret"; value = { Read-DotEnvValue $OpsEnvPath "ZOOM_OAUTH_CLIENT_SECRET" }; required = $true },
        @{ id = "nova-agents-zoom-oauth-refresh-token"; value = { Read-DotEnvValue $OpsEnvPath "ZOOM_OAUTH_REFRESH_TOKEN" }; required = $true },
        @{ id = "nova-agents-zoom-s2s-account-id"; value = { Read-DotEnvValue $OpsEnvPath "ZOOM_ACCOUNT_ID" }; required = $true },
        @{ id = "nova-agents-zoom-s2s-client-id"; value = { Read-DotEnvValue $OpsEnvPath "ZOOM_CLIENT_ID" }; required = $true },
        @{ id = "nova-agents-zoom-s2s-client-secret"; value = { Read-DotEnvValue $OpsEnvPath "ZOOM_CLIENT_SECRET" }; required = $true },
        @{ id = "nova-agents-zoom-team-chat-sender-user-id"; value = { Read-DotEnvValue $OpsEnvPath "ZOOM_TEAM_CHAT_SENDER_USER_ID" }; required = $true },
        @{ id = "nova-agents-zoom-singapore-julio-contact"; value = { Read-DotEnvValue $OpsEnvPath "ZOOM_SINGAPORE_JULIO_CONTACT" }; required = $true },
        @{ id = "nova-agents-zoom-internal-wiko-contact"; value = { Read-DotEnvValue $OpsEnvPath "ZOOM_INTERNAL_REQUEST_WIKO_CONTACT" }; required = $true },
        @{ id = "nova-agents-singapore-gmail-client"; value = { if (Test-Path -LiteralPath $SingaporeGmailClientPath) { [IO.File]::ReadAllText((Resolve-Path -LiteralPath $SingaporeGmailClientPath).Path) } else { "" } }; required = $true },
        @{ id = "nova-agents-singapore-gmail-token"; value = { if (Test-Path -LiteralPath $GmailTokenPath) { [IO.File]::ReadAllText((Resolve-Path -LiteralPath $GmailTokenPath).Path) } else { "" } }; required = $true },
        @{ id = "nova-agents-singapore-server-catalog"; value = { if (Test-Path -LiteralPath $SingaporeServerCatalogPath) { [IO.File]::ReadAllText((Resolve-Path -LiteralPath $SingaporeServerCatalogPath).Path) } else { "" } }; required = $true },
        @{ id = "nova-agents-singapore-salesforce-identity-map"; value = { if (Test-Path -LiteralPath $SingaporeIdentityMapPath) { [IO.File]::ReadAllText((Resolve-Path -LiteralPath $SingaporeIdentityMapPath).Path) } else { "" } }; required = $true },
        @{ id = "nova-agents-github-app-id"; value = { if (Test-Path -LiteralPath $GitHubAppIdPath) { [IO.File]::ReadAllText((Resolve-Path -LiteralPath $GitHubAppIdPath).Path).Trim() } else { "" } }; required = (-not $AllowMissingGitHubApp) },
        @{ id = "nova-agents-github-app-installation-id"; value = { if (Test-Path -LiteralPath $GitHubAppInstallationIdPath) { [IO.File]::ReadAllText((Resolve-Path -LiteralPath $GitHubAppInstallationIdPath).Path).Trim() } else { "" } }; required = (-not $AllowMissingGitHubApp) },
        @{ id = "nova-agents-github-app-private-key"; value = { if (Test-Path -LiteralPath $GitHubAppPrivateKeyPath) { [IO.File]::ReadAllText((Resolve-Path -LiteralPath $GitHubAppPrivateKeyPath).Path) } else { "" } }; required = (-not $AllowMissingGitHubApp) },
        @{ id = "nova-agents-github-user-token"; value = { Read-GitHubUserToken }; required = $true },
        @{ id = "nova-agents-google-workspace-adc"; value = { if (Test-Path -LiteralPath $GoogleWorkspaceAdcPath) { [IO.File]::ReadAllText((Resolve-Path -LiteralPath $GoogleWorkspaceAdcPath).Path) } else { "" } }; required = $true },
        @{ id = "nova-agents-codex-access-token"; value = { Read-CodexAccessToken }; required = (-not $AllowMissingCodexAccessToken) }
    )
    if ($OnlyCodexAccessToken) {
        $sources = @($sources | Where-Object { [string]$_.id -eq "nova-agents-codex-access-token" })
    }
    elseif ($OnlyRoryOperatorSecrets) {
        $sources = @($sources | Where-Object { [string]$_.id -in @(
            "nova-agents-github-user-token",
            "nova-agents-google-workspace-adc"
        ) })
    }

    $values = @{}
    $missing = New-Object System.Collections.Generic.List[string]
    foreach ($source in $sources) {
        $value = & $source.value
        if ([string]::IsNullOrEmpty([string]$value)) {
            if ([bool]$source.required) { [void]$missing.Add([string]$source.id) }
            continue
        }
        $values[[string]$source.id] = [string]$value
    }
    if ($missing.Count -gt 0) {
        throw "Required secret sources are unavailable: $($missing -join ', ')"
    }

    if ($VerifyExisting) {
        $readback = @()
        foreach ($secretId in ($values.Keys | Sort-Object)) {
            $version = Resolve-LatestSecretVersion $secretId
            $matches = $false
            if ($version) { $matches = Test-SecretVersionValue $secretId $version $values[$secretId] }
            $readback += [pscustomobject]@{ secret = $secretId; version = $version; matchesSource = $matches }
        }
        if (-not $OnlyCodexAccessToken -and -not $OnlyRoryOperatorSecrets) {
            $operatorVersion = Resolve-LatestSecretVersion "nova-agents-operator-signing-key"
            $operatorPresent = $false
            if ($operatorVersion) {
                $temporary = Join-Path ([IO.Path]::GetTempPath()) ("nova-secret-readback-" + [guid]::NewGuid().ToString("N") + ".tmp")
                try {
                    Invoke-Gcloud secrets versions access $operatorVersion --secret=nova-agents-operator-signing-key `
                        "--project=$ProjectId" "--out-file=$temporary" "--billing-project=$ProjectId" --quiet | Out-Null
                    $operatorPresent = (Get-Item -LiteralPath $temporary).Length -ge 32
                }
                finally { Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue }
            }
            $readback += [pscustomobject]@{ secret = "nova-agents-operator-signing-key"; version = $operatorVersion; matchesSource = $operatorPresent }
        }
        $ok = @($readback | Where-Object { -not $_.matchesSource }).Count -eq 0
        [pscustomobject]@{
            ok = $ok
            mode = "verify"
            project = $ProjectId
            readback = $readback
            missingOptional = @($sources | Where-Object { -not $values.ContainsKey([string]$_.id) } | ForEach-Object { [string]$_.id })
            valuesPrinted = $false
        } | ConvertTo-Json -Depth 6
        if (-not $ok) { exit 1 }
        exit 0
    }

    if (-not $Apply) {
        [pscustomobject]@{
            ok = $true
            mode = "plan"
            project = $ProjectId
            ready = @($values.Keys | Sort-Object)
            missingOptional = @($sources | Where-Object { -not $values.ContainsKey([string]$_.id) } | ForEach-Object { [string]$_.id })
            valuesPrinted = $false
        } | ConvertTo-Json -Depth 5
        exit 0
    }

    Invoke-Gcloud services enable secretmanager.googleapis.com "--project=$ProjectId" --quiet | Out-Null
    $versions = @{}
    foreach ($secretId in ($values.Keys | Sort-Object)) {
        $versions[$secretId] = Add-SecretVersion $secretId $values[$secretId]
    }

    if (-not $OnlyCodexAccessToken -and -not $OnlyRoryOperatorSecrets -and -not (Test-SecretExists "nova-agents-operator-signing-key")) {
        $random = [byte[]]::new(48)
        [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($random)
        try {
            $versions["nova-agents-operator-signing-key"] = Add-SecretVersion `
                "nova-agents-operator-signing-key" ([Convert]::ToBase64String($random))
        }
        finally { [Array]::Clear($random, 0, $random.Length) }
    }

    [pscustomobject]@{
        ok = $true
        mode = "applied"
        project = $ProjectId
        versions = $versions
        valuesPrinted = $false
    } | ConvertTo-Json -Depth 6
}
finally {
    Remove-Item Env:CLOUDSDK_AUTH_ACCESS_TOKEN -ErrorAction SilentlyContinue
}
