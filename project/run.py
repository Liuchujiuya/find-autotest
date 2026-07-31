from __future__ import annotations  # 让类型注解延迟解析，兼容不同 Python 版本的注解行为。

import argparse  # 用于解析命令行参数，例如是否打开 Allure 报告。
import os  # 用于给 pytest 子进程设置默认并发和轮询环境变量。
import shutil  # 用于查找系统 allure 命令，以及删除旧的测试结果目录。
import socket  # 用于寻找本地 Allure 报告服务可用端口。
import subprocess  # 用于调用 pytest 和 Allure CLI。
import sys  # 用于获取当前 Python 解释器路径和返回进程退出码。
import time  # 用于给本地报告服务短暂启动时间。
from pathlib import Path  # 用于统一处理 Windows 路径和相对路径。

import requests  # 用于调用企业微信群机器人 webhook。

from tools.config import load_yaml, save_findai_base_url  # 用于读取和回写 login_info.yaml 中的 findai.base_url。
from tools.extension_storage import extract_findai_base_url_from_extension_dir  # 用于从已解压插件目录中提取接口域名。
from tools.platform_selection import normalize_platforms, platform_display_text  # 用于解析用户指定的平台列表。


ROOT_DIR = Path(__file__).resolve().parent  # 项目根目录，也就是 run.py 所在目录。
ALLURE_RESULTS_DIR = ROOT_DIR / "testresult" / "allure-results"  # pytest 执行后生成的 Allure 原始结果目录。
ALLURE_REPORT_DIR = ROOT_DIR / "testresult" / "allure-report"  # Allure CLI 生成的 HTML 报告目录。
LOCAL_ALLURE = ROOT_DIR / "testresult" / "tools" / "allure-2.29.0" / "bin" / "allure.bat"  # 项目内置 Allure CLI 路径。
LOGIN_INFO_PATH = ROOT_DIR / "login_info.yaml"  # findai 账号、token 和 base_url 的配置文件路径。
EXTENSION_DIR = ROOT_DIR / "extension"  # 已解压 Chrome 插件所在目录，支持 extension/findai_xxx 子目录结构。
DEFAULT_REPORT_HOST = "127.0.0.1"  # Allure 静态报告服务默认只监听本机。
DEFAULT_REPORT_PORT = 8765  # Allure 静态报告服务默认端口。


def parse_args() -> argparse.Namespace:
    """解析 run.py 支持的命令行参数。"""
    parser = argparse.ArgumentParser(description="执行 findai 自动化测试并生成 Allure 报告。")  # 创建命令行参数解析器。
    parser.add_argument("pytest_args", nargs="*", help="透传给 pytest 的额外参数，例如 testcases/test_smoke.py -q。")  # 支持追加 pytest 参数。
    parser.add_argument("--no-clean", action="store_true", help="不清理历史 allure-results。")  # 调试时可保留历史结果。
    parser.add_argument("--no-report", action="store_true", help="只执行 pytest，不生成 Allure HTML 报告。")  # 只想快速跑用例时可跳过报告。
    parser.add_argument("--open-report", action="store_true", help="生成报告后自动打开 Allure 报告服务。")  # 需要浏览报告时使用。
    parser.add_argument("--no-notify", action="store_true", help="测试结束后不发送企业微信机器人通知。")  # 临时调试时可关闭群通知。
    parser.add_argument("--no-sync-base-url", action="store_true", help="执行前不从插件目录自动同步 findai.base_url。")  # 特殊调试时可关闭自动域名同步。
    parser.add_argument("--sync-browser-context", action="store_true", help="兼容旧参数；现在 pytest 会话会自动保持浏览器并同步上下文。")  # 保留旧参数，避免用户命令报错。
    parser.add_argument("--platforms", default="", help="指定执行平台，支持：蒲公英,星图,小红书,抖音 或 pgy,xt,xhs,dy。默认执行全部平台。")  # 允许用户自由指定平台。
    return parser.parse_args()  # 返回解析后的参数对象。


