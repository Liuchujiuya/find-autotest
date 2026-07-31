import requests  # requests 负责执行 HTTP 接口调用。

from tools.allure_helper import attach_json, attach_text, mask_headers  # Allure 附件工具用于记录请求/响应日志。


class RequestClient:
    """Simple requests wrapper for API test cases."""

    def __init__(self, base_url: str = "", headers: dict | None = None, timeout: int = 30):
        self.base_url = base_url.rstrip("/")  # 统一去掉末尾斜杠，避免拼接 path 时出现双斜杠。
        self.session = requests.Session()  # 使用 Session 复用连接，并统一保存公共请求头。
        self.session.headers.update(headers or {})  # 写入鉴权头、版本号等公共 headers。
        self.timeout = timeout  # 默认请求超时时间，避免接口无响应时测试无限等待。

    def request(self, method: str, path: str, **kwargs):
        """执行任意 HTTP 方法，并自动把请求/响应写入 Allure。"""
        url = path if path.startswith("http") else f"{self.base_url}/{path.lstrip('/')}"  # 支持完整 URL，也支持相对接口路径。
        kwargs.setdefault("timeout", self.timeout)  # 如果调用方没传 timeout，则使用客户端默认超时时间。
        response = self.session.request(method=method, url=url, **kwargs)  # 真正发起 HTTP 请求。
        self._attach_request_response(method, url, kwargs, response)  # 把本次请求和响应记录到 Allure 报告。
        return response  # 返回原始 Response，交给业务封装做断言和解析。

    def get(self, path: str, **kwargs):
        """执行 GET 请求。"""
        return self.request("GET", path, **kwargs)  # 复用统一 request 方法，保证日志行为一致。

    def post(self, path: str, **kwargs):
        """执行 POST 请求。"""
        return self.request("POST", path, **kwargs)  # 复用统一 request 方法，保证日志行为一致。

    def _attach_request_response(self, method: str, url: str, kwargs: dict, response) -> None:
        """把一次接口调用的请求头、请求体、响应状态和响应体写入 Allure。"""
        request_body = kwargs.get("json", kwargs.get("data", kwargs.get("params", "")))  # 优先展示 JSON 请求体，其次展示 data/params。
        request_headers = dict(self.session.headers)  # 复制 Session 公共请求头，避免直接修改 session。
        request_headers.update(kwargs.get("headers") or {})  # 合并单次请求额外传入的 headers。

        attach_json(
            f"接口请求头 {method.upper()} {url}",  # 附件名包含方法和 URL，便于在 Allure 中定位接口。
            mask_headers(request_headers),  # 请求头写入报告前先脱敏，避免暴露 token/cookie。
        )
        attach_json(f"接口请求体 {method.upper()} {url}", request_body)  # 附加请求体，便于复现接口调用。
        attach_text(f"接口响应状态码 {method.upper()} {url}", str(response.status_code))  # 单独记录 HTTP 状态码。

        try:  # 响应体通常是 JSON，但异常页或网关错误可能是文本/HTML。
            response_body = response.json()  # 尝试按 JSON 解析响应体。
            attach_json(f"接口响应体 {method.upper()} {url}", response_body)  # JSON 响应用结构化附件展示。
        except ValueError:  # JSON 解析失败时说明响应体不是合法 JSON。
            attach_text(f"接口响应体 {method.upper()} {url}", response.text)  # 非 JSON 响应用文本附件展示。
