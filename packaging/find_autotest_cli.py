from __future__ import annotations

import argparse
import importlib.util
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml


APP_HOME = Path.home() / ".find-autotest"
RUNTIME_ROOT = Path(os.getenv("LOCALAPPDATA") or tempfile.gettempdir()) / "find-autotest"
PROJECT_DIR = RUNTIME_ROOT / "project"


def resource_root() -> Path:
    if getattr(sys, "frozen", False):
        root = Path(getattr(sys, "_MEIPASS"))
        browsers = root / "ms-playwright"
        if browsers.exists():
            os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(browsers))
        return root
    return Path(__file__).resolve().parents[1]


def exe_config_path() -> Path:
    if getattr(sys, "frozen", False):
        exe_path = Path(sys.executable).resolve()
        candidates = [
            exe_path.parent.parent / "config.yaml",
            exe_path.parent / "config.yaml",
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return candidates[0]
    return APP_HOME / "config.yaml"


def release_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent.parent
    return resource_root()


def external_extension_dir() -> Path:
    return release_root() / "extension"


def copy_tree(source: Path, destination: Path, overwrite: bool = True) -> None:
    if not source.exists():
        raise FileNotFoundError(f"Missing bundled resource: {source}")
    if destination.exists() and overwrite:
        shutil.rmtree(destination)
    if not destination.exists():
        shutil.copytree(source, destination)


def has_extension_files(path: Path) -> bool:
    if not path.exists() or not path.is_dir():
        return False
    return any(item.name != ".gitkeep" for item in path.iterdir())


def sync_external_extension() -> None:
    source = external_extension_dir()
    destination = PROJECT_DIR / "extension"
    destination.mkdir(parents=True, exist_ok=True)
    if not has_extension_files(source):
        return
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination)


def bundled_project_dir() -> Path:
    return resource_root() / "project"


def bundled_config_example() -> Path:
    return bundled_project_dir() / "login_info.yaml.example"


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def save_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def install_resources(force: bool = False) -> None:
    config_path = exe_config_path()
    APP_HOME.mkdir(parents=True, exist_ok=True)
    if force or not PROJECT_DIR.exists():
        copy_tree(bundled_project_dir(), PROJECT_DIR, overwrite=True)
    PROJECT_DIR.joinpath("extension").mkdir(parents=True, exist_ok=True)
    PROJECT_DIR.joinpath("testresult").mkdir(parents=True, exist_ok=True)
    sync_external_extension()

    if not config_path.exists():
        config_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(bundled_config_example(), config_path)
    sync_config_to_project()


def sync_config_to_project() -> None:
    config_path = exe_config_path()
    if config_path.exists():
        shutil.copy2(config_path, PROJECT_DIR / "login_info.yaml")
    sync_external_extension()


def ensure_installed() -> None:
    if not PROJECT_DIR.exists() or not exe_config_path().exists():
        install_resources(force=False)
    sync_config_to_project()


def mask(value: str | None) -> str:
    if not value:
        return ""
    if len(value) <= 6:
        return "*" * len(value)
    return f"{value[:3]}***{value[-3:]}"


def ensure_mapping(config: dict[str, Any], *keys: str) -> dict[str, Any]:
    node = config
    for key in keys:
        value = node.get(key)
        if not isinstance(value, dict):
            value = {}
            node[key] = value
        node = value
    return node


def set_if_present(target: dict[str, Any], key: str, value: str | None) -> bool:
    if value is None:
        return False
    target[key] = value
    return True


def update_config(args: argparse.Namespace) -> None:
    ensure_installed()
    config_path = exe_config_path()
    config = load_yaml(config_path)
    changed = False

    pgy = ensure_mapping(config, "platforms", "pugongying")
    changed |= set_if_present(pgy, "username", args.pgy_username)
    changed |= set_if_present(pgy, "password", args.pgy_password)

    xt = ensure_mapping(config, "platforms", "xingtu")
    changed |= set_if_present(xt, "username", args.xt_username)
    changed |= set_if_present(xt, "password", args.xt_password)

    collect_key = args.collect_api_key
    xhs = ensure_mapping(config, "platforms", "xiaohongshu")
    dy = ensure_mapping(config, "platforms", "douyin")
    if collect_key is not None:
        changed |= set_if_present(xhs, "api_key", collect_key)
        changed |= set_if_present(dy, "api_key", collect_key)

    findai = ensure_mapping(config, "findai")
    changed |= set_if_present(findai, "username", args.findai_username)
    changed |= set_if_present(findai, "password", args.findai_password)

    notification = ensure_mapping(config, "notification")
    changed |= set_if_present(notification, "wecom_webhook", args.wecom_webhook)

    if not changed:
        print("No config fields were provided.")
        return
    save_yaml(config_path, config)
    sync_config_to_project()
    print(f"Updated config: {config_path}")
    print(f"pugongying.username={pgy.get('username', '')}")
    print(f"pugongying.password={mask(pgy.get('password'))}")
    print(f"xingtu.username={xt.get('username', '')}")
    print(f"xingtu.password={mask(xt.get('password'))}")
    print(f"collect.api_key={mask(xhs.get('api_key'))}")
    print(f"findai.username={findai.get('username', '')}")
    print(f"findai.password={mask(findai.get('password'))}")
    print(f"notification.wecom_webhook={mask(notification.get('wecom_webhook'))}")


