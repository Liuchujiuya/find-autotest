# Windows exe packaging

Build on Windows:

```powershell
cd D:\find-autotest-repo
powershell -ExecutionPolicy Bypass -File .\packaging\build_exe.ps1
```

Output:

```text
dist-release/
  bin/
    find-autotest.exe
  config.yaml
```

The exe embeds:

- Python application code
- pytest/allure-pytest/playwright/requests/PyYAML dependencies
- FindAI autotest project template
- Codex skill files
- Playwright Chromium browser cache, when available under `%LOCALAPPDATA%\ms-playwright`

Users do not need Git or Python when using the packaged release.
