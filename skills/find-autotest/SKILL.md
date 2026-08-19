---
name: find-autotest
description: Run and maintain FindAI automated tests for 蒲公英, 星图, 小红书, and 抖音, using the installed Windows CLI by default.
---

# Find Autotest

## Default Runtime

Use the installed CLI by default. Do not invoke `D:\apitest_dev`, its Python environment, or its `login_info.yaml` unless the user explicitly asks for development-mode debugging or code changes.

```powershell
$findAutotest = Join-Path $env:USERPROFILE ".find-autotest\bin\find-autotest.exe"
& $findAutotest run --platforms xhs,dy
```

The installed CLI stores user configuration and the unpacked plugin in `%USERPROFILE%\.find-autotest`:

```text
.find-autotest/
  bin/find-autotest.exe
  config.yaml
  extension/
```

The installed runtime is `%LOCALAPPDATA%\find-autotest\project`; do not edit it directly because the CLI manages it.

## Test Setup

Before every live test, check `%USERPROFILE%\.find-autotest\extension` for an unpacked plugin. It must contain `manifest.json` directly or in a first-level child folder. If it is missing, stop and say:

`请将待测试插件安装包解压到 %USERPROFILE%\.find-autotest\extension，确保该目录或其一级子目录中包含 manifest.json，然后再开始测试。`

For 小红书 (`xhs`) or 抖音 (`dy`), require the shared collection API key before running:

```powershell
& $findAutotest config --collect-api-key "..."
```

Open selected platforms in this order: `小红书 > 抖音 > 蒲公英 > 星图`. Open the FindAI plugin login page last, and wait for a valid token before running cases.

小红书和抖音始终由用户手动扫码登录，不读取或填写平台账号密码。蒲公英和星图只有在用户明确配置用户名和密码后才自动填写；账号为空时只打开登录页并等待手动登录。

## Commands

Run all platforms:

```powershell
& $findAutotest run
```

Run selected platforms:

```powershell
& $findAutotest run --platforms 小红书,抖音
& $findAutotest run --platforms pgy,xt
```

Configure only values explicitly supplied by the user:

```powershell
& $findAutotest config --pgy-username "..." --pgy-password "..." --xt-username "..." --xt-password "..." --findai-username "..." --findai-password "..."
```

Do not print passwords, tokens, or API keys. Keep the shared collection API key identical for 小红书 and 抖音.

## Runtime Notes

蒲公英和星图 use `/api/smartPluginTask/build`; they require the plugin token, `base_url`, `device_id`, and platform `third_id`.

小红书和抖音 use `/api/collectTask/buildCollectTask`; they require the shared collection API key and do not require `device_id` or `third_id`.

Allure HTML reports are saved under `%LOCALAPPDATA%\find-autotest\project\testresult\allure-report`. The local report URL is accessible only from the test-running computer while its local HTTP service is still running.

## Development Mode

Only when the user explicitly requests work on the source project, use `D:\apitest_dev`. In that mode, use `D:\apitest_dev\extension`, `D:\apitest_dev\login_info.yaml`, and `D:\apitest_dev\.venv\Scripts\python.exe D:\apitest_dev\run.py`.
