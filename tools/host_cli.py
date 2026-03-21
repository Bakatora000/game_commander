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


def _repo_root_from_args(args: argparse.Namespace) -> Path:
    repo_root = getattr(args, "repo_root", None)
    if repo_root:
        return Path(repo_root).resolve()
    main_script = getattr(args, "main_script", None)
    if main_script:
        return Path(main_script).resolve().parent
    raise ValueError("repo_root or main_script required")


def cmd_service_action(args: argparse.Namespace) -> int:
    ok, message = hostops.run_command(
        hostops.service_action_cmd(args.service, args.action),
        timeout=120,
    )
    discord_status = _notify(args.action, ok, instance_id=_service_instance(args.service), service=args.service, source=args.source, details=message)
    if not ok and message:
        _print_discord_status(discord_status)
        print(message, file=sys.stderr)
        return 1
    if message:
        print(message)
    _print_discord_status(discord_status)
    return 0


def cmd_update_instance(args: argparse.Namespace) -> int:
    config_file = hostctl.resolve_instance_config(args.instance)
    if not config_file:
        _print_discord_status(_notify("update", False, instance_id=args.instance, source=args.source, details="Configuration d'instance introuvable"))
        print("Configuration d'instance introuvable", file=sys.stderr)
        return 1
    env = hostctl.parse_env_file(config_file)
    game_id = env.get("GAME_ID", "")
    repo_root = _repo_root_from_args(args)
    ok, result = updatecore.run_core_update(config_file, repo_root)
    if not ok:
        _print_discord_status(_notify('update', False, instance_id=args.instance, game_id=game_id, source=args.source, details=_compact_discord_details('update', False, result)))
        print(result, file=sys.stderr)
        return 1
    for line in result:
        print(line)
    ok, hooks = updatehooks.run_post_update_hooks(config_file, repo_root)
    if not ok:
        _print_discord_status(_notify('update', False, instance_id=args.instance, game_id=game_id, source=args.source, details=_compact_discord_details('update', False, hooks)))
        print(hooks, file=sys.stderr)
        return 1
    for line in hooks:
        print(line)
    if not args.skip_hub_sync:
        ok, hub = hubsync.sync_hub_service(config_file, repo_root)
        if not ok:
            _print_discord_status(_notify('update', False, instance_id=args.instance, game_id=game_id, source=args.source, details=_compact_discord_details('update', False, hub)))
            print(hub, file=sys.stderr)
            return 1
        for line in hub:
            print(line)
    _print_discord_status(_notify('update', True, instance_id=args.instance, game_id=game_id, source=args.source, details=_compact_discord_details('update', True, result + hooks)))
    return 0


def cmd_redeploy_instance(args: argparse.Namespace) -> int:
    env = hostctl.parse_env_file(args.config)
    instance_id = env.get("INSTANCE_ID", "")
    game_id = env.get("GAME_ID", "")
    ok, result = redeploycore.run_redeploy(args.config, _repo_root_from_args(args))
    if not ok:
        _print_discord_status(_notify('redeploy', False, instance_id=instance_id, game_id=game_id, source=args.source, details=_compact_discord_details('redeploy', False, result)))
        print(result, file=sys.stderr)
        return 1
    for line in result:
        print(line)
    try:
        discord_cfg = discordnotify.load_config()
        if discordnotify.notifications_enabled(discord_cfg):
            exit_code = discordnotify._cli_create_channel(instance_id, game_id)
            if exit_code != 0:
                print("Discord : création/réutilisation du canal échouée", file=sys.stderr)
    except Exception as exc:
        print(f"Discord : {exc}", file=sys.stderr)
    _print_discord_status(_notify('redeploy', True, instance_id=instance_id, game_id=game_id, source=args.source, details=_compact_discord_details('redeploy', True, result)))
    return 0


def _default_sys_user(repo_root: Path) -> str:
    return pwd.getpwuid(repo_root.stat().st_uid).pw_name


def _default_domain() -> str:
    try:
        return socket.getfqdn() or "localhost"
    except Exception:
        return "localhost"


def _details_text(result: str | list[str]) -> str:
    if isinstance(result, list):
        return "\n".join(str(line) for line in result if str(line).strip())
    return str(result or "")


