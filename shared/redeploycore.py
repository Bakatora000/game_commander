#!/usr/bin/env python3
"""Native non-interactive redeploy orchestration."""
from __future__ import annotations

from pathlib import Path

from . import deployenv, hostops


def run_redeploy(config_file: str | Path, main_script: str | Path) -> tuple[bool, list[str] | str]:
    cfg = Path(config_file).resolve()
    if not cfg.is_file():
        return False, f"Fichier de config introuvable : {cfg}"

    env = deployenv.normalize_deploy_env(cfg)
    missing = [key for key in ("GAME_ID", "INSTANCE_ID", "SYS_USER") if not env.get(key)]
    if missing:
        return False, f"Config de déploiement incomplète : {', '.join(missing)}"

    ok, message = hostops.run_command(
        hostops.redeploy_instance_cmd(main_script, cfg),
        timeout=1200,
    )
    if not ok:
        return False, message or "Échec redéploiement"

    lines = []
    if message:
        lines.extend([line for line in message.splitlines() if line.strip()])
    if not lines:
        lines.append(f"Instance {env['INSTANCE_ID']} redéployée")
    return True, lines