def get_wecom_webhook() -> str:
    """读取企业微信群机器人 webhook，优先使用环境变量，其次使用 login_info.yaml。"""
    env_webhook = os.getenv("FINDAI_WECOM_WEBHOOK", "").strip()  # CI 或临时运行时可通过环境变量覆盖。
    if env_webhook:
        return env_webhook  # 环境变量优先级最高，便于不同群机器人切换。
    config = load_yaml(LOGIN_INFO_PATH)  # 读取项目配置文件。
    return str(config.get("notification", {}).get("wecom_webhook", "") or "").strip()  # 未配置时返回空字符串。


def remove_dir(path: Path) -> None:
    """删除目录并重新创建空目录。"""
    if path.exists():
        shutil.rmtree(path)  # 删除旧结果，避免历史用例污染本次报告。
    path.mkdir(parents=True, exist_ok=True)  # 创建空目录，保证 pytest/allure 有写入位置。


def find_allure_command() -> str | None:
    """查找可用的 Allure CLI 命令。"""
    if LOCAL_ALLURE.exists():
        return str(LOCAL_ALLURE)  # 优先使用项目内置的 Allure CLI，避免依赖系统 PATH。
    return shutil.which("allure")  # 项目内没有时，尝试使用系统环境变量中的 allure 命令。


def ensure_findai_base_url() -> str | None:
    """确保 login_info.yaml 中存在 findai.base_url，缺失时从插件目录自动提取。"""
    config = load_yaml(LOGIN_INFO_PATH)  # 读取当前登录配置，检查是否已经保存过 base_url。
    base_url = (config.get("findai", {}).get("base_url") or "").rstrip("/")  # 读取并规范化已有接口域名。
    if base_url:
        print(f"findai.base_url 已存在：{base_url}")  # 已有域名时直接复用，避免不必要的文件写入。
        return base_url  # 返回已有域名。
    try:
        base_url = extract_findai_base_url_from_extension_dir(str(EXTENSION_DIR))  # 从解压插件脚本中提取当前环境接口域名。
    except Exception as error:
        print(f"未能从插件目录自动提取 findai.base_url：{error}")  # 提取失败时提示用户继续使用同步脚本。
        print("请先执行：python scripts/sync_findai_from_plugin.py")  # 保留原有手动同步方案作为兜底。
        return None  # 返回 None，让后续 pytest fixture 给出跳过原因。
    saved_url = save_findai_base_url(base_url, LOGIN_INFO_PATH)  # 将提取到的域名写回 login_info.yaml。
    print(f"已从插件目录同步 findai.base_url：{saved_url}")  # 打印同步结果，方便确认当前环境。
    return saved_url  # 返回最终保存的域名。


def run_command(command: list[str], selected_platforms: list[str] | None = None) -> int:
    """执行外部命令，并返回命令退出码。"""
    print(f"\n>>> {' '.join(command)}")  # 打印即将执行的命令，方便定位运行步骤。
    env = os.environ.copy()  # 复制当前环境变量，避免破坏用户已有设置。
    if selected_platforms:
        env["FINDAI_TEST_PLATFORMS"] = ",".join(selected_platforms)  # 传给 pytest fixture 和用例过滤逻辑。
        env.setdefault("FINDAI_PLATFORM_WORKERS", str(len(selected_platforms)))  # 平台级并行 worker 默认等于所选平台数量。
    env.setdefault("FINDAI_PLATFORM_PARALLEL", "1")  # 默认开启平台级并行：蒲公英一条串行链路，星图一条串行链路。
    env.setdefault("FINDAI_PARALLEL_CASES", "0")  # 单个平台内部仍按 Excel 顺序串行执行，避免依赖用例提前执行。
    env.setdefault("FINDAI_CASE_WORKERS", "1")  # 平台内部串行链路只需要 1 个 worker。
    env.setdefault("FINDAI_TASK_POLL_INTERVAL", "10")  # 默认每 10 秒查询一次任务状态，避免 300 秒长时间卡住。
    env.setdefault("FINDAI_TASK_STATUS_ATTEMPTS", "60")  # 默认最多等 10 分钟，兼顾长任务完成时间。
    env.setdefault("FINDAI_TASK_INFO_INTERVAL", "5")  # 任务完成后默认每 5 秒查询一次达人明细。
    env.setdefault("FINDAI_TASK_INFO_ATTEMPTS", "24")  # 任务完成后默认最多等 2 分钟等待明细落库。
    completed = subprocess.run(command, cwd=ROOT_DIR, env=env)  # 在项目根目录执行命令，避免路径错位。
    return completed.returncode  # 返回命令退出码，0 表示成功。