def _compact_discord_details(event: str, ok: bool, result: str | list[str]) -> str:
    text = _details_text(result)
    if not text:
        return ""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if event not in {"deploy", "redeploy", "update", "uninstall"}:
        return text[:900]
    interesting_prefixes = (
        "Config chargée depuis",
        "Journal :",
        "Config sauvegardée :",
        "Service ",
        "Accès :",
        "Instance ",
        "Game Commander répond",
        "Nginx :",
        "Hub Admin synchronisé",
        "Service game-commander-hub redémarré",
        "Répartition CPU recalculée",
        "users.json ",
        "Channel ",
        "Discord :",
    )
    filtered = [
        line for line in lines
        if line.startswith(interesting_prefixes)
        and "DÉPLOIEMENT v2.0" not in line
        and "Serveur de jeu + Interface web" not in line
    ]
    if not filtered:
        filtered = [lines[-1]]
    if ok and len(filtered) > 6:
        filtered = filtered[:2] + filtered[-4:]
    return "\n".join(filtered)[:900]


def _print_discord_status(status: str, *, stream=None) -> None:
    if status:
        if stream is None:
            stream = sys.stdout
        print(f"Discord : {status}", file=stream)


def _service_instance(service: str) -> str:
    if service.startswith("game-commander-"):
        return service.removeprefix("game-commander-")
    if "-server-" in service:
        return service.split("-server-", 1)[1]
    return service


def _notify(event: str, ok: bool, *, instance_id: str = "", game_id: str = "", service: str = "", source: str = "", details: str = "") -> str:
    if not source:
        return ""
    try:
        sent, status = discordnotify.notify_event(
            event=event,
            ok=ok,
            instance_id=instance_id,
            game_id=game_id,
            service=service,
            source=source,
            details=details,
        )
        return "notification envoyee" if sent else status
    except Exception:
        return "erreur"


