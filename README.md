# find-autotest

FindAI 自动化测试分发仓库，包含：

- Codex skill：`skills/find-autotest`
- 本地自动化测试项目模板：`project`
- 一键安装脚本：`install.ps1`

## 远程一键安装

推荐命令，会下载整个项目、安装 Codex skill，并创建 Python 虚拟环境依赖：

```powershell
powershell -ExecutionPolicy Bypass -Command "& ([scriptblock]::Create((irm 'https://raw.githubusercontent.com/Liuchujiuya/find-autotest/main/install.ps1'))) -InstallDeps"
```

如果只想安装文件，不安装 Python 依赖：

```powershell
powershell -ExecutionPolicy Bypass -Command "irm https://raw.githubusercontent.com/Liuchujiuya/find-autotest/main/install.ps1 | iex"
```

默认安装位置：

- 自动化测试项目：`D:\apitest_dev`
- Codex skill：`%USERPROFILE%\.codex\skills\find-autotest`

自定义项目安装目录：

```powershell
powershell -ExecutionPolicy Bypass -Command "& ([scriptblock]::Create((irm 'https://raw.githubusercontent.com/Liuchujiuya/find-autotest/main/install.ps1'))) -ProjectDir 'E:\find-autotest' -InstallDeps"
```

## 本地克隆安装

```powershell
git clone https://github.com/Liuchujiuya/find-autotest.git
cd find-autotest
powershell -ExecutionPolicy Bypass -File .\install.ps1 -InstallDeps
```

## 安装后配置

安装后不要提交真实账号、密码、token、API key。使用 skill 内置脚本写入本地配置：

```powershell
D:\apitest_dev\.venv\Scripts\python.exe C:\Users\Administrator\.codex\skills\find-autotest\scripts\update_login_info.py --pgy-username "..." --pgy-password "..."
D:\apitest_dev\.venv\Scripts\python.exe C:\Users\Administrator\.codex\skills\find-autotest\scripts\update_login_info.py --xt-username "..." --xt-password "..."
D:\apitest_dev\.venv\Scripts\python.exe C:\Users\Administrator\.codex\skills\find-autotest\scripts\update_login_info.py --collect-api-key "..."
```

小红书和抖音共用 `--collect-api-key`。

## 安装后在 Codex 中引用

安装完成后，用户可以在 Codex 里直接说：

```text
使用 find-autotest，执行蒲公英和星图用例
```

或：

```text
使用 find-autotest，更新蒲公英账号和小红书/抖音 api key
```

Codex 会在下一轮对话中发现已安装的 skill。