def run_browser_context_sync() -> int:
    """兼容旧入口；浏览器上下文现在由 pytest session fixture 管理。"""
    print("浏览器上下文将由 pytest 会话自动启动并保持到所有用例结束。")  # 避免旧逻辑提前启动并关闭浏览器。
    return 0  # 不再单独执行会关闭浏览器的同步脚本。


def warn_missing_build_context() -> None:
    """提示动态上下文会在 pytest 浏览器会话中获取。"""
    print("蒲公英/星图登录态、third_id、device_id、token、base_url 将在 pytest 会话开始时通过同一个浏览器获取。")  # 说明当前执行模式。


def run_pytest(pytest_args: list[str], clean: bool, selected_platforms: list[str]) -> int:
    """执行 pytest 全量或指定用例。"""
    if clean:
        remove_dir(ALLURE_RESULTS_DIR)  # 默认清理旧 allure-results，保证报告只包含本次执行结果。
    command = [sys.executable, "-m", "pytest", "--clean-alluredir"]  # 使用当前 Python 环境执行 pytest。
    command.extend(pytest_args)  # 追加用户传入的 pytest 参数，例如 -q 或某个测试文件。
    return run_command(command, selected_platforms=selected_platforms)  # 执行 pytest 并返回退出码。


def generate_allure_report(open_report: bool) -> int:
    """基于 allure-results 生成 HTML 报告，并可选择打开报告。"""
    allure_command = find_allure_command()  # 查找 Allure CLI。
    if not allure_command:
        print("未找到 Allure CLI，已跳过 HTML 报告生成。")  # 没有 CLI 时只保留 pytest 生成的原始结果。
        return 0  # 跳过报告生成不影响 pytest 执行结果。
    if not ALLURE_RESULTS_DIR.exists():
        print("未找到 allure-results，已跳过 HTML 报告生成。")  # 没有结果目录时无法生成报告。
        return 0  # 没有结果时直接返回。
    generate_code = run_command(
        [
            allure_command,  # Allure CLI 可执行文件。
            "generate",  # 生成静态 HTML 报告。
            str(ALLURE_RESULTS_DIR),  # 输入 pytest 生成的 Allure 原始结果。
            "-o",  # 指定输出目录参数。
            str(ALLURE_REPORT_DIR),  # 输出到 testresult/allure-report。
            "--clean",  # 生成前清理旧 HTML 报告。
        ]
    )
    if generate_code != 0:
        return generate_code  # 报告生成失败时把 Allure 的退出码返回给调用方。
    if open_report:
        return run_command([allure_command, "open", str(ALLURE_REPORT_DIR)])  # 用户要求时启动 Allure 本地报告服务。
    print(f"Allure 报告已生成：{ALLURE_REPORT_DIR}")  # 不自动打开时打印报告目录。
    return 0  # 报告生成成功。


def start_allure_report_server() -> str:
    """启动 Allure HTML 目录的本地 HTTP 服务，并返回可直接访问的报告地址。"""
    if not (ALLURE_REPORT_DIR / "index.html").exists():
        return ""  # 报告还未生成时无法启动静态服务。
    port = find_free_port(DEFAULT_REPORT_PORT)  # 优先使用固定端口，方便群里报告地址稳定。
    command = [
        sys.executable,
        "-m",
        "http.server",
        str(port),
        "--bind",
        DEFAULT_REPORT_HOST,
        "--directory",
        str(ALLURE_REPORT_DIR),
    ]  # 用 Python 内置静态服务托管 Allure 报告目录，避免 file:// 路由 404。
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # Windows 下隐藏服务窗口。
    subprocess.Popen(command, cwd=ROOT_DIR, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=creationflags)  # 后台保持报告服务。
    time.sleep(1)  # 给 http.server 一点启动时间。
    return f"http://{DEFAULT_REPORT_HOST}:{port}/"  # 返回企业微信消息中可点击的本地报告地址。


