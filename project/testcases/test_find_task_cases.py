from __future__ import annotations

import os
import re
import traceback
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

import allure
import pytest
import yaml

from bases.find_task_api import FindTaskApi, normalize_field_value, parse_distribution_top_names, render_template
from tools.allure_helper import attach_json, set_title
from tools.platform_selection import platform_display_text, selected_platforms_from_env
from tools.request_client import RequestClient


ALL_CASES = []
SELECTED_PLATFORMS = selected_platforms_from_env()
PLATFORM_PARALLEL_ENABLED = os.getenv("FINDAI_PLATFORM_PARALLEL", "0").strip() == "1"


def load_cases() -> list[dict[str, Any]]:
    data_path = Path("testdata/find_task_cases.yaml")
    data = yaml.safe_load(data_path.read_text(encoding="utf-8")) or {}
    cases = data.get("cases", [])
    return [case_data for case_data in cases if case_data.get("platform") in SELECTED_PLATFORMS]


ALL_CASES = load_cases()


def case_id(case_data: dict[str, Any]) -> str:
    return case_data["id"]


@pytest.fixture(scope="session")
def case_state() -> dict[str, Any]:
    return {"variables": {}, "results": {}}


if PLATFORM_PARALLEL_ENABLED:

    def test_find_task_cases_by_platform_parallel(browser_runtime, findai_runtime_context):
        set_title(f"findai 用例按平台并行执行：{platform_display_text(SELECTED_PLATFORMS)}")
        logged_in_platforms = set(browser_runtime.get("logged_in_platforms", SELECTED_PLATFORMS))
        runnable_cases = [case_data for case_data in ALL_CASES if case_data.get("platform") in logged_in_platforms]
        skipped_cases = [case_data for case_data in ALL_CASES if case_data.get("platform") not in logged_in_platforms]
        grouped_cases = group_cases_by_platform(runnable_cases)
        attach_json(
            "platform parallel plan",
            {
                "selected_platforms": SELECTED_PLATFORMS,
                "selected_platforms_text": platform_display_text(SELECTED_PLATFORMS),
                "logged_in_platforms": sorted(logged_in_platforms),
                "platform_login_status": browser_runtime.get("platform_login_status", {}),
                "skipped_cases_by_login_gate": [
                    {"id": case_data["id"], "title": case_data["title"], "platform": case_data["platform"]}
                    for case_data in skipped_cases
                ],
                "cases_by_platform": {
                    platform: [case_data["id"] for case_data in cases]
                    for platform, cases in grouped_cases.items()
                },
            },
        )
        if not grouped_cases:
            pytest.skip("No selected platform is logged in. Scan-login platform cases were skipped by login gate.")

        errors = {}
        configured_workers = int(os.getenv("FINDAI_PLATFORM_WORKERS", str(len(grouped_cases) or 1)))
        max_workers = min(configured_workers, len(grouped_cases)) or 1
        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="findai-platform") as executor:
            futures = {
                executor.submit(run_platform_cases, platform, cases, browser_runtime, findai_runtime_context): platform
                for platform, cases in grouped_cases.items()
            }
            for future in as_completed(futures):
                platform = futures[future]
                try:
                    platform_errors = future.result()
                    if platform_errors:
                        errors[platform] = platform_errors
                except BaseException:
                    errors[platform] = [{"case_id": "__platform_runner__", "traceback": traceback.format_exc()}]

        if errors:
            attach_json("platform parallel failures", errors)
            pytest.fail(format_platform_failures(errors))

else:

    @pytest.mark.parametrize("case_data", ALL_CASES, ids=case_id)
    def test_find_task_case(case_data, browser_runtime, findai_runtime_context, case_state):
        set_title(f"{case_data['id']} {case_data['title']}")
        if case_data.get("platform") not in set(browser_runtime.get("logged_in_platforms", SELECTED_PLATFORMS)):
            attach_json(
                "platform login gate skipped",
                {
                    "case_id": case_data["id"],
                    "platform": case_data.get("platform"),
                    "platform_login_status": browser_runtime.get("platform_login_status", {}),
                },
            )
            pytest.skip(f"{case_data.get('platform')} is not logged in, skip this platform case.")
        find_task_api = create_thread_find_task_api(browser_runtime)
        with allure.step(f"{case_data['id']} {case_data['title']}"):
            execute_find_task_case(case_data, find_task_api, findai_runtime_context, case_state)


