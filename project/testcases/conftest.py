import os  # 用于读取登录等待时间、浏览器用户目录等运行参数。
import json  # 用于解析插件 storage 中可能被多包一层的 token/device_id JSON 字符串。
import threading  # 用于记录浏览器是否被用户手动关闭。
from pathlib import Path  # 用于创建本次测试会话专属的浏览器用户数据目录。
from uuid import uuid4  # 用于给每次测试会话生成独立浏览器目录，避免账号变化时复用旧登录态。

import pytest  # pytest 框架，用于定义 session 级浏览器和接口 fixture。

from bases.base_login import PLATFORM_URLS, FindaiLogin, PlatformLogin, load_login_info  # 读取配置并执行平台/findai 登录。
from bases.find_task_api import FindTaskApi  # 找号任务接口封装类。
from tools.config import save_findai_base_url, save_findai_device_id, save_findai_token, save_platform_runtime_context  # 回写本次浏览器会话获取到的动态参数。
from tools.extension_storage import (
    extract_findai_base_url_from_extension_dir,  # 浏览器不可用时从插件目录兜底提取 base_url。
    get_extension_version,  # 从插件 manifest 读取版本号。
    get_findai_base_url_from_extension,  # 从当前插件脚本读取真实接口域名。
    get_findai_device_id_from_extension,  # 从当前插件 storage 读取浏览器设备 ID。
    get_findai_storage_snapshot,  # token 未写入时读取关键 storage 快照用于定位。
    get_findai_token_from_extension,  # 从当前插件 storage 读取 findai token。
    get_platform_runtime_context_from_extension,  # 从当前插件 storage 读取蒲公英/星图账号 ID。
)
from tools.request_client import RequestClient  # 统一 requests 客户端封装。
from tools.platform_selection import platform_display_text, selected_platforms_from_env  # 读取用户本次指定的平台列表。


SMART_TASK_PLATFORMS = {"pgy", "xt"}  # 需要插件 token/device_id/third_id 的找号任务平台。


@pytest.fixture(scope="session")
def login_info():
    """会话级 fixture：整个测试会话只读取一次登录配置。"""
    return load_login_info()  # 返回平台账号、findai 账号、base_url、token 等配置。


@pytest.fixture(scope="session")
def selected_test_platforms() -> list[str]:
    """会话级 fixture：读取本次用户指定要测试的平台。"""
    platforms = selected_platforms_from_env()  # 默认四个平台全选；指定时按小红书>抖音>蒲公英>星图排序。
    print(f"[setup] 本次测试平台：{platform_display_text(platforms)}")  # 在控制台输出最终平台顺序。
    return platforms  # 返回标准平台编码列表。


