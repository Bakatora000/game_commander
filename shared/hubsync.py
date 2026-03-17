#!/usr/bin/env python3
"""Native Hub Admin sync helpers."""
from __future__ import annotations

import json
import os
import pwd
import secrets
import shutil
import subprocess
from pathlib import Path

import bcrypt

from . import instanceenv

GC_NGINX_MANIFEST = "/etc/nginx/game-commander-manifest.json"
GC_CPU_MONITOR_STATE = "/var/lib/game-commander/cpu-monitor.json"
GC_HUB_PORT = "5090"


def _chown_tree(path: Path, sys_user: str) -> None:
    pw = pwd.getpwnam(sys_user)
    for root, dirs, files in os.walk(path):
        os.chown(root, pw.pw_uid, pw.pw_gid)
        for name in dirs:
            os.chown(Path(root, name), pw.pw_uid, pw.pw_gid)
        for name in files:
            os.chown(Path(root, name), pw.pw_uid, pw.pw_gid)


def _hash_from_source_users(source_users_file: Path, admin_login: str) -> str:
    if not source_users_file.is_file():
        return ""
    try:
        users = json.loads(source_users_file.read_text(encoding="utf-8"))
    except Exception:
        return ""
    user = users.get(admin_login, {})
    return user.get("password_hash", "")


def _hub_admin_hash(env: dict[str, str], source_users_file: Path) -> str:
    admin_password = env.get("ADMIN_PASSWORD", "")
    if admin_password:
        return bcrypt.hashpw(admin_password.encode(), bcrypt.gensalt()).decode()
    admin_login = env.get("ADMIN_LOGIN", "")
    if admin_login:
        return _hash_from_source_users(source_users_file, admin_login)
    return ""


def _write_hub_users(env: dict[str, str], hub_users_file: Path, source_users_file: Path) -> bool:
    if hub_users_file.is_file():
        return True
    admin_login = env.get("ADMIN_LOGIN", "").strip()
    admin_hash = _hub_admin_hash(env, source_users_file)
    if not admin_login or not admin_hash:
        return False
    hub_users_file.write_text(
        json.dumps(
            {
                admin_login: {
                    "password_hash": admin_hash,
                    "permissions": ["view_hub"],
                }
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    hub_users_file.chmod(0o600)
    return True


def _write_hub_service(repo_root: Path, hub_app_dir: Path, sys_user: str) -> None:
    hub_secret = secrets.token_hex(32)
    service_file = Path("/etc/systemd/system/game-commander-hub.service")
    service_file.write_text(
        "[Unit]\n"
        "Description=Game Commander — Hub Admin\n"
        "After=network.target\n\n"
        "[Service]\n"
        "Type=simple\n"
        f"User={sys_user}\n"
        f"WorkingDirectory={hub_app_dir}\n"
        f'Environment="GAME_COMMANDER_HUB_SECRET={hub_secret}"\n'
        f'Environment="GC_HUB_PORT={GC_HUB_PORT}"\n'
        f'Environment="GC_HUB_MANIFEST={GC_NGINX_MANIFEST}"\n'
        f'Environment="GC_HUB_CPU_MONITOR_STATE={GC_CPU_MONITOR_STATE}"\n'
        f'Environment="GC_HUB_MAIN_SCRIPT={repo_root / "game_commander.sh"}"\n'
        f'Environment="GC_HUB_HOST_CLI={repo_root / "tools" / "host_cli.py"}"\n'
        f"ExecStart=/usr/bin/python3 {hub_app_dir / 'app.py'}\n"
        "Restart=on-failure\n"
        "RestartSec=5\n"
        "StandardOutput=journal\n"
        "StandardError=journal\n\n"
        "[Install]\n"
        "WantedBy=multi-user.target\n",
        encoding="utf-8",
    )


def _write_hub_sudoers(repo_root: Path, sys_user: str) -> None:
    host_cli = repo_root / "tools" / "host_cli.py"
    sudoers_file = Path("/etc/sudoers.d/game-commander-hub")
    sudoers_file.write_text(
        "# Game Commander — Hub actions\n"
        f"{sys_user} ALL=(ALL) NOPASSWD: /usr/bin/python3 {host_cli} service-action --service * --action *\n"
        f"{sys_user} ALL=(ALL) NOPASSWD: /usr/bin/python3 {host_cli} update-instance --main-script * --instance *\n"
        f"{sys_user} ALL=(ALL) NOPASSWD: /usr/bin/python3 {host_cli} redeploy-instance --main-script * --config *\n"
        f"{sys_user} ALL=(ALL) NOPASSWD: /usr/bin/python3 {host_cli} uninstall-instance --main-script * --instance *\n"
        f"{sys_user} ALL=(ALL) NOPASSWD: /usr/bin/python3 {host_cli} rebalance --main-script *\n"
        f"{sys_user} ALL=(ALL) NOPASSWD: /usr/bin/python3 {host_cli} rebalance --main-script * --restart\n",
        encoding="utf-8",
    )
    sudoers_file.chmod(0o440)
    subprocess.run(["visudo", "-cf", str(sudoers_file)], check=True, capture_output=True, text=True)


def sync_hub_service(config_file: str | Path, repo_root: str | Path) -> tuple[bool, list[str] | str]:
    env = instanceenv.parse_env_file(config_file)
    sys_user = env.get("SYS_USER", "").strip()
    if not sys_user:
        return False, "SYS_USER manquant pour la synchro Hub"

    repo_root = Path(repo_root).resolve()
    runtime_hub_src = repo_root / "runtime_hub"
    if not runtime_hub_src.is_dir():
        return False, "Sources runtime_hub introuvables"

    home_dir = Path(pwd.getpwnam(sys_user).pw_dir)
    hub_app_dir = home_dir / "game-commander-hub"
    hub_users_file = hub_app_dir / "users.json"
    source_users_file = Path(env.get("APP_DIR", "")) / "users.json"
    hub_app_dir.mkdir(parents=True, exist_ok=True)

    subprocess.run(
        [
            "rsync",
            "-a",
            "--delete",
            "--exclude=__pycache__",
            "--exclude=*.pyc",
            "--exclude=users.json",
            f"{runtime_hub_src}/",
            f"{hub_app_dir}/",
        ],
        check=True,
    )
    _write_hub_users(env, hub_users_file, source_users_file)
    _write_hub_service(repo_root, hub_app_dir, sys_user)
    _write_hub_sudoers(repo_root, sys_user)
    _chown_tree(hub_app_dir, sys_user)
    subprocess.run(["systemctl", "daemon-reload"], check=False)
    subprocess.run(["systemctl", "enable", "game-commander-hub"], check=False, capture_output=True, text=True)
    subprocess.run(["systemctl", "restart", "game-commander-hub"], check=True)
    return True, [f"Hub Admin synchronisé : {hub_app_dir}", "Service game-commander-hub redémarré"]
