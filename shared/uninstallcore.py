#!/usr/bin/env python3
"""Native non-interactive uninstall helpers for managed Game Commander instances."""
from __future__ import annotations

import os
import pwd
import shutil
import subprocess
from pathlib import Path

from . import hostctl, instanceenv

GC_NGINX_MANIFEST = Path("/etc/nginx/game-commander-manifest.json")
GC_NGINX_LOCATIONS = Path("/etc/nginx/game-commander-locations.conf")
GC_NGINX_HUB_HTML = Path("/etc/nginx/game-commander-hub.html")
GC_HUB_PORT = "5090"


def _run(cmd: list[str], check: bool = False, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        check=check,
        capture_output=True,
        text=True,
        input=input_text,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )


def _path_value(env: dict[str, str], key: str) -> Path | None:
    value = env.get(key, "").strip()
    return Path(value) if value else None


def _shared_with_other_instances(path: Path, current_cfg: Path) -> list[str]:
    shared: list[str] = []
    needle = str(path)
    for cfg in hostctl.discover_instance_configs():
        if cfg == current_cfg:
            continue
        env = instanceenv.parse_env_file(cfg)
        values = {
            env.get("APP_DIR", ""),
            env.get("SERVER_DIR", ""),
            env.get("DATA_DIR", ""),
            env.get("BACKUP_DIR", ""),
        }
        if needle in values:
            shared.append(env.get("INSTANCE_ID") or env.get("GAME_ID") or str(cfg))
    return shared


def _effective_backup_dir(env: dict[str, str]) -> Path | None:
    backup_dir = _path_value(env, "BACKUP_DIR")
    if not backup_dir:
        return None
    instance_id = env.get("INSTANCE_ID", "")
    if not instance_id:
        return backup_dir
    if backup_dir.name == instance_id:
        return backup_dir
    instance_subdir = backup_dir / instance_id
    if instance_subdir.exists():
        return instance_subdir
    return backup_dir


def _remove_tree_if_owned(path: Path | None, label: str, current_cfg: Path, messages: list[str]) -> None:
    if not path or not path.exists():
        return
    others = _shared_with_other_instances(path, current_cfg)
    if others:
        messages.append(f"{label} conservé : partagé avec {', '.join(sorted(others))}")
        return
    shutil.rmtree(path, ignore_errors=True)
    messages.append(f"{label} supprimé : {path}")


def _stop_disable_remove_service(service: str, messages: list[str]) -> None:
    unit = f"{service}.service"
    unit_file = Path("/etc/systemd/system") / unit
    _run(["systemctl", "stop", service])
    _run(["systemctl", "disable", service])
    if unit_file.exists():
        unit_file.unlink()
        messages.append(f"Service supprimé : {service}")
    else:
        messages.append(f"Service absent : {service}")
    _run(["systemctl", "daemon-reload"])


def _remove_nginx_instance(instance_id: str, repo_root: Path, messages: list[str]) -> None:
    if not GC_NGINX_MANIFEST.is_file():
        return
    check = _run(
        [
            "python3",
            str(repo_root / "tools" / "nginx_manager.py"),
            "manifest-check",
            "--manifest",
            str(GC_NGINX_MANIFEST),
            "--instance-id",
            instance_id,
        ]
    )
    if check.returncode != 0:
        return
    _run(
        [
            "python3",
            str(repo_root / "tools" / "nginx_manager.py"),
            "manifest-remove",
            "--manifest",
            str(GC_NGINX_MANIFEST),
            "--instance-id",
            instance_id,
        ],
        check=False,
    )
    _run(
        [
            "python3",
            str(repo_root / "tools" / "nginx_manager.py"),
            "regenerate",
            "--manifest",
            str(GC_NGINX_MANIFEST),
            "--out",
            str(GC_NGINX_LOCATIONS),
            "--hub-file",
            str(GC_NGINX_HUB_HTML),
            "--hub-port",
            GC_HUB_PORT,
        ],
        check=False,
    )
    test = _run(["nginx", "-t"])
    if test.returncode == 0:
        _run(["systemctl", "reload", "nginx"])
        messages.append(f"Nginx mis à jour pour {instance_id}")
    else:
        messages.append(f"Nginx à vérifier manuellement pour {instance_id}")


def _remove_sudoers(game_id: str, instance_id: str, messages: list[str]) -> None:
    gc_service = f"game-commander-{instance_id}"
    for path in (
        Path(f"/etc/sudoers.d/game-commander-{game_id}"),
        Path(f"/etc/sudoers.d/game-commander-{instance_id}"),
        Path(f"/etc/sudoers.d/{gc_service}"),
    ):
        if path.is_file():
            path.unlink()
            messages.append(f"Sudoers supprimé : {path.name}")


def _remove_cron(sys_user: str, app_dir: Path, messages: list[str]) -> None:
    current = _run(["crontab", "-u", sys_user, "-l"])
    if current.returncode != 0 or not current.stdout:
        return
    filtered = [line for line in current.stdout.splitlines() if str(app_dir) not in line]
    if filtered == current.stdout.splitlines():
        return
    new_content = "\n".join(filtered).rstrip("\n")
    if new_content:
        new_content += "\n"
    _run(["crontab", "-u", sys_user, "-"], input_text=new_content)
    messages.append(f"Cron nettoyé pour {sys_user}")