def cmd_deploy_instance(args: argparse.Namespace) -> int:
    repo_root = _repo_root_from_args(args)
    ok, result = deploycore.run_deploy_instance(
        game_id=args.game_id,
        sys_user=args.sys_user or _default_sys_user(repo_root),
        repo_root=repo_root,
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
        _print_discord_status(_notify('deploy', False, instance_id=args.instance, game_id=args.game_id, source=args.source, details=_compact_discord_details('deploy', False, result)))
        print(result, file=sys.stderr)
        return 1
    for line in result:
        print(line)
    _print_discord_status(_notify('deploy', True, instance_id=args.instance, game_id=args.game_id, source=args.source, details=_compact_discord_details('deploy', True, result)))
    return 0


def cmd_uninstall_instance(args: argparse.Namespace) -> int:
    config_file = hostctl.resolve_instance_config(args.instance)
    repo_root = _repo_root_from_args(args)
    if config_file:
        env = hostctl.parse_env_file(config_file)
        game_id = env.get("GAME_ID", args.game_id)
        ok, result = uninstallcore.run_full_uninstall(config_file, repo_root)
    else:
        if not args.game_id:
            _print_discord_status(_notify("uninstall", False, instance_id=args.instance, source=args.source, details="Configuration d'instance introuvable"))
            print("Configuration d'instance introuvable", file=sys.stderr)
            return 1
        game_id = args.game_id
        ok, result = uninstallcore.run_partial_uninstall(args.instance, args.game_id, repo_root)
    if not ok:
        _print_discord_status(_notify('uninstall', False, instance_id=args.instance, game_id=game_id, source=args.source, details=_compact_discord_details('uninstall', False, result)))
        print(result, file=sys.stderr)
        return 1
    for line in result:
        print(line)
    _print_discord_status(_notify('uninstall', True, instance_id=args.instance, game_id=game_id, source=args.source, details=_compact_discord_details('uninstall', True, result)))
    return 0


def cmd_rebalance(args: argparse.Namespace) -> int:
    core_groups = cpuplan.detect_core_groups()
    if not core_groups:
        _print_discord_status(_notify('rebalance', False, source=args.source, details='Topologie CPU introuvable'))
        print("Topologie CPU introuvable", file=sys.stderr)
        return 1
    instances = cpuplan.collect_managed_instances()
    if not instances:
        _print_discord_status(_notify('rebalance', False, source=args.source, details='Aucune instance gérée trouvée'))
        print("Aucune instance gérée trouvée", file=sys.stderr)
        return 1
    plan = cpuplan.plan_instances(instances, core_groups)
    messages = cpuplan.apply_plan(plan, restart_running=args.restart)
    for message in messages:
        print(message)
    print("Répartition CPU recalculée")
    _print_discord_status(_notify('rebalance', True, source=args.source, details=_details_text(messages + ['Répartition CPU recalculée'])))
    return 0


def cmd_bootstrap_hub(args: argparse.Namespace) -> int:
    repo_root = _repo_root_from_args(args)
    ok, result = bootstraphub.run_bootstrap_hub(
        repo_root=repo_root,
        sys_user=args.sys_user or _default_sys_user(repo_root),
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
    _print_discord_status(_notify('bootstrap-hub', ok, source=args.source, details=_details_text(result)), stream=stream)
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


def cmd_discord_test(args: argparse.Namespace) -> int:
    ok, message = discordnotify.send_test_message(
        event=args.event,
        instance_id=args.instance,
        game_id=args.game_id,
        source="Hub",
        details=args.message,
    )
    stream = sys.stdout if ok else sys.stderr
    print(message, file=stream)
    return 0 if ok else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Game Commander host action CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_search_flags(cmd):
        cmd.add_argument("--root", action="append", default=[])
        cmd.add_argument("--max-depth", type=int, default=hostctl.DEFAULT_MAX_DEPTH)

    service = sub.add_parser("service-action")
    service.add_argument("--service", required=True)
    service.add_argument("--action", choices=["start", "stop", "restart"], required=True)
    service.add_argument("--source", default="")
    service.set_defaults(func=cmd_service_action)

    update = sub.add_parser("update-instance")
    update.add_argument("--repo-root", type=_existing_path)
    update.add_argument("--main-script", type=_existing_path)
    update.add_argument("--instance", required=True)
    update.add_argument("--skip-hub-sync", action="store_true")
    update.add_argument("--source", default="")
    update.set_defaults(func=cmd_update_instance)

    redeploy = sub.add_parser("redeploy-instance")
    redeploy.add_argument("--repo-root", type=_existing_path)
    redeploy.add_argument("--main-script", type=_existing_path)
    redeploy.add_argument("--config", required=True, type=_existing_path)
    redeploy.add_argument("--source", default="")
    redeploy.set_defaults(func=cmd_redeploy_instance)

    deploy = sub.add_parser("deploy-instance")
    deploy.add_argument("--repo-root", type=_existing_path)
    deploy.add_argument("--main-script", type=_existing_path)
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
    deploy.add_argument("--source", default="")
    deploy.set_defaults(func=cmd_deploy_instance)

    uninstall = sub.add_parser("uninstall-instance")
    uninstall.add_argument("--repo-root", type=_existing_path)
    uninstall.add_argument("--main-script", type=_existing_path)
    uninstall.add_argument("--instance", required=True)
    uninstall.add_argument("--game-id", default="")
    uninstall.add_argument("--source", default="")
    uninstall.set_defaults(func=cmd_uninstall_instance)

    rebalance = sub.add_parser("rebalance")
    rebalance.add_argument("--repo-root", type=_existing_path)
    rebalance.add_argument("--main-script", type=_existing_path)
    rebalance.add_argument("--restart", action="store_true")
    rebalance.add_argument("--source", default="")
    rebalance.set_defaults(func=cmd_rebalance)

    bootstrap = sub.add_parser("bootstrap-hub")
    bootstrap.add_argument("--repo-root", type=_existing_path)
    bootstrap.add_argument("--main-script", type=_existing_path)
    bootstrap.add_argument("--sys-user", default="")
    bootstrap.add_argument("--domain", default="")
    bootstrap.add_argument("--admin-login", default="admin")
    bootstrap.add_argument("--admin-password", default="")
    bootstrap.add_argument("--ssl-mode", default="none", choices=["none", "existing", "certbot"])
    bootstrap.add_argument("--source", default="")
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

    discord_test = sub.add_parser("discord-test")
    discord_test.add_argument("--instance", default="")
    discord_test.add_argument("--game-id", default="")
    discord_test.add_argument("--event", default="discord-test")
    discord_test.add_argument("--message", default="Test de notification Discord Game Commander")
    discord_test.set_defaults(func=cmd_discord_test)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if hasattr(args, "root") and not args.root:
        args.root = list(hostctl.DEFAULT_SEARCH_ROOTS)
    if hasattr(args, "repo_root") or hasattr(args, "main_script"):
        if not getattr(args, "repo_root", None) and not getattr(args, "main_script", None):
            parser.error("one of --repo-root or --main-script is required")
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
