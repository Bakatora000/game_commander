#!/usr/bin/env python3
"""Non-interactive host actions for Game Commander v3.0."""
from __future__ import annotations

import argparse
import pwd
import socket
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from shared import bootstraphub, cpuplan, deploycore, discordnotify, hostctl, hostops, hubsync, redeploycore, uninstallcore, updatecore, updatehooks


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
    _notify(args.action, ok, instance_id=_service_instance(args.service), service=args.service, details=message)
    if not ok and message:
        print(message, file=sys.stderr)
        return 1
    if message:
        print(message)
    return 0


def cmd_update_instance(args: argparse.Namespace) -> int:
    config_file = hostctl.resolve_instance_config(args.instance)
    if not config_file:
        _notify("update", False, instance_id=args.instance, details="Configuration d'instance introuvable")
        print("Configuration d'instance introuvable", file=sys.stderr)
        return 1
    env = hostctl.parse_env_file(config_file)
    game_id = env.get("GAME_ID", "")
    ok, result = updatecore.run_core_update(config_file, Path(args.main_script).resolve().parent)
    if not ok:
        _notify("update", False, instance_id=args.instance, game_id=game_id, details=_details_text(result))
        print(result, file=sys.stderr)
        return 1
    for line in result:
        print(line)
    ok, hooks = updatehooks.run_post_update_hooks(config_file, Path(args.main_script).resolve().parent)
    if not ok:
        _notify("update", False, instance_id=args.instance, game_id=game_id, details=_details_text(hooks))
        print(hooks, file=sys.stderr)
        return 1
    for line in hooks:
        print(line)
    if not args.skip_hub_sync:
        ok, hub = hubsync.sync_hub_service(config_file, Path(args.main_script).resolve().parent)
        if not ok:
            _notify("update", False, instance_id=args.instance, game_id=game_id, details=_details_text(hub))
            print(hub, file=sys.stderr)
            return 1
        for line in hub:
            print(line)
    _notify("update", True, instance_id=args.instance, game_id=game_id, details=_details_text(result + hooks))
    return 0


def cmd_redeploy_instance(args: argparse.Namespace) -> int:
    env = hostctl.parse_env_file(args.config)
    instance_id = env.get("INSTANCE_ID", "")
    game_id = env.get("GAME_ID", "")
    ok, result = redeploycore.run_redeploy(args.config, args.main_script)
    if not ok:
        _notify("redeploy", False, instance_id=instance_id, game_id=game_id, details=_details_text(result))
        print(result, file=sys.stderr)
        return 1
    for line in result:
        print(line)
    _notify("redeploy", True, instance_id=instance_id, game_id=game_id, details=_details_text(result))
    return 0


def _default_sys_user(main_script: Path) -> str:
    return pwd.getpwuid(main_script.stat().st_uid).pw_name


def _default_domain() -> str:
    try:
        return socket.getfqdn() or "localhost"
    except Exception:
        return "localhost"


def _details_text(result: str | list[str]) -> str:
    if isinstance(result, list):
        return "\n".join(str(line) for line in result if str(line).strip())
    return str(result or "")


def _service_instance(service: str) -> str:
    if service.startswith("game-commander-"):
        return service.removeprefix("game-commander-")
    if "-server-" in service:
        return service.split("-server-", 1)[1]
    return service


def _notify(event: str, ok: bool, *, instance_id: str = "", game_id: str = "", service: str = "", details: str = "") -> None:
    try:
        discordnotify.notify_event(
            event=event,
            ok=ok,
            instance_id=instance_id,
            game_id=game_id,
            service=service,
            details=details,
        )
    except Exception:
        pass


def cmd_deploy_instance(args: argparse.Namespace) -> int:
    main_script = Path(args.main_script).resolve()
    ok, result = deploycore.run_deploy_instance(
        main_script=main_script,
        game_id=args.game_id,
        sys_user=args.sys_user or _default_sys_user(main_script),
        repo_root=main_script.parent,
        domain=args.domain,
        instance_id=args.instance,
        url_prefix=args.url_prefix,
        admin_login=args.admin_login or "admin",
        admin_password=args.admin_password,
        server_name=args.server_name,
        server_password=str(args.server_password or ""),
        server_port=str(args.server_port or ""),
        max_players=str(args.max_players or ""),
    )
    if not ok:
        _notify("deploy", False, instance_id=args.instance, game_id=args.game_id, details=_details_text(result))
        print(result, file=sys.stderr)
        return 1
    for line in result:
        print(line)
    _notify("deploy", True, instance_id=args.instance, game_id=args.game_id, details=_details_text(result))
    return 0


