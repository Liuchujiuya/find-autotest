from __future__ import annotations  # 允许类型注解在运行时延迟解析，减少循环导入风险。

import time  # 用于登录成功等待和超时轮询。
import os  # 用于读取蒲公英自动登录每步操作间隔。
from pathlib import Path  # 用于兼容字符串路径和 Path 路径对象。
from typing import TYPE_CHECKING, Any  # TYPE_CHECKING 避免运行期强依赖 Playwright，Any 用于兜底类型。

try:
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError  # 优先使用 Playwright 自带超时异常。
except ModuleNotFoundError:
    PlaywrightTimeoutError = TimeoutError  # 未安装 Playwright 时兜底为 Python 内置超时异常，便于静态检查。

if TYPE_CHECKING:
    from playwright.sync_api import Page  # 仅类型检查阶段导入 Page，避免运行期额外依赖。
else:
    Page = Any  # 运行期用 Any 代替 Page，保持模块在缺少 Playwright 时可被导入。

from tools.config import load_yaml, save_findai_base_url, save_findai_device_id, save_findai_token, save_platform_runtime_context  # 读取账号配置并保存 token/base_url/DeviceId。
from tools.extension_storage import (
    get_findai_base_url_from_extension,  # 从插件脚本中提取当前环境接口域名。
    get_findai_device_id_from_extension,  # 从插件 storage 中读取真实 DeviceId。
    get_findai_token_from_extension,  # 从插件 storage 中读取 USER_TOKEN。
    get_platform_runtime_context_from_extension,  # 从插件 storage 中读取平台账号 ID 和浏览器设备 ID。
    set_findai_token_to_extension,  # 将接口 token 写入插件 storage。
)
from tools.request_client import RequestClient  # 统一接口请求客户端。


PLATFORM_URLS = {
    "pugongying": "https://pgy.xiaohongshu.com/",  # 蒲公英平台入口。
    "xingtu": "https://sso.oceanengine.com/xingtu/login?role=1",  # 星图平台客户邮箱登录。
    "xiaohongshu": "https://www.xiaohongshu.com/",  # 小红书官网入口，用于扫码登录并保持登录态。
    "douyin": "https://www.douyin.com/",  # 抖音官网入口，用于扫码登录并保持登录态。
}

SCAN_LOGIN_PLATFORMS = {"xiaohongshu", "douyin"}  # 只需要打开页面扫码登录的平台，不参与 third_id/device_id 参数提取。


def load_login_info(config_path: str | Path = "login_info.yaml") -> dict[str, Any]:
    """读取登录配置文件。"""
    return load_yaml(config_path)  # 返回 YAML 中的平台账号和 findai 账号信息。


