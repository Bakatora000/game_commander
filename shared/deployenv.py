#!/usr/bin/env python3
"""Shared deploy_config.env parsing and normalization."""
from __future__ import annotations

import argparse
import shlex
import sys
from pathlib import Path

if __package__ in {None, ""}:
    ROOT_DIR = Path(__file__).resolve().parents[1]
    if str(ROOT_DIR) not in sys.path:
        sys.path.insert(0, str(ROOT_DIR))
    from shared import instanceenv
else:
    from . import instanceenv


BASE_DEFAULTS: dict[str, str] = {
    "GAME_ID": "",
    "DEPLOY_MODE": "managed",
    "SYS_USER": "gameserver",
    "INSTANCE_ID": "",
    "SERVER_DIR": "",
    "DATA_DIR": "",
    "BACKUP_DIR": "",
    "APP_DIR": "",
    "SRC_DIR": "",
    "GAME_SERVICE": "",
    "SERVER_NAME": "Mon Serveur",
    "SERVER_PASSWORD": "",
    "SERVER_ADMIN_PASSWORD": "",
    "SERVER_PORT": "",
    "QUERY_PORT": "",
    "ECHO_PORT": "",
    "MAX_PLAYERS": "",
    "SERVER_MODE": "pve",
    "BACKUP_ENABLED": "true",
    "SAVING_ENABLED": "true",
    "BACKUP_INTERVAL": "7200",
    "WORLD_NAME": "Monde1",
    "CROSSPLAY": "false",
    "BEPINEX": "true",
    "DOMAIN": "monserveur.example.com",
    "URL_PREFIX": "",
    "FLASK_PORT": "",
    "SSL_MODE": "existing",
    "ADMIN_LOGIN": "admin",
    "ADMIN_PASSWORD": "",
    "AUTO_INSTALL_DEPS": "true",
    "AUTO_INSTALL_STEAMCMD": "true",
    "AUTO_INSTALL_BEPINEX": "true",
    "AUTO_UPDATE_SERVER": "false",
    "AUTO_CONFIRM": "true",
}

GAME_DEFAULTS: dict[str, dict[str, str]] = {
    "valheim": {
        "SERVER_PORT": "2456",
        "MAX_PLAYERS": "10",
        "URL_PREFIX": "/valheim",
        "FLASK_PORT": "5002",
        "SERVER_NAME": "Mon Serveur Valheim",
    },
    "enshrouded": {
        "SERVER_PORT": "15636",
        "MAX_PLAYERS": "16",
        "URL_PREFIX": "/enshrouded",
        "FLASK_PORT": "5003",
        "SERVER_NAME": "Mon Serveur Enshrouded",
    },
    "minecraft": {
        "SERVER_PORT": "25565",
        "MAX_PLAYERS": "20",
        "URL_PREFIX": "/minecraft",
        "FLASK_PORT": "5004",
        "SERVER_NAME": "Mon Serveur Minecraft Java",
    },
    "minecraft-fabric": {
        "SERVER_PORT": "25565",
        "MAX_PLAYERS": "20",
        "URL_PREFIX": "/minecraft-fabric",
        "FLASK_PORT": "5005",
        "SERVER_NAME": "Mon Serveur Minecraft Fabric",
    },
    "terraria": {
        "SERVER_PORT": "7777",
        "MAX_PLAYERS": "8",
        "URL_PREFIX": "/terraria",
        "FLASK_PORT": "5006",
        "SERVER_NAME": "Mon Serveur Terraria",
    },
    "satisfactory": {
        "SERVER_PORT": "7777",
        "QUERY_PORT": "8888",
        "MAX_PLAYERS": "8",
        "URL_PREFIX": "/satisfactory",
        "FLASK_PORT": "5007",
        "SERVER_NAME": "Mon Serveur Satisfactory",
    },
    "soulmask": {
        "SERVER_PORT": "8777",
        "QUERY_PORT": "27015",
        "ECHO_PORT": "18888",
        "MAX_PLAYERS": "50",
        "URL_PREFIX": "/soulmask",
        "FLASK_PORT": "5011",
        "SERVER_NAME": "Mon Serveur Soulmask",
        "SERVER_MODE": "pve",
        "BACKUP_INTERVAL": "7200",
    },
}


def normalize_deploy_env(path: str | Path) -> dict[str, str]:
    env = dict(BASE_DEFAULTS)
    env.update(instanceenv.parse_env_file(path))
    game_id = env.get("GAME_ID", "")
    if game_id in GAME_DEFAULTS:
        for key, value in GAME_DEFAULTS[game_id].items():
            if not env.get(key):
                env[key] = value
    return env


def to_shell_exports(env: dict[str, str]) -> str:
    lines = []
    for key in sorted(env):
        lines.append(f'{key}={shlex.quote(str(env[key]))}')
    return "\n".join(lines) + "\n"


def _cmd_exports(args: argparse.Namespace) -> int:
    cfg = Path(args.config)
    if not cfg.is_file():
        raise SystemExit(f"Fichier introuvable : {cfg}")
    print(to_shell_exports(normalize_deploy_env(cfg)), end="")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Game Commander deploy env helper")
    sub = parser.add_subparsers(dest="command", required=True)
    exports = sub.add_parser("exports")
    exports.add_argument("--config", required=True)
    exports.set_defaults(func=_cmd_exports)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
