# find-autotest

FindAI 自动化测试分发仓库，包含 Codex skill 和本地 pytest/playwright/request/allure 自动化测试项目模板。

## 安装

克隆仓库后执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1 -InstallDeps
```

远程一键安装时，先把下面的地址替换为实际 GitLab raw 地址和仓库地址：

```powershell
powershell -ExecutionPolicy Bypass -Command "irm https://gitlab.example.com/find/find-autotest/-/raw/main/install.ps1 | iex" -RepoUrl "https://gitlab.example.com/find/find-autotest.git" -InstallDeps
```

## 配置

安装后不要手动提交真实账号密码。使用 skill 内置脚本写入本地配置：

```powershell
D:\apitest_dev\.venv\Scripts\python.exe C:\Users\Administrator\.codex\skills\find-autotest\scripts\update_login_info.py --pgy-username "..." --pgy-password "..."
D:\apitest_dev\.venv\Scripts\python.exe C:\Users\Administrator\.codex\skills\find-autotest\scripts\update_login_info.py --xt-username "..." --xt-password "..."
D:\apitest_dev\.venv\Scripts\python.exe C:\Users\Administrator\.codex\skills\find-autotest\scripts\update_login_info.py --collect-api-key "..."
```

小红书和抖音共用 `--collect-api-key`。
