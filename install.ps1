param(
    [string]$Repo = "Liuchujiuya/find-autotest",
    [string]$InstallDir = (Join-Path $env:USERPROFILE ".find-autotest"),
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$archiveUrl = "https://github.com/$Repo/releases/latest/download/find-autotest-windows.zip"
$tempRoot = Join-Path $env:TEMP ("find-autotest-" + [guid]::NewGuid().ToString("N"))

try {
    New-Item -ItemType Directory -Force -Path $tempRoot | Out-Null
    $archivePath = Join-Path $tempRoot "find-autotest-windows.zip"
    Invoke-WebRequest -Uri $archiveUrl -OutFile $archivePath
    Expand-Archive -LiteralPath $archivePath -DestinationPath $tempRoot -Force

    foreach ($name in @("bin", "config.yaml", "extension")) {
        $source = Join-Path $tempRoot $name
        if (-not (Test-Path -LiteralPath $source)) {
            throw "Release archive is missing: $name"
        }
    }

    New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
    foreach ($name in @("bin", "extension")) {
        $source = Join-Path $tempRoot $name
        $destination = Join-Path $InstallDir $name
        if (Test-Path -LiteralPath $destination) {
            Remove-Item -LiteralPath $destination -Recurse -Force
        }
        Copy-Item -LiteralPath $source -Destination $destination -Recurse -Force
    }

    $configSource = Join-Path $tempRoot "config.yaml"
    $configDestination = Join-Path $InstallDir "config.yaml"
    if ($Force -or -not (Test-Path -LiteralPath $configDestination)) {
        Copy-Item -LiteralPath $configSource -Destination $configDestination -Force
    }

    Write-Host "Installed Find Autotest: $InstallDir"
    Write-Host "Run: & '$InstallDir\bin\find-autotest.exe' where"
} finally {
    if (Test-Path -LiteralPath $tempRoot) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force
    }
}