@pytest.fixture(scope="session")
def browser_runtime(login_info, selected_test_platforms):
    """会话级 fixture：启动并保持同一个平台/插件浏览器环境直到所有用例结束。"""
    try:
        from tools.playwright_driver import launch_chromium_with_extension, open_extension_page  # 启动带插件浏览器并打开插件页。
    except ModuleNotFoundError as error:
        pytest.skip(f"playwright is not installed: {error}. Run pip install -r requirements.txt and playwright install chromium.")  # 浏览器依赖缺失时给出明确提示。
    user_data_dir = _make_session_user_data_dir()  # 每次测试使用独立浏览器目录，避免账号变化时复用旧状态。
    playwright, context = launch_chromium_with_extension(headless=False, user_data_dir=user_data_dir)  # 启动有头 Chromium 并加载 findai 插件。
    browser_closed_event = threading.Event()  # 浏览器中途关闭时用于通知接口轮询尽快退出。
    context.on("close", lambda _: browser_closed_event.set())  # 用户手动关闭浏览器窗口时标记中断。
    try:
        platform_pages, extension_page, token_info, base_url, platform_login_status = _prepare_logged_browser_context(context, login_info, open_extension_page, selected_test_platforms)  # 按用户指定平台准备浏览器，并记录登录门禁结果。
        _attach_browser_close_watch(context, browser_closed_event)  # 监听页面/浏览器关闭，用户手动关闭时让接口轮询快速失败。
        logged_in_platforms = [platform for platform in selected_test_platforms if platform_login_status.get(platform, True)]  # 未完成扫码登录的小红书/抖音不进入后续用例调度。
        runtime = _wait_platform_runtime_context(extension_page, logged_in_platforms)  # 等待插件从已登录找号平台页拿到 third_id 和 device_id。
        device_id = runtime.get("device_id") or get_findai_device_id_from_extension(extension_page)  # 获取 build 请求体和请求头共用的设备 ID。
        token_info = _normalize_token_info(get_findai_token_from_extension(extension_page) or token_info)  # 以插件 storage 中最终 token 为准，并兼容纯字符串 token。
        token = _extract_token(token_info)  # 提取 access_token。
        version = get_extension_version(extension_page) or "1.4.3"  # 从插件读取版本号，失败时兜底旧版本号。
        _assert_runtime_ready(base_url, token, device_id, runtime, logged_in_platforms)  # 只校验已登录且会真正执行用例的平台所需参数。
        _persist_runtime(base_url, device_id, token_info, runtime)  # 将本次真实浏览器会话参数写入 login_info.yaml 方便排查。
        yield {
            "playwright": playwright,  # Playwright 驱动对象，主要用于 teardown。
            "context": context,  # 持久化浏览器上下文，用于保持平台登录态。
            "platform_pages": platform_pages,  # 平台页面对象，保持打开直到测试结束。
            "extension_page": extension_page,  # findai 插件页面对象，保持打开直到测试结束。
            "base_url": base_url,  # 当前插件环境接口域名。
            "device_id": device_id,  # 当前浏览器设备 ID。
            "token": token,  # 当前插件登录 token。
            "version": version,  # 当前插件版本号。
            "runtime": runtime,  # 平台 third_id 和 device_id 上下文。
            "collect_api_keys": _collect_api_keys(login_info),  # 小红书/抖音采集接口 API key。
            "selected_platforms": selected_test_platforms,  # 本次用户指定的平台列表。
            "logged_in_platforms": logged_in_platforms,  # 本次完成登录、允许执行用例的平台列表。
            "platform_login_status": platform_login_status,  # 每个平台的登录门禁结果，便于报告和调试。
            "browser_closed_event": browser_closed_event,  # 暴露给接口封装，用于浏览器中途关闭时快速失败。
        }
    finally:
        context.close()  # 所有用例结束后才关闭浏览器上下文。
        playwright.stop()  # 停止 Playwright 驱动进程。


@pytest.fixture(scope="session")
def findai_client(browser_runtime):
    """会话级 fixture：创建与当前插件浏览器会话一致的接口请求客户端。"""
    token = browser_runtime.get("token")  # 使用当前插件 storage 里的 token。
    selected_platforms = set(browser_runtime.get("logged_in_platforms", browser_runtime.get("selected_platforms", [])))  # 只按已登录平台判断是否需要找号任务 token。
    if not token and selected_platforms & SMART_TASK_PLATFORMS:
        pytest.skip("findai token is empty after browser plugin login.")  # 插件登录后仍无 token 时跳过接口用例。
    base_url = browser_runtime.get("base_url")  # 使用当前插件脚本里的 base_url。
    if not base_url:
        base_url = _sync_base_url_from_extension_dir()  # 极端情况下兜底从插件目录解析 base_url。
        if not base_url:
            pytest.skip("findai base_url is empty after browser plugin login.")  # 仍然没有域名时跳过。
    headers = {
        "Authorization": f"Bearer{token}",  # 与插件源码保持一致：Bearer 后不加空格。
        "DeviceId": browser_runtime.get("device_id", ""),  # 与浏览器插件当前 DeviceId 保持一致。
        "Version": browser_runtime.get("version") or "1.4.3",  # 与当前加载插件版本保持一致。
    }
    return RequestClient(base_url=base_url, headers=headers, timeout=30)  # 返回与当前浏览器会话一致的接口客户端。


@pytest.fixture(scope="session")
def findai_runtime_context(browser_runtime):
    """会话级 fixture：提供 build 接口需要的平台账号 ID 和浏览器设备 ID。"""
    runtime = browser_runtime.get("runtime", {})  # 读取当前浏览器插件同步出的平台上下文。
    return {
        "device_id": runtime.get("device_id") or browser_runtime.get("device_id", ""),  # build 请求体 fdOriginalDeviceId。
        "platforms": runtime.get("platforms", {}),  # build 请求体 fdOriginalThirdId 的平台映射。
    }