def group_cases_by_platform(cases: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for case_data in cases:
        grouped.setdefault(case_data["platform"], []).append(case_data)
    return grouped


def run_platform_cases(platform: str, cases: list[dict[str, Any]], browser_runtime, findai_runtime_context):
    case_state = {"variables": {}, "results": {}}
    thread_api = create_thread_find_task_api(browser_runtime)
    errors = []
    with allure.step(f"{platform} 平台串行执行 {len(cases)} 条用例"):
        for case_data in cases:
            with allure.step(f"{case_data['id']} {case_data['title']}"):
                print(f"[{platform}] start {case_data['id']} {case_data['title']}")
                try:
                    execute_find_task_case(case_data, thread_api, findai_runtime_context, case_state)
                    print(f"[{platform}] passed {case_data['id']}")
                except BaseException as error:
                    if isinstance(error, (KeyboardInterrupt, SystemExit)):
                        raise
                    error_info = {
                        "case_id": case_data["id"],
                        "title": case_data["title"],
                        "traceback": "".join(traceback.format_exception(type(error), error, error.__traceback__)),
                    }
                    errors.append(error_info)
                    print(f"[{platform}] failed {case_data['id']}: {error}")
                    attach_json(f"{platform} {case_data['id']} failure", error_info)
                    continue
    return errors


def format_platform_failures(errors: dict[str, list[dict[str, str]]]) -> str:
    lines = []
    for platform, platform_errors in errors.items():
        failed_ids = ", ".join(error.get("case_id", "") for error in platform_errors)
        lines.append(f"[{platform}] failed cases: {failed_ids}")
        for error in platform_errors:
            lines.append(f"\n[{platform}] {error.get('case_id')} {error.get('title', '')}\n{error.get('traceback', '')}")
    return "\n".join(lines)


def create_thread_find_task_api(browser_runtime) -> FindTaskApi:
    headers = {
        "Authorization": f"Bearer{browser_runtime.get('token', '')}",
        "DeviceId": browser_runtime.get("device_id", ""),
        "Version": browser_runtime.get("version") or "1.4.3",
    }
    client = RequestClient(base_url=browser_runtime.get("base_url", ""), headers=headers, timeout=30)
    return FindTaskApi(
        client,
        collect_api_keys=browser_runtime.get("collect_api_keys", {}),
        abort_checker=browser_runtime.get("browser_closed_event").is_set,
    )


def task_info_endpoint(platform: str) -> str:
    return "/api/smartPluginTaskUser/xtList" if platform == "xt" else "/api/smartPluginTaskUser/list"


def summarize_build_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "接口": "/api/smartPluginTask/build",
        "任务名称": payload.get("fdName"),
        "平台类型fdType": payload.get("fdType"),
        "平台账号ID fdOriginalThirdId": payload.get("fdOriginalThirdId"),
        "浏览器设备ID fdOriginalDeviceId": payload.get("fdOriginalDeviceId"),
        "开发数量 fdDevelopmentNum": payload.get("fdDevelopmentNum"),
        "是否打开页面 fdIsOpenPage": payload.get("fdIsOpenPage"),
        "基础筛选展示": payload.get("fdGeneralThirdFilter"),
        "增强筛选展示": payload.get("fdEnhancedThirdFilter"),
    }


def summarize_api_response(response: dict[str, Any]) -> dict[str, Any]:
    return {
        "业务状态码code": response.get("code"),
        "业务消息message": response.get("message"),
        "响应data摘要": summarize_any(response.get("data")),
    }


def summarize_task(task: dict[str, Any]) -> dict[str, Any]:
    return {
        "任务ID": task.get("id"),
        "任务编号fdNo": task.get("fdNo"),
        "任务名称fdName": task.get("fdName"),
        "平台类型fdType": task.get("fdType"),
        "任务状态fdStatus": task.get("fdStatus"),
        "任务状态文本fdStatusStr": task.get("fdStatusStr"),
        "任务总数fdTaskSum": task.get("fdTaskSum"),
        "完成数量fdFinishCount": task.get("fdFinishCount"),
        "创建时间": task.get("createdTime") or task.get("fdCreateTime"),
    }


def summarize_saved_results(results: dict[str, Any]) -> dict[str, Any]:
    return {
        case_id: {
            "任务名称": result.get("task_name"),
            "任务编号": result.get("task_status", {}).get("fdNo"),
            "明细数量": len(result.get("items", [])),
        }
        for case_id, result in results.items()
    }


def summarize_variables(variables: dict[str, Any]) -> dict[str, Any]:
    return {name: summarize_any(value) for name, value in variables.items()}


def summarize_any(value: Any, limit: int = 10) -> Any:
    if isinstance(value, list):
        return {"数量": len(value), "预览": value[:limit]}
    if isinstance(value, dict):
        keys = list(value.keys())
        return {"字段数量": len(keys), "预览": {key: value[key] for key in keys[:limit]}}
    return value