def _home_dir_for_user(sys_user: str) -> Path:
    return Path(pwd.getpwnam(sys_user).pw_dir)


def _discover_partial_app_dir(instance_id: str) -> Path | None:
    candidates = []
    for root in hostctl.DEFAULT_SEARCH_ROOTS:
        root_path = Path(root)
        if not root_path.exists():
            continue
        if root_path.name == "root":
            candidate = root_path / f"game-commander-{instance_id}"
            candidates.append(candidate)
            continue
        for home in root_path.iterdir():
            if not home.is_dir():
                continue
            candidates.append(home / f"game-commander-{instance_id}")
    for candidate in candidates:
        if candidate.is_dir():
            return candidate.resolve()
    return None


def _infer_env_for_partial_instance(instance_id: str, game_id: str) -> dict[str, str] | None:
    app_dir = _discover_partial_app_dir(instance_id)
    if not app_dir:
        return None
    home_dir = app_dir.parent
    sys_user = ""
    try:
        sys_user = pwd.getpwuid(app_dir.stat().st_uid).pw_name
    except KeyError:
        if home_dir.parent == Path("/home"):
            sys_user = home_dir.name
    backup_dir = home_dir / "gamebackups"
    return {
        "INSTANCE_ID": instance_id,
        "GAME_ID": game_id,
        "SYS_USER": sys_user,
        "APP_DIR": str(app_dir),
        "SERVER_DIR": str(home_dir / f"{instance_id}_server"),
        "DATA_DIR": str(home_dir / f"{instance_id}_data"),
        "BACKUP_DIR": str(backup_dir),
        "GAME_SERVICE": instanceenv.default_game_service(game_id, instance_id),
    }


def run_full_uninstall(config_file: str | Path, repo_root: str | Path) -> tuple[bool, list[str] | str]:
    cfg = Path(config_file).resolve()
    env = instanceenv.parse_env_file(cfg)
    instance_id = env.get("INSTANCE_ID") or env.get("GAME_ID", "")
    game_id = env.get("GAME_ID", "")
    if not instance_id or not game_id:
        return False, "Config d'instance incomplète"

    messages: list[str] = []
    repo_root = Path(repo_root).resolve()
    game_service = env.get("GAME_SERVICE") or instanceenv.default_game_service(game_id, instance_id)
    gc_service = f"game-commander-{instance_id}"

    _stop_disable_remove_service(game_service, messages)
    _stop_disable_remove_service(gc_service, messages)
    _remove_nginx_instance(instance_id, repo_root, messages)
    _remove_sudoers(game_id, instance_id, messages)

    sys_user = env.get("SYS_USER", "").strip()
    app_dir = _path_value(env, "APP_DIR")
    if sys_user and app_dir and app_dir.exists():
        _remove_cron(sys_user, app_dir, messages)

    _remove_tree_if_owned(app_dir, "Répertoire Game Commander", cfg, messages)
    server_dir = _path_value(env, "SERVER_DIR")
    data_dir = _path_value(env, "DATA_DIR")
    _remove_tree_if_owned(server_dir, "Répertoire serveur", cfg, messages)
    if data_dir and data_dir != server_dir:
        _remove_tree_if_owned(data_dir, "Répertoire données", cfg, messages)
    _remove_tree_if_owned(_effective_backup_dir(env), "Répertoire sauvegardes", cfg, messages)

    if sys_user:
        steamcmd_dir = _home_dir_for_user(sys_user) / "steamcmd"
        _remove_tree_if_owned(steamcmd_dir, "SteamCMD", cfg, messages)

    if cfg.exists():
        try:
            cfg.unlink()
            messages.append(f"Config supprimée : {cfg}")
        except FileNotFoundError:
            pass

    return True, messages


def run_partial_uninstall(instance_id: str, game_id: str, repo_root: str | Path) -> tuple[bool, list[str] | str]:
    env = _infer_env_for_partial_instance(instance_id, game_id)
    if not env:
        return False, "Configuration d'instance introuvable"

    messages: list[str] = []
    repo_root = Path(repo_root).resolve()
    game_service = env.get("GAME_SERVICE") or instanceenv.default_game_service(game_id, instance_id)
    gc_service = f"game-commander-{instance_id}"

    _stop_disable_remove_service(game_service, messages)
    _stop_disable_remove_service(gc_service, messages)
    _remove_nginx_instance(instance_id, repo_root, messages)
    _remove_sudoers(game_id, instance_id, messages)

    sys_user = env.get("SYS_USER", "").strip()
    app_dir = _path_value(env, "APP_DIR")
    if sys_user and app_dir and app_dir.exists():
        _remove_cron(sys_user, app_dir, messages)

    cfg = Path(env["APP_DIR"]) / "deploy_config.env"
    _remove_tree_if_owned(app_dir, "Répertoire Game Commander", cfg, messages)
    server_dir = _path_value(env, "SERVER_DIR")
    data_dir = _path_value(env, "DATA_DIR")
    _remove_tree_if_owned(server_dir, "Répertoire serveur", cfg, messages)
    if data_dir and data_dir != server_dir:
        _remove_tree_if_owned(data_dir, "Répertoire données", cfg, messages)
    _remove_tree_if_owned(_effective_backup_dir(env), "Répertoire sauvegardes", cfg, messages)

    return True, messages
