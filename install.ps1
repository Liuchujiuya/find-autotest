param(
    [string]$RepoUrl = "",
    [string]$Ref = "main",
    [string]$ProjectDir = "D:\apitest_dev",
    [string]$SkillName = "find-autotest",
    [switch]$InstallDeps,
    [switch]$Force
)

$ErrorActionPreference = "Stop"

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host ">>> $Message" -ForegroundColor Cyan
}

function Resolve-SourceRoot {
    $localRoot = $PSScriptRoot
    if ($localRoot -and (Test-Path -LiteralPath (Join-Path $localRoot "skills\$SkillName")) -and (Test-Path -LiteralPath (Join-Path $localRoot "project"))) {
        return $localRoot
    }

    if (-not $RepoUrl) {
        throw "RepoUrl is required when install.ps1 is executed from a remote one-liner. Example: powershell -ExecutionPolicy Bypass -Command `"irm <raw-install.ps1-url> | iex`" -RepoUrl <git-url>"
    }

    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        throw "git is not installed or not in PATH."
    }

    $tempRoot = Join-Path $env:TEMP ("find-autotest-" + [guid]::NewGuid().ToString("N"))
    Write-Step "Clone repository"
    git clone --branch $Ref --depth 1 $RepoUrl $tempRoot
    return $tempRoot
}

function Copy-DirectoryContent([string]$Source, [string]$Destination) {
    if (-not (Test-Path -LiteralPath $Source)) {
        throw "Source path not found: $Source"
    }
    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    Copy-Item -LiteralPath (Join-Path $Source "*") -Destination $Destination -Recurse -Force
}

$sourceRoot = Resolve-SourceRoot
$skillSource = Join-Path $sourceRoot "skills\$SkillName"
$projectSource = Join-Path $sourceRoot "project"
$skillDestRoot = Join-Path $env:USERPROFILE ".codex\skills"
$skillDest = Join-Path $skillDestRoot $SkillName

Write-Step "Install Codex skill"
New-Item -ItemType Directory -Force -Path $skillDestRoot | Out-Null
if ((Test-Path -LiteralPath $skillDest) -and $Force) {
    Remove-Item -LiteralPath $skillDest -Recurse -Force
}
Copy-Item -LiteralPath $skillSource -Destination $skillDestRoot -Recurse -Force
Write-Host "Skill installed: $skillDest"

Write-Step "Install autotest project"
New-Item -ItemType Directory -Force -Path $ProjectDir | Out-Null
foreach ($name in @("bases", "scripts", "testcases", "testdata", "tools")) {
    Copy-DirectoryContent -Source (Join-Path $projectSource $name) -Destination (Join-Path $ProjectDir $name)
}
foreach ($name in @("pytest.ini", "requirements.txt", "run.py")) {
    Copy-Item -LiteralPath (Join-Path $projectSource $name) -Destination (Join-Path $ProjectDir $name) -Force
}
New-Item -ItemType Directory -Force -Path (Join-Path $ProjectDir "extension"), (Join-Path $ProjectDir "testresult") | Out-Null

$exampleConfig = Join-Path $projectSource "login_info.yaml.example"
$installedExampleConfig = Join-Path $ProjectDir "login_info.yaml.example"
$installedConfig = Join-Path $ProjectDir "login_info.yaml"
Copy-Item -LiteralPath $exampleConfig -Destination $installedExampleConfig -Force
if (-not (Test-Path -LiteralPath $installedConfig)) {
    Copy-Item -LiteralPath $exampleConfig -Destination $installedConfig -Force
    Write-Host "Created config from example: $installedConfig"
} else {
    Write-Host "Existing config kept: $installedConfig"
}

if ($InstallDeps) {
    Write-Step "Install Python dependencies"
    $venvPython = Join-Path $ProjectDir ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $venvPython)) {
        python -m venv (Join-Path $ProjectDir ".venv")
    }
    & $venvPython -m pip install -r (Join-Path $ProjectDir "requirements.txt")
    & $venvPython -m playwright install chromium
}

Write-Step "Done"
Write-Host "Next:"
Write-Host "1. Put the unpacked FindAI Chrome extension into: $(Join-Path $ProjectDir 'extension')"
Write-Host "2. Update accounts/API key with:"
Write-Host ('   {0}\.venv\Scripts\python.exe {1}\scripts\update_login_info.py --pgy-username "..." --pgy-password "..."' -f $ProjectDir, $skillDest)
Write-Host ('   {0}\.venv\Scripts\python.exe {1}\scripts\update_login_info.py --xt-username "..." --xt-password "..."' -f $ProjectDir, $skillDest)
Write-Host ('   {0}\.venv\Scripts\python.exe {1}\scripts\update_login_info.py --collect-api-key "..."' -f $ProjectDir, $skillDest)
Write-Host "3. Run tests:"
Write-Host ('   {0}\.venv\Scripts\python.exe {0}\run.py --platforms pgy,xt' -f $ProjectDir)
