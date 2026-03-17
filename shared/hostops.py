#!/usr/bin/env python3
"""Shared host action builders/execution for Game Commander."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path


def run_command(cmd: list[str], timeout: int = 300) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
    except Exception as exc:
        return False, str(exc)
    if result.returncode == 0:
        return True, (result.stdout or "").strip()
    message = (result.stderr or result.stdout or "").strip()
    return False, message or f"Commande échouée ({result.returncode})"


def service_action_cmd(service_name: str, action: str) -> list[str]:
    if action not in {"start", "stop", "restart"}:
        raise ValueError(f"Unsupported service action: {action}")
    return ["sudo", "/usr/bin/systemctl", action, service_name]


def update_instance_cmd(main_script: str | Path, instance_name: str) -> list[str]:
    return ["sudo", "/bin/bash", str(main_script), "update", "--instance", instance_name]


def redeploy_instance_cmd(main_script: str | Path, config_file: str | Path) -> list[str]:
    return ["sudo", "/bin/bash", str(main_script), "deploy", "--config", str(config_file)]


def uninstall_instance_cmd(main_script: str | Path, instance_name: str) -> list[str]:
    return [
        "sudo", "/bin/bash", str(main_script),
        "uninstall", "--instance", instance_name, "--full", "--yes",
    ]


def rebalance_cmd(main_script: str | Path, restart: bool = False) -> list[str]:
    cmd = ["sudo", "/bin/bash", str(main_script), "rebalance"]
    if restart:
        cmd.append("--restart")
    return cmd


def service_action_success_message(action: str, instance_name: str) -> str:
    labels = {
        "start": f"Démarrage lancé pour {instance_name}",
        "stop": f"Arrêt lancé pour {instance_name}",
        "restart": f"Redémarrage lancé pour {instance_name}",
    }
    return labels.get(action, "Action lancée")

