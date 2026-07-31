# find-autotest

Windows CLI for FindAI automated tests. Users need neither Git nor Python; Google Chrome must be installed.

## Install

Download the latest Windows release and install it to `%USERPROFILE%\.find-autotest`:

```powershell
$installer = Join-Path $env:TEMP 'find-autotest-install.ps1'; Invoke-WebRequest -UseBasicParsing 'https://raw.githubusercontent.com/Liuchujiuya/find-autotest/main/install.ps1' -OutFile $installer; powershell -NoProfile -ExecutionPolicy Bypass -File $installer
```

The GitHub release must include an asset named `find-autotest-windows.zip`. The installed directory contains only:

```text
.find-autotest/
  bin/find-autotest.exe
  config.yaml
  extension/
```

Existing `config.yaml` is preserved during upgrades. Add `-Force` to reset it.

## Use

Put the unpacked FindAI Chrome extension in `%USERPROFILE%\.find-autotest\extension`, then run:

```powershell
& "$env:USERPROFILE\.find-autotest\bin\find-autotest.exe" config --collect-api-key "..."
& "$env:USERPROFILE\.find-autotest\bin\find-autotest.exe" run --platforms dy
```

The executable stores its temporary test runtime under `%LOCALAPPDATA%\find-autotest`; credentials remain only in `config.yaml`.

## Release build

```powershell
powershell -ExecutionPolicy Bypass -File .\packaging\build_exe.ps1
```

Upload `dist-release\find-autotest-windows.zip` to a GitHub Release. The installer downloads that release asset.

The default build uses the user's installed Google Chrome and keeps the ZIP small. Use `-IncludePlaywrightBrowser` only for a fully bundled browser build; it adds roughly 500 MB.
