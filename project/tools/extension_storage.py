import json  # 用于把插件 chrome.storage.local 中保存的 token 字符串反序列化成字典。
import re  # 用于从插件打包后的 JavaScript 文件中正则提取接口域名。


def _parse_jsonish_value(value):
    """递归解析可能被多包了一层 JSON 字符串的 storage 值。"""
    current = value  # 保存当前待解析值。
    for _ in range(3):  # 最多解三层，避免异常数据导致无限循环。
        if not isinstance(current, str):
            return current  # 非字符串说明已经是 dict/list 等真实结构。
        stripped = current.strip()  # 去掉前后空白，便于判断 JSON 字符串。
        if not stripped:
            return ""  # 空字符串直接返回。
        try:
            parsed = json.loads(stripped)  # 尝试把 JSON 字符串解成真实对象。
        except json.JSONDecodeError:
            return current  # 不是 JSON 时保留原始字符串。
        if parsed == current:
            return parsed  # 解析后无变化时直接返回。
        current = parsed  # 继续处理可能嵌套的 JSON 字符串。
    return current  # 返回最终解析结果。


def set_findai_token_to_extension(page, token_info: dict) -> None:
    """把接口登录得到的 token 写入插件使用的 chrome.storage.local。"""
    page.evaluate(
        """async (tokenInfo) => {
            await chrome.storage.local.set({ USER_TOKEN: JSON.stringify(tokenInfo) });
        }""",
        token_info,
    )


def get_findai_token_from_extension(page) -> dict:
    """从当前插件页面读取 USER_TOKEN，并统一返回 Python 字典。"""
    raw = page.evaluate(
        """async () => {
            const key = "USER_TOKEN";
            const localData = await chrome.storage.local.get(key).catch(() => ({}));
            const syncData = await chrome.storage.sync.get(key).catch(() => ({}));
            return localData[key] || syncData[key] || "";
        }"""
    )
    if not raw:
        return {}
    parsed = _parse_jsonish_value(raw)  # 兼容 USER_TOKEN 被保存成 JSON 字符串或二次 JSON 字符串。
    if isinstance(parsed, dict):
        access_token = _parse_jsonish_value(parsed.get("access_token") or parsed.get("token") or "")  # 兼容 access_token 字段内又套一层 JSON。
        if isinstance(access_token, dict):
            return access_token  # 内层才是真正 token 字典时返回内层。
        parsed["access_token"] = str(access_token or "")  # 确保请求头使用的是纯 token。
        return parsed  # 返回清洗后的 token 字典。
    return {"access_token": str(parsed or "")}  # 统一返回字典，避免调用方误把 JSON 字符串当 token。


def get_findai_storage_snapshot(page) -> dict:
    """读取插件关键 storage 快照，用于 token 未写入时定位实际写入位置。"""
    snapshot = page.evaluate(
        """async () => {
            const keys = ["USER_TOKEN", "IS_LOGIN", "PLUGIN_ACCOUNT_INFO", "ACCOUNT_INFO", "XT_ACCOUNT_INFO", "FINGERPRINT_ID_WITH_UUID"];
            const localData = await chrome.storage.local.get(keys).catch(() => ({}));
            const syncData = await chrome.storage.sync.get(keys).catch(() => ({}));
            const summarize = (data) => Object.fromEntries(Object.entries(data).map(([key, value]) => {
                if (typeof value === "string") return [key, value.length > 120 ? `${value.slice(0, 120)}...` : value];
                return [key, value];
            }));
            return { local: summarize(localData), sync: summarize(syncData) };
        }"""
    )
    return snapshot if isinstance(snapshot, dict) else {}


def get_findai_base_url_from_extension(page) -> str:
    """从已加载的插件脚本中读取当前环境的 findai 接口域名。"""
    base_url = page.evaluate(
        """async () => {
            const scripts = Array.from(document.scripts)
                .map((script) => script.getAttribute("src"))
                .filter(Boolean);
            const urls = scripts.length ? scripts : ["options.95eda3f3.js", "sidepanel.b7741352.js", "static/background/index.js"];

            for (const src of urls) {
                try {
                    const url = src.startsWith("chrome-extension://") ? src : chrome.runtime.getURL(src.replace(/^\\//, ""));
                    const text = await fetch(url).then((response) => response.text());
                    const match =
                        text.match(/(?:HOST|baseURL)["']?\\s*,?\\s*=>\\s*[^\\n]*?["'](https?:\\/\\/[^"']+)["']/) ||
                        text.match(/\\b(?:HOST|v|_)\\s*=\\s*["'](https?:\\/\\/[^"']+)["']\\s*,\\s*(?:LOG_BASE_URL|y|v)\\s*=/) ||
                        text.match(/baseURL\\s*:\\s*["']?(https?:\\/\\/[^"',}]+)/);
                    if (match && match[1]) return match[1].replace(/\\/+$/, "");
                } catch (error) {
                    // Keep trying the next bundled script.
                }
            }
            return "";
        }"""
    )
    if not base_url:
        raise RuntimeError("Could not read findai API base URL from the loaded extension.")
    return str(base_url).rstrip("/")


