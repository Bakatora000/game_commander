#!/usr/bin/env python3
"""Post-deploy helpers shared by deploy and redeploy flows."""
from __future__ import annotations

import argparse
import os
import pwd
import subprocess
import sys
from datetime import datetime
from pathlib import Path

if __package__ in {None, ""}:
    ROOT_DIR = Path(__file__).resolve().parents[1]
    if str(ROOT_DIR) not in sys.path:
        sys.path.insert(0, str(ROOT_DIR))
    from shared import deployenv, instanceenv
else:
    from . import deployenv, instanceenv


def _bool(env: dict[str, str], key: str, default: bool = False) -> bool:
    value = str(env.get(key, str(default).lower())).strip().lower()
    return value in {"1", "true", "yes", "y", "o", "oui"}


def _query_port(env: dict[str, str]) -> str:
    return env.get("QUERY_PORT", "")


def _echo_port(env: dict[str, str]) -> str:
    return env.get("ECHO_PORT", "")


def render_saved_config(env: dict[str, str], config_path: str | Path) -> str:
    config_path = Path(config_path)
    lines = [
        f"# Game Commander — Config sauvegardée le {datetime.now():%Y-%m-%d %H:%M:%S}",
        f"# Redéploiement : sudo bash game_commander.sh deploy --config {config_path}",
        "",
        f'GAME_ID="{env.get("GAME_ID", "")}"',
        f'DEPLOY_MODE="{env.get("DEPLOY_MODE", "managed")}"',
        f'INSTANCE_ID="{env.get("INSTANCE_ID", "")}"',
        f'SYS_USER="{env.get("SYS_USER", "")}"',
        f'SERVER_DIR="{env.get("SERVER_DIR", "")}"',
        f'DATA_DIR="{env.get("DATA_DIR", "")}"',
        f'BACKUP_DIR="{env.get("BACKUP_DIR", "")}"',
        f'APP_DIR="{env.get("APP_DIR", "")}"',
        f'SRC_DIR="{env.get("SRC_DIR", "")}"',
        f'GAME_SERVICE="{env.get("GAME_SERVICE", "")}"',
        f'SERVER_NAME="{env.get("SERVER_NAME", "")}"',
        f'SERVER_PORT="{env.get("SERVER_PORT", "")}"',
    ]
    if _query_port(env):
        lines.append(f'QUERY_PORT="{_query_port(env)}"')
    if _echo_port(env):
        lines.append(f'ECHO_PORT="{_echo_port(env)}"')
    lines.append(f'MAX_PLAYERS="{env.get("MAX_PLAYERS", "")}"')
    if env.get("GAME_ID") == "valheim":
        lines.extend(
            [
                f'WORLD_NAME="{env.get("WORLD_NAME", "")}"',
                f'CROSSPLAY={str(_bool(env, "CROSSPLAY")).lower()}',
                f'BEPINEX={str(_bool(env, "BEPINEX", True)).lower()}',
            ]
        )
    if env.get("GAME_ID") == "soulmask":
        lines.extend(
            [
                'SERVER_ADMIN_PASSWORD=""',
                f'SERVER_MODE="{env.get("SERVER_MODE", "pve")}"',
                f'BACKUP_ENABLED={str(_bool(env, "BACKUP_ENABLED", True)).lower()}',
                f'SAVING_ENABLED={str(_bool(env, "SAVING_ENABLED", True)).lower()}',
                f'BACKUP_INTERVAL="{env.get("BACKUP_INTERVAL", "7200")}"',
            ]
        )
    lines.extend(
        [
            f'DOMAIN="{env.get("DOMAIN", "")}"',
            f'URL_PREFIX="{env.get("URL_PREFIX", "")}"',
            f'FLASK_PORT="{env.get("FLASK_PORT", "")}"',
            f'SSL_MODE="{env.get("SSL_MODE", "existing")}"',
            f'ADMIN_LOGIN="{env.get("ADMIN_LOGIN", "admin")}"',
            "# ADMIN_PASSWORD=  <-- ne pas sauvegarder en clair",
            "AUTO_INSTALL_DEPS=true",
            "AUTO_UPDATE_SERVER=false",
            "AUTO_CONFIRM=true",
            "",
        ]
    )
    return "\n".join(lines)


