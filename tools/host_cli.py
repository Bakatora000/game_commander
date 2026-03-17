#!/usr/bin/env python3
"""Non-interactive host actions for Game Commander v3.0."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from shared import cpuplan, hostctl, hostops, hubsync, uninstallcore, updatecore, updatehooks


def _existing_path(value: str) -> Path:
    path = Path(value)
    if not path.exists():
        raise argparse.ArgumentTypeError(f"Path not found: {value}")
    return path


def cmd_service_action(args: argparse.Namespace) -> int:
    ok, message = hostops.run_command(
        hostops.service_action_cmd(args.service, args.action),
        timeout=120,
    )
    if not ok and message:
        print(message, file=sys.stderr)
        return 1
    if message:
        print(message)
    return 0


def cmd_update_instance(args: argparse.Namespace) -> int:
    config_file = hostctl.resolve_instance_config(args.instance)
    if not config_file:
        print("Configuration d'instance introuvable", file=sys.stderr)
        return 1
    ok, result = updatecore.run_core_update(config_file, Path(args.main_script).resolve().parent)
    if not ok:
        print(result, file=sys.stderr)
        return 1
    for line in result:
        print(line)
    ok, hooks = updatehooks.run_post_update_hooks(config_file, Path(args.main_script).resolve().parent)
    if not ok:
        print(hooks, file=sys.stderr)
        return 1
    for line in hooks:
        print(line)
    ok, hub = hubsync.sync_hub_service(config_file, Path(args.main_script).resolve().parent)
    if not ok:
        print(hub, file=sys.stderr)
        return 1
    for line in hub:
        print(line)
    return 0


def cmd_redeploy_instance(args: argparse.Namespace) -> int:
    ok, message = hostops.run_command(
        hostops.redeploy_instance_cmd(args.main_script, args.config),
        timeout=1200,
    )
    if not ok and message:
        print(message, file=sys.stderr)
        return 1
    if message:
        print(message)
    return 0


def cmd_uninstall_instance(args: argparse.Namespace) -> int:
    config_file = hostctl.resolve_instance_config(args.instance)
    if not config_file:
        print("Configuration d'instance introuvable", file=sys.stderr)
        return 1
    ok, result = uninstallcore.run_full_uninstall(config_file, Path(args.main_script).resolve().parent)
    if not ok:
        print(result, file=sys.stderr)
        return 1
    for line in result:
        print(line)
    return 0


def cmd_rebalance(args: argparse.Namespace) -> int:
    core_groups = cpuplan.detect_core_groups()
    if not core_groups:
        print("Topologie CPU introuvable", file=sys.stderr)
        return 1
    instances = cpuplan.collect_managed_instances()
    if not instances:
        print("Aucune instance gérée trouvée", file=sys.stderr)
        return 1
    plan = cpuplan.plan_instances(instances, core_groups)
    messages = cpuplan.apply_plan(plan, restart_running=args.restart)
    for message in messages:
        print(message)
    print("Répartition CPU recalculée")
    return 0


def cmd_list_configs(args: argparse.Namespace) -> int:
    configs = hostctl.discover_instance_configs(search_roots=args.root, max_depth=args.max_depth)
    for path in configs:
        print(path)
    return 0


def cmd_list_instances(args: argparse.Namespace) -> int:
    records = hostctl.discover_instance_records(search_roots=args.root, max_depth=args.max_depth)
    for item in records:
        print(f"{item['instance_id']} {item['game_id']} {item['config']}")
    return 0


def cmd_resolve_config(args: argparse.Namespace) -> int:
    path = hostctl.resolve_instance_config(args.instance, search_roots=args.root, max_depth=args.max_depth)
    if not path:
        return 1
    print(path)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Game Commander host action CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_search_flags(cmd):
        cmd.add_argument("--root", action="append", default=[])
        cmd.add_argument("--max-depth", type=int, default=hostctl.DEFAULT_MAX_DEPTH)

    service = sub.add_parser("service-action")
    service.add_argument("--service", required=True)
    service.add_argument("--action", choices=["start", "stop", "restart"], required=True)
    service.set_defaults(func=cmd_service_action)

    update = sub.add_parser("update-instance")
    update.add_argument("--main-script", required=True, type=_existing_path)
    update.add_argument("--instance", required=True)
    update.set_defaults(func=cmd_update_instance)

    redeploy = sub.add_parser("redeploy-instance")
    redeploy.add_argument("--main-script", required=True, type=_existing_path)
    redeploy.add_argument("--config", required=True, type=_existing_path)
    redeploy.set_defaults(func=cmd_redeploy_instance)

    uninstall = sub.add_parser("uninstall-instance")
    uninstall.add_argument("--main-script", required=True, type=_existing_path)
    uninstall.add_argument("--instance", required=True)
    uninstall.set_defaults(func=cmd_uninstall_instance)

    rebalance = sub.add_parser("rebalance")
    rebalance.add_argument("--main-script", required=True, type=_existing_path)
    rebalance.add_argument("--restart", action="store_true")
    rebalance.set_defaults(func=cmd_rebalance)

    list_configs = sub.add_parser("list-configs")
    add_search_flags(list_configs)
    list_configs.set_defaults(func=cmd_list_configs)

    list_instances = sub.add_parser("list-instances")
    add_search_flags(list_instances)
    list_instances.set_defaults(func=cmd_list_instances)

    resolve_config = sub.add_parser("resolve-config")
    add_search_flags(resolve_config)
    resolve_config.add_argument("--instance", required=True)
    resolve_config.set_defaults(func=cmd_resolve_config)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if hasattr(args, "root") and not args.root:
        args.root = list(hostctl.DEFAULT_SEARCH_ROOTS)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
