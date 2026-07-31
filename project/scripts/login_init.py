from pathlib import Path  # 用于定位 login_info.yaml 配置文件。

from bases.base_login import FindaiLogin, PlatformLogin, load_login_info  # 导入平台登录、findai 登录和配置读取能力。
from tools.playwright_driver import launch_chromium_with_extension, open_extension_page  # 导入带插件浏览器启动和插件页打开工具。


def main() -> None:
    """初始化平台和 findai 登录态，并把 findai token 保存到配置文件。"""
    config_path = Path("login_info.yaml")  # 项目根目录下的登录配置文件路径。
    login_info = load_login_info(config_path)  # 读取平台和 findai 账号密码。

    playwright, context = launch_chromium_with_extension(headless=False)  # 启动有头 Chromium 并加载 findai 插件。
    try:
        platform_page = context.pages[0] if context.pages else context.new_page()  # 复用已有页面或新建平台登录页面。
        platform_login = PlatformLogin(platform_page, login_info)  # 创建平台登录业务对象。

        for platform in ("pugongying", "xingtu"):
            ok = platform_login.login(platform)  # 依次登录蒲公英和星图，保持平台登录态。
            if not ok:
                raise RuntimeError(f"{platform} login was not completed within the wait time.")  # 超时未登录时终止初始化。

        extension_page = open_extension_page(context, "options.html#/login")  # 打开 findai 插件登录页。
        token_info = FindaiLogin(
            page=extension_page,  # 注入插件页面，便于读取 storage 和填写登录表单。
            login_info=login_info,  # 注入账号配置。
            config_path=config_path,  # 指定 token/base_url 回写位置。
        ).login_plugin_in_browser()  # 通过插件 UI 登录并保存 token。
        print(f"Findai login success. token saved, token length={len(token_info['access_token'])}")  # 输出 token 长度，避免直接打印敏感 token。
    finally:
        context.close()  # 无论成功失败都关闭浏览器上下文。
        playwright.stop()  # 停止 Playwright 驱动进程。


if __name__ == "__main__":
    main()  # 允许通过 python scripts/login_init.py 直接执行初始化。
