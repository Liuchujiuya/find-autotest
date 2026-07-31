param(
    [string]$Python = "python",
    [switch]$IncludePlaywrightBrowser
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$distRoot = Join-Path $root "dist-release"
$workRoot = Join-Path $root "build-release"
$venvRoot = Join-Path $root ".build-venv"
$browserPath = Join-Path $env:LOCALAPPDATA "ms-playwright"

Set-Location $root

if (-not (Test-Path -LiteralPath (Join-Path $venvRoot "Scripts\python.exe"))) {
    & $Python -m venv $venvRoot
}
$buildPython = Join-Path $venvRoot "Scripts\python.exe"
& $buildPython -m pip install --upgrade pip
& $buildPython -m pip install -r (Join-Path $root "project\requirements.txt") pyinstaller

if ($IncludePlaywrightBrowser) {
    & $buildPython -m playwright install chromium
}

$addData = @(
    "--add-data", "$root\project;project"
)

if ($IncludePlaywrightBrowser -and (Test-Path -LiteralPath $browserPath)) {
    $addData += @("--add-data", "$browserPath;ms-playwright")
}

& $buildPython -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --name find-autotest `
    --hidden-import requests `
    --hidden-import yaml `
    --hidden-import playwright `
    --hidden-import playwright.sync_api `
    --hidden-import allure `
    --hidden-import allure_pytest `
    --hidden-import allure_pytest.plugin `
    --hidden-import allure_pytest.listener `
    --hidden-import allure_pytest.helper `
    --hidden-import allure_pytest.utils `
    --hidden-import allure_commons `
    --hidden-import openpyxl `
    --distpath (Join-Path $distRoot "bin") `
    --workpath $workRoot `
    @addData `
    (Join-Path $root "packaging\find_autotest_cli.py")

Copy-Item -LiteralPath (Join-Path $root "project\login_info.yaml.example") -Destination (Join-Path $distRoot "config.yaml") -Force
New-Item -ItemType Directory -Force -Path (Join-Path $distRoot "extension") | Out-Null
New-Item -ItemType File -Force -Path (Join-Path $distRoot "extension\.gitkeep") | Out-Null
Compress-Archive -Path (Join-Path $distRoot "bin"), (Join-Path $distRoot "config.yaml"), (Join-Path $distRoot "extension") -DestinationPath (Join-Path $distRoot "find-autotest-windows.zip") -Force

Write-Host ""
Write-Host "Release generated:"
Write-Host "  $distRoot\bin\find-autotest.exe"
Write-Host "  $distRoot\config.yaml"
Write-Host "  $distRoot\extension\"
Write-Host "  $distRoot\find-autotest-windows.zip"
Write-Host ""
Write-Host "User quick start:"
Write-Host "  .\bin\find-autotest.exe install"
Write-Host "  .\bin\find-autotest.exe config --pgy-username `"..."`" --pgy-password `"..."`""
Write-Host "  .\bin\find-autotest.exe run --platforms pgy,xt"