def summarize_items(items: list[dict[str, Any]], limit: int = 5) -> list[dict[str, Any]]:
    preview = []
    for item in items[:limit]:
        preview.append(
            {
                "达人名称": item.get("fdName"),
                "蒲公英ID fdCode": item.get("fdCode"),
                "星图ID fdUid": item.get("fdUid"),
                "标签 fdLabels": item.get("fdLabels"),
                "内容标签 fdContentTags": item.get("fdContentTags"),
                "特征标签 fdFeatureTags": item.get("fdFeatureTags"),
                "机构名称 fdMcnName": item.get("fdMcnName"),
                "行业 fdTopTradeType": item.get("fdTopTradeType"),
                "30天日常笔记数 fdPgyNoteNumber": item.get("fdPgyNoteNumber"),
                "90天日常笔记数 fdPgyNinetyNoteNumber": item.get("fdPgyNinetyNoteNumber"),
            }
        )
    return preview


def execute_find_task_case(case_data, find_task_api, findai_runtime_context, case_state):
    if case_data["request"].get("endpoint") == "/api/collectTask/buildCollectTask":
        execute_collect_task_case(case_data, find_task_api, case_state)
        return

    with allure.step("步骤1：准备前置变量"):
        prepare_case_variables(case_data, case_state)
        attach_json(
            "步骤1-前置变量与依赖结果摘要",
            {
                "用例ID": case_data["id"],
                "用例标题": case_data["title"],
                "平台": case_data["platform"],
                "前置规则": case_data.get("prepare_variables", []),
                "当前变量": summarize_variables(case_state["variables"]),
                "已保存依赖结果": summarize_saved_results(case_state["results"]),
            },
        )

    task_name = f"{case_data['id']}_{datetime.now():%Y-%m-%d %H:%M:%S}"
    with allure.step("步骤2：调用创建任务接口 /api/smartPluginTask/build"):
        payload = render_template(case_data["request"]["json"], {"fdName": task_name, **case_state["variables"]})
        apply_runtime_context(payload, case_data["platform"], findai_runtime_context)
        assert_no_unresolved_variables(payload)
        attach_json("步骤2-创建任务请求关键数据", summarize_build_payload(payload))
        attach_json("步骤2-创建任务完整请求体", payload)
        build_result = find_task_api.build_task(payload)
        attach_json("步骤2-创建任务响应关键数据", summarize_api_response(build_result))
        if case_data.get("assertions", {}).get("build_success", True):
            assert build_result.get("code") in (None, 1)

    with allure.step("步骤3：调用任务列表接口 /api/smartPluginTask/backendList 查询任务编号"):
        task = find_task_api.get_task_list(task_name, fd_type=payload.get("fdType"))
        attach_json("步骤3-任务列表匹配结果", summarize_task(task))

    with allure.step("步骤4：调用任务状态接口 /api/smartPluginTask/list 等待任务完成"):
        task_status = find_task_api.get_task_status(task["fdNo"])
        expected_detail_count = task_status.get("fdFinishCount") or task_status.get("fdTaskSum")
        attach_json(
            "步骤4-任务状态断言数据",
            {
                "断言逻辑": "fdStatus 必须等于 10 后，才允许查询任务明细",
                "任务ID": task_status.get("id"),
                "任务编号": task_status.get("fdNo"),
                "任务状态": task_status.get("fdStatus"),
                "任务状态文本": task_status.get("fdStatusStr"),
                "完成数量": task_status.get("fdFinishCount"),
                "任务总数": task_status.get("fdTaskSum"),
                "预期明细数量": expected_detail_count,
            },
        )

    with allure.step(f"步骤5：调用任务明细接口 {task_info_endpoint(case_data['platform'])} 获取达人结果"):
        if case_data["platform"] == "xt":
            items = find_task_api.wait_task_info_xt(task_status["id"], task_status["fdNo"], expected_count=expected_detail_count)
        else:
            items = find_task_api.wait_task_info_pgy(task_status["id"], task_status["fdNo"], expected_count=expected_detail_count)
        attach_json(
            "步骤5-任务明细关键数据",
            {
                "接口": task_info_endpoint(case_data["platform"]),
                "任务ID": task_status.get("id"),
                "任务编号": task_status.get("fdNo"),
                "实际明细数量": len(items),
                "预期明细数量": expected_detail_count,
                "明细预览": summarize_items(items),
            },
        )

    with allure.step("步骤6：保存当前用例结果，供后续依赖用例使用"):
        save_case_result(case_data, case_state, task_name, task, task_status, items)

    with allure.step("步骤7：执行结果断言"):
        attach_json("步骤7-断言配置", case_data.get("assertions", {}))
        assert_case_result(case_data, items, case_state)