class PlatformLogin:
    """封装平台登录流程，用于保持蒲公英/星图等平台登录态。"""

    def __init__(self, page: Page, login_info: dict[str, Any]):
        self.page = page  # 保存 Playwright 页面对象，后续所有页面操作都基于它执行。
        self.login_info = login_info  # 保存 login_info.yaml 中读取出的账号信息。

    def login(self, platform_name: str, wait_manual_seconds: int = 120) -> bool:
        """根据平台名称执行通用登录流程。"""
        url = PLATFORM_URLS.get(platform_name)  # 根据平台名称获取登录入口地址。
        if not url:
            raise ValueError(f"Unsupported platform: {platform_name}")  # 未配置的平台不允许继续执行。
        if platform_name in SCAN_LOGIN_PLATFORMS:
            return self._open_scan_login_platform(platform_name, url, wait_manual_seconds)  # 小红书/抖音只打开页面并等待人工扫码。

        account = self.login_info.get("platforms", {}).get(platform_name, {})  # 读取指定平台账号配置。
        username = account.get("username")  # 平台登录用户名/手机号。
        password = account.get("password")  # 平台登录密码。
        if not username or not password:
            self.page.goto(url, wait_until="domcontentloaded")
            self.page.wait_for_timeout(2000)
            if self._looks_logged_in():
                return True
            print(f"[setup] {platform_name} username/password is empty; please complete login manually in the opened browser page.")
            return self._wait_login_success(wait_manual_seconds)
        if platform_name == "pugongying":
            return self._login_pugongying_xhs(url, username, password, wait_manual_seconds)  # 蒲公英使用小红书平台专用登录流程。
        if platform_name == "xingtu":
            return self._login_xingtu_oceanengine(url, username, password, wait_manual_seconds)  # 星图新版 OceanEngine SSO 使用独立登录流程。

        self.page.goto(url, wait_until="domcontentloaded")  # 打开平台页面并等待 DOM 加载完成。
        self.page.wait_for_timeout(2000)  # 给平台前端脚本一点初始化时间。
        if self._looks_logged_in():
            return True  # 页面已经是登录态时直接返回成功。

        self._open_login_panel()  # 尝试打开账号密码登录面板。
        self._fill_first_match(
            [
                'input[type="tel"]',  # 手机号输入框。
                'input[type="email"]',  # 邮箱输入框。
                'input[name*="phone" i]',  # name 中包含 phone 的输入框。
                'input[name*="mobile" i]',  # name 中包含 mobile 的输入框。
                'input[name*="user" i]',  # name 中包含 user 的输入框。
                'input[placeholder*="手机"]',  # 中文“手机”占位符匹配。
                'input[placeholder*="邮箱"]',  # 中文“邮箱”占位符匹配。
                'input[placeholder*="账号"]',  # 中文“账号”占位符匹配。
                'input[placeholder*="鎵嬫満"]',  # 历史编码下的“手机”占位符匹配。
                'input[placeholder*="閭"]',  # 历史编码下的“邮箱”占位符匹配。
                'input[placeholder*="璐﹀彿"]',  # 历史编码下的“账号”占位符匹配。
                'input:not([type]), input[type="text"]',  # 兜底匹配普通文本输入框。
            ],
            username,  # 将平台用户名填入第一个可见匹配输入框。
        )
        self._fill_first_match(
            [
                'input[type="password"]',  # 密码类型输入框。
                'input[placeholder*="密码"]',  # 中文“密码”占位符匹配。
                'input[placeholder*="瀵嗙爜"]',  # 历史编码下的“密码”占位符匹配。
            ],
            password,  # 将平台密码填入第一个可见匹配输入框。
        )
        self._click_first_match(
            [
                'button:has-text("登录")',  # 中文登录按钮匹配。
                'text=登录',  # 中文登录文本匹配。
                'button:has-text("鐧诲綍")',  # 历史编码下的“登录”按钮匹配。
                'button:has-text("鐧?褰?)',  # 历史编码下的另一种“登录”按钮匹配。
                'text=鐧诲綍',  # 文本节点登录匹配。
                'button[type="submit"]',  # 兜底点击提交按钮。
            ]
        )

        return self._wait_login_success(wait_manual_seconds)  # 等待自动登录或人工验证完成。

    def login_pugongying(self, wait_manual_seconds: int = 120) -> bool:
        """登录蒲公英平台。"""
        return self.login("pugongying", wait_manual_seconds)  # 复用通用登录流程并传入蒲公英平台名。

    def login_xingtu(self, wait_manual_seconds: int = 120) -> bool:
        """登录星图平台。"""
        return self.login("xingtu", wait_manual_seconds)  # 复用通用登录流程并传入星图平台名。

    def login_xiaohongshu(self, wait_manual_seconds: int = 120) -> bool:
        """打开小红书官网并等待人工扫码登录。"""
        return self.login("xiaohongshu", wait_manual_seconds)  # 小红书官网扫码登录，不需要账号密码。

    def login_douyin(self, wait_manual_seconds: int = 120) -> bool:
        """打开抖音官网并等待人工扫码登录。"""
        return self.login("douyin", wait_manual_seconds)  # 抖音官网扫码登录，不需要账号密码。

    def _open_scan_login_platform(self, platform_name: str, url: str, wait_manual_seconds: int) -> bool:
        """打开扫码登录平台页面，等待用户完成扫码，页面会保持到所有用例结束。"""
        self.page.goto(url, wait_until="domcontentloaded")  # 打开小红书/抖音官网。
        self.page.wait_for_timeout(5000)  # 等待登录二维码、首页脚本和插件注入完成。
        if self._looks_scan_platform_logged_in(platform_name):
            return True  # 如果页面已经复用登录态，直接返回。
        self._open_scan_login_entry(platform_name)  # 尝试点击登录入口，让二维码或登录弹窗展示出来。
        return self._wait_scan_login_success(platform_name, wait_manual_seconds)  # 等待扫码完成；超时也保留页面继续执行。

    def _open_scan_login_entry(self, platform_name: str) -> None:
        """尝试点击小红书/抖音官网登录入口。"""
        selectors = [
            'text=登录',  # 两个平台常见登录入口。
            'button:has-text("登录")',  # 按钮形式的登录入口。
            '[class*="login"]',  # class 中包含 login 的兜底入口。
            '[class*="Login"]',  # class 中包含 Login 的兜底入口。
        ]
        if platform_name == "douyin":
            selectors.extend(['text=登录/注册', 'button:has-text("登录/注册")'])  # 抖音常见登录/注册文案。
        self._click_first_match(selectors, required=False)  # 找不到入口不失败，可能页面已展示二维码或已登录。
        self.page.wait_for_timeout(2000)  # 等待扫码弹窗渲染。

    def _looks_scan_platform_logged_in(self, platform_name: str) -> bool:
        """粗略判断小红书/抖音官网是否已经登录。"""
        if platform_name in SCAN_LOGIN_PLATFORMS:
            return not self._scan_login_button_exists(platform_name)  # 登录文本按钮仍可见时视为未登录；不可见时才执行对应平台用例。
        return False  # 未知扫码平台默认视为未登录。

    def _scan_login_button_exists(self, platform_name: str) -> bool:
        """检查扫码平台页面上是否还有可见的登录文本按钮。"""
        selectors = [
            'text=登录',
            'button:has-text("登录")',
            '[role="button"]:has-text("登录")',
        ]
        if platform_name == "douyin":
            selectors.extend([
                'text=登录/注册',
                'button:has-text("登录/注册")',
                '[role="button"]:has-text("登录/注册")',
            ])
        return any(self._safe_visible_count(selector) > 0 for selector in selectors)

    def _scan_logged_in_marker_count(self) -> int:
        """统计扫码平台登录后常见的头像/我的入口，避免混用 CSS 和 text 选择器。"""
        selectors = [
            '[class*="avatar"]',  # 常见小写头像 class。
            '[class*="Avatar"]',  # 常见大写头像 class。
            'img[alt*="头像"]',  # 头像图片 alt。
            'text=我',  # “我/我的”入口。
            'text=我的',  # “我的”入口。
        ]
        return sum(self._safe_count(selector) for selector in selectors)  # 每个选择器单独统计，避免 Playwright 解析错误。

    def _safe_count(self, selector: str) -> int:
        """安全统计 locator 数量，选择器不兼容或页面瞬时变化时返回 0。"""
        try:
            return self.page.locator(selector).count()  # 正常统计当前选择器匹配数量。
        except Exception:
            return 0  # 第三方页面结构变化或选择器不兼容时不阻塞测试前置流程。

    def _safe_visible_count(self, selector: str) -> int:
        """安全统计可见元素数量，避免隐藏登录模板误判未登录。"""
        try:
            locator = self.page.locator(selector)
            count = locator.count()
            visible_count = 0
            for index in range(min(count, 20)):
                try:
                    if locator.nth(index).is_visible():
                        visible_count += 1
                except Exception:
                    continue
            return visible_count
        except Exception:
            return 0

    def _wait_scan_login_success(self, platform_name: str, wait_manual_seconds: int) -> bool:
        """等待小红书/抖音人工扫码登录，超时后让对应平台用例跳过。"""
        deadline = time.time() + wait_manual_seconds  # 计算扫码等待截止时间。
        while time.time() < deadline:
            self.page.wait_for_timeout(2000)  # 每 2 秒检查一次登录状态。
            if self._looks_scan_platform_logged_in(platform_name):
                return True  # 检测到登录态后返回成功。
        return False  # 登录入口仍存在时表示未登录，对应平台用例不执行。

    def _open_login_panel(self) -> None:
        """尝试点击页面上的登录入口或账号密码登录入口。"""
        self._click_first_match(
            [
                'text=账号登录',  # 中文“账号登录”入口。
                'text=密码登录',  # 中文“密码登录”入口。
                'text=登录',  # 中文“登录”入口。
                'button:has-text("登录")',  # 中文登录按钮入口。
                'text=璐﹀彿鐧诲綍',  # 历史编码下的“账号登录”入口。
                'text=瀵嗙爜鐧诲綍',  # 历史编码下的“密码登录”入口。
                'text=鐧诲綍',  # 通用“登录”文本入口。
                'button:has-text("鐧诲綍")',  # 登录按钮入口。
            ],
            required=False,  # 有些页面默认展示登录框，找不到入口也不立即失败。
        )
        self.page.wait_for_timeout(1000)  # 等待登录面板动画和输入框渲染。

    def _fill_first_match(self, selectors: list[str], value: str) -> None:
        """按选择器顺序查找第一个可见输入框并填充值。"""
        for selector in selectors:
            locator = self.page.locator(selector).first  # 只操作第一个匹配元素，避免多个输入框时误填全部。
            try:
                locator.wait_for(state="visible", timeout=3000)  # 等待当前候选输入框可见。
                locator.fill(value)  # 输入账号或密码。
                return  # 成功填充后立即结束。
            except PlaywrightTimeoutError:
                continue  # 当前选择器不可见时继续尝试下一个选择器。
        raise RuntimeError(f"No visible input matched selectors: {selectors}")  # 所有选择器都失败时抛出明确错误。

    def _click_first_match(self, selectors: list[str], required: bool = True) -> bool:
        """按选择器顺序点击第一个可见元素。"""
        for selector in selectors:
            locator = self.page.locator(selector).first  # 只点击第一个匹配元素。
            try:
                locator.wait_for(state="visible", timeout=3000)  # 等待按钮或入口可见。
                locator.click()  # 执行点击动作。
                return True  # 点击成功后返回 True。
            except PlaywrightTimeoutError:
                continue  # 当前候选元素不可见时尝试下一个。
        if required:
            raise RuntimeError(f"No visible clickable element matched selectors: {selectors}")  # 必须点击但找不到元素时失败。
        return False  # 非必需点击找不到元素时返回 False。

    def _looks_logged_in(self) -> bool:
        """通过页面是否仍有密码框/登录文本粗略判断平台是否已登录。"""
        password_inputs = self.page.locator('input[type="password"]').count()  # 统计页面上的密码输入框数量。
        login_text = self.page.locator('text=鐧诲綍').count()  # 统计页面上的登录文本数量。
        return password_inputs == 0 and login_text == 0  # 没有密码框和登录入口时认为已登录。

    def _wait_login_success(self, wait_manual_seconds: int) -> bool:
        """等待登录成功，支持人工扫码/验证码等需要手动完成的场景。"""
        deadline = time.time() + wait_manual_seconds  # 计算等待截止时间。
        while time.time() < deadline:
            self.page.wait_for_timeout(2000)  # 每 2 秒检查一次登录状态。
            if self._looks_logged_in():
                return True  # 登录态出现后返回成功。
        return False  # 超时仍未登录则返回失败。

    def _login_pugongying_xhs(self, url: str, username: str, password: str, wait_manual_seconds: int) -> bool:
        """按蒲公英页面真实交互流程执行账号密码登录。"""
        self.page.goto(url, wait_until="domcontentloaded")  # 打开蒲公英首页。
        self._pgy_step_wait(3000)  # 等待小红书蒲公英页面初始化。
        if self._looks_pugongying_logged_in():
            return True  # 已经是登录态时直接复用。
        self.page.get_by_role("button", name="登录", exact=True).click()  # 点击首页右上角登录按钮。
        self._pgy_step_wait()  # 等待登录弹层出现。
        self.page.get_by_text("账号登录").nth(1).click()  # 切换到账号登录 tab。
        self._pgy_step_wait()  # 等待账号登录表单渲染。
        self.page.get_by_role("textbox", name="邮箱").click()  # 聚焦邮箱输入框。
        self._pgy_step_wait()  # 放慢聚焦后的输入节奏，避免表单动画未结束。
        self.page.get_by_role("textbox", name="邮箱").fill(username)  # 填写蒲公英邮箱账号。
        self._pgy_step_wait()  # 等待邮箱值写入并触发表单校验。
        self.page.get_by_role("textbox", name="密码").click()  # 聚焦密码输入框。
        self._pgy_step_wait()  # 放慢密码框聚焦节奏。
        self.page.get_by_role("textbox", name="密码").fill(password)  # 填写蒲公英密码。
        self._pgy_step_wait()  # 等待密码值写入并触发表单校验。
        self._accept_pugongying_terms()  # 勾选“我已阅读并同意《蒲公英用户隐私政策》”协议。
        self._pgy_step_wait()  # 等待协议勾选状态同步到登录按钮。
        self.page.get_by_role("button", name="登 录").click()  # 点击登录按钮。
        return self._wait_pugongying_login_success(wait_manual_seconds)  # 等待登录完成或人工验证完成。

    def _pgy_step_wait(self, default_ms: int = 1500) -> None:
        """蒲公英登录专用慢速等待，可通过 FINDAI_PGY_STEP_DELAY_MS 调整每步间隔。"""
        delay_ms = int(os.getenv("FINDAI_PGY_STEP_DELAY_MS", str(default_ms)))  # 默认每步等待 1.5 秒，页面初始化处可传更长默认值。
        self.page.wait_for_timeout(delay_ms)  # 使用 Playwright 页面等待，避免阻塞浏览器事件处理。

    def _accept_pugongying_terms(self) -> None:
        """勾选蒲公英登录弹窗里的隐私政策协议复选框。"""
        self.page.get_by_text("我已阅读并同意").nth(1).click(timeout=3000)  # 使用已验证可生效的蒲公英隐私政策文本定位。

    def _looks_pugongying_logged_in(self) -> bool:
        """判断蒲公英是否已经登录。"""
        login_buttons = self.page.get_by_role("button", name="登录", exact=True).count()  # 未登录首页通常有登录按钮。
        password_inputs = self.page.get_by_role("textbox", name="密码").count()  # 登录弹层通常有密码输入框。
        return login_buttons == 0 and password_inputs == 0  # 没有登录按钮和密码框时认为已登录。

    def _wait_pugongying_login_success(self, wait_manual_seconds: int) -> bool:
        """等待蒲公英登录成功，支持验证码或二次验证人工处理。"""
        deadline = time.time() + wait_manual_seconds  # 计算等待截止时间。
        while time.time() < deadline:
            self.page.wait_for_timeout(2000)  # 每 2 秒检查一次页面状态。
            if self._looks_pugongying_logged_in():
                return True  # 页面不再展示登录入口/密码框时认为成功。
        return False  # 超时仍未登录则返回失败。

    def _login_xingtu_oceanengine(self, url: str, username: str, password: str, wait_manual_seconds: int) -> bool:
        """登录星图新版 OceanEngine SSO 邮箱登录页。"""
        self.page.goto(url, wait_until="domcontentloaded")  # 打开新版星图 SSO 登录页。
        self.page.wait_for_timeout(3000)  # 等待登录卡片和背景资源渲染完成。
        if self._looks_xingtu_logged_in():
            return True  # 如果已登录并自动跳转到业务页，直接返回成功。
        self.page.get_by_text("邮箱登录").click()  # 按星图新版登录页文本切换到邮箱登录。
        self.page.wait_for_timeout(500)  # 等待邮箱登录表单切换完成。
        self.page.get_by_role("textbox", name="请输入邮箱").click()  # 聚焦邮箱输入框。
        self.page.get_by_role("textbox", name="请输入邮箱").fill(username)  # 填写星图邮箱账号。
        self._fill_xingtu_password(password)  # 填写星图密码，兼容“密码/请输入密码”两个无障碍名称。
        self._accept_xingtu_terms()  # 勾选“我已阅读并同意”协议，否则登录按钮不可用。
        self.page.get_by_role("button", name="登录").click()  # 点击登录按钮。
        return self._wait_xingtu_login_success(wait_manual_seconds)  # 等待自动跳转或人工完成验证码。

    def _fill_xingtu_password(self, password: str) -> None:
        """填写星图密码输入框。"""
        for name in ("请输入密码", "密码"):
            try:
                textbox = self.page.get_by_role("textbox", name=name)  # 优先使用用户提供的 role/name 定位。
                textbox.click(timeout=2000)  # 聚焦密码框。
                textbox.fill(password)  # 填写配置中的星图密码。
                return
            except Exception:
                continue  # 当前 name 不存在时尝试下一个。
        self._fill_first_match(["input[type='password']", "input[placeholder*='密码']"], password)  # 兜底 CSS 定位密码框。

    def _accept_xingtu_terms(self) -> None:
        """勾选星图登录页的用户协议复选框。"""
        selectors = [
            'input[type="checkbox"]',  # 原生复选框。
            'label:has-text("我已阅读") input',  # 协议 label 内的复选框。
            '.semi-checkbox input',  # OceanEngine/Semi UI 复选框。
            '.byted-checkbox input',  # 字节系旧版复选框。
        ]
        for selector in selectors:
            locator = self.page.locator(selector).first  # 只处理第一个协议复选框。
            try:
                locator.wait_for(state="attached", timeout=1500)  # 有些复选框不可见但 attached，可用 force 勾选。
                if hasattr(locator, "is_checked") and locator.is_checked():
                    return  # 已勾选时无需重复点击。
                locator.check(force=True)  # 强制勾选，兼容自定义样式导致的不可见 input。
                return
            except Exception:
                continue  # 当前选择器失败则尝试文本点击兜底。
        self._click_first_match(
            [
                'text=我已阅读并同意',  # 点击协议文本附近区域。
                'label:has-text("我已阅读")',  # 点击包含协议文本的 label。
                'span:has-text("我已阅读")',  # 点击协议 span 文本。
            ],
            required=False,
        )
        try:
            self.page.locator("use").nth(1).click(timeout=2000)  # 用户提供的星图协议勾选定位。
        except Exception:
            pass  # use 图标不存在或已勾选时忽略，继续 JS 兜底。
        self.page.evaluate(
            """() => {
                const inputs = Array.from(document.querySelectorAll('input[type="checkbox"]'));
                for (const input of inputs) {
                    input.checked = true;
                    input.dispatchEvent(new Event('input', { bubbles: true }));
                    input.dispatchEvent(new Event('change', { bubbles: true }));
                    input.click();
                }
            }"""
        )  # JS 兜底触发协议复选框的 checked/change/click，兼容自定义样式组件。

    def _looks_xingtu_logged_in(self) -> bool:
        """判断星图是否已经离开 SSO 登录页。"""
        current_url = self.page.url  # 读取当前页面地址。
        password_inputs = self.page.locator('input[type="password"]').count()  # 登录页通常存在密码输入框。
        login_card_text = self.page.locator('text=邮箱登录').count() + self.page.locator('text=手机登录').count()  # 登录页 tab 文本。
        return "sso.oceanengine.com" not in current_url and password_inputs == 0 and login_card_text == 0  # 跳出 SSO 且无登录表单时认为成功。

    def _wait_xingtu_login_success(self, wait_manual_seconds: int) -> bool:
        """等待星图登录成功，支持验证码或二次验证人工处理。"""
        deadline = time.time() + wait_manual_seconds  # 计算等待截止时间。
        while time.time() < deadline:
            self.page.wait_for_timeout(2000)  # 每 2 秒检查一次。
            if self._looks_xingtu_logged_in():
                return True  # 跳转到业务页后返回成功。
        return False  # 超时仍停留登录页则返回失败。