def cmd_uninstall_instance(args: argparse.Namespace) -> int:
    config_file = hostctl.resolve_instance_config(args.instance)
    repo_root = Path(args.main_script).resolve().parent
    if config_file:
        env = hostctl.parse_env_file(config_file)
        game_id = env.get("GAME_ID", args.game_id)
        ok, result = uninstallcore.run_full_uninstall(config_file, repo_root)
    else:
        if not args.game_id:
            _notify("uninstall", False, instance_id=args.instance, details="Configuration d'instance introuvable")
            print("Configuration d'instance introuvable", file=sys.stderr)
            return 1
        game_id = args.game_id
        ok, result = uninstallcore.run_partial_uninstall(args.instance, args.game_id, repo_root)
    if not ok:
        _notify("uninstall", False, instance_id=args.instance, game_id=game_id, details=_details_text(result))
        print(result, file=sys.stderr)
        return 1
    for line in result:
        print(line)
    _notify("uninstall", True, instance_id=args.instance, game_id=game_id, details=_details_text(result))
    return 0


def cmd_rebalance(args: argparse.Namespace) -> int:
    core_groups = cpuplan.detect_core_groups()
    if not core_groups:
        _notify("rebalance", False, details="Topologie CPU introuvable")
        print("Topologie CPU introuvable", file=sys.stderr)
        return 1
    instances = cpuplan.collect_managed_instances()
    if not instances:
        _notify("rebalance", False, details="Aucune instance gérée trouvée")
        print("Aucune instance gérée trouvée", file=sys.stderr)
        return 1
    plan = cpuplan.plan_instances(instances, core_groups)
    messages = cpuplan.apply_plan(plan, restart_running=args.restart)
    for message in messages:
        print(message)
    print("Répartition CPU recalculée")
    _notify("rebalance", True, details=_details_text(messages + ["Répartition CPU recalculée"]))
    return 0


def cmd_bootstrap_hub(args: argparse.Namespace) -> int:
    ok, result = bootstraphub.run_bootstrap_hub(
        repo_root=Path(args.main_script).resolve().parent,
        sys_user=args.sys_user or _default_sys_user(Path(args.main_script).resolve()),
        domain=args.domain or _default_domain(),
        admin_login=args.admin_login or "admin",
        admin_password=args.admin_password,
        ssl_mode=args.ssl_mode,
    )
    stream = sys.stdout if ok else sys.stderr
    if isinstance(result, str):
        print(result, file=stream)
    else:
        for line in result:
            print(line, file=stream)
    _notify("bootstrap-hub", ok, details=_details_text(result))
    return 0 if ok else 1


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
    update.add_argument("--skip-hub-sync", action="store_true")
    update.set_defaults(func=cmd_update_instance)

    redeploy = sub.add_parser("redeploy-instance")
    redeploy.add_argument("--main-script", required=True, type=_existing_path)
    redeploy.add_argument("--config", required=True, type=_existing_path)
    redeploy.set_defaults(func=cmd_redeploy_instance)

    deploy = sub.add_parser("deploy-instance")
    deploy.add_argument("--main-script", required=True, type=_existing_path)
    deploy.add_argument("--game-id", required=True)
    deploy.add_argument("--instance", required=True)
    deploy.add_argument("--domain", required=True)
    deploy.add_argument("--url-prefix", default="")
    deploy.add_argument("--admin-login", default="admin")
    deploy.add_argument("--admin-password", required=True)
    deploy.add_argument("--sys-user", default="")
    deploy.add_argument("--server-name", default="")
    deploy.add_argument("--server-password", default="")
    deploy.add_argument("--server-port", default="")
    deploy.add_argument("--max-players", default="")
    deploy.set_defaults(func=cmd_deploy_instance)

    uninstall = sub.add_parser("uninstall-instance")
    uninstall.add_argument("--main-script", required=True, type=_existing_path)
    uninstall.add_argument("--instance", required=True)
    uninstall.add_argument("--game-id", default="")
    uninstall.set_defaults(func=cmd_uninstall_instance)

    rebalance = sub.add_parser("rebalance")
    rebalance.add_argument("--main-script", required=True, type=_existing_path)
    rebalance.add_argument("--restart", action="store_true")
    rebalance.set_defaults(func=cmd_rebalance)

    bootstrap = sub.add_parser("bootstrap-hub")
    bootstrap.add_argument("--main-script", required=True, type=_existing_path)
    bootstrap.add_argument("--sys-user", default="")
    bootstrap.add_argument("--domain", default="")
    bootstrap.add_argument("--admin-login", default="admin")
    bootstrap.add_argument("--admin-password", default="")
    bootstrap.add_argument("--ssl-mode", default="none", choices=["none", "existing", "certbot"])
    bootstrap.set_defaults(func=cmd_bootstrap_hub)

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