def execute_collect_task_case(case_data, find_task_api, case_state):
    """执行小红书/抖音采集任务用例。"""
    with allure.step("步骤1：准备采集任务请求数据"):
        payload = render_template(case_data["request"]["json"], case_state["variables"])
        assert_no_unresolved_variables(payload)
        attach_json(
            "步骤1-采集任务请求关键数据",
            {
                "用例ID": case_data["id"],
                "用例标题": case_data["title"],
                "平台": case_data["platform"],
                "接口": "/api/collectTask/buildCollectTask",
                "采集类型fdType": payload.get("fdType"),
                "采集平台fdPlatform": payload.get("fdPlatform"),
                "采集参数fdParams": payload.get("fdParams"),
            },
        )
        attach_json("步骤1-采集任务完整请求体", payload)

    with allure.step("步骤2：调用采集任务创建接口 /api/collectTask/buildCollectTask"):
        build_result = find_task_api.build_collect_task(payload, case_data["platform"])
        collect_meta = extract_collect_task_meta(build_result)
        attach_json(
            "步骤2-采集任务创建响应关键数据",
            {
                "业务状态码code": build_result.get("code"),
                "业务消息message": build_result.get("message"),
                "采集任务ID": collect_meta.get("id"),
                "采集任务编号": collect_meta.get("fdNo"),
                "响应摘要": summarize_api_response(build_result),
            },
        )
        if case_data.get("assertions", {}).get("build_success", True):
            assert build_result.get("code") in (None, 1)
        if not collect_meta.get("fdNo") or not collect_meta.get("id"):
            raise AssertionError(f"Collect build response missing fdNo/id: {build_result}")

    with allure.step("步骤3：调用采集任务状态接口 /api/collectTask/list 等待任务完成"):
        task_status = find_task_api.get_collect_task_status(collect_meta["fdNo"], case_data["platform"])
        attach_json(
            "步骤3-采集任务状态断言数据",
            {
                "断言逻辑": "fdStatus 必须等于 10",
                "采集任务ID": task_status.get("id"),
                "采集任务编号": task_status.get("fdTaskNo") or task_status.get("fdNo"),
                "采集状态fdStatus": task_status.get("fdStatus"),
                "采集状态文本": task_status.get("fdStatusStr"),
                "结果数量fdResultCount": task_status.get("fdResultCount"),
                "总数量fdTotalCount": task_status.get("fdTotalCount"),
            },
        )

    items = []
    if case_data.get("assertions", {}).get("collect_detail_required") or case_data.get("assertions", {}).get("item_checks"):
        with allure.step("步骤4：调用采集任务详情接口 /api/collectTask/detail 获取采集结果"):
            items = find_task_api.get_collect_task_info(task_status.get("id") or collect_meta["id"], case_data["platform"])
            attach_json(
                "步骤4-采集任务详情关键数据",
                {
                    "采集任务ID": task_status.get("id") or collect_meta["id"],
                    "采集任务编号": task_status.get("fdTaskNo") or collect_meta["fdNo"],
                    "详情数量": len(items),
                    "详情预览": summarize_collect_items(items),
                },
            )

    with allure.step("步骤5：保存采集任务结果"):
        save_collect_case_result(case_data, case_state, collect_meta, task_status, items)

    with allure.step("步骤6：执行采集结果断言"):
        attach_json("步骤6-采集断言配置", case_data.get("assertions", {}))
        assert_collect_case_result(case_data, task_status, items, case_state)


def extract_collect_task_meta(build_result: dict[str, Any]) -> dict[str, Any]:
    """从采集任务创建响应中提取 id 和 fdNo/fdTaskNo。"""
    records = collect_dict_nodes(build_result)
    for record in records:
        fd_no = record.get("fdNo") or record.get("fdTaskNo")
        task_id = record.get("id")
        if fd_no and task_id:
            return {"id": task_id, "fdNo": fd_no}
    data = build_result.get("data") if isinstance(build_result, dict) else None
    if isinstance(data, str):
        return {"id": build_result.get("id") or data, "fdNo": build_result.get("fdNo") or build_result.get("fdTaskNo") or data}
    return {"id": build_result.get("id"), "fdNo": build_result.get("fdNo") or build_result.get("fdTaskNo")}


def collect_dict_nodes(value: Any) -> list[dict[str, Any]]:
    """递归收集响应中的所有 dict 节点，便于兼容不同响应层级。"""
    nodes = []
    if isinstance(value, dict):
        nodes.append(value)
        for item in value.values():
            nodes.extend(collect_dict_nodes(item))
    elif isinstance(value, list):
        for item in value:
            nodes.extend(collect_dict_nodes(item))
    return nodes