@pytest.fixture(scope="session")
def find_task_api(findai_client, login_info, browser_runtime):
    """会话级 fixture：创建找号任务 API 业务对象。"""
    return FindTaskApi(
        findai_client,
        collect_api_keys=_collect_api_keys(login_info),
        abort_checker=browser_runtime.get("browser_closed_event").is_set,
    )  # 注入请求客户端、采集 API key 和浏览器关闭检查器。


def _collect_api_keys(login_info: dict) -> dict[str, str]:
    """从 login_info.yaml 读取小红书/抖音采集接口 API key。"""
    platforms = login_info.get("platforms", {})  # 平台配置节点。
    xhs_key = platforms.get("xiaohongshu", {}).get("api_key", "")  # 小红书采集 key。
    dy_key = platforms.get("douyin", {}).get("api_key", "")  # 抖音采集 key。
    return {
        "xhs": xhs_key,
        "xiaohongshu": xhs_key,
        "dy": dy_key,
        "douyin": dy_key,
    }


def _make_session_user_data_dir() -> Path:
    """创建本次测试会话独立的浏览器用户数据目录。"""
    configured = os.getenv("FINDAI_BROWSER_USER_DATA_DIR", "").strip()  # 允许外部指定浏览器用户目录，方便调试复用。
    if configured:
        return Path(configured)  # 如果指定了目录，就按调用方要求使用。
    return Path("testresult/browser_user_data") / f"session_{os.getpid()}_{uuid4().hex[:8]}"  # 默认每次执行使用全新目录。

def _attach_browser_close_watch(context, browser_closed_event: threading.Event) -> None:
    """监听当前浏览器上下文里的页面关闭事件。"""
    for page in context.pages:
        try:
            page.on("close", lambda _: browser_closed_event.set())
        except Exception:
            continue


def _prepare_logged_browser_context(context, login_info, open_extension_page, selected_platforms: list[str]):
    """按用户指定平台准备浏览器会话，打开顺序：小红书、抖音、蒲公英、星图。"""
    wait_seconds = _platform_wait_seconds()  # 读取平台登录等待时间，兼容验证码/扫码等人工处理。
    platform_pages = {}  # 保存平台页面对象，直到测试结束都不关闭。
    platform_login_status = {platform: True for platform in selected_platforms}  # 默认账号密码平台登录成功才会继续，扫码平台会覆盖真实状态。
    if "xhs" in selected_platforms:
        platform_login_status["xhs"] = _open_one_scan_login_platform_page(context, login_info, platform_pages, "xiaohongshu", "小红书")  # 小红书优先打开，未登录则跳过小红书用例。
    if "dy" in selected_platforms:
        platform_login_status["dy"] = _open_one_scan_login_platform_page(context, login_info, platform_pages, "douyin", "抖音")  # 抖音第二打开，未登录则跳过抖音用例。
    if "pgy" in selected_platforms:
        print("[setup] 开始登录蒲公英平台。")  # 输出当前前置流程阶段。
        pgy_page = context.new_page()  # 蒲公英页面，findai 插件浮层会注入到该平台页。
        pgy_login = PlatformLogin(pgy_page, login_info)  # 创建蒲公英平台登录对象。
        if not pgy_login.login("pugongying", wait_manual_seconds=wait_seconds):
            raise RuntimeError(f"pugongying login was not completed within {wait_seconds} seconds.")  # 蒲公英登录失败时阻止后续蒲公英用例。
        platform_pages["pugongying"] = pgy_page  # 保存蒲公英页面，保持登录态。
    if "xt" in selected_platforms:
        print("[setup] 开始打开星图平台。")  # 星图按优先级最后打开。
        xt_page = context.new_page()  # 星图单独一个页面，保持打开。
        xt_login = PlatformLogin(xt_page, login_info)  # 创建星图登录对象。
        if not xt_login.login("xingtu", wait_manual_seconds=wait_seconds):
            raise RuntimeError(f"xingtu login was not completed within {wait_seconds} seconds.")  # 星图登录失败时阻止后续星图用例。
        platform_pages["xingtu"] = xt_page  # 保存星图页面，保持登录态。
    print("[setup] 指定平台页面已打开，最后打开 FindAI 插件登录页。")  # 无论选择哪个平台，均在平台页准备完毕后再登录 FindAI。
    extension_page = open_extension_page(context, "options.html#/login")  # 打开 FindAI 插件登录页，用于完成登录并读取 token/base_url/storage。
    base_url = get_findai_base_url_from_extension(extension_page)  # 从当前插件读取测试/生产环境接口域名。
    _login_findai_from_plugin_page(extension_page, login_info)  # FindAI 登录完成并取得 token 前，不开始任何平台用例。
    token_info = _normalize_token_info(_wait_findai_token(extension_page, login_info, base_url))
    return platform_pages, extension_page, token_info, base_url, platform_login_status  # 返回平台页、插件页、findai 动态参数和登录门禁结果。


