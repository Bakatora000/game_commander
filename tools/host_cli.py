#!/usr/bin/env python3
"""Non-interactive host actions for Game Commander v3.0."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from shared import hostops


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
    ok, message = hostops.run_command(
        hostops.update_instance_cmd(args.main_script, args.instance),
        timeout=900,
    )
    if not ok and message:
        print(message, file=sys.stderr)
        return 1
    if message:
        print(message)
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
    ok, message = hostops.run_command(
        hostops.uninstall_instance_cmd(args.main_script, args.instance),
        timeout=1200,
    )
    if not ok and message:
        print(message, file=sys.stderr)
        return 1
    if message:
        print(message)
    return 0


def cmd_rebalance(args: argparse.Namespace) -> int:
    ok, message = hostops.run_command(
        hostops.rebalance_cmd(args.main_script, restart=args.restart),
        timeout=900,
    )
    if not ok and message:
        print(message, file=sys.stderr)
        return 1
    if message:
        print(message)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Game Commander host action CLI")
    sub = parser.add_subparsers(dest="command", required=True)

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

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

