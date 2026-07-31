---
name: find-autotest
description: Run and maintain the local FindAI automated testing project for platform-specific tests and configuration updates. Use when the user asks to execute, update, debug, or generate FindAI pytest/playwright/request/allure tests for 蒲公英, 星图, 小红书, or 抖音; when they specify which platform(s) to test; when browser pages must open in platform priority order; or when they need to modify login_info.yaml values such as 蒲公英/星图 accounts, FindAI account, or 小红书/抖音 API keys.
---

# Find Autotest

## Project

Use the local project at `D:\apitest_dev`.

The project runs Python + pytest + Playwright + requests + Allure tests for four platforms:

- `xhs` / `xiaohongshu` / `小红书`
- `dy` / `douyin` / `抖音`
- `pgy` / `pugongying` / `蒲公英`
- `xt` / `xingtu` / `星图`

When a user specifies platforms, always normalize and open them in this priority order:

`小红书 > 抖音 > 蒲公英 > 星图`

## Commands

## Mandatory preflight — do this before announcing or starting a test

For every request to run tests, perform these checks first. Do **not** say that testing has started, open browser pages, or run the CLI until all required checks pass.

1. Check `%USERPROFILE%\.find-autotest\extension` for an unpacked plugin, identified by `manifest.json` (a ZIP file alone is not sufficient).
2. If `manifest.json` is absent, stop and tell the user: `请将待测试插件安装包解压到 %USERPROFILE%\.find-autotest\extension，确保该目录或其一级子目录中包含 manifest.json，然后再开始测试。`
3. If the requested platforms include 小红书 (`xhs`) or 抖音 (`dy`), read the configured API key before running. If it is blank, stop and ask the user for the shared collect API key; update it with `find-autotest config --collect-api-key "..."` before testing.
4. Open the selected platform pages in priority order. After all selected platform pages are ready, always open the FindAI plugin login page last and wait until FindAI login has produced a token before running any test case. This applies to every platform selection, including only 小红书 or 抖音.
5. Only after these checks and the FindAI login complete may the test command be run. These checks apply even when the user asks to run all four platforms.

## Account configuration

Users can provide account credentials for 蒲公英、星图 and FindAI, which are saved in `config.yaml`:

```powershell
find-autotest config --pgy-username "..." --pgy-password "..." --xt-username "..." --xt-password "..." --findai-username "..." --findai-password "..."
```

Only update fields that the user explicitly provides. Never print passwords. If an account is not configured, do not attempt to auto-fill its login form; leave the opened platform or plugin login page for the user to complete manually.

Before running any live test, check that the FindAI Chrome extension package has been unpacked into `extension/` and that an `extension/manifest.json` file exists. If not, stop and ask the user to unpack the plugin installation package into that folder.

Before running `xhs` or `dy`, check the corresponding API key in `login_info.yaml`. If it is absent, stop and ask the user for the shared collect API key; update both platform keys with `--collect-api-key` before running the test.

Run all platforms:

```powershell
D:\apitest_dev\.venv\Scripts\python.exe D:\apitest_dev\run.py
```

Run selected platforms:

```powershell
D:\apitest_dev\.venv\Scripts\python.exe D:\apitest_dev\run.py --platforms 小红书,抖音
D:\apitest_dev\.venv\Scripts\python.exe D:\apitest_dev\run.py --platforms pgy,xt
```

Regenerate test data from the latest Excel file before running, when the user says the cases changed:

```powershell
cd D:\apitest_dev
D:\apitest_dev\.venv\Scripts\python.exe D:\apitest_dev\scripts\import_find_cases_v2.py
```

## Configuration

When the user asks to modify accounts, passwords, or API keys, update `D:\apitest_dev\login_info.yaml`.

Use the bundled helper because it creates a timestamped backup and prints only masked secrets:

```powershell
D:\apitest_dev\.venv\Scripts\python.exe C:\Users\Administrator\.codex\skills\find-autotest\scripts\update_login_info.py --pgy-username "..." --pgy-password "..."
D:\apitest_dev\.venv\Scripts\python.exe C:\Users\Administrator\.codex\skills\find-autotest\scripts\update_login_info.py --xt-username "..." --xt-password "..."
D:\apitest_dev\.venv\Scripts\python.exe C:\Users\Administrator\.codex\skills\find-autotest\scripts\update_login_info.py --collect-api-key "..."
```

Supported fields:

- `platforms.pugongying.username`
- `platforms.pugongying.password`
- `platforms.xingtu.username`
- `platforms.xingtu.password`
- `platforms.xiaohongshu.api_key` and `platforms.douyin.api_key`, written together with `--collect-api-key`
- `platforms.xiaohongshu.api_key`
- `platforms.douyin.api_key`
- `findai.username`
- `findai.password`

小红书 and 抖音 use the same API key. Prefer `--collect-api-key` so both `platforms.xiaohongshu.api_key` and `platforms.douyin.api_key` stay identical. Keep `--xhs-api-key` and `--dy-api-key` only for backward-compatible manual fixes.

Do not print full passwords, tokens, or API keys back to the user. If the user provides only some fields, update only those fields and leave the rest unchanged.

## Runtime Rules

`run.py --platforms ...` sets `FINDAI_TEST_PLATFORMS` for pytest. `testcases/conftest.py` opens only the requested browser pages, and `testcases/test_find_task_cases.py` filters `testdata/find_task_cases.yaml` to those platforms.

蒲公英 and 星图 use `/api/smartPluginTask/build`; they require the FindAI plugin login plus `base_url`, `token`, `device_id`, and platform `third_id`.

小红书 and 抖音 use `/api/collectTask/buildCollectTask`; they open the official websites for scan login but do not require `device_id` or `third_id`. They share one API key, stored in both locations in `login_info.yaml`:

- `platforms.xiaohongshu.api_key`
- `platforms.douyin.api_key`

The collect API request header must include:

```text
Authorization: key=<api_key>
```

## Reports

Allure raw results are written to `D:\apitest_dev\testresult\allure-results`.

The generated HTML report is written to `D:\apitest_dev\testresult\allure-report`.

Do not run live tests unless the user asks to execute them; these tests create real FindAI tasks.