def _open_scan_login_platform_pages(context, login_info, platform_pages: dict) -> None:
    """打开小红书和抖音官网页面，等待用户扫码登录，但不要求读取 third_id/device_id。"""
    _open_one_scan_login_platform_page(context, login_info, platform_pages, "xiaohongshu", "小红书")  # 兼容旧调用。
    _open_one_scan_login_platform_page(context, login_info, platform_pages, "douyin", "抖音")  # 兼容旧调用。


def _open_one_scan_login_platform_page(context, login_info, platform_pages: dict, platform_key: str, platform_label: str) -> bool:
    """打开一个扫码登录平台页面，等待用户扫码登录，但不要求读取 third_id/device_id。"""
    wait_seconds = _scan_login_wait_seconds()  # 读取扫码等待时间。
    print(f"[setup] 开始打开{platform_label}官网，请在浏览器中扫码登录。")  # 控制台提示用户扫码。
    page = context.new_page()  # 每个平台独立页面，保持到测试结束。
    platform_login = PlatformLogin(page, login_info)  # 复用平台登录对象中的扫码登录流程。
    logged_in = platform_login.login(platform_key, wait_manual_seconds=wait_seconds)  # 返回扫码登录后的真实状态。
    platform_pages[platform_key] = page  # 保存页面对象，避免登录态页面被关闭。
    status_text = "已登录，可以执行对应平台用例" if logged_in else "未检测到登录态，对应平台用例将跳过"
    print(f"[setup] {platform_label}页面已保持打开，登录检查结果：{status_text}。")  # 提示扫码平台最终门禁结果。
    return logged_in


def _login_findai_from_plugin_page(page, login_info) -> None:
    """在最后打开的 FindAI 插件登录页完成自动或手动登录。"""
    account = login_info.get("findai", {})  # 读取 findai 账号配置。
    mobile = account.get("username", "")  # findai 手机号。
    password = account.get("password", "")  # findai 密码。
    if not mobile or not password:
        print("[setup] FindAI 未配置账号密码；请在当前插件登录页手动登录，测试将等待 token 写入。")
        return
    overlay = page.locator(".overlay-container")  # 部分插件版本仍需先激活 overlay。
    if overlay.count():
        overlay.click(timeout=10000)
    page.get_by_role("textbox", name="请输入手机号码").fill(mobile)  # 填写 findai 手机号。
    page.get_by_role("textbox", name="请输入密码").fill(password)  # 填写 findai 密码。
    _click_findai_login_button(page)  # 点击 findai 插件弹窗里的蓝色登录按钮。
    page.wait_for_timeout(5000)  # 登录接口和 chrome.storage 写入都在插件异步流程内，点击后给它固定缓冲时间。


def _click_findai_login_button(page) -> None:
    """点击 findai 插件登录弹窗按钮，兼容“登录”和“登 录”两种文本。"""
    for name in ("登 录", "登录"):
        try:
            page.get_by_role("button", name=name, exact=True).click(timeout=3000)  # 优先用无障碍名称精确点击登录按钮。
            return
        except Exception:
            continue  # 当前按钮文本不存在时尝试下一个。
    page.locator(".ant-modal button, .overlay-container button, button").filter(has_text="登").last.click()  # 兜底点击弹窗内最后一个含“登”的按钮。


