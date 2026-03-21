#!/usr/bin/env python3
"""CLI update — replaces lib/cmd_update.sh."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

_here = Path(__file__).resolve().parent.parent
if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))

from shared import console, cpuplan, deploybackups, hostctl, hubsync, instanceenv, sysutil

_BOLD = "\033[1m"
_CYAN = "\033[0;36m"
_RESET = "\033[0m"


def _game_meta(game_id: str) -> dict[str, str]:
    meta = instanceenv.GAME_META.get(game_id)
    if not meta:
        console.die(f"GAME_ID non supporté pour update : {game_id}")
    return meta  # type: ignore[return-value]


def _process_hooks(
    cfg: Path,
    script_dir: Path,
    hub_only: bool,
) -> None:
    """Run hooks-only or hub-only update for a single instance."""
    env = instanceenv.parse_env_file(cfg)
    game_id     = env.get("GAME_ID", "")
    instance_id = env.get("INSTANCE_ID") or game_id
    sys_user    = env.get("SYS_USER", "gameserver")
    app_dir     = env.get("APP_DIR", "")
    server_dir  = env.get("SERVER_DIR", "")
    data_dir    = env.get("DATA_DIR") or server_dir
    backup_dir  = env.get("BACKUP_DIR", "")
    world_name  = env.get("WORLD_NAME", "")
    admin_login = env.get("ADMIN_LOGIN", "admin")
    admin_password = env.get("ADMIN_PASSWORD", "")
    gc_service  = f"game-commander-{instance_id}"

    if not (game_id and instance_id and app_dir):
        console.warn(f"Config incomplète ignorée : {cfg}")
        return
    if not Path(app_dir).is_dir():
        console.warn(f"APP_DIR introuvable, instance ignorée : {app_dir}")
        return

    console.info(f"Mise à jour hooks de {instance_id} ({game_id})")

    if not hub_only:
        # Backups
        ok, msgs = deploybackups.install_backup_assets(
            sys_user=sys_user,
            app_dir=app_dir,
            backup_dir=backup_dir,
            instance_id=instance_id,
            game_id=game_id,
            server_dir=server_dir,
            data_dir=data_dir,
            world_name=world_name,
            skip_backup_test=True,
        )
        for msg in (msgs if isinstance(msgs, list) else [str(msgs)]):
            (console.ok if ok else console.warn)(msg)

        # CPU affinity
        core_groups = cpuplan.detect_core_groups()
        instances   = cpuplan.collect_managed_instances()
        plan        = cpuplan.plan_instances(instances, core_groups)
        for msg in cpuplan.apply_plan(plan, restart_running=False):
            console.ok(msg)

        # CPU monitor
        for msg in cpuplan.install_cpu_monitor(str(script_dir)):
            console.ok(msg)

    # Hub service
    ok_hub, msgs_hub = hubsync.sync_hub_service_from_values(
        sys_user=sys_user,
        app_dir=app_dir,
        admin_login=admin_login,
        admin_password=admin_password,
        repo_root=script_dir,
        restart=False,
    )
    for msg in (msgs_hub if isinstance(msgs_hub, list) else [str(msgs_hub)]):
        (console.ok if ok_hub else console.warn)(msg)
    if not ok_hub:
        console.warn("Échec synchro Hub Admin")

    # Restart GC service
    subprocess.run(["systemctl", "restart", gc_service], check=False)
    if sysutil.service_active(gc_service):
        console.ok(f"Service {gc_service} redémarré")
    else:
        console.warn(f"{gc_service} inactif après update — journalctl -u {gc_service} -n 30")


def _collect_configs() -> list[Path]:
    return list(hostctl.discover_instance_configs())


def _select_interactive(configs: list[Path]) -> list[Path] | None:
    """Interactive menu. Returns selected list, or None to cancel."""
    print()
    print(f"  {_CYAN}[0]{_RESET} Quit")
    for i, cfg in enumerate(configs, 1):
        env = instanceenv.parse_env_file(cfg)
        iid = env.get("INSTANCE_ID") or env.get("GAME_ID", "?")
        gid = env.get("GAME_ID", "?")
        print(f"  {_CYAN}[{i}]{_RESET} {_BOLD}{iid}{_RESET} ({gid})")
    print()

    choice = console.prompt("Numéro à mettre à jour, ou 'all'", "")
    if not choice or choice == "0":
        return None
    if choice == "all":
        return configs
    try:
        n = int(choice)
        if 1 <= n <= len(configs):
            return [configs[n - 1]]
    except ValueError:
        pass
    console.die(f"Choix invalide : {choice}")
    return None  # unreachable


def main() -> None:
    parser = argparse.ArgumentParser(description="Mise à jour des instances Game Commander")
    parser.add_argument("--script-dir", required=True)
    parser.add_argument("--instance", default="", help="Mettre à jour une instance précise")
    parser.add_argument("--all", action="store_true", dest="update_all",
                        help="Mettre à jour toutes les instances")
    parser.add_argument("--hooks-only", action="store_true",
                        help="Re-appliquer sauvegardes/CPU/hub sans rsync")
    parser.add_argument("--hub-only", action="store_true",
                        help="Re-synchroniser uniquement le Hub Admin")
    args = parser.parse_args()

    script_dir = Path(args.script_dir).resolve()
    hooks_only: bool = args.hooks_only or args.hub_only
    hub_only: bool   = args.hub_only

    if os.geteuid() != 0:
        console.die("Lancez en root : sudo ./gcctl update")

    console.hdr("Mise à jour des instances Game Commander")

    configs = _collect_configs()
    if not configs:
        console.die("Aucune instance Game Commander trouvée.")

    # Select which configs to process
    selected: list[Path] = []
    if args.update_all:
        selected = configs
    elif args.instance:
        for cfg in configs:
            env = instanceenv.parse_env_file(cfg)
            if env.get("INSTANCE_ID") == args.instance or env.get("GAME_ID") == args.instance:
                selected.append(cfg)
                break
        if not selected:
            console.die(f"Instance introuvable : {args.instance}")
    elif hooks_only:
        console.die("--hooks-only / --hub-only requièrent --instance")
    else:
        result = _select_interactive(configs)
        if result is None:
            console.info("Mise à jour annulée.")
            print()
            return
        selected = result

    # Hooks-only path: pure Python
    if hooks_only:
        console.sep()
        _process_hooks(selected[0], script_dir, hub_only)
        return

    # Normal path: delegate to host_cli.py (handles rsync, game.json, service restart, etc.)
    batch = len(selected) > 1
    for cfg in selected:
        console.sep()
        env = instanceenv.parse_env_file(cfg)
        instance_id = env.get("INSTANCE_ID") or env.get("GAME_ID", "")
        if not instance_id:
            console.die(f"INSTANCE_ID introuvable dans {cfg}")
        cmd = [
            "python3", str(script_dir / "tools" / "host_cli.py"),
            "update-instance",
            "--repo-root", str(script_dir),
            "--instance", instance_id,
        ]
        if batch:
            cmd.append("--skip-hub-sync")
        r = subprocess.run(cmd, check=False)
        if r.returncode != 0:
            console.die(f"Mise à jour échouée pour {instance_id}")

    if batch:
        console.sep()
        console.info("Synchronisation finale du Hub Admin")
        r = subprocess.run(
            ["python3", str(script_dir / "shared" / "hubsync.py"),
             "sync-config",
             "--config", str(selected[0]),
             "--repo-root", str(script_dir)],
            check=False,
        )
        if r.returncode != 0:
            console.die("Synchronisation finale du Hub échouée")


if __name__ == "__main__":
    main()
