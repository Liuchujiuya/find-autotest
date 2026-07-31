from __future__ import annotations  # 允许在类型注解中延迟解析类型，避免运行时不必要的导入开销。

import json  # 用于把字典、列表等对象序列化成 Allure 可展示的 JSON 文本。
from typing import Any  # Any 表示该工具函数可以接收任意类型的数据。

try:  # Allure 不是普通 pytest 执行的强依赖，所以这里做可选导入。
    import allure  # allure-pytest 安装后会提供该模块，用于动态标题和附件。
except ModuleNotFoundError:  # 如果没有安装 allure-pytest，项目仍然可以用普通 pytest 运行。
    allure = None  # 用 None 表示当前运行环境不支持 Allure 附件能力。


def set_title(title: str) -> None:
    """设置 Allure 单条用例标题。"""
    if allure:  # 只有安装了 Allure 插件时才调用动态标题 API。
        allure.dynamic.title(title)  # 在报告中把参数化用例展示为“用例ID + 用例标题”。


def attach_json(name: str, data: Any) -> None:
    """把任意 Python 对象作为 JSON 附件写入 Allure 报告。"""
    if not allure:  # 普通 pytest 环境没有 Allure 时直接跳过，不影响测试逻辑。
        return  # 这里提前返回，避免调用不存在的 allure API。
    allure.attach(
        json.dumps(data, ensure_ascii=False, indent=2, default=str),  # 格式化 JSON，并保留中文可读性。
        name=name,  # 附件名称会显示在 Allure 单条用例详情中。
        attachment_type=allure.attachment_type.JSON,  # 指定附件类型，便于 Allure 用 JSON 视图展示。
    )


def attach_text(name: str, text: str) -> None:
    """把普通文本作为附件写入 Allure 报告。"""
    if not allure:  # 没装 Allure 时保持静默，保证工具函数可复用。
        return  # 直接退出，避免普通测试环境报错。
    allure.attach(str(text), name=name, attachment_type=allure.attachment_type.TEXT)  # 文本附件适合状态码、非 JSON 响应等内容。


def mask_headers(headers: dict[str, Any]) -> dict[str, Any]:
    """对请求头中的敏感字段做脱敏，避免报告泄露凭据。"""
    masked = {}  # 创建一个新的字典，避免修改调用方传入的原始 headers。
    for key, value in headers.items():  # 遍历每一个请求头字段。
        if key.lower() in {"authorization", "cookie", "set-cookie", "token"}:  # 常见鉴权/会话字段需要隐藏。
            masked[key] = mask_secret(str(value))  # 保留少量首尾字符，便于定位环境，同时隐藏主体。
        else:  # 非敏感字段可以原样展示在报告中。
            masked[key] = value  # 保留原值，方便排查请求上下文。
    return masked  # 返回脱敏后的 headers，供 Allure 附件使用。


def mask_secret(value: str) -> str:
    """对单个敏感字符串做首尾保留式脱敏。"""
    if len(value) <= 12:  # 太短的密钥没有足够安全的首尾展示空间。
        return "***"  # 短字符串直接完全隐藏。
    return f"{value[:8]}***{value[-4:]}"  # 长字符串保留前 8 位和后 4 位，方便人工识别是哪一套 token。
