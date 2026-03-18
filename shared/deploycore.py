#!/usr/bin/env python3
"""Native non-interactive deploy orchestration for Hub-driven instances."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from . import deployenv, hostops


def _write_temp_deploy_config(env: dict[str, str]) -> Path:
    fd, path_str = tempfile.mkstemp(prefix="gc-hub-deploy-", suffix=".env")
    path = Path(path_str)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        for key, value in env.items():
            escaped = str(value).replace('"', r'\"')
            fh.write(f'{key}="{escaped}"\n')
    return path


def run_deploy_instance(
    *,
    main_script: str | Path,
    game_id: str,
    instance_id: str,
    sys_user: str,
    repo_root: str | Path,
    domain: str,
    admin_login: str,
    admin_password: str,
    url_prefix: str = "",
    server_name: str = "",
    server_password: str = "",
    server_port: str = "",
    max_players: str = "",
) -> tuple[bool, list[str] | str]:
    env = deployenv.prepare_managed_instance_env(
        game_id=game_id,
        instance_id=instance_id,
        sys_user=sys_user,
        repo_root=repo_root,
        domain=domain,
        url_prefix=url_prefix,
        admin_login=admin_login,
        admin_password=admin_password,
        server_name=server_name,
        server_password=server_password,
        server_port=server_port,
        max_players=max_players,
    )
    temp_config = _write_temp_deploy_config(env)
    try:
        cmd = ["/bin/bash", str(Path(main_script).resolve()), "deploy", "--config", str(temp_config)]
        if os.geteuid() != 0:
            cmd.insert(0, "sudo")
        ok, message = hostops.run_command(
            cmd,
            timeout=1800,
        )
    finally:
        temp_config.unlink(missing_ok=True)
    if not ok:
        return False, message or "Déploiement échoué"
    lines = [line for line in (message or "").splitlines() if line.strip()]
    if not lines:
        lines.append(f"Instance {instance_id} déployée")
    return True, lines