def _wait_findai_token(extension_page, login_info: dict, base_url: str) -> dict:
    """等待 findai 插件 token 写入 chrome.storage.local，超时后用接口登录兜底并写回插件。"""
    timeout_seconds = _findai_wait_seconds()  # 读取 findai 登录等待时间。
    elapsed = 0  # 已等待秒数。
    while elapsed <= timeout_seconds:
        token_info = get_findai_token_from_extension(extension_page)  # 从插件 storage 读取 token。
        if token_info:
            return token_info  # 读取到 token 后返回。
        extension_page.wait_for_timeout(1000)  # 每秒轮询一次。
        elapsed += 1  # 更新已等待秒数。
    snapshot = get_findai_storage_snapshot(extension_page)  # 超时后读取关键 storage，便于判断是否写到其他 key。
    print(f"[setup] 插件 storage 暂未读取到 USER_TOKEN，尝试通过 findai 登录接口兜底。storage={snapshot}")  # 输出诊断信息但不泄露完整 token。
    account = login_info.get("findai", {})
    if not account.get("username") or not account.get("password"):
        raise RuntimeError("FindAI plugin login was not completed manually, and no username/password is configured for automatic login.")
    if not base_url:
        raise RuntimeError(f"Findai plugin login did not create USER_TOKEN in extension storage, and base_url is empty. Storage snapshot: {snapshot}")  # 没有域名时无法兜底登录。
    return FindaiLogin(
        page=extension_page,  # 使用当前插件页，便于把接口 token 写回 chrome.storage。
        request_client=RequestClient(base_url=base_url),  # 使用插件当前环境域名发起登录请求。
        login_info=login_info,  # 使用 login_info.yaml 中的 findai 账号密码。
        base_url=base_url,  # 保存并复用当前插件域名。
    ).login_plugin(sync_to_extension=True)  # 接口登录成功后把 token 同步回插件 storage。


def _normalize_token_info(token_info) -> dict:
    """把插件或接口返回的 token 统一规范成字典，兼容纯字符串 token。"""
    parsed = _parse_jsonish_value(token_info)  # 先解析可能被多包一层的 JSON 字符串。
    if isinstance(parsed, dict):
        access_token = _parse_jsonish_value(parsed.get("access_token") or parsed.get("token") or "")  # 兼容 access_token 字段里又套了一段 JSON。
        if isinstance(access_token, dict):
            return access_token  # access_token 本身是 token 字典时取内层真实结构。
        parsed["access_token"] = str(access_token or "")  # 确保 access_token 是纯 token 字符串。
        return parsed  # 字典结构直接返回。
    if isinstance(parsed, str):
        return {"access_token": parsed} if parsed else {}  # 纯字符串按 access_token 处理。
    return {}  # 其它类型统一视为空 token。


def _extract_token(token_info) -> str:
    """从 token 字典或纯字符串中提取最终 access_token。"""
    normalized = _normalize_token_info(token_info)  # 先规范化，避免对字符串调用 get。
    return normalized.get("access_token") or normalized.get("token") or ""  # 返回最终可放进 Authorization 的 token。


def _parse_jsonish_value(value):
    """递归解析可能被多包了一层 JSON 的值。"""
    current = value  # 保存当前待解析值。
    for _ in range(3):  # 最多解析三层，防止异常数据无限循环。
        if not isinstance(current, str):
            return current  # 非字符串说明已经是目标结构。
        stripped = current.strip()  # 去掉前后空白。
        if not stripped:
            return ""  # 空字符串直接返回。
        try:
            parsed = json.loads(stripped)  # 尝试解析 JSON。
        except json.JSONDecodeError:
            return current  # 不是 JSON 时保留原字符串。
        if parsed == current:
            return parsed  # 解析后没变化时返回。
        current = parsed  # 继续解析二次 JSON 字符串。
    return current  # 返回最终解析结果。


def _wait_platform_runtime_context(extension_page, selected_platforms: list[str]) -> dict:
    """等待当前所选智能找号平台需要的 device_id 和 third_id。"""
    required_smart_platforms = [platform for platform in selected_platforms if platform in SMART_TASK_PLATFORMS]
    if not required_smart_platforms:
        return {
            "device_id": get_findai_device_id_from_extension(extension_page) or "",
            "platforms": get_platform_runtime_context_from_extension(extension_page).get("platforms", {}),
        }
    timeout_seconds = int(os.getenv("FINDAI_CONTEXT_WAIT_SECONDS", "60"))  # 最长等待插件采集平台上下文的时间。
    elapsed = 0  # 已等待秒数。
    last_context = {}  # 保存最后一次读取结果，失败时用于错误信息。
    while elapsed <= timeout_seconds:
        last_context = get_platform_runtime_context_from_extension(extension_page)  # 从插件 storage 读取上下文。
        platforms = last_context.get("platforms", {})  # 获取平台映射。
        device_id = last_context.get("device_id", "")  # 浏览器设备 ID。
        platform_ready = all(platforms.get(platform, {}).get("third_id", "") for platform in required_smart_platforms)
        if platform_ready and device_id:
            return last_context  # 三个关键参数齐全后返回。
        extension_page.wait_for_timeout(1000)  # 每秒轮询一次，给插件后台脚本采集平台信息的时间。
        elapsed += 1  # 更新已等待秒数。
    raise RuntimeError(f"Could not read required platform third_id/device_id from extension storage. required={required_smart_platforms}, last_context={last_context}")  # 超时仍缺关键参数则失败。