def save_collect_case_result(case_data, case_state, collect_meta, task_status, items):
    """保存采集任务结果，供报告和后续扩展使用。"""
    result = {"case_id": case_data["id"], "collect_meta": collect_meta, "task_status": task_status, "items": items}
    case_state["results"][case_data["id"]] = result
    attach_json(
        f"保存采集结果-{case_data['id']}",
        {
            "中文说明": "保存采集任务编号、任务状态和采集详情，供报告查看和后续用例扩展",
            "用例ID": case_data["id"],
            "采集任务ID": collect_meta.get("id"),
            "采集任务编号": collect_meta.get("fdNo"),
            "状态摘要": {
                "fdStatus": task_status.get("fdStatus"),
                "fdStatusStr": task_status.get("fdStatusStr"),
                "fdResultCount": task_status.get("fdResultCount"),
                "fdTotalCount": task_status.get("fdTotalCount"),
            },
            "详情数量": len(items),
            "详情预览": summarize_collect_items(items),
        },
    )


def assert_collect_case_result(case_data, task_status, items, case_state):
    """断言采集任务状态和详情结果。"""
    status_passed = task_status.get("fdStatus") == 10
    attach_json(
        "断言-采集任务状态完成",
        {
            "断言逻辑": "get_cjtask_status 返回 fdStatus == 10",
            "实际fdStatus": task_status.get("fdStatus"),
            "实际状态文本": task_status.get("fdStatusStr"),
            "是否通过": status_passed,
        },
    )
    assert status_passed, f"Collect task fdStatus should be 10, actual={task_status.get('fdStatus')}"
    checks = case_data.get("assertions", {}).get("item_checks", [])
    if checks:
        if not items:
            raise AssertionError("Collect detail items should not be empty")
        assert_items(items, checks, case_state)


def summarize_collect_items(items: list[dict[str, Any]], limit: int = 5) -> list[dict[str, Any]]:
    """采集任务详情预览。"""
    preview = []
    for item in items[:limit]:
        preview.append(
            {
                "小红书号fdRedId": item.get("fdRedId"),
                "抖音号fdUniqueId": item.get("fdUniqueId"),
                "博主昵称fdBloggerNickname": item.get("fdBloggerNickname") or item.get("fdNickname"),
                "笔记标题fdNoteTitle": item.get("fdNoteTitle"),
                "视频描述fdVideoDesc": item.get("fdVideoDesc"),
                "链接fdUrl": item.get("fdUrl") or item.get("fdLink"),
            }
        )
    return preview


def prepare_case_variables(case_data, case_state):
    for rule in case_data.get("prepare_variables", []):
        rule_type = rule.get("type")
        if rule_type == "value_filter":
            prepare_value_filter(rule, case_state)
        elif rule_type == "numeric_filter":
            prepare_numeric_filter(rule, case_state)
        elif rule_type == "empty_filter":
            prepare_empty_filter(rule, case_state)
        elif rule_type == "task_difference":
            prepare_task_difference(rule, case_state)
        else:
            raise AssertionError(f"Unsupported prepare variable rule: {rule}")


def prepare_value_filter(rule, case_state):
    items = source_items(rule, case_state)
    item_values = [(item, extract_values(item.get(rule["source_field"]), rule.get("extractor", "split"))) for item in items]

    for variable_rule in rule.get("value_variables", []):
        scoped = filter_items_by_variables(
            item_values,
            case_state,
            variable_rule.get("scope_include_variables", []),
            variable_rule.get("scope_exclude_variables", []),
        )
        counter = Counter(value for _, values in scoped for value in values)
        for excluded_variable in variable_rule.get("exclude_variables", []):
            counter.pop(case_state["variables"].get(excluded_variable), None)
        selected = select_ranked_value(counter, variable_rule.get("rank", 1), variable_rule.get("order", "desc"))
        case_state["variables"][variable_rule["name"]] = selected

    include_values = [case_state["variables"][name] for name in rule.get("include_variables", [])]
    exclude_values = [case_state["variables"][name] for name in rule.get("exclude_variables", [])]
    result_ids = [
        str(item.get(rule["id_field"]))
        for item, values in item_values
        if item.get(rule["id_field"]) and all(value in values for value in include_values) and not any(value in values for value in exclude_values)
    ]
    case_state["variables"][rule["result_variable"]] = result_ids
    attach_json(
        f"前置变量-标签/热词/行业筛选结果-{rule['result_variable']}",
        {
            "中文说明": "从源用例保存的达人明细中提取字段值，按包含/不包含规则生成预期达人ID列表",
            "源用例": rule.get("source_case"),
            "解析字段": rule.get("source_field"),
            "达人ID字段": rule.get("id_field"),
            "提取方式": rule.get("extractor"),
            "选中的变量": {name: case_state["variables"].get(name) for name in rule.get("include_variables", []) + rule.get("exclude_variables", [])},
            "包含变量": rule.get("include_variables", []),
            "不包含变量": rule.get("exclude_variables", []),
            "结果变量": rule["result_variable"],
            "结果数量": len(result_ids),
            "结果ID列表": result_ids,
            "原始规则": rule,
        },
    )


