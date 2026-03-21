#!/usr/bin/env python3
"""Shared deploy_config.env parsing and normalization."""
from __future__ import annotations

import argparse
import os
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

TEMPLATE_TEXT = """# ═══════════════════════════════════════════════════════════════════════════════
#  Game Commander — Fichier de configuration de déploiement
#  Usage : sudo ./gcctl deploy --config env/deploy_config.env
# ═══════════════════════════════════════════════════════════════════════════════

# Jeu : valheim | enshrouded | minecraft | minecraft-fabric | terraria | soulmask | satisfactory
GAME_ID="valheim"

# Mode de déploiement : managed | attach
DEPLOY_MODE="managed"

# Utilisateur système
SYS_USER="gameserver"

# Chemins (laisser vide = valeur par défaut basée sur le home de SYS_USER)
INSTANCE_ID=""      # identifiant unique (ex. valheim2, mc-skyblock)
SERVER_DIR=""
DATA_DIR=""
BACKUP_DIR=""
APP_DIR=""
SRC_DIR=""          # racine du projet Game Commander ou dossier runtime
GAME_SERVICE=""     # vide = nom par défaut, utile en mode attach

# Configuration du serveur de jeu
SERVER_NAME="Mon Serveur Valheim"
SERVER_PASSWORD=""
SERVER_ADMIN_PASSWORD=""
SERVER_PORT=""          # vide = défaut du jeu
QUERY_PORT=""           # Soulmask / Satisfactory
ECHO_PORT=""            # Soulmask uniquement
MAX_PLAYERS=""
SERVER_MODE="pve"       # Soulmask : pve | pvp
BACKUP_ENABLED=true     # Soulmask
SAVING_ENABLED=true     # Soulmask
BACKUP_INTERVAL="7200"  # Soulmask, en secondes
WORLD_NAME="Monde1"     # Valheim uniquement
CROSSPLAY=false
BEPINEX=true

# Interface web Game Commander
DOMAIN="monserveur.example.com"
URL_PREFIX=""           # vide = défaut du jeu
FLASK_PORT=""
SSL_MODE="existing"     # certbot | none | existing

# Compte administrateur
ADMIN_LOGIN="admin"
ADMIN_PASSWORD=""       # OBLIGATOIRE — renseigner ici ou laisser vide pour prompt

# Automatisation
AUTO_INSTALL_DEPS=true
AUTO_INSTALL_STEAMCMD=true
AUTO_INSTALL_BEPINEX=true
AUTO_UPDATE_SERVER=false
AUTO_CONFIRM=true
"""


def apply_game_defaults(env: dict[str, str]) -> dict[str, str]:
    merged = dict(BASE_DEFAULTS)
    merged.update(env)
    game_id = merged.get("GAME_ID", "")
    if game_id in GAME_DEFAULTS:
        for key, value in GAME_DEFAULTS[game_id].items():
            if not merged.get(key):
                merged[key] = value
    return merged


def runtime_src_dir(src_dir: str | Path) -> Path | None:
    root = Path(src_dir)
    candidate = root / "runtime"
    if (candidate / "app.py").is_file():
        return candidate
    if (root / "app.py").is_file():
        return root
    return None


def validate_config_file(path: str | Path, required: tuple[str, ...] = ("GAME_ID", "INSTANCE_ID")) -> tuple[bool, str]:
    cfg = Path(path)
    if not cfg.is_file():
        return False, f"Fichier introuvable : {cfg}"
    env = normalize_deploy_env(cfg)
    missing = [key for key in required if not env.get(key)]
    if missing:
        return False, f"Config invalide : {', '.join(missing)} manquant(s) dans {cfg}"
    return True, ""


def fill_defaults_from_process_env() -> dict[str, str]:
    env = {key: os.environ.get(key, "") for key in BASE_DEFAULTS}
    return apply_game_defaults(env)


def render_template() -> str:
    return TEMPLATE_TEXT


def prepare_managed_instance_env(
    *,
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
) -> dict[str, str]:
    repo_path = Path(repo_root).resolve()
    home_dir = Path.home() if not sys_user else Path(f"~{sys_user}").expanduser()
    env = apply_game_defaults(
        {
            "GAME_ID": game_id,
            "DEPLOY_MODE": "managed",
            "INSTANCE_ID": instance_id,
            "SYS_USER": sys_user,
            "DOMAIN": domain,
            "ADMIN_LOGIN": admin_login or "admin",
            "ADMIN_PASSWORD": admin_password,
            "AUTO_CONFIRM": "true",
        }
    )
    env["SERVER_DIR"] = str(home_dir / f"{instance_id}_server")
    env["DATA_DIR"] = str(home_dir / f"{instance_id}_data")
    if game_id == "enshrouded":
        env["DATA_DIR"] = env["SERVER_DIR"]
    env["BACKUP_DIR"] = str(home_dir / "gamebackups")
    env["APP_DIR"] = str(home_dir / f"game-commander-{instance_id}")
    env["SRC_DIR"] = str(repo_path)
    env["GAME_SERVICE"] = f"{game_id}-server-{instance_id}"
    if url_prefix:
        env["URL_PREFIX"] = url_prefix
    if server_name:
        env["SERVER_NAME"] = server_name
    if server_password:
        env["SERVER_PASSWORD"] = server_password
    if server_port:
        env["SERVER_PORT"] = str(server_port)
    if max_players:
        env["MAX_PLAYERS"] = str(max_players)
    return env


def normalize_deploy_env(path: str | Path) -> dict[str, str]:
    return apply_game_defaults(instanceenv.parse_env_file(path))


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


def _cmd_fill_defaults(_args: argparse.Namespace) -> int:
    print(to_shell_exports(fill_defaults_from_process_env()), end="")
    return 0


def _cmd_template(args: argparse.Namespace) -> int:
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_template(), encoding="utf-8")
    print(out)
    return 0


def _cmd_runtime_src(args: argparse.Namespace) -> int:
    resolved = runtime_src_dir(args.src_dir)
    if not resolved:
        print(f"Sources runtime introuvables dans {args.src_dir}", file=sys.stderr)
        return 1
    print(resolved)
    return 0


def _cmd_validate_config(args: argparse.Namespace) -> int:
    ok, message = validate_config_file(args.config, tuple(args.require))
    if not ok:
        print(message, file=sys.stderr)
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Game Commander deploy env helper")
    sub = parser.add_subparsers(dest="command", required=True)
    exports = sub.add_parser("exports")
    exports.add_argument("--config", required=True)
    exports.set_defaults(func=_cmd_exports)
    fill_defaults = sub.add_parser("fill-defaults")
    fill_defaults.set_defaults(func=_cmd_fill_defaults)
    template = sub.add_parser("template")
    template.add_argument("--out", required=True)
    template.set_defaults(func=_cmd_template)
    runtime_src = sub.add_parser("runtime-src")
    runtime_src.add_argument("--src-dir", required=True)
    runtime_src.set_defaults(func=_cmd_runtime_src)
    validate = sub.add_parser("validate-config")
    validate.add_argument("--config", required=True)
    validate.add_argument("--require", action="append", default=["GAME_ID", "INSTANCE_ID"])
    validate.set_defaults(func=_cmd_validate_config)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
