from __future__ import annotations

import os


PLATFORM_PRIORITY = ["xhs", "dy", "pgy", "xt"]

PLATFORM_ALIASES = {
    "xhs": "xhs",
    "xiaohongshu": "xhs",
    "小红书": "xhs",
    "red": "xhs",
    "dy": "dy",
    "douyin": "dy",
    "抖音": "dy",
    "pgy": "pgy",
    "pugongying": "pgy",
    "蒲公英": "pgy",
    "xt": "xt",
    "xingtu": "xt",
    "星图": "xt",
}

PLATFORM_DISPLAY_NAMES = {
    "xhs": "小红书",
    "dy": "抖音",
    "pgy": "蒲公英",
    "xt": "星图",
}


def normalize_platforms(value: str | None) -> list[str]:
    """把用户传入的平台列表标准化为 xhs/dy/pgy/xt，并按固定优先级排序。"""
    if not value or not value.strip():
        selected = set(PLATFORM_PRIORITY)
    else:
        raw_names = [part.strip() for part in value.replace("，", ",").split(",") if part.strip()]
        selected = set()
        for raw_name in raw_names:
            platform = PLATFORM_ALIASES.get(raw_name.lower()) or PLATFORM_ALIASES.get(raw_name)
            if not platform:
                allowed = ", ".join(PLATFORM_ALIASES)
                raise ValueError(f"Unsupported platform: {raw_name}. Allowed values: {allowed}")
            selected.add(platform)
    return [platform for platform in PLATFORM_PRIORITY if platform in selected]


def selected_platforms_from_env() -> list[str]:
    """从 FINDAI_TEST_PLATFORMS 读取本次执行的平台；为空时默认四个平台全选。"""
    return normalize_platforms(os.getenv("FINDAI_TEST_PLATFORMS", ""))


def platform_display_text(platforms: list[str]) -> str:
    """把标准平台列表转换为中文展示文本。"""
    return "、".join(PLATFORM_DISPLAY_NAMES[platform] for platform in platforms)