def run_tests(args: argparse.Namespace) -> int:
    ensure_installed()
    sys.path.insert(0, str(PROJECT_DIR))
    os.chdir(PROJECT_DIR)
    if args.platforms:
        os.environ["FINDAI_TEST_PLATFORMS"] = args.platforms
    os.environ.setdefault("FINDAI_PLATFORM_PARALLEL", "1")
    os.environ.setdefault("FINDAI_PARALLEL_CASES", "0")

    import pytest

    pytest_args = ["--clean-alluredir"]
    if getattr(sys, "frozen", False):
        pytest_args[0:0] = ["-p", "allure_pytest.plugin"]
    if args.pytest_args:
        extra_args = list(args.pytest_args)
        if extra_args and extra_args[0] == "--":
            extra_args = extra_args[1:]
        pytest_args.extend(extra_args)
    pytest_code = int(pytest.main(pytest_args))
    project_run = load_project_run_module()
    report_code = 0
    report_url = ""
    if not args.no_report:
        report_code = project_run.generate_allure_report(open_report=False)
        if report_code == 0:
            report_url = project_run.start_allure_report_server()
            if report_url:
                print(f"Allure report server: {report_url}")
    if not args.no_notify:
        selected_platforms = project_run.normalize_platforms(args.platforms)
        project_run.send_wecom_notification(pytest_code, report_code, report_url, selected_platforms)
    if pytest_code == 0 and report_code != 0:
        return report_code
    return pytest_code


def load_project_run_module():
    run_path = PROJECT_DIR / "run.py"
    spec = importlib.util.spec_from_file_location("find_autotest_project_run", run_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load project run module: {run_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def print_paths() -> None:
    ensure_installed()
    print(f"Home: {APP_HOME}")
    print(f"Config: {exe_config_path()}")
    print(f"Project: {PROJECT_DIR}")
    print(f"Extension: {PROJECT_DIR / 'extension'}")
    print(f"Release extension source: {external_extension_dir()}")
    print(f"Runtime: {PROJECT_DIR}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="find-autotest", description="FindAI autotest bundled CLI.")
    subparsers = parser.add_subparsers(dest="command")

    install = subparsers.add_parser("install", help="Prepare the bundled runtime files.")
    install.add_argument("--force", action="store_true", help="Overwrite the local runtime files.")

    config = subparsers.add_parser("config", help="Update config.yaml safely.")
    config.add_argument("--pgy-username")
    config.add_argument("--pgy-password")
    config.add_argument("--xt-username")
    config.add_argument("--xt-password")
    config.add_argument("--collect-api-key")
    config.add_argument("--findai-username")
    config.add_argument("--findai-password")
    config.add_argument("--wecom-webhook")

    run = subparsers.add_parser("run", help="Run pytest cases from the bundled project.")
    run.add_argument("--platforms", default="", help="Platforms: xhs,dy,pgy,xt or Chinese aliases.")
    run.add_argument("--no-report", action="store_true", help="Do not generate Allure HTML report.")
    run.add_argument("--no-notify", action="store_true", help="Do not send WeCom webhook notification.")
    run.add_argument("pytest_args", nargs=argparse.REMAINDER, help="Extra pytest args after --.")

    subparsers.add_parser("where", help="Print installed paths.")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "install":
        install_resources(force=args.force)
        print_paths()
        return 0
    if args.command == "config":
        update_config(args)
        return 0
    if args.command == "run":
        return run_tests(args)
    if args.command == "where":
        print_paths()
        return 0
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