class FindaiLogin:
    """封装 findai 插件登录、接口登录、token 同步和 base_url 同步。"""

    def __init__(
        self,
        page: Page | None = None,
        request_client: RequestClient | None = None,
        login_info: dict[str, Any] | None = None,
        config_path: str | Path = "login_info.yaml",
        base_url: str | None = None,
    ):
        self.page = page  # 插件页面对象，可为空；为空时只能走接口侧逻辑。
        self.login_info = login_info or {}  # 登录配置为空时使用空字典，避免 None 判断分散在各处。
        self.config_path = config_path  # 保存配置文件路径，用于回写 token 和 base_url。
        self.base_url = (base_url or self.login_info.get("findai", {}).get("base_url") or "").rstrip("/")  # 优先使用入参，其次使用配置文件中的域名。
        if not self.base_url and self.page:
            self.base_url = get_findai_base_url_from_extension(self.page)  # 配置中没有域名时从插件脚本动态提取。
            save_findai_base_url(self.base_url, self.config_path)  # 将动态提取到的域名保存回配置文件。
        if not self.base_url and request_client is None:
            raise ValueError("findai base_url is empty. Open/login the plugin first and sync base_url.")  # 没有域名且没有现成客户端时无法请求接口。
        self.request_client = request_client or RequestClient(self.base_url)  # 创建或复用请求客户端。

    def sync_from_browser_plugin(self) -> dict[str, Any]:
        """从已打开且已登录的插件页面同步 base_url 和 token。"""
        if not self.page:
            raise ValueError("sync_from_browser_plugin requires an extension page.")  # 读取插件 storage 必须依赖插件页面。

        self.base_url = get_findai_base_url_from_extension(self.page)  # 从当前插件版本提取接口域名。
        save_findai_base_url(self.base_url, self.config_path)  # 回写 base_url，解决测试/生产域名动态变化问题。

        device_id = get_findai_device_id_from_extension(self.page)  # 读取插件真实 DeviceId，便于接口测试复刻插件请求。
        if device_id:
            save_findai_device_id(device_id, self.config_path)  # 有 DeviceId 时保存到 login_info.yaml。

        token_info = get_findai_token_from_extension(self.page)  # 从 chrome.storage.local 读取 USER_TOKEN。
        if token_info:
            save_findai_token(token_info, self.config_path, base_url=self.base_url)  # 有 token 时保存到 login_info.yaml。
        runtime_context = self._save_platform_runtime_context()  # 同步平台账号 ID 和浏览器设备 ID。
        return {"base_url": self.base_url, "token_info": token_info, "device_id": device_id, "runtime": runtime_context}  # 返回同步结果给脚本或调用方打印。

    def login_plugin_in_browser(self, wait_seconds: int = 30) -> dict[str, Any]:
        """通过插件 UI 登录，并持久化插件内的 base_url 和 token。"""
        if not self.page:
            raise ValueError("login_plugin_in_browser requires an extension page.")  # 插件 UI 登录必须有页面对象。

        account = self.login_info.get("findai", {})  # 读取 findai 账号配置。
        mobile = account.get("username")  # findai 手机号/用户名。
        password = account.get("password")  # findai 密码。
        if not mobile or not password:
            raise ValueError("findai username/password is empty in login_info.yaml")  # 账号密码缺失时提前失败。

        self.base_url = get_findai_base_url_from_extension(self.page)  # 登录前先读取当前插件环境域名。
        save_findai_base_url(self.base_url, self.config_path)  # 保存域名，后续接口测试会使用它。
        device_id = get_findai_device_id_from_extension(self.page)  # 读取插件当前 DeviceId。
        if device_id:
            save_findai_device_id(device_id, self.config_path)  # 保存 DeviceId，后续接口请求带同一个设备标识。

        token_info = get_findai_token_from_extension(self.page)  # 如果插件已登录，直接复用已有 token。
        if not token_info:
            self._fill_plugin_login_form(mobile, password)  # 未登录时填写插件登录表单。
            deadline = time.time() + wait_seconds  # 计算等待 token 写入 storage 的截止时间。
            while time.time() < deadline:
                self.page.wait_for_timeout(1000)  # 每秒检查一次 storage。
                token_info = get_findai_token_from_extension(self.page)  # 读取插件登录后写入的 token。
                if token_info:
                    break  # 读取到 token 后停止等待。

        if not token_info:
            raise RuntimeError("Findai browser login did not create USER_TOKEN in extension storage.")  # 登录后仍无 token，说明插件登录失败。

        save_findai_token(token_info, self.config_path, base_url=self.base_url)  # 保存 token，供 pytest 接口用例使用。
        self._save_platform_runtime_context()  # 登录插件后同步平台账号 ID 和浏览器设备 ID。
        return token_info  # 返回 token 信息给调用方。

    def login_plugin(self, sync_to_extension: bool = True) -> dict[str, Any]:
        """通过 findai 接口登录，并可选择把 token 同步回插件 storage。"""
        account = self.login_info.get("findai", {})  # 读取 findai 账号配置。
        mobile = account.get("username")  # findai 手机号/用户名。
        password = account.get("password")  # findai 密码。
        if not mobile or not password:
            raise ValueError("findai username/password is empty in login_info.yaml")  # 账号密码缺失时提前失败。

        response = self.request_client.post(
            "/signInByMobile",  # findai 手机号密码登录接口。
            json={"fdMobile": mobile, "fdPassword": password},  # 登录请求体字段与插件接口保持一致。
        )
        response.raise_for_status()  # HTTP 状态非成功时抛出异常。
        payload = response.json()  # 解析登录响应 JSON。
        token_info = self._extract_token_info(payload)  # 兼容不同响应层级提取 token。
        if not token_info.get("access_token"):
            raise RuntimeError(f"Findai login did not return access_token: {payload}")  # 没有 access_token 时认为登录失败。

        save_findai_token(token_info, self.config_path, base_url=self.base_url)  # 将 token 保存到配置文件。
        if sync_to_extension and self.page:
            set_findai_token_to_extension(self.page, token_info)  # 需要时把接口 token 写回插件 storage。
        return token_info  # 返回 token 信息。

    def get_token(self) -> str:
        """快捷获取 access_token。"""
        token_info = self.login_plugin()  # 通过接口登录获取 token 信息。
        return token_info["access_token"]  # 返回 access_token 字段。

    @staticmethod
    def _extract_token_info(payload: dict[str, Any]) -> dict[str, Any]:
        """兼容不同登录响应结构提取 token 字典。"""
        if "access_token" in payload:
            return payload  # token 在顶层时直接返回响应本身。
        data = payload.get("data")  # 部分接口会把 token 放在 data 节点。
        if isinstance(data, dict) and "access_token" in data:
            return data  # data 中存在 access_token 时返回 data。
        return payload  # 兜底返回原响应，让调用方抛出更完整的错误信息。

    def _fill_plugin_login_form(self, mobile: str, password: str) -> None:
        """填写并提交插件登录表单。"""
        self.page.locator(".overlay-container").click()  # 点击插件 overlay，确保登录面板获得焦点。
        self.page.get_by_role("textbox", name="请输入手机号码").fill(mobile)  # 填写 findai 手机号。
        self.page.get_by_role("textbox", name="请输入密码").fill(password)  # 填写 findai 密码。
        self._click_first_match(
            [
                'button:has-text("登录")',  # 插件中文登录按钮。
                'button[type="button"]',  # 插件按钮兜底。
                'button[type="submit"]',  # submit 按钮兜底。
            ]
        )

    def _save_platform_runtime_context(self) -> dict[str, Any]:
        """从插件 storage 保存平台账号 ID 和浏览器设备 ID。"""
        if not self.page:
            return {}  # 没有插件页面时无法读取平台上下文。
        context = get_platform_runtime_context_from_extension(self.page)  # 读取插件保存的平台账号和设备信息。
        device_id = context.get("device_id", "")  # 浏览器设备 ID，对应 build 请求的 fdOriginalDeviceId。
        for platform_name, platform_data in context.get("platforms", {}).items():
            third_id = platform_data.get("third_id", "") if isinstance(platform_data, dict) else ""  # 平台账号 ID，对应 build 请求的 fdOriginalThirdId。
            if third_id:
                save_platform_runtime_context(platform_name, third_id, device_id, self.config_path)  # 将平台账号 ID 和设备 ID 写入配置文件。
        return context  # 返回读取到的上下文，便于脚本打印或调试。