def get_findai_device_id_from_extension(page) -> str:
    """从插件 storage 中读取真实 DeviceId。"""
    device_id = page.evaluate(
        """async () => {
            const key = "FINGERPRINT_ID_WITH_UUID";
            const syncData = await chrome.storage.sync.get(key).catch(() => ({}));
            const localData = await chrome.storage.local.get(key).catch(() => ({}));
            return syncData[key] || localData[key] || "";
        }"""
    )
    parsed = _parse_jsonish_value(device_id)  # 兼容 DeviceId 被保存成带引号的 JSON 字符串。
    return str(parsed or "")  # 没有读取到时返回空字符串，由调用方决定是否生成兜底 DeviceId。


def get_platform_runtime_context_from_extension(page) -> dict:
    """从插件 storage 中读取平台账号 ID 和浏览器设备 ID。"""
    context = page.evaluate(
        """async () => {
            const keys = ["FINGERPRINT_ID_WITH_UUID", "ACCOUNT_INFO", "XT_ACCOUNT_INFO"];
            const localData = await chrome.storage.local.get(keys).catch(() => ({}));
            const syncData = await chrome.storage.sync.get(keys).catch(() => ({}));
            const readJson = (value) => {
                if (!value) return {};
                if (typeof value === "string") {
                    try { return JSON.parse(value); } catch (error) { return {}; }
                }
                return value;
            };
            const pgyInfo = readJson(localData.ACCOUNT_INFO || syncData.ACCOUNT_INFO);
            const xtInfo = readJson(localData.XT_ACCOUNT_INFO || syncData.XT_ACCOUNT_INFO);
            const parseJsonish = (value) => {
                let current = value;
                for (let index = 0; index < 3; index += 1) {
                    if (typeof current !== "string") return current;
                    try {
                        const parsed = JSON.parse(current);
                        if (parsed === current) return parsed;
                        current = parsed;
                    } catch (error) {
                        return current;
                    }
                }
                return current;
            };
            return {
                device_id: parseJsonish(syncData.FINGERPRINT_ID_WITH_UUID || localData.FINGERPRINT_ID_WITH_UUID || ""),
                platforms: {
                    pgy: { third_id: pgyInfo.userId || "" },
                    pugongying: { third_id: pgyInfo.userId || "" },
                    xt: { third_id: (xtInfo.user && xtInfo.user.id) || "" },
                    xingtu: { third_id: (xtInfo.user && xtInfo.user.id) || "" }
                }
            };
        }"""
    )
    return context if isinstance(context, dict) else {}  # 统一返回字典，异常结构时返回空字典。


def get_extension_version(page) -> str:
    """读取当前加载的 findai 插件版本号。"""
    version = page.evaluate("() => chrome.runtime.getManifest().version")  # 通过插件运行时 API 获取 manifest 里的 version。
    return str(version or "")  # 返回字符串版本号，读取失败时返回空字符串。


def extract_findai_base_url_from_extension_dir(extension_dir: str) -> str:
    """无浏览器页面时，直接扫描插件目录并提取 findai 接口域名。"""
    from pathlib import Path  # 延迟导入路径工具，只有使用目录扫描兜底逻辑时才需要。

    root = Path(extension_dir)  # 把传入的字符串路径包装成 Path，便于递归遍历。
    for path in root.rglob("*.js"):  # 遍历插件目录下所有打包后的 JavaScript 文件。
        text = path.read_text(encoding="utf-8", errors="ignore")  # 忽略异常字符，尽量读取压缩脚本内容。
        match = re.search(r'\b(?:HOST|v|_)\s*=\s*["\'](https?://[^"\']+)["\']\s*,\s*(?:LOG_BASE_URL|y|v)\s*=', text)  # 匹配常见的 HOST 变量赋值写法。
        if match:
            return match.group(1).rstrip("/")  # 返回不带末尾斜杠的域名，方便后续拼接 endpoint。
    raise RuntimeError(f"Could not read findai API base URL from {root}")
