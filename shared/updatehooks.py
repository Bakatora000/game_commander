#!/usr/bin/env python3
"""Native post-update hooks for Game Commander instances."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from . import cpuplan, deploybackups, hostops, instanceenv


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
    ok, backup_messages = deploybackups.install_backup_assets(
        sys_user=env.get("SYS_USER", "gameserver"),
        app_dir=env["APP_DIR"],
        backup_dir=env["BACKUP_DIR"],
        instance_id=env["INSTANCE_ID"],
        game_id=env["GAME_ID"],
        server_dir=env.get("SERVER_DIR", ""),
        data_dir=env.get("DATA_DIR") or env.get("SERVER_DIR", ""),
        world_name=env.get("WORLD_NAME", ""),
        skip_backup_test=True,
    )
    if not ok:
        return False, backup_messages or "Échec configuration sauvegardes"
    messages.extend(backup_messages)

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
