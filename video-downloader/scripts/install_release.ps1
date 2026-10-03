param(
    [switch]$BrowserCapture
)

$ErrorActionPreference = "Stop"
$ReleaseRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvPath = Join-Path $ReleaseRoot ".venv"
$PythonPath = Join-Path $VenvPath "Scripts\python.exe"
$Wheel = Get-ChildItem -LiteralPath $ReleaseRoot -Filter "videodownloader-*.whl" | Select-Object -First 1
$InstallTemp = Join-Path $ReleaseRoot ".install-temp"

function Assert-ExternalCommand {
    param([string]$Step)
    if ($LASTEXITCODE -ne 0) {
        throw "$Step 실패 (종료 코드: $LASTEXITCODE)"
    }
}

if ($null -eq $Wheel) {
    throw "설치할 VideoDownloader wheel을 찾을 수 없습니다."
}

New-Item -ItemType Directory -Force -Path $InstallTemp | Out-Null
$env:TEMP = $InstallTemp
$env:TMP = $InstallTemp
$env:TMPDIR = $InstallTemp

python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)"
Assert-ExternalCommand "Python 3.12 버전 확인"

if (-not (Test-Path -LiteralPath $PythonPath)) {
    python -m venv $VenvPath
    Assert-ExternalCommand "가상환경 생성"
}

$Package = $Wheel.FullName
if ($BrowserCapture) {
    $Package = "$($Wheel.FullName)[browser]"
}

& $PythonPath -m pip install $Package
Assert-ExternalCommand "VideoDownloader 설치"
if (-not (Test-Path -LiteralPath (Join-Path $ReleaseRoot "config.toml"))) {
    Copy-Item -LiteralPath (Join-Path $ReleaseRoot "config.example.toml") -Destination (Join-Path $ReleaseRoot "config.toml")
}

& (Join-Path $VenvPath "Scripts\video-downloader.exe") --version
Assert-ExternalCommand "설치 확인"
Remove-Item -LiteralPath $InstallTemp -Recurse -Force -ErrorAction SilentlyContinue
Write-Output "설치 완료: .\.venv\Scripts\video-downloader.exe doctor"