def _assert_runtime_ready(base_url: str, token: str, device_id: str, runtime: dict, selected_platforms: list[str]) -> None:
    """确认此时已经满足所选平台用例的执行条件。"""
    platforms = runtime.get("platforms", {}) if isinstance(runtime, dict) else {}  # 读取插件同步出的平台上下文。
    missing = []  # 收集缺失项，便于一次性输出完整原因。
    if selected_platforms and not base_url:
        missing.append("base_url")  # 缺少接口域名时 build/status 等接口无法请求。
    selected_smart_platforms = set(selected_platforms) & SMART_TASK_PLATFORMS
    if selected_smart_platforms and not token:
        missing.append("token")  # 缺少 token 时接口会返回 401。
    if selected_smart_platforms and not device_id:
        missing.append("device_id")  # 缺少设备 ID 时 build 请求体和请求头不完整。
    if "pgy" in selected_platforms and not platforms.get("pgy", {}).get("third_id", ""):
        missing.append("pgy.third_id")  # 缺少蒲公英账号 ID 时蒲公英 build 参数不完整。
    if "xt" in selected_platforms and not platforms.get("xt", {}).get("third_id", ""):
        missing.append("xt.third_id")  # 缺少星图账号 ID 时星图 build 参数不完整。
    if missing:
        raise RuntimeError(f"Browser/login runtime is not ready, missing: {', '.join(missing)}. Current runtime: {runtime}")  # 前置数据不齐时阻止执行用例。
    print(f"[setup] 前置参数已就绪：{platform_display_text(selected_platforms)} 可以开始执行测试用例。")  # 明确告诉用户 pytest 将开始跑接口用例。


def _persist_runtime(base_url: str, device_id: str, token_info: dict, runtime: dict) -> None:
    """把当前浏览器会话中的动态参数写回 login_info.yaml 便于报告排查。"""
    if base_url:
        save_findai_base_url(base_url)  # 保存当前插件环境域名。
    if device_id:
        save_findai_device_id(device_id)  # 保存当前浏览器设备 ID。
    if token_info:
        save_findai_token(token_info, base_url=base_url)  # 保存当前插件 token。
    for platform_name, platform_data in runtime.get("platforms", {}).items():
        third_id = platform_data.get("third_id", "") if isinstance(platform_data, dict) else ""  # 获取当前平台 third_id。
        if third_id:
            save_platform_runtime_context(platform_name, third_id, device_id)  # 保存平台账号 ID 和设备 ID。


def _sync_base_url_from_extension_dir() -> str:
    """从 extension 目录提取 findai.base_url 并写回 login_info.yaml。"""
    try:
        base_url = extract_findai_base_url_from_extension_dir("extension")  # 扫描 extension 下所有插件 JS 文件。
    except Exception:
        return ""  # 提取失败时返回空字符串，由 fixture 统一 skip。
    return save_findai_base_url(base_url)  # 提取成功后保存并返回规范化后的接口域名。


def _platform_wait_seconds() -> int:
    """读取平台登录等待时间。"""
    return int(os.getenv("FINDAI_PLATFORM_LOGIN_WAIT_SECONDS", "180"))  # 默认等待 180 秒，兼容验证码/扫码。


def _scan_login_wait_seconds() -> int:
    """读取小红书/抖音扫码登录等待时间。"""
    return int(os.getenv("FINDAI_SCAN_LOGIN_WAIT_SECONDS", "120"))  # 默认每个平台等待 120 秒，扫码超时也保留页面继续执行。


def _findai_wait_seconds() -> int:
    """读取 findai 插件登录等待时间。"""
    return int(os.getenv("FINDAI_PLUGIN_LOGIN_WAIT_SECONDS", "60"))  # 默认等待 60 秒，兼容插件页面渲染和登录写 storage。
