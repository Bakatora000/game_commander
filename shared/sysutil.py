#!/usr/bin/env python3
"""System-level helpers — Python equivalents of helpers.sh utility functions."""
from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path


def service_state(name: str) -> str:
    """Return the systemctl is-active state: 'active', 'inactive', 'failed', etc."""
    result = subprocess.run(
        ["systemctl", "is-active", name],
        capture_output=True, text=True, check=False,
    )
    return result.stdout.strip() or "inactive"


def service_active(name: str) -> bool:
    """Return True if the service is currently active."""
    return service_state(name) == "active"


def service_enabled(name: str) -> bool:
    """Return True if the service is enabled."""
    result = subprocess.run(
        ["systemctl", "is-enabled", "--quiet", name],
        capture_output=True, check=False,
    )
    return result.returncode == 0


def cmd_exists(name: str) -> bool:
    """Return True if the command is available on PATH."""
    return shutil.which(name) is not None


def wait_for_process(pattern: str, timeout: int = 30) -> bool:
    """Wait until a process matching *pattern* appears. Returns True if found within timeout."""
    elapsed = 0
    while elapsed < timeout:
        result = subprocess.run(
            ["pgrep", "-f", pattern],
            capture_output=True, check=False,
        )
        if result.returncode == 0:
            return True
        time.sleep(2)
        elapsed += 2
    return False


def stop_and_disable(service: str, dry_run: bool = False) -> list[str]:
    """Stop, disable, and remove the systemd unit file for *service*.

    Returns a list of human-readable log messages.
    """
    messages: list[str] = []
    unit_file = Path("/etc/systemd/system") / f"{service}.service"
    dropin_dir = Path("/etc/systemd/system") / f"{service}.service.d"

    def _run(cmd: list[str]) -> None:
        if not dry_run:
            subprocess.run(cmd, capture_output=True, check=False)

    if service_state(service) != "inactive":
        _run(["systemctl", "stop", service])

    _run(["systemctl", "disable", service])

    if unit_file.exists():
        if not dry_run:
            unit_file.unlink()
        messages.append(f"Service supprimé : {service}")
    else:
        messages.append(f"Service absent : {service}")

    if dropin_dir.is_dir() and not dry_run:
        shutil.rmtree(dropin_dir, ignore_errors=True)

    _run(["systemctl", "daemon-reload"])
    return messages


def shared_by_others(check_dir: str | Path, current_cfg: str | Path) -> list[str]:
    """Return instance IDs of other deploy configs that reference *check_dir*."""
    from . import hostctl, instanceenv  # lazy to avoid circular imports

    needle = str(check_dir)
    current = str(current_cfg)
    others: list[str] = []
    for cfg in hostctl.discover_instance_configs():
        if str(cfg) == current:
            continue
        env = instanceenv.parse_env_file(cfg)
        values = {
            env.get("APP_DIR", ""),
            env.get("SERVER_DIR", ""),
            env.get("DATA_DIR", ""),
            env.get("BACKUP_DIR", ""),
        }
        if needle in values:
            others.append(env.get("INSTANCE_ID") or env.get("GAME_ID") or str(cfg))
    return others
