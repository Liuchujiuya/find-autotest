param(
    [string]$Repo = "Liuchujiuya/find-autotest",
    [string]$InstallDir = (Join-Path $env:USERPROFILE ".find-autotest"),
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$assetUrl = "https://github.com/$Repo/releases/latest/download/find-autotest.exe"
$binDir = Join-Path $InstallDir "bin"
$exePath = Join-Path $binDir "find-autotest.exe"

New-Item -ItemType Directory -Force -Path $binDir, (Join-Path $InstallDir "extension") | Out-Null
Invoke-WebRequest -Uri $assetUrl -OutFile $exePath
Unblock-File -LiteralPath $exePath -ErrorAction SilentlyContinue

$installArgs = @("install")
if ($Force) {
    $installArgs += "--force"
}
& $exePath @installArgs
if ($LASTEXITCODE -ne 0) {
    throw "find-autotest setup failed with exit code $LASTEXITCODE"
}

Write-Host "Installed Find Autotest: $InstallDir"
Write-Host "Extension folder: $(Join-Path $InstallDir 'extension')"
