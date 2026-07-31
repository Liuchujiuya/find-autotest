from pathlib import Path  # 用于定位 login_info.yaml 配置文件。

from bases.base_login import FindaiLogin, load_login_info  # 导入 findai 插件登录和配置读取能力。
from tools.playwright_driver import launch_chromium_with_extension, open_extension_page  # 导入带插件浏览器启动和插件页打开工具。


def main() -> None:
    """从插件当前环境同步 findai base_url 和 token 到 login_info.yaml。"""
    config_path = Path("login_info.yaml")  # 项目根目录下的登录配置文件路径。
    login_info = load_login_info(config_path)  # 读取 findai 账号密码和已有配置。

    playwright, context = launch_chromium_with_extension(headless=False)  # 启动有头 Chromium 并加载插件。
    try:
        extension_page = open_extension_page(context, "options.html#/login")  # 打开插件登录页。
        sync_result = FindaiLogin(
            page=extension_page,  # 注入插件页面，便于读取当前环境域名和 storage token。
            login_info=login_info,  # 注入账号配置，未登录时可自动登录。
            config_path=config_path,  # 指定 base_url/token 回写文件。
        ).login_plugin_in_browser()  # 登录插件并同步 token。

        token = sync_result.get("access_token") or sync_result.get("token") or ""  # 兼容不同 token 字段名。
        print(f"Findai plugin synced. base_url saved, token length={len(token)}")  # 输出同步结果，避免泄露完整 token。
    finally:
        context.close()  # 无论成功失败都关闭浏览器上下文。
        playwright.stop()  # 停止 Playwright 驱动进程。


if __name__ == "__main__":
    main()  # 允许通过 python scripts/sync_findai_from_plugin.py 直接执行同步。
