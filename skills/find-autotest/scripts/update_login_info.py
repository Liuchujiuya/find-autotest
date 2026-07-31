from __future__ import annotations

import argparse
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml


DEFAULT_CONFIG = Path(r"D:\apitest_dev\login_info.yaml")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Update FindAI autotest login_info.yaml safely.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="Path to login_info.yaml.")
    parser.add_argument("--pgy-username", help="蒲公英平台账号。")
    parser.add_argument("--pgy-password", help="蒲公英平台密码。")
    parser.add_argument("--xt-username", help="星图平台账号。")
    parser.add_argument("--xt-password", help="星图平台密码。")
    parser.add_argument("--collect-api-key", help="小红书和抖音共用的采集接口 api_key。")
    parser.add_argument("--xhs-api-key", help="小红书采集接口 api_key。")
    parser.add_argument("--dy-api-key", help="抖音采集接口 api_key。")
    parser.add_argument("--findai-username", help="FindAI 插件账号。")
    parser.add_argument("--findai-password", help="FindAI 插件密码。")
    return parser.parse_args()


def load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def ensure_mapping(config: dict[str, Any], *keys: str) -> dict[str, Any]:
    current = config
    for key in keys:
        value = current.get(key)
        if not isinstance(value, dict):
            value = {}
            current[key] = value
        current = value
    return current


def set_if_present(target: dict[str, Any], key: str, value: str | None, changes: list[str]) -> None:
    if value is None:
        return
    target[key] = value
    changes.append(key)


def mask(value: str | None) -> str:
    if not value:
        return ""
    if len(value) <= 6:
        return "*" * len(value)
    return f"{value[:3]}***{value[-3:]}"


def main() -> int:
    args = parse_args()
    config_path = Path(args.config)
    config = load_config(config_path)
    changes: list[str] = []

    pgy = ensure_mapping(config, "platforms", "pugongying")
    set_if_present(pgy, "username", args.pgy_username, changes)
    set_if_present(pgy, "password", args.pgy_password, changes)

    xt = ensure_mapping(config, "platforms", "xingtu")
    set_if_present(xt, "username", args.xt_username, changes)
    set_if_present(xt, "password", args.xt_password, changes)

    xhs = ensure_mapping(config, "platforms", "xiaohongshu")
    set_if_present(xhs, "api_key", args.collect_api_key or args.xhs_api_key, changes)

    dy = ensure_mapping(config, "platforms", "douyin")
    set_if_present(dy, "api_key", args.collect_api_key or args.dy_api_key, changes)

    findai = ensure_mapping(config, "findai")
    set_if_present(findai, "username", args.findai_username, changes)
    set_if_present(findai, "password", args.findai_password, changes)

    if not changes:
        print("No fields were provided; config was not changed.")
        return 0

    backup_path = config_path.with_suffix(f"{config_path.suffix}.bak.{datetime.now():%Y%m%d%H%M%S}")
    shutil.copy2(config_path, backup_path)
    config_path.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")

    print(f"Updated config: {config_path}")
    print(f"Backup created: {backup_path}")
    print("Current safe summary:")
    print(f"  pugongying.username={pgy.get('username', '')}")
    print(f"  pugongying.password={mask(pgy.get('password'))}")
    print(f"  xingtu.username={xt.get('username', '')}")
    print(f"  xingtu.password={mask(xt.get('password'))}")
    print(f"  xiaohongshu.api_key={mask(xhs.get('api_key'))}")
    print(f"  douyin.api_key={mask(dy.get('api_key'))}")
    print(f"  findai.username={findai.get('username', '')}")
    print(f"  findai.password={mask(findai.get('password'))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