def find_free_port(start_port: int) -> int:
    """从指定端口开始寻找可用端口。"""
    for port in range(start_port, start_port + 50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.2)
            if sock.connect_ex((DEFAULT_REPORT_HOST, port)) != 0:
                return port
    raise RuntimeError(f"No free local port found from {start_port}.")  # 极端情况下端口全占用时给出明确错误。


def send_wecom_notification(pytest_code: int, report_code: int, report_url: str, selected_platforms: list[str]) -> None:
    """把本次测试结果发送到企业微信群机器人。"""
    webhook = get_wecom_webhook()  # 读取 webhook，未配置则不发送。
    if not webhook:
        print("未配置企业微信机器人 webhook，已跳过测试结果通知。")
        return
    passed = pytest_code == 0 and report_code == 0  # pytest 和报告生成都成功才算本次执行成功。
    status_text = "成功" if passed else "失败"
    platform_text = platform_display_text(selected_platforms)
    content = (
        f"## FindAI 自动化测试结果：{status_text}\n"
        f"> 测试平台：{platform_text}\n"
        f"> pytest退出码：{pytest_code}\n"
        f"> Allure报告退出码：{report_code}\n"
        f"> Allure报告地址：{report_url or '未生成'}"
    )  # 企业微信 markdown 消息，保留最关键的执行结论和报告入口。
    try:
        response = requests.post(webhook, json={"msgtype": "markdown", "markdown": {"content": content}}, timeout=10)
        response.raise_for_status()
        result = response.json()
        if result.get("errcode") != 0:
            print(f"企业微信通知发送失败：{result}")
            return
        print("企业微信通知已发送。")
    except Exception as error:
        print(f"企业微信通知发送异常：{error}")


def main() -> int:
    """脚本主入口：执行用例并按需生成报告。"""
    args = parse_args()  # 读取命令行参数。
    try:
        selected_platforms = normalize_platforms(args.platforms)  # 解析用户指定的平台，默认按优先级执行全部平台。
    except ValueError as error:
        print(error)  # 平台名不支持时给出明确提示。
        return 2  # 命令行参数错误。
    print(f"本次选择执行平台：{platform_display_text(selected_platforms)}")  # 显示最终执行平台和顺序。
    if not args.no_sync_base_url:
        ensure_findai_base_url()  # 执行用例前自动补齐 findai.base_url，避免接口用例被跳过。
    if args.sync_browser_context:
        sync_code = run_browser_context_sync()  # 按需打开浏览器同步平台账号 ID、浏览器设备 ID 和 token。
        if sync_code != 0:
            return sync_code  # 同步失败时直接返回同步脚本退出码。
    warn_missing_build_context()  # 正式执行用例前提示 third_id/device_id 是否齐全。
    pytest_code = run_pytest(args.pytest_args, clean=not args.no_clean, selected_platforms=selected_platforms)  # 先执行 pytest。
    report_code = 0  # 默认报告生成成功，用户关闭报告生成时仍可用于通知判断。
    report_url = ""  # 企业微信通知里的 Allure 本地报告服务地址。
    if not args.no_report:
        report_code = generate_allure_report(open_report=args.open_report)  # 再根据本次结果生成 Allure 报告。
        if report_code == 0:
            report_url = start_allure_report_server()  # 生成报告后启动本地静态服务，避免 file:// 打开 Allure 路由 404。
            if report_url:
                print(f"Allure 本地报告服务：{report_url}")  # 打印可直接访问的报告地址。
    if not args.no_notify:
        send_wecom_notification(pytest_code, report_code, report_url, selected_platforms)  # 测试结束后发送企业微信结果通知。
    if pytest_code == 0 and report_code != 0:
        return report_code  # 用例成功但报告失败时，返回报告失败码。
    return pytest_code  # 默认以 pytest 退出码作为 run.py 的退出码。


if __name__ == "__main__":
    raise SystemExit(main())  # 将 main 的返回值作为进程退出码，方便 CI 判断成功失败。