def prepare_numeric_filter(rule, case_state):
    items = source_items(rule, case_state)
    all_values = [(item, extract_number(item.get(rule["source_field"]))) for item in items]
    numeric_values = [(item, number) for item, number in all_values if number is not None]
    avg_values = [(item, number) for item, number in numeric_values if number != 0]
    if not avg_values:
        raise AssertionError(f"No numeric values found for {rule['source_case']}.{rule['source_field']}")

    numbers = [number for _, number in avg_values]
    avg_value = sum(numbers) / len(numbers)
    max_value = max(numbers)
    if rule.get("average_variable"):
        case_state["variables"][rule["average_variable"]] = round(avg_value, 2)
    if rule.get("max_variable"):
        case_state["variables"][rule["max_variable"]] = max_value

    relation = rule["relation"]
    result_ids = []
    for item, number in numeric_values:
        if relation == "gte_avg":
            passed = number >= avg_value
        elif relation == "lte_avg":
            passed = number <= avg_value
        elif relation == "between_avg_max":
            passed = avg_value <= number <= max_value
        else:
            raise AssertionError(f"Unsupported numeric relation: {relation}")
        if passed and item.get(rule["id_field"]):
            result_ids.append(str(item.get(rule["id_field"])))

    case_state["variables"][rule["result_variable"]] = result_ids
    attach_json(
        f"前置变量-笔记数量筛选结果-{rule['result_variable']}",
        {
            "中文说明": "计算平均值/最大值时排除0；生成预期达人ID列表时保留0，并按关系判断是否命中",
            "源用例": rule.get("source_case"),
            "解析字段": rule.get("source_field"),
            "达人ID字段": rule.get("id_field"),
            "关系": rule.get("relation"),
            "平均值变量": rule.get("average_variable"),
            "最大值变量": rule.get("max_variable"),
            "源明细数量": len(items),
            "有数值数量": len(numeric_values),
            "参与avg/max计算数量_排除0": len(avg_values),
            "字段值为0数量": sum(1 for _, number in numeric_values if number == 0),
            "计算得到avg1": avg_value,
            "计算得到max1": max_value,
            "结果变量": rule["result_variable"],
            "结果数量": len(result_ids),
            "结果ID列表": result_ids,
            "原始规则": rule,
        },
    )


def prepare_empty_filter(rule, case_state):
    result_ids = []
    for item in source_items(rule, case_state):
        matched = is_empty_value(item.get(rule["source_field"])) is bool(rule["should_be_empty"])
        if matched and item.get(rule["id_field"]):
            result_ids.append(str(item.get(rule["id_field"])))
    case_state["variables"][rule["result_variable"]] = result_ids
    attach_json(
        f"前置变量-空值筛选结果-{rule['result_variable']}",
        {
            "中文说明": "从源用例保存的达人明细中判断字段为空/不为空，生成预期达人ID列表",
            "源用例": rule.get("source_case"),
            "解析字段": rule.get("source_field"),
            "达人ID字段": rule.get("id_field"),
            "是否要求为空": rule.get("should_be_empty"),
            "结果变量": rule["result_variable"],
            "结果数量": len(result_ids),
            "结果ID列表": result_ids,
            "原始规则": rule,
        },
    )


def prepare_task_difference(rule, case_state):
    include_result = source_result(rule["source_case"], case_state)
    exclude_result = source_result(rule["exclude_case"], case_state)
    metadata = source_result(rule["metadata_case"], case_state)
    id_field = rule["id_field"]
    include_ids = {str(item.get(id_field)) for item in include_result["items"] if item.get(id_field)}
    exclude_ids = {str(item.get(id_field)) for item in exclude_result["items"] if item.get(id_field)}
    result_ids = sorted(include_ids - exclude_ids)
    case_state["variables"][rule["result_variable"]] = result_ids
    case_state["variables"][rule["fdname_variable"]] = metadata["task_name"]
    case_state["variables"][rule["id_variable"]] = metadata["task_status"]["id"]
    attach_json(
        f"前置变量-任务名单差集结果-{rule['result_variable']}",
        {
            "中文说明": "用包含任务明细ID集合减去排除任务明细ID集合，生成过滤任务名单的预期达人ID列表",
            "包含源用例": rule.get("source_case"),
            "排除源用例": rule.get("exclude_case"),
            "任务元数据来源用例": rule.get("metadata_case"),
            "包含集合数量": len(include_ids),
            "排除集合数量": len(exclude_ids),
            "结果变量": rule["result_variable"],
            "结果数量": len(result_ids),
            "结果ID列表": result_ids,
            "过滤任务名称变量值": metadata["task_name"],
            "过滤任务ID变量值": metadata["task_status"]["id"],
            "原始规则": rule,
        },
    )


def source_result(case_id: str, case_state) -> dict[str, Any]:
    result = case_state["results"].get(case_id)
    if not result:
        raise AssertionError(f"Missing source result for {case_id}; run dependent cases in Excel order.")
    return result


