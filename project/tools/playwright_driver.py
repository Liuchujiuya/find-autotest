import time  # 用于等待真正的插件 service worker 出现。
from pathlib import Path  # 路径工具，用于解析插件目录和浏览器用户数据目录。

from playwright.sync_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeoutError, sync_playwright  # Playwright 同步 API，用于启动带插件的 Chromium。


def find_extension_dir(extension_root: str | Path = "extension") -> Path:
    """查找包含 manifest.json 的解压版 Chrome 插件目录。"""
    root = Path(extension_root)  # 兼容字符串路径和 Path 对象。
    if (root / "manifest.json").exists():
        return root.resolve()  # 如果传入的就是插件根目录，直接返回绝对路径。

    manifests = sorted(root.glob("*/manifest.json"))  # 否则在 extension 下查找一级子目录中的 manifest.json。
    if not manifests:
        raise FileNotFoundError(f"No manifest.json found under {root.resolve()}")  # 找不到插件时给出明确错误。
    return manifests[0].parent.resolve()  # 返回第一个匹配的插件目录，适配 extension/findai_xxx 的结构。


def launch_chromium_with_extension(
    extension_dir: str | Path | None = None,
    headless: bool = False,
    user_data_dir: str | Path = "testresult/browser_user_data",
):
    """启动加载 findai 插件的 Chromium 持久化上下文。"""
    extension_path = str(Path(extension_dir).resolve() if extension_dir else find_extension_dir())  # 解析插件绝对路径。
    playwright = sync_playwright().start()  # 启动 Playwright 驱动进程。
    launch_options = dict(
        user_data_dir=str(Path(user_data_dir).resolve()),  # 使用持久化用户目录保存平台和插件登录态。
        headless=headless,  # 插件调试通常需要有头模式，默认 False。
        no_viewport=True,  # 不使用 Playwright 默认固定视口，让浏览器窗口真实最大化后页面也占满窗口。
        args=[
            "--start-maximized",  # 启动 Chromium 时最大化窗口，方便用户观察自动登录过程。
            f"--disable-extensions-except={extension_path}",  # 仅启用当前待测插件，减少其它扩展干扰。
            f"--load-extension={extension_path}",  # 加载解压后的 findai 插件目录。
        ],
    )
    try:
        context = playwright.chromium.launch_persistent_context(channel="chrome", **launch_options)
    except PlaywrightError as error:
        playwright.stop()
        raise RuntimeError(
            "Google Chrome is required to run Find Autotest. Install Chrome, then retry. "
            "Use the release build with -IncludePlaywrightBrowser only when a bundled browser is required."
        ) from error
    return playwright, context  # 返回 Playwright 实例和浏览器上下文，调用方负责关闭。


def get_extension_id(context) -> str:
    """从真正的 Chrome 插件页面或 service worker 地址中获取插件 ID。"""
    existing_id = _find_extension_id_from_context(context)  # 先从已存在的页面、后台页、service worker 中查找插件 ID。
    if existing_id:
        return existing_id  # 找到 chrome-extension:// 开头的地址后直接返回插件 ID。

    deadline = time.time() + 15  # 最多等待 15 秒，避免误等第三方网站 service worker。
    while time.time() < deadline:
        try:
            service_worker = context.wait_for_event("serviceworker", timeout=3000)  # 等待新的 service worker 事件。
        except PlaywrightTimeoutError:
            service_worker = None  # 没有新 worker 时继续扫描已有上下文。
        if service_worker:
            extension_id = _extract_extension_id(service_worker.url)  # 只接受 chrome-extension:// 地址。
            if extension_id:
                return extension_id  # 命中插件 service worker 后返回。
        existing_id = _find_extension_id_from_context(context)  # 再扫一遍上下文中已有对象。
        if existing_id:
            return existing_id  # 找到插件 ID 后返回。
    raise RuntimeError("Could not find loaded Chrome extension id from chrome-extension:// service worker/page.")  # 超时仍找不到插件 ID 时明确失败。


def _find_extension_id_from_context(context) -> str:
    """从当前上下文已有的页面、后台页、service worker 中查找插件 ID。"""
    candidates = []  # 收集可能包含插件地址的对象。
    candidates.extend(getattr(context, "service_workers", []))  # MV3 插件后台 service worker。
    candidates.extend(getattr(context, "background_pages", []))  # MV2 插件后台页，兼容旧插件。
    candidates.extend(getattr(context, "pages", []))  # 已打开的插件页面或平台页面。
    for candidate in candidates:
        extension_id = _extract_extension_id(getattr(candidate, "url", ""))  # 只从 chrome-extension:// URL 提取。
        if extension_id:
            return extension_id  # 返回第一个真正插件 ID。
    return ""  # 没找到时返回空字符串。


def _extract_extension_id(url: str) -> str:
    """只从 chrome-extension://<id>/... 地址中提取插件 ID。"""
    if not url.startswith("chrome-extension://"):
        return ""  # 网站 service worker 不能当作插件 ID。
    parts = url.split("/")  # chrome-extension://<id>/... 的第三段是 ID。
    return parts[2] if len(parts) > 2 and parts[2] else ""  # 返回插件 ID。


def open_extension_page(context, path: str = "options.html"):
    """打开插件内部页面，默认进入 options.html 登录页/配置页。"""
    extension_id = get_extension_id(context)  # 获取当前加载插件的动态 ID。
    page = context.new_page()  # 新建浏览器标签页，避免影响平台页面。
    page.goto(f"chrome-extension://{extension_id}/{path}")  # 跳转到插件内部页面。
    return page  # 返回页面对象，供后续登录、读取 storage 或提取域名。
