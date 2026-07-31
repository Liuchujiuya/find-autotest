from __future__ import annotations  # 允许在类型注解中使用当前模块尚未完全定义的类型写法。

import json  # 用于解析接口字段中可能嵌套的 JSON 字符串。
import os  # 用于读取轮询次数、轮询间隔等环境变量配置。
import time  # 用于任务状态轮询时 sleep 等待。
from copy import deepcopy  # 用于模板渲染兜底返回，避免修改原始测试数据。
from typing import Any  # 用于标注接口响应这类结构不固定的数据。


class FindTaskApi:
    """封装 Excel bases 页定义的找号任务公共接口能力。"""

    def __init__(self, request_client, collect_api_keys: dict[str, str] | None = None):
        self.client = request_client  # 保存统一请求客户端，复用鉴权头、日志和 Allure 附件逻辑。
        self.collect_api_keys = collect_api_keys or {}  # 保存小红书/抖音采集接口 API key，用于 Authorization: key=xxx。

    def build_task(self, payload: dict[str, Any]) -> dict[str, Any]:
        """创建智能插件任务。"""
        return self._post_json("/api/smartPluginTask/build", payload)  # 发送创建任务请求并返回校验后的响应。

    def build_collect_task(self, payload: dict[str, Any], platform: str) -> dict[str, Any]:
        """创建小红书/抖音采集任务。"""
        headers = self._collect_auth_headers(platform)  # 采集接口使用 Authorization: key=xxx 鉴权。
        return self._post_json("/api/collectTask/buildCollectTask", payload, headers=headers)  # 发送采集任务创建请求。

    def get_collect_task_status(
        self,
        fd_no: str,
        platform: str,
        attempts: int | None = None,
        interval_seconds: int | None = None,
    ) -> dict[str, Any]:
        """轮询采集任务状态，直到 fdStatus=10 并返回任务记录。"""
        attempts = attempts or int(os.getenv("FINDAI_COLLECT_STATUS_ATTEMPTS", os.getenv("FINDAI_TASK_STATUS_ATTEMPTS", "3")))
        interval_seconds = interval_seconds or int(os.getenv("FINDAI_COLLECT_POLL_INTERVAL", os.getenv("FINDAI_TASK_POLL_INTERVAL", "300")))
        headers = self._collect_auth_headers(platform)  # 采集状态接口沿用 API key 请求头。
        last_payload: dict[str, Any] | None = None  # 保存最后一次响应，失败时便于排查。
        for index in range(attempts):
            payload = {
                "fdTaskNo": fd_no,
                "limit": 10,
                "pageIndex": 1,
                "sortName": "createdDate",
                "sortOrder": "asc",
            }
            data = self._post_json("/api/collectTask/list", payload, headers=headers)  # 查询采集任务列表。
            last_payload = data  # 保存响应。
            task = self._find_record(data, lambda item: item.get("fdTaskNo") == fd_no or item.get("fdNo") == fd_no)  # 兼容 fdTaskNo/fdNo。
            if task and task.get("fdStatus") == 10:
                if not task.get("id"):
                    raise AssertionError(f"Collect task status success but id is empty: {task}")  # 完成状态必须能拿到详情 id。
                return task  # fdStatus=10 代表采集结束。
            if index < attempts - 1:
                time.sleep(interval_seconds)  # 未完成时等待下一次轮询。
        raise AssertionError(f"Collect task did not reach fdStatus=10 after {attempts} attempts: {last_payload}")  # 超时失败。

    def get_collect_task_info(self, task_id: str | int, platform: str) -> list[dict[str, Any]]:
        """查询采集任务详情数据。"""
        headers = self._collect_auth_headers(platform)  # 采集详情接口沿用 API key 请求头。
        response = self.client.get(f"/api/collectTask/detail?id={task_id}", headers=headers)  # GET 查询采集详情。
        response.raise_for_status()  # HTTP 非 2xx 直接失败。
        data = response.json()  # 解析 JSON 响应。
        self.assert_api_success(data)  # 校验业务 code/message。
        records = self._extract_records(data)  # 递归提取详情中的列表数据。
        if records:
            return records  # 找到列表时返回所有记录。
        data_node = data.get("data") if isinstance(data, dict) else None  # 有些详情接口 data 本身是对象。
        return [data_node] if isinstance(data_node, dict) else []  # data 是对象时按单条记录处理。

    def _collect_auth_headers(self, platform: str) -> dict[str, str]:
        """生成采集接口 Authorization 请求头。"""
        key = self.collect_api_keys.get(platform, "")  # 优先按 xhs/dy 读取 key。
        if not key and platform == "xhs":
            key = self.collect_api_keys.get("xiaohongshu", "")  # 兼容配置长平台名。
        if not key and platform == "dy":
            key = self.collect_api_keys.get("douyin", "")  # 兼容配置长平台名。
        if not key:
            raise AssertionError(f"Collect api key is empty for platform: {platform}")  # key 缺失时提前失败。
        return {"Authorization": f"key={key}"}  # 按接口要求传 Authorization: key=xxx。

    def get_task_list(self, fd_name: str, fd_type: int | None = None) -> dict[str, Any]:
        """按任务名称查询后台任务列表，并返回匹配的任务记录。"""
        payload = {
            "fdType": fd_type,  # 平台类型，不传时查询全部平台。
            "createdBy": None,  # 创建人筛选为空，保持与插件默认请求一致。
            "fdNo": "",  # 任务编号为空，表示不按编号过滤。
            "fdCompanyType": None,  # 公司类型不限制。
            "fdIsFastTask": None,  # 是否快速任务不限制。
            "fdIsScheduled": False,  # 默认查询非定时任务。
            "fdIsSelf": True,  # 查询当前账号自己的后台任务。
            "limit": 10,  # 每页取 10 条，足够覆盖刚创建任务的首屏查询。
            "pageIndex": 1,  # 从第一页查询。
            "sortName": "",  # 不指定排序字段，沿用服务端默认。
            "sortOrder": "",  # 不指定排序方向，沿用服务端默认。
        }
        data = self._post_json("/api/smartPluginTask/backendList", payload)  # 请求后台任务列表接口。
        task = self._find_record(data, lambda item: item.get("fdName") == fd_name)  # 在嵌套响应中查找名称完全一致的任务。
        if not task:
            raise AssertionError(f"Task not found in backendList: fdName={fd_name}")  # 未找到任务时直接让用例失败。
        if not task.get("fdNo"):
            raise AssertionError(f"Task found but fdNo is empty: {task}")  # 找到任务但编号为空说明任务数据异常。
        return task  # 返回包含 fdNo 等信息的任务记录。

    def get_task_status(
        self,
        fd_no: str,
        attempts: int | None = None,
        interval_seconds: int | None = None,
    ) -> dict[str, Any]:
        """轮询任务状态，直到任务完成并返回任务记录。"""
        attempts = attempts or int(os.getenv("FINDAI_TASK_STATUS_ATTEMPTS", "3"))  # 默认最多轮询 3 次，可用环境变量覆盖。
        interval_seconds = interval_seconds or int(os.getenv("FINDAI_TASK_POLL_INTERVAL", "300"))  # 默认每 300 秒轮询一次。
        last_payload: dict[str, Any] | None = None  # 保存最后一次响应，失败时输出给断言信息。

        for index in range(attempts):
            payload = {
                "fdType": None,  # 状态查询不限制平台类型。
                "createdBy": None,  # 不按创建人过滤。
                "fdNo": fd_no,  # 使用任务编号精确查询目标任务。
                "fdCompanyType": None,  # 公司类型不限制。
                "fdIsFastTask": None,  # 快速任务标识不限制。
                "fdIsScheduled": False,  # 查询非定时任务。
                "fdIsSelf": False,  # 与插件列表接口保持一致的自有任务筛选值。
                "limit": 10,  # 返回数量保持小范围，避免响应过大。
                "pageIndex": 1,  # 从第一页查询。
                "sortOrder": None,  # 不指定排序方向。
            }
            data = self._post_json("/api/smartPluginTask/list", payload)  # 请求任务状态列表接口。
            last_payload = data  # 记录本次响应，便于最终超时时诊断。
            task = self._find_record(data, lambda item: item.get("fdNo") == fd_no)  # 从响应中查找当前任务编号。
            if task and task.get("fdStatus") == 10:
                if not task.get("id"):
                    raise AssertionError(f"Task status success but id is empty: {task}")  # 完成状态下必须有任务 id 才能查明细。
                return task  # fdStatus=10 代表任务完成，返回任务记录。
            if index < attempts - 1:
                time.sleep(interval_seconds)  # 未完成且还有重试机会时等待下一轮。

        raise AssertionError(f"Task did not reach fdStatus=10 after {attempts} attempts: {last_payload}")  # 超过最大次数仍未完成则失败。

    def get_task_info_pgy(self, task_id: str | int, fd_no: str) -> list[dict[str, Any]]:
        """Query full paged Pugongying task user details."""
        payload = {
            "fdQueryType": 1,
            "enable": 1,
            "fdNo": fd_no,
            "fdSmartPluginTaskId": task_id,
            "limit": int(os.getenv("FINDAI_TASK_INFO_PAGE_SIZE", "100")),
            "pageIndex": 1,
            "sortName": "",
            "sortOrder": "",
            "isMatch": None,
        }
        return self._get_all_task_info_pages("/api/smartPluginTaskUser/list", payload)

    def wait_task_info_pgy(
        self,
        task_id: str | int,
        fd_no: str,
        attempts: int | None = None,
        interval_seconds: int | None = None,
        expected_count: int | None = None,
    ) -> list[dict[str, Any]]:
        """After fdStatus=10, wait until Pugongying detail rows are queryable and stable."""
        attempts = attempts or int(os.getenv("FINDAI_TASK_INFO_ATTEMPTS", "24"))
        interval_seconds = interval_seconds or int(os.getenv("FINDAI_TASK_INFO_INTERVAL", "5"))
        return self._wait_task_info_stable(self.get_task_info_pgy, task_id, fd_no, attempts, interval_seconds, expected_count)

    def get_task_info_xt(self, task_id: str | int, fd_no: str) -> list[dict[str, Any]]:
        """Query full paged Xingtu task user details."""
        payload = {
            "fdQueryType": 1,
            "enable": 1,
            "fdNo": fd_no,
            "fdSmartPluginTaskId": task_id,
            "limit": int(os.getenv("FINDAI_TASK_INFO_PAGE_SIZE", "100")),
            "pageIndex": 1,
            "sortName": "",
            "sortOrder": "",
            "fdName": "",
            "fdUid": "",
            "isMatch": None,
        }
        return self._get_all_task_info_pages("/api/smartPluginTaskUser/xtList", payload)

    def wait_task_info_xt(
        self,
        task_id: str | int,
        fd_no: str,
        attempts: int | None = None,
        interval_seconds: int | None = None,
        expected_count: int | None = None,
    ) -> list[dict[str, Any]]:
        """After fdStatus=10, wait until Xingtu detail rows are queryable and stable."""
        attempts = attempts or int(os.getenv("FINDAI_TASK_INFO_ATTEMPTS", "24"))
        interval_seconds = interval_seconds or int(os.getenv("FINDAI_TASK_INFO_INTERVAL", "5"))
        return self._wait_task_info_stable(self.get_task_info_xt, task_id, fd_no, attempts, interval_seconds, expected_count)

    def _get_all_task_info_pages(self, endpoint: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
        """Read all task detail pages so assertions use complete result data."""
        first_data = self._post_json(endpoint, payload)
        records = self._extract_records(first_data)
        page_count = self._extract_page_count(first_data)
        for page_index in range(2, page_count + 1):
            page_payload = dict(payload, pageIndex=page_index)
            records.extend(self._extract_records(self._post_json(endpoint, page_payload)))
        return records

    def _wait_task_info_stable(self, getter, task_id: str | int, fd_no: str, attempts: int, interval_seconds: int, expected_count: int | None = None) -> list[dict[str, Any]]:
        """Wait for stable task details after task status is completed."""
        stable_rounds = int(os.getenv("FINDAI_TASK_INFO_STABLE_ROUNDS", "2"))
        expected_count = int(expected_count) if expected_count else None
        last_items: list[dict[str, Any]] = []
        last_fingerprint = ""
        stable_count = 0
        for index in range(attempts):
            last_items = getter(task_id, fd_no)
            if expected_count and len(last_items) >= expected_count:
                return last_items
            fingerprint = self._items_fingerprint(last_items)
            if last_items and fingerprint == last_fingerprint:
                stable_count += 1
            else:
                stable_count = 1 if last_items else 0
            if last_items and stable_count >= stable_rounds:
                return last_items
            last_fingerprint = fingerprint
            if index < attempts - 1:
                time.sleep(interval_seconds)
        raise AssertionError(f"No stable task user data returned after {attempts} attempts: task_id={task_id}, fdNo={fd_no}, last_items={last_items}")

    @classmethod
    def _extract_page_count(cls, payload: Any) -> int:
        """Extract pageCount from nested API response."""
        if isinstance(payload, dict):
            page_count = payload.get("pageCount")
            if isinstance(page_count, int):
                return max(1, page_count)
            data = payload.get("data")
            if data is not None:
                return cls._extract_page_count(data)
        return 1

    @staticmethod
    def _items_fingerprint(items: list[dict[str, Any]]) -> str:
        """Create a stable fingerprint for task detail rows."""
        return json.dumps(
            [
                {
                    "fdCode": item.get("fdCode"),
                    "fdUid": item.get("fdUid"),
                    "fdFeatureTags": item.get("fdFeatureTags"),
                    "fdLabels": item.get("fdLabels"),
                }
                for item in items
            ],
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
    def _post_json(self, endpoint: str, payload: dict[str, Any], headers: dict[str, str] | None = None) -> dict[str, Any]:
        """发送 POST JSON 请求，并校验 HTTP 与业务状态。"""
        response = self.client.post(endpoint, json=payload, headers=headers)  # 使用统一客户端发送请求并自动写 Allure 附件。
        response.raise_for_status()  # HTTP 非 2xx 时抛出异常。
        data = response.json()  # 将响应体解析为 JSON 字典。
        self.assert_api_success(data)  # 校验业务 code/message 是否成功。
        return data  # 返回通过校验的业务响应。

    @staticmethod
    def assert_api_success(data: dict[str, Any]) -> None:
        """校验接口响应业务状态是否成功。"""
        code = data.get("code")  # 读取业务状态码。
        message = data.get("message")  # 读取业务提示信息。
        if code not in (None, 1):
            raise AssertionError(f"API code is not success: code={code}, message={message}, data={data}")  # code 非 1 视为业务失败。
        if message and str(message).lower() not in ("success", "ok"):
            raise AssertionError(f"API message is not success: message={message}, data={data}")  # message 明确非成功时视为失败。

    @classmethod
    def _extract_records(cls, payload: Any) -> list[dict[str, Any]]:
        """递归提取响应中的记录列表，兼容 records/list/rows/items/data 等结构。"""
        if isinstance(payload, dict):
            for key in ("records", "list", "rows", "items"):
                value = payload.get(key)  # 尝试读取常见列表字段。
                if isinstance(value, list):
                    return [item for item in value if isinstance(item, dict)]  # 只保留字典记录，过滤异常元素。
            data = payload.get("data")  # 继续向 data 节点递归查找。
            if data is not None:
                return cls._extract_records(data)  # data 可能还是 dict 或 list，交给自身处理。
            for value in payload.values():
                records = cls._extract_records(value)  # 兜底扫描所有子节点。
                if records:
                    return records  # 找到第一组非空记录即返回。
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]  # 顶层就是列表时直接过滤返回。
        return []  # 其它类型没有可提取记录，返回空列表。

    @classmethod
    def _find_record(cls, payload: Any, predicate) -> dict[str, Any] | None:
        """在提取出的记录列表中查找第一个满足条件的记录。"""
        for record in cls._extract_records(payload):  # 遍历兼容提取后的所有记录。
            if predicate(record):
                return record  # 命中条件后立即返回。
        return None  # 未命中时返回 None，交给调用方决定断言策略。


def render_template(value: Any, variables: dict[str, Any]) -> Any:
    """递归替换 YAML 请求模板里的 ${name} 占位符。"""
    if isinstance(value, dict):
        return {key: render_template(val, variables) for key, val in value.items()}  # 字典中每个值都递归渲染。
    if isinstance(value, list):
        return [render_template(item, variables) for item in value]  # 列表中每个元素都递归渲染。
    if isinstance(value, str):
        if value.startswith("${") and value.endswith("}"):
            return variables.get(value[2:-1], value)  # 纯占位符保留原始变量类型，例如 int/bool/dict。
        rendered = value  # 非纯占位符字符串按文本替换处理。
        for key, replacement in variables.items():
            rendered = rendered.replace("${" + key + "}", str(replacement))  # 替换字符串中出现的每个变量。
        return rendered  # 返回渲染后的字符串。
    return deepcopy(value)  # 其它类型直接深拷贝，避免调用方修改原始 YAML 数据。


def normalize_field_value(value: Any) -> str:
    """把接口字段统一转换成便于 contains/not_contains 断言的字符串。"""
    if value is None:
        return ""  # None 统一视为空字符串。
    if isinstance(value, str):
        try:
            parsed = json.loads(value)  # 尝试解析 JSON 字符串，兼容字段中存数组/对象的情况。
        except (TypeError, ValueError):
            return value  # 普通字符串直接返回。
        return normalize_field_value(parsed)  # JSON 字符串解析成功后继续归一化。
    if isinstance(value, (list, tuple, set)):
        return " ".join(normalize_field_value(item) for item in value)  # 多值字段拼成一个可搜索文本。
    if isinstance(value, dict):
        return " ".join(f"{key} {normalize_field_value(val)}" for key, val in value.items())  # 对象字段保留 key 和 value。
    return str(value)  # 数字、布尔等其它类型转成字符串。


def top_distribution_text(value: Any, top: int = 3) -> str:
    """提取分布字段前 N 名名称并拼成字符串，便于断言包含关系。"""
    return " ".join(parse_distribution_top_names(value, top=top))  # 复用解析函数，输出给 contains 断言。


def parse_distribution_top_names(value: Any, top: int = 3) -> list[str]:
    """解析“广东：8.8%，山东：8.7%”这类分布字段并返回前 N 名名称。"""
    if value is None:
        return []  # 空值没有排名数据。
    if isinstance(value, str):
        text = value.strip()  # 去掉首尾空格，避免空白影响判断。
        if not text or text == "--":
            return []  # 空字符串和占位符都视为无数据。
        try:
            value = json.loads(text)  # 有些接口可能把分布字段作为 JSON 字符串返回。
        except (TypeError, ValueError):
            parts = [part.strip() for part in text.replace("\uff0c", ",").split(",") if part.strip()]  # 同时兼容中文逗号和英文逗号。
            names = []  # 保存按原始顺序解析出的排名名称。
            for part in parts:
                name = part.split("\uff1a", 1)[0].split(":", 1)[0].strip()  # 冒号前面的内容就是省份/城市/设备名称。
                if name:
                    names.append(name)  # 忽略空名称，保留有效排名项。
            return names[:top]  # 返回前 N 名用于“是否排名前 3”断言。
    if isinstance(value, list):
        names = []  # 保存列表结构中的前 N 名名称。
        for item in value[:top]:
            if isinstance(item, dict):
                name = item.get("name") or item.get("label") or item.get("key") or item.get("title")  # 兼容常见名称字段。
                names.append(str(name) if name else normalize_field_value(item))  # 没有名称字段时把整个对象转文本。
            else:
                names.append(normalize_field_value(item).split("\uff1a", 1)[0].split(":", 1)[0].strip())  # 普通元素按“名称:占比”格式解析。
        return [name for name in names if name]  # 过滤空名称后返回。
    return [normalize_field_value(value)]  # 其它类型兜底转成单个名称。
