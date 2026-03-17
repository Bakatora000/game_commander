#!/usr/bin/env python3
"""Native post-update hooks for Game Commander instances."""
from __future__ import annotations

import os
import pwd
import subprocess
from pathlib import Path

from . import cpuplan, hostops, instanceenv


def _chown(path: Path, sys_user: str) -> None:
    pw = pwd.getpwnam(sys_user)
    os.chown(path, pw.pw_uid, pw.pw_gid)


def _ensure_dir(path: Path, sys_user: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _chown(path, sys_user)


def _effective_backup_dir(env: dict[str, str]) -> Path:
    backup_dir = Path(env["BACKUP_DIR"])
    instance_id = env.get("INSTANCE_ID", "")
    if instance_id and backup_dir.name != instance_id:
        return backup_dir / instance_id
    return backup_dir


def _world_dir(env: dict[str, str]) -> Path:
    game_id = env["GAME_ID"]
    server_dir = Path(env.get("SERVER_DIR", ""))
    data_dir = Path(env.get("DATA_DIR") or env.get("SERVER_DIR", ""))
    if game_id == "valheim":
        worlds_local = data_dir / "worlds_local"
        return worlds_local if worlds_local.is_dir() else data_dir / "worlds"
    if game_id == "enshrouded":
        return server_dir / "savegame"
    if game_id in {"minecraft", "minecraft-fabric"}:
        return server_dir / "world"
    if game_id == "terraria":
        return data_dir
    if game_id == "satisfactory":
        return data_dir / ".config" / "Epic" / "FactoryGame" / "Saved" / "SaveGames"
    if game_id == "soulmask":
        return server_dir / "WS" / "Saved"
    return server_dir


def _backup_script_content(env: dict[str, str], effective_backup_dir: Path, world_dir: Path) -> str:
    game_id = env["GAME_ID"]
    if game_id == "valheim":
        world_name = env.get("WORLD_NAME", "Monde1")
        return f"""#!/usr/bin/env bash
BACKUP_DIR="{effective_backup_dir}"
WORLD_DIR="{world_dir}"
WORLD_NAME="{world_name}"
RETENTION=7
TS=$(date +%Y%m%d_%H%M%S)
ARC="${{BACKUP_DIR}}/${{WORLD_NAME}}_${{TS}}.zip"
FILES=()
for f in "${{WORLD_DIR}}/${{WORLD_NAME}}.db" "${{WORLD_DIR}}/${{WORLD_NAME}}.fwl" "${{WORLD_DIR}}/${{WORLD_NAME}}.db.old" "${{WORLD_DIR}}/${{WORLD_NAME}}.fwl.old"; do
    [[ -f "$f" ]] && FILES+=("$f")
done
[[ ${{#FILES[@]}} -eq 0 ]] && {{ echo "[$(date)] WARN: aucun fichier monde" >&2; exit 1; }}
mkdir -p "$BACKUP_DIR"
zip -j "$ARC" "${{FILES[@]}}" -q && echo "[$(date)] OK: $(basename "$ARC") ($(du -sh "$ARC"|cut -f1))" || {{ echo "[$(date)] ERROR: zip échoué" >&2; exit 1; }}
find "$BACKUP_DIR" -name "${{WORLD_NAME}}_*.zip" -mtime +${{RETENTION}} -delete
"""
    if game_id in {"minecraft", "minecraft-fabric"}:
        server_dir = Path(env["SERVER_DIR"])
        return f"""#!/usr/bin/env bash
BACKUP_DIR="{effective_backup_dir}"
SERVER_DIR="{server_dir}"
WORLD_DIR="{world_dir}"
PREFIX="{game_id}"
RETENTION=7
TS=$(date +%Y%m%d_%H%M%S)
ARC="${{BACKUP_DIR}}/${{PREFIX}}_save_${{TS}}.zip"
[[ ! -d "$WORLD_DIR" ]] && {{ echo "[$(date)] WARN: $WORLD_DIR introuvable" >&2; exit 1; }}
mkdir -p "$BACKUP_DIR"
FILES=("$(basename "$WORLD_DIR")")
for f in server.properties ops.json whitelist.json banned-players.json banned-ips.json usercache.json; do
    [[ -f "$SERVER_DIR/$f" ]] && FILES+=("$f")
done
(
    cd "$SERVER_DIR"
    zip -r "$ARC" "${{FILES[@]}}" -q
) && echo "[$(date)] OK: $(basename "$ARC") ($(du -sh "$ARC"|cut -f1))" || {{ echo "[$(date)] ERROR" >&2; exit 1; }}
find "$BACKUP_DIR" -name "${{PREFIX}}_save_*.zip" -mtime +${{RETENTION}} -delete
"""
    return f"""#!/usr/bin/env bash
BACKUP_DIR="{effective_backup_dir}"
WORLD_DIR="{world_dir}"
PREFIX="{game_id}"
RETENTION=7
TS=$(date +%Y%m%d_%H%M%S)
ARC="${{BACKUP_DIR}}/${{PREFIX}}_save_${{TS}}.zip"
[[ ! -d "$WORLD_DIR" ]] && {{ echo "[$(date)] WARN: $WORLD_DIR introuvable" >&2; exit 1; }}
mkdir -p "$BACKUP_DIR"
ROOT_PARENT="$(dirname "$WORLD_DIR")"
ROOT_NAME="$(basename "$WORLD_DIR")"
(
    cd "$ROOT_PARENT"
    zip -r "$ARC" "$ROOT_NAME" -q
) && echo "[$(date)] OK: $(basename "$ARC") ($(du -sh "$ARC"|cut -f1))" || {{ echo "[$(date)] ERROR" >&2; exit 1; }}
find "$BACKUP_DIR" -name "${{PREFIX}}_save_*.zip" -mtime +${{RETENTION}} -delete
"""


def _install_backup_hook(env: dict[str, str]) -> str:
    sys_user = env.get("SYS_USER", "gameserver")
    app_dir = Path(env["APP_DIR"])
    _ensure_dir(app_dir, sys_user)
    effective_backup_dir = _effective_backup_dir(env)
    _ensure_dir(effective_backup_dir, sys_user)
    world_dir = _world_dir(env)
    script_path = app_dir / f"backup_{env['GAME_ID']}.sh"
    script_path.write_text(_backup_script_content(env, effective_backup_dir, world_dir), encoding="utf-8")
    script_path.chmod(0o755)
    _chown(script_path, sys_user)
    cron_line = f"0 3 * * * {script_path} >> {app_dir}/backup_{env['GAME_ID']}.log 2>&1"
    existing = subprocess.run(["crontab", "-u", sys_user, "-l"], capture_output=True, text=True, check=False)
    current = existing.stdout if existing.returncode == 0 else ""
    if cron_line not in current:
        new_content = current.rstrip("\n")
        if new_content:
            new_content += "\n"
        new_content += cron_line + "\n"
        subprocess.run(["crontab", "-u", sys_user, "-"], input=new_content, text=True, check=False)
    return str(script_path)


def _install_cpu_monitor(repo_root: Path) -> None:
    state_file = Path(os.environ.get("GC_CPU_MONITOR_STATE", "/var/lib/game-commander/cpu-monitor.json"))
    state_file.parent.mkdir(parents=True, exist_ok=True)
    script_path = repo_root / "tools" / "cpu_monitor.py"
    if not script_path.is_file():
        return
    service_file = Path("/etc/systemd/system/game-commander-cpu-monitor.service")
    timer_file = Path("/etc/systemd/system/game-commander-cpu-monitor.timer")
    service_file.write_text(
        "[Unit]\n"
        "Description=Game Commander — CPU imbalance monitor\n"
        "After=network.target\n\n"
        "[Service]\n"
        "Type=oneshot\n"
        f"ExecStart=/usr/bin/python3 {script_path} --state-file {state_file}\n",
        encoding="utf-8",
    )
    timer_file.write_text(
        "[Unit]\n"
        "Description=Game Commander — CPU imbalance monitor (timer)\n\n"
        "[Timer]\n"
        "OnBootSec=2min\n"
        "OnUnitActiveSec=1min\n"
        "RandomizedDelaySec=10s\n"
        "Persistent=true\n\n"
        "[Install]\n"
        "WantedBy=timers.target\n",
        encoding="utf-8",
    )
    subprocess.run(["systemctl", "daemon-reload"], check=False)
    subprocess.run(["systemctl", "enable", "--now", "game-commander-cpu-monitor.timer"], check=False)
    subprocess.run(["systemctl", "start", "game-commander-cpu-monitor.service"], check=False)


def run_post_update_hooks(config_file: str | Path, repo_root: str | Path) -> tuple[bool, list[str] | str]:
    env = instanceenv.parse_env_file(config_file)
    if not env.get("INSTANCE_ID") or not env.get("GAME_ID"):
        return False, "Config d'instance incomplète"
    messages: list[str] = []
    backup_script = _install_backup_hook(env)
    messages.append(f"Script de sauvegarde : {backup_script}")

    core_groups = cpuplan.detect_core_groups()
    if core_groups:
        plan = cpuplan.plan_instances(cpuplan.collect_managed_instances(), core_groups)
        for line in cpuplan.apply_plan(plan, restart_running=False):
            messages.append(line)

    _install_cpu_monitor(Path(repo_root))
    messages.append("Monitor CPU vérifié")

    gc_service = f"game-commander-{env['INSTANCE_ID']}"
    ok, message = hostops.run_command(["systemctl", "restart", gc_service], timeout=60)
    if not ok:
        return False, message or f"Échec restart {gc_service}"
    messages.append(f"Service {gc_service} redémarré")
    return True, messages