def source_items(rule, case_state) -> list[dict[str, Any]]:
    return source_result(rule["source_case"], case_state)["items"]


def filter_items_by_variables(item_values, case_state, include_variables, exclude_variables):
    include_values = [case_state["variables"].get(name) for name in include_variables]
    exclude_values = [case_state["variables"].get(name) for name in exclude_variables]
    return [
        (item, values)
        for item, values in item_values
        if all(value in values for value in include_values) and not any(value in values for value in exclude_values)
    ]


def select_ranked_value(counter: Counter[str], rank: int, order: str) -> str:
    if not counter:
        raise AssertionError("No values available for ranking")
    reverse = order != "asc"
    ranked = sorted(counter.items(), key=lambda item: (item[1], item[0]), reverse=reverse)
    index = min(max(int(rank), 1), len(ranked)) - 1
    return ranked[index][0]


def extract_values(value, extractor: str) -> list[str]:
    if extractor == "distribution_top3":
        return parse_distribution_top_names(value, top=3)
    if extractor == "hotkey":
        return split_hotkeys(value)
    if extractor == "labels":
        return split_labels(value)
    return split_multi_value(value)


def split_multi_value(value) -> list[str]:
    text = normalize_field_value(value).strip()
    if is_empty_value(text):
        return []
    separators = "".join(chr(code) for code in (0x3001, 0x002C, 0xFF0C, 0x003B, 0xFF1B))
    return [part.strip() for part in re.split(f"[{re.escape(separators)}]+", text) if part.strip() and part.strip() != "--"]


def split_labels(value) -> list[str]:
    text = normalize_field_value(value).strip()
    if is_empty_value(text):
        return []
    labels: list[str] = []
    for bracket_content in re.findall(r"\[([^\]]+)]", text):
        labels.extend(split_multi_value(bracket_content))
    return labels or split_multi_value(text)


def split_hotkeys(value) -> list[str]:
    text = normalize_field_value(value).strip()
    if is_empty_value(text):
        return []
    names = []
    for part in split_multi_value(text):
        name = part.split(":", 1)[0].split("：", 1)[0].strip()
        if name:
            names.append(name)
    return names


def extract_number(value) -> float | None:
    text = normalize_field_value(value).replace(",", "")
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    return float(match.group(0)) if match else None


def is_empty_value(value) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip().lower() in {"", "--", "null", "none"}
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) == 0
    return False


def save_case_result(case_data, case_state, task_name, task, task_status, items):
    result = {"case_id": case_data["id"], "task_name": task_name, "task": task, "task_status": task_status, "items": items}
    case_state["results"][case_data["id"]] = result
    attach_json(
        f"保存结果-{case_data['id']}",
        {
            "中文说明": "保存当前用例的任务名称、任务编号、任务状态和达人明细，供后续依赖用例提取变量",
            "用例ID": case_data["id"],
            "任务名称": task_name,
            "任务摘要": summarize_task(task),
            "任务状态摘要": summarize_task(task_status),
            "明细数量": len(items),
            "明细预览": summarize_items(items),
        },
    )


def assert_case_result(case_data, items, case_state):
    assertions = case_data.get("assertions", {})
    numeric_rules = [rule for rule in case_data.get("prepare_variables", []) if rule.get("type") == "numeric_filter"]

    expected_list_name = assertions.get("item_count_equals_variable_length")
    if expected_list_name:
        expected_values = [str(value) for value in case_state["variables"].get(expected_list_name, [])]
        passed = len(items) == len(expected_values)
        attach_json(
            "断言-达人数量等于前置变量列表长度",
            {
                "断言逻辑": f"实际返回达人数量 == {expected_list_name} 列表 length",
                "预期变量": expected_list_name,
                "预期数量": len(expected_values),
                "实际数量": len(items),
                "预期ID列表": expected_values,
                "实际ID预览": [item.get("fdCode") or item.get("fdUid") for item in items[:20]],
                "是否通过": passed,
            },
        )
        assert passed, f"Expected {len(expected_values)} items from {expected_list_name}, actual={len(items)}"
    elif not items:
        raise AssertionError("Task detail items should not be empty")
    else:
        attach_json(
            "断言-达人明细非空",
            {
                "断言逻辑": "没有配置数量变量时，至少要求 get_task_info 返回达人明细不为空",
                "实际数量": len(items),
                "明细预览": summarize_items(items),
            },
        )

    assert_items(items, assertions.get("item_checks", []), case_state)
    if numeric_rules:
        assert_numeric_rules(items, numeric_rules, case_state)


