#!/usr/bin/env python3
"""Native Hub Admin sync helpers."""
from __future__ import annotations

import argparse
import json
import os
import pwd
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

import bcrypt

if __package__ in {None, ""}:
    ROOT_DIR = Path(__file__).resolve().parents[1]
    if str(ROOT_DIR) not in sys.path:
        sys.path.insert(0, str(ROOT_DIR))
    from shared import instanceenv
else:
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


def _read_existing_hub_secret() -> str:
    service_file = Path("/etc/systemd/system/game-commander-hub.service")
    if service_file.is_file():
        for line in service_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if "GAME_COMMANDER_HUB_SECRET=" in line:
                # Environment="GAME_COMMANDER_HUB_SECRET=<value>"
                value = line.split("GAME_COMMANDER_HUB_SECRET=", 1)[1].rstrip('"')
                if value:
                    return value
    return secrets.token_hex(32)


def _write_hub_service(repo_root: Path, hub_app_dir: Path, sys_user: str) -> None:
    hub_secret = _read_existing_hub_secret()
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
        f"{sys_user} ALL=(ALL) NOPASSWD: /usr/bin/python3 {host_cli} deploy-instance --main-script * --game-id * --instance * --domain * --admin-login * --admin-password * --sys-user *\n"
        f"{sys_user} ALL=(ALL) NOPASSWD: /usr/bin/python3 {host_cli} redeploy-instance --main-script * --config *\n"
        f"{sys_user} ALL=(ALL) NOPASSWD: /usr/bin/python3 {host_cli} uninstall-instance --main-script * --instance *\n"
        f"{sys_user} ALL=(ALL) NOPASSWD: /usr/bin/python3 {host_cli} rebalance --main-script *\n"
        f"{sys_user} ALL=(ALL) NOPASSWD: /usr/bin/python3 {host_cli} rebalance --main-script * --restart\n",
        encoding="utf-8",
    )
    sudoers_file.chmod(0o440)
    subprocess.run(["visudo", "-cf", str(sudoers_file)], check=True, capture_output=True, text=True)


def _sync_hub_from_env(env: dict[str, str], repo_root: str | Path) -> tuple[bool, list[str] | str]:
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
            "--exclude=shared",
            f"{runtime_hub_src}/",
            f"{hub_app_dir}/",
        ],
        check=True,
    )
    shared_src = repo_root / "shared"
    if shared_src.is_dir():
        subprocess.run(
            [
                "rsync",
                "-a",
                "--delete",
                "--exclude=__pycache__",
                "--exclude=*.pyc",
                f"{shared_src}/",
                f"{hub_app_dir}/shared/",
            ],
            check=True,
        )
    _write_hub_users(env, hub_users_file, source_users_file)
    _write_hub_service(repo_root, hub_app_dir, sys_user)
    _write_hub_sudoers(repo_root, sys_user)
    _chown_tree(hub_app_dir, sys_user)
    subprocess.run(["systemctl", "daemon-reload"], check=False)
    subprocess.run(["systemctl", "enable", "game-commander-hub"], check=False, capture_output=True, text=True)
    # Restart detached so the caller's stdout pipe is not broken mid-deploy.
    # The Hub may be the parent of the process that called hubsync; restarting
    # it synchronously would kill the pipe and stop the bash deploy script.
    subprocess.Popen(
        ["systemctl", "restart", "game-commander-hub"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return True, [f"Hub Admin synchronisé : {hub_app_dir}", "Service game-commander-hub redémarré"]


def sync_hub_service(config_file: str | Path, repo_root: str | Path) -> tuple[bool, list[str] | str]:
    return _sync_hub_from_env(instanceenv.parse_env_file(config_file), repo_root)


def sync_hub_service_from_values(
    *,
    sys_user: str,
    app_dir: str,
    admin_login: str,
    admin_password: str = "",
    repo_root: str | Path,
) -> tuple[bool, list[str] | str]:
    env = {
        "SYS_USER": sys_user,
        "APP_DIR": app_dir,
        "ADMIN_LOGIN": admin_login,
        "ADMIN_PASSWORD": admin_password,
    }
    return _sync_hub_from_env(env, repo_root)


def _cmd_sync_from_config(args: argparse.Namespace) -> int:
    ok, result = sync_hub_service(args.config, args.repo_root)
    if not ok:
        print(result)
        return 1
    for line in result:
        print(line)
    return 0


def _cmd_sync_from_values(args: argparse.Namespace) -> int:
    ok, result = sync_hub_service_from_values(
        sys_user=args.sys_user,
        app_dir=args.app_dir,
        admin_login=args.admin_login,
        admin_password=args.admin_password,
        repo_root=args.repo_root,
    )
    if not ok:
        print(result)
        return 1
    for line in result:
        print(line)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Game Commander Hub sync helper")
    sub = parser.add_subparsers(dest="command", required=True)

    sync_cfg = sub.add_parser("sync-config")
    sync_cfg.add_argument("--config", required=True)
    sync_cfg.add_argument("--repo-root", required=True)
    sync_cfg.set_defaults(func=_cmd_sync_from_config)

    sync_values = sub.add_parser("sync-values")
    sync_values.add_argument("--sys-user", required=True)
    sync_values.add_argument("--app-dir", required=True)
    sync_values.add_argument("--admin-login", required=True)
    sync_values.add_argument("--admin-password", default="")
    sync_values.add_argument("--repo-root", required=True)
    sync_values.set_defaults(func=_cmd_sync_from_values)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