def save_deploy_config(env: dict[str, str], config_path: str | Path) -> tuple[bool, str]:
    config_path = Path(config_path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(render_saved_config(env, config_path), encoding="utf-8")
    try:
        config_path.chmod(0o600)
    except OSError:
        pass
    sys_user = env.get("SYS_USER", "").strip()
    if sys_user:
        pw = pwd.getpwnam(sys_user)
        os.chown(config_path, pw.pw_uid, pw.pw_gid)
    return True, f"Config sauvegardée : {config_path}"


def save_deploy_config_from_process_env(config_path: str | Path) -> tuple[bool, str]:
    env = dict(deployenv.BASE_DEFAULTS)
    for key in deployenv.BASE_DEFAULTS:
        value = os.environ.get(key)
        if value is not None:
            env[key] = value
    game_id = env.get("GAME_ID", "")
    if game_id in deployenv.GAME_DEFAULTS:
        for key, value in deployenv.GAME_DEFAULTS[game_id].items():
            if not env.get(key):
                env[key] = value
    return save_deploy_config(env, config_path)


def _service_active(service: str) -> bool:
    return subprocess.run(["systemctl", "is-active", "--quiet", service], check=False).returncode == 0


def _http_ok(url: str) -> bool:
    return subprocess.run(["curl", "-sf", url, "-o", "/dev/null"], check=False).returncode == 0


def validation_report(env: dict[str, str], config_path: str | Path) -> tuple[int, list[str], str]:
    errors = 0
    lines: list[str] = []
    game_service = env.get("GAME_SERVICE") or instanceenv.default_game_service(env.get("GAME_ID", ""), env.get("INSTANCE_ID", ""))
    gc_service = f"game-commander-{env.get('INSTANCE_ID', '')}"
    deploy_app = bool(env.get("APP_DIR"))
    if _service_active(game_service):
        lines.append(f"Service {game_service} : actif")
    else:
        lines.append(f"Service {game_service} : inactif")
        errors += 1
    if deploy_app:
        url = f"http://127.0.0.1:{env.get('FLASK_PORT', '')}{env.get('URL_PREFIX', '')}"
        if _http_ok(url):
            lines.append(f"Game Commander répond sur :{env.get('FLASK_PORT', '')}{env.get('URL_PREFIX', '')}")
        else:
            lines.append("Game Commander ne répond pas encore")
            errors += 1
    if _service_active("nginx"):
        lines.append("Nginx : actif")
    else:
        lines.append("Nginx : inactif")
        errors += 1

    scheme = "https" if env.get("SSL_MODE", "existing") != "none" else "http"
    access_url = f"{scheme}://{env.get('DOMAIN', '')}{env.get('URL_PREFIX', '')}"
    summary = "\n".join(
        [
            f"Accès : {access_url}",
            f"Redéploiement : sudo bash game_commander.sh deploy --config {Path(config_path)}",
        ]
    )
    return errors, lines, summary


def firewall_specs(env: dict[str, str]) -> list[str]:
    game_id = env.get("GAME_ID", "")
    server_port = env.get("SERVER_PORT", "")
    query_port = env.get("QUERY_PORT", "")
    echo_port = env.get("ECHO_PORT", "")
    if game_id in {"minecraft", "minecraft-fabric", "terraria"}:
        return [f"{server_port}/tcp", "80/tcp", "443/tcp"]
    if game_id == "satisfactory":
        return [f"{server_port}/tcp", f"{server_port}/udp", f"{query_port}/tcp", "80/tcp", "443/tcp"]
    if game_id == "soulmask":
        return [f"{server_port}/udp", f"{query_port}/udp", f"{echo_port}/tcp", "80/tcp", "443/tcp"]
    return [f"{server_port}/udp", f"{int(server_port) + 1}/udp", "80/tcp", "443/tcp"] if server_port else ["80/tcp", "443/tcp"]


def validation_lines(env: dict[str, str], config_path: str | Path) -> list[str]:
    errors, lines, summary = validation_report(env, config_path)
    rendered = [f"VALIDATION_ERRORS={errors}"]
    rendered.extend(lines)
    rendered.append(summary)
    rendered.extend(f"FIREWALL={spec}" for spec in firewall_specs(env))
    return rendered


def save_from_file(config_file: str | Path) -> tuple[bool, str]:
    env = deployenv.normalize_deploy_env(config_file)
    app_dir = Path(env.get("APP_DIR", ""))
    if not app_dir:
        return False, "APP_DIR introuvable"
    return save_deploy_config(env, app_dir / "deploy_config.env")


def _cmd_save(args: argparse.Namespace) -> int:
    env = deployenv.normalize_deploy_env(args.config)
    ok, message = save_deploy_config(env, args.config)
    if not ok:
        print(message)
        return 1
    print(message)
    return 0


def _cmd_save_values(args: argparse.Namespace) -> int:
    ok, message = save_deploy_config_from_process_env(args.config)
    if not ok:
        print(message)
        return 1
    print(message)
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    env = deployenv.normalize_deploy_env(args.config)
    for line in validation_lines(env, args.config):
        print(line)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Game Commander deploy post helpers")
    sub = parser.add_subparsers(dest="command", required=True)
    save = sub.add_parser("save")
    save.add_argument("--config", required=True)
    save.set_defaults(func=_cmd_save)
    save_values = sub.add_parser("save-values")
    save_values.add_argument("--config", required=True)
    save_values.set_defaults(func=_cmd_save_values)
    validate = sub.add_parser("validate")
    validate.add_argument("--config", required=True)
    validate.set_defaults(func=_cmd_validate)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
