param(
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$RuntimeRoot = Join-Path $Root "data\local_voice"
$VenvRoot = Join-Path $RuntimeRoot ".venv"
$Python = Join-Path $VenvRoot "Scripts\python.exe"
$WhisperRoot = Join-Path $RuntimeRoot "models\faster-whisper-base.en"
$KokoroRoot = Join-Path $RuntimeRoot "models\kokoro"
$ManifestPath = Join-Path $RuntimeRoot "SHA256SUMS.json"
$WhisperRevision = "fad79c08a643e3aa623adfae1c1861e50438482d"

# The bridge normally exports its shared .packages path. Do not let that path
# satisfy dependencies for this deliberately isolated local inference runtime.
$env:PYTHONPATH = ""
$env:PYTHONHOME = ""

New-Item -ItemType Directory -Force -Path $RuntimeRoot, $WhisperRoot, $KokoroRoot | Out-Null

if (-not (Test-Path -LiteralPath $Python)) {
    & py -3 -m venv $VenvRoot
    if ($LASTEXITCODE -ne 0) { throw "Could not create the local voice virtual environment." }
}

& $Python -m pip install --disable-pip-version-check --only-binary=:all: --requirement (Join-Path $Root "requirements-local-voice.txt")
if ($LASTEXITCODE -ne 0) { throw "Could not install the pinned local voice packages." }

$Downloads = @(
    @{
        Name = "Whisper config"
        Url = "https://huggingface.co/Systran/faster-whisper-base.en/resolve/$WhisperRevision/config.json?download=true"
        Path = Join-Path $WhisperRoot "config.json"
    },
    @{
        Name = "Whisper model"
        Url = "https://huggingface.co/Systran/faster-whisper-base.en/resolve/$WhisperRevision/model.bin?download=true"
        Path = Join-Path $WhisperRoot "model.bin"
        ExpectedSha256 = "2a166925539a16005f14ff328359f9b9adb9dc4fb631bb3b227526862e93e2ef"
    },
    @{
        Name = "Whisper tokenizer"
        Url = "https://huggingface.co/Systran/faster-whisper-base.en/resolve/$WhisperRevision/tokenizer.json?download=true"
        Path = Join-Path $WhisperRoot "tokenizer.json"
    },
    @{
        Name = "Whisper vocabulary"
        Url = "https://huggingface.co/Systran/faster-whisper-base.en/resolve/$WhisperRevision/vocabulary.txt?download=true"
        Path = Join-Path $WhisperRoot "vocabulary.txt"
    },
    @{
        Name = "Kokoro int8 model"
        Url = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.int8.onnx"
        Path = Join-Path $KokoroRoot "kokoro-v1.0.int8.onnx"
        ExpectedSha256 = "6e742170d309016e5891a994e1ce1559c702a2ccd0075e67ef7157974f6406cb"
    },
    @{
        Name = "Kokoro voices"
        Url = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin"
        Path = Join-Path $KokoroRoot "voices-v1.0.bin"
        ExpectedSha256 = "bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d"
    }
)

foreach ($Item in $Downloads) {
    if ((Test-Path -LiteralPath $Item.Path) -and -not $Force) {
        Write-Host "$($Item.Name) already exists; preserving it."
        continue
    }
    $Partial = "$($Item.Path).partial"
    Remove-Item -LiteralPath $Partial -Force -ErrorAction SilentlyContinue
    Write-Host "Downloading $($Item.Name) from its pinned official source..."
    Invoke-WebRequest -Uri $Item.Url -OutFile $Partial -UseBasicParsing
    Move-Item -LiteralPath $Partial -Destination $Item.Path -Force
}

$Files = foreach ($Item in $Downloads) {
    if (-not (Test-Path -LiteralPath $Item.Path)) { throw "Missing expected file: $($Item.Path)" }
    $Hash = Get-FileHash -LiteralPath $Item.Path -Algorithm SHA256
    $ActualSha256 = $Hash.Hash.ToLowerInvariant()
    if ($Item.ExpectedSha256 -and $ActualSha256 -ne $Item.ExpectedSha256) {
        throw "SHA256 verification failed for $($Item.Name). The file was not accepted."
    }
    if (-not $Item.Path.StartsWith($Root, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Downloaded file escaped the repository runtime directory."
    }
    [ordered]@{
        path = $Item.Path.Substring($Root.Length).TrimStart('\')
        sha256 = $ActualSha256
        expectedSha256 = $Item.ExpectedSha256
        verified = (-not $Item.ExpectedSha256) -or ($ActualSha256 -eq $Item.ExpectedSha256)
        source = $Item.Url
    }
}

$FreezePath = Join-Path $RuntimeRoot "requirements-resolved.txt"
& $Python -m pip freeze --all | Set-Content -LiteralPath $FreezePath -Encoding UTF8

[ordered]@{
    generatedAt = [DateTimeOffset]::UtcNow.ToString("o")
    whisperRevision = $WhisperRevision
    files = @($Files)
} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $ManifestPath -Encoding UTF8

Write-Host "Local voice runtime installed without enabling any cloud fallback."
Write-Host "Runtime Python: $Python"
Write-Host "Integrity manifest: $ManifestPath"
