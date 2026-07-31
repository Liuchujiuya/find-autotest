from __future__ import annotations  # 让类型注解延迟求值，兼容更复杂的类型声明。

import json  # 用于兼容 token/device_id 被保存成 JSON 字符串的情况。
from datetime import datetime  # 用于记录 token/base_url 保存时间，便于排查环境同步时间。
from pathlib import Path  # 用 pathlib 统一处理 Windows 路径和相对路径。
from typing import Any  # 配置文件是动态 YAML，值类型可能是字符串、字典、列表等。

import yaml  # 用于读取和写入 login_info.yaml 以及测试数据 YAML。


DEFAULT_CONFIG_PATH = Path("login_info.yaml")  # 项目默认账号配置文件路径。


def load_yaml(config_path: str | Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    """读取 YAML 文件；文件不存在时返回空字典。"""
    path = Path(config_path)  # 将传入的字符串或 Path 统一转换为 Path 对象。
    if not path.exists():  # 配置文件可能在首次运行前还不存在。
        return {}  # 不抛异常，方便调用方用默认值继续处理。
    with path.open("r", encoding="utf-8") as file:  # 使用 UTF-8 保证中文账号说明和测试数据不乱码。
        return yaml.safe_load(file) or {}  # 空文件会解析为 None，这里统一转为空字典。


def save_yaml(data: dict[str, Any], config_path: str | Path = DEFAULT_CONFIG_PATH) -> None:
    """把字典数据保存为 YAML 文件。"""
    path = Path(config_path)  # 统一路径类型，后续 open 更稳定。
    with path.open("w", encoding="utf-8") as file:  # 写入时固定 UTF-8，避免中文字段被系统编码破坏。
        yaml.safe_dump(data, file, allow_unicode=True, sort_keys=False)  # 保留中文和原始键顺序，提高可读性。


def get_account(config: dict[str, Any], section: str, name: str | None = None) -> dict[str, Any]:
    """从配置中读取账号节点，例如 platforms.pugongying 或 findai。"""
    node: Any = config.get(section, {})  # 先取一级配置节点，例如 platforms。
    if name:  # 如果传入二级名称，则继续下钻。
        node = node.get(name, {})  # 读取指定平台或指定账号配置。
    return node or {}  # 保证返回字典，避免调用方处理 None。


def save_findai_token(
    token_info: dict[str, Any] | str,
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    base_url: str | None = None,
) -> str:
    """保存 findai 登录后的 token 信息，并可同时保存当前插件环境域名。"""
    config = load_yaml(config_path)  # 先读取已有配置，避免覆盖账号密码等其它字段。
    config.setdefault("findai", {})  # 确保 findai 节点存在，便于后续写入 token。
    token_data = _normalize_token_info(token_info)  # 兼容插件保存 dict、纯 token 字符串或 JSON 字符串。
    access_token = token_data.get("access_token") or token_data.get("token") or ""  # 兼容不同接口返回的 token 字段名。
    config["findai"]["token"] = access_token  # 保存纯 token，供接口请求头快速使用。
    config["findai"]["token_info"] = token_data  # 保存完整 token 结构，便于后续刷新或排查。
    config["findai"]["token_saved_at"] = datetime.now().isoformat(timespec="seconds")  # 记录保存时间，方便判断 token 是否过期。
    if base_url:  # 插件可能有测试/生产不同域名，传入时一并保存。
        config["findai"]["base_url"] = base_url.rstrip("/")  # 去掉末尾斜杠，避免拼接接口路径时出现双斜杠。
        config["findai"]["base_url_saved_at"] = datetime.now().isoformat(timespec="seconds")  # 记录域名同步时间。
    save_yaml(config, config_path)  # 把更新后的配置写回 login_info.yaml。
    return access_token  # 返回 access_token，便于调用方打印长度或继续使用。


def save_findai_base_url(base_url: str, config_path: str | Path = DEFAULT_CONFIG_PATH) -> str:
    """单独保存 findai 插件当前使用的接口域名。"""
    config = load_yaml(config_path)  # 读取现有 YAML，保留原有账号和 token。
    config.setdefault("findai", {})  # 确保 findai 节点存在。
    config["findai"]["base_url"] = base_url.rstrip("/")  # 规范化域名，统一不带末尾斜杠。
    config["findai"]["base_url_saved_at"] = datetime.now().isoformat(timespec="seconds")  # 保存域名同步时间。
    save_yaml(config, config_path)  # 写回配置文件。
    return config["findai"]["base_url"]  # 返回最终保存的域名，便于调用方确认。


def save_findai_device_id(device_id: str, config_path: str | Path = DEFAULT_CONFIG_PATH) -> str:
    """保存模拟插件请求使用的 DeviceId。"""
    config = load_yaml(config_path)  # 读取现有 YAML，避免覆盖账号、token 和 base_url。
    config.setdefault("findai", {})  # 确保 findai 节点存在。
    config["findai"]["device_id"] = _normalize_string_value(device_id)  # 保存稳定设备 ID，后续登录和接口请求保持一致。
    config["findai"]["device_id_saved_at"] = datetime.now().isoformat(timespec="seconds")  # 记录设备 ID 保存时间。
    save_yaml(config, config_path)  # 写回配置文件。
    return config["findai"]["device_id"]  # 返回最终保存的设备 ID。


def _normalize_token_info(token_info: dict[str, Any] | str) -> dict[str, Any]:
    """把 dict、纯 token 字符串或 JSON 字符串统一成 token 字典。"""
    parsed = _parse_jsonish_value(token_info)  # 先解析可能嵌套的 JSON 字符串。
    if isinstance(parsed, dict):
        access_token = _parse_jsonish_value(parsed.get("access_token") or parsed.get("token") or "")  # 兼容 access_token 字段里又套了一段 JSON。
        if isinstance(access_token, dict):
            return access_token  # access_token 本身是 token 字典时取内层真实结构。
        parsed["access_token"] = str(access_token or "")  # 确保 access_token 是纯 token 字符串。
        return parsed  # 已经是 token 字典时返回清洗后的结构。
    return {"access_token": str(parsed or "")}  # 纯 token 字符串按 access_token 保存。


def _normalize_string_value(value: Any) -> str:
    """把可能被 JSON 包装的字符串还原成普通字符串。"""
    parsed = _parse_jsonish_value(value)  # 先解析 JSON 字符串。
    return str(parsed or "")  # 统一返回字符串。


def _parse_jsonish_value(value: Any) -> Any:
    """递归解析可能被多包了一层 JSON 的值。"""
    current = value  # 保存当前待解析值。
    for _ in range(3):  # 最多解析三层，避免异常数据无限循环。
        if not isinstance(current, str):
            return current  # 非字符串说明已经解析完成。
        stripped = current.strip()  # 去掉前后空白。
        if not stripped:
            return ""  # 空字符串直接返回。
        try:
            parsed = json.loads(stripped)  # 尝试按 JSON 解码。
        except json.JSONDecodeError:
            return current  # 不是 JSON 时返回原始字符串。
        if parsed == current:
            return parsed  # 解析后没有变化时返回。
        current = parsed  # 继续处理二次 JSON 字符串。
    return current  # 返回最终解析值。


def save_platform_runtime_context(
    platform_name: str,
    third_id: str,
    device_id: str = "",
    config_path: str | Path = DEFAULT_CONFIG_PATH,
) -> dict[str, Any]:
    """保存平台账号 ID 和浏览器设备 ID，供 build 接口模板渲染使用。"""
    config = load_yaml(config_path)  # 读取现有 YAML，保留账号、token、base_url 等字段。
    config.setdefault("runtime", {})  # runtime 节点专门保存执行时动态上下文。
    config["runtime"].setdefault("platforms", {})  # platforms 子节点按平台名称保存 third_id。
    config["runtime"]["platforms"].setdefault(platform_name, {})  # 确保目标平台节点存在。
    config["runtime"]["platforms"][platform_name]["third_id"] = str(third_id or "")  # 保存平台账号 ID。
    if device_id:
        config["runtime"]["device_id"] = str(device_id)  # 保存浏览器设备 ID，build 请求体会使用它。
    config["runtime"]["saved_at"] = datetime.now().isoformat(timespec="seconds")  # 记录动态上下文保存时间。
    save_yaml(config, config_path)  # 写回配置文件。
    return config["runtime"]  # 返回 runtime 节点，便于调用方打印或继续使用。