def assert_numeric_rules(items, numeric_rules, case_state):
    for rule in numeric_rules:
        field = rule["source_field"]
        relation = rule["relation"]
        avg_value = case_state["variables"].get(rule.get("average_variable"))
        max_value = case_state["variables"].get(rule.get("max_variable"))
        for index, item in enumerate(items, start=1):
            actual_number = extract_number(item.get(field))
            if actual_number is None:
                record_assertion(index, item, field, relation, {"avg": avg_value, "max": max_value}, item.get(field), False)
                raise AssertionError(f"{field} should be numeric, actual={item.get(field)}")
            if relation == "gte_avg":
                passed = actual_number >= float(avg_value)
                expected = f">= {avg_value}"
            elif relation == "lte_avg":
                passed = actual_number <= float(avg_value)
                expected = f"<= {avg_value}"
            elif relation == "between_avg_max":
                passed = float(avg_value) <= actual_number <= float(max_value)
                expected = f">= {avg_value} and <= {max_value}"
            else:
                raise AssertionError(f"Unsupported numeric relation: {relation}")
            record_assertion(index, item, field, relation, expected, actual_number, passed)
            assert passed, f"{field} should be {expected}, actual={actual_number}"


def assert_items(items, checks, case_state):
    attach_json("断言前-达人明细预览", {"明细数量": len(items), "明细预览": summarize_items(items, limit=10)})
    for check in checks:
        field = check["field"]
        for index, item in enumerate(items, start=1):
            actual_text = normalize_field_value(item.get(field))
            for keyword in check.get("contains", []):
                passed = keyword in actual_text
                record_assertion(index, item, field, "contains", keyword, actual_text, passed)
                assert passed, f"{field} should contain {keyword}, actual={actual_text}"
            if "contains_any" in check:
                expected = check["contains_any"]
                passed = any(keyword in actual_text for keyword in expected)
                record_assertion(index, item, field, "contains_any", expected, actual_text, passed)
                assert passed, f"{field} should contain any of {expected}, actual={actual_text}"
            if "equals" in check:
                expected = str(check["equals"])
                actual_value = str(item.get(field))
                passed = actual_value == expected
                record_assertion(index, item, field, "equals", expected, actual_value, passed)
                assert passed, f"{field} should equal {expected}, actual={actual_value}"
            if "in_values" in check:
                expected_values = [str(value) for value in check["in_values"]]
                actual_value = str(item.get(field))
                passed = actual_value in expected_values
                record_assertion(index, item, field, "in_values", expected_values, actual_value, passed)
                assert passed, f"{field}={actual_value} should be in {expected_values}"
            if "in_variable" in check:
                variable_name = check["in_variable"]
                expected_values = [str(value) for value in case_state["variables"].get(variable_name, [])]
                actual_value = str(item.get(field))
                passed = actual_value in expected_values
                record_assertion(index, item, field, f"in_variable:{variable_name}", expected_values, actual_value, passed)
                assert passed, f"{field}={actual_value} should be in {variable_name}: {expected_values}"


def record_assertion(item_index, item, field, assertion_type, expected, actual, passed):
    item_name = item.get("fdName") or item.get("fdCode") or item.get("fdUid") or item.get("id") or f"item_{item_index}"
    status = "通过" if passed else "失败"
    with allure.step(f"断言{status}：第{item_index}个达人 {field} {assertion_type}"):
        attach_json(
            f"断言详情-第{item_index}个达人-{field}-{assertion_type}",
            {
                "断言状态": status,
                "达人序号": item_index,
                "达人名称或ID": item_name,
                "断言字段": field,
                "断言类型": assertion_type,
                "预期值": expected,
                "实际值": actual,
                "是否通过": passed,
                "达人完整数据": item,
            },
        )


def assert_no_unresolved_variables(value):
    unresolved: list[str] = []
    collect_unresolved_variables(value, unresolved)
    assert not unresolved, f"Unresolved variables in request payload: {sorted(set(unresolved))}"


def collect_unresolved_variables(value, unresolved):
    if isinstance(value, dict):
        for item in value.values():
            collect_unresolved_variables(item, unresolved)
    elif isinstance(value, list):
        for item in value:
            collect_unresolved_variables(item, unresolved)
    elif isinstance(value, str):
        unresolved.extend(re.findall(r"\$\{[^}]+}", value))


def apply_runtime_context(payload, platform, runtime_context):
    platform_context = runtime_context.get("platforms", {}).get(platform, {})
    third_id = platform_context.get("third_id", "") if isinstance(platform_context, dict) else ""
    device_id = runtime_context.get("device_id", "")
    if not third_id:
        pytest.skip(f"{platform} third_id is empty. Run python scripts/login_init.py first.")
    if not device_id:
        pytest.skip("browser device_id is empty. Run python scripts/login_init.py first.")
    payload["fdOriginalThirdId"] = third_id
    payload["fdOriginalDeviceId"] = device_id
