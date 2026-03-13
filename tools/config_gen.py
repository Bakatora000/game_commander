#!/usr/bin/env python3
"""
config_gen.py — Génération des fichiers de configuration pour Game Commander.

Sous-commandes :
  game-json        Génère game.json pour une instance.
  users-json       Génère users.json (compte admin).
  enshrouded-cfg   Génère enshrouded_server.json.
  minecraft-props  Génère server.properties pour Minecraft.
  terraria-cfg     Génère serverconfig.txt pour Terraria.
  soulmask-cfg     Génère soulmask_server.json.
  patch-bepinex    Injecte les paramètres dans start_server_bepinex.sh.

Usage :
  python3 tools/config_gen.py game-json --out /path/game.json \\
      --game-id valheim --game-label Valheim \\
      --game-binary valheim_server.x86_64 --game-service valheim-server-valheim8 \\
      --server-dir /home/gameserver/valheim8_server \\
      --data-dir /home/gameserver/valheim8_data --world-name Monde1 \\
      --max-players 10 --port 5900 \\
      --url-prefix /valheim8 --flask-port 5002 --admin-user admin \\
      [--bepinex-path /path/BepInEx] [--steam-appid 896660] [--steamcmd-path /path]

  python3 tools/config_gen.py users-json --out /path/users.json \\
      --admin admin --hash '$2b$...' --game-id valheim

  python3 tools/config_gen.py enshrouded-cfg --out /path/enshrouded_server.json \\
      --name "Mon Serveur" --password "xxx" --port 15639 --max-players 16

  python3 tools/config_gen.py minecraft-props --out /path/server.properties \\
      --name "Mon Serveur" --port 25565 --max-players 20

  python3 tools/config_gen.py terraria-cfg --out /path/serverconfig.txt \\
      --name "Mon Serveur" --port 7777 --max-players 8 --world-path /srv/worlds

  python3 tools/config_gen.py soulmask-cfg --out /path/soulmask_server.json \\
      --name "Mon Serveur" --port 8777 --query-port 27015 --echo-port 18888 \\
      --max-players 50 --password xxx --admin-password yyy --mode pve

  python3 tools/config_gen.py patch-bepinex --script /path/start_server_bepinex.sh \\
      --name "Mon Serveur" --port 5900 --world Monde1 --password xxx \\
      --savedir /home/gameserver/valheim8_data [--extra-flag -playfab]
"""

import argparse
import json
import re
import sys
from pathlib import Path


# ── Sous-commandes ─────────────────────────────────────────────────────────────

def cmd_game_json(args):
    game_id    = args.game_id
    game_label = args.game_label

    logos = {"valheim": "⚔", "enshrouded": "🌿", "minecraft": "⛏", "minecraft-fabric": "🧵", "terraria": "🌳", "soulmask": "🗿"}
    module_id = game_id.replace('-', '_')
    template_id = module_id
    theme_name = game_id

    game = {
        "id":       game_id,
        "module_id": module_id,
        "template_id": template_id,
        "name":     game_label,
        "subtitle": args.game_label,
        "logo":     logos.get(game_id, "🎮"),
        "server": {
            "binary":      args.game_binary,
            "service":     args.game_service,
            "install_dir": args.server_dir,
            "data_dir":    args.data_dir or args.server_dir,
            "world_name":  args.world_name if game_id == "valheim" else None,
            "max_players": args.max_players,
            "port":        args.port,
        },
        "web": {
            "url_prefix": args.url_prefix,
            "flask_port": args.flask_port,
            "admin_user": args.admin_user,
        },
        "features": {
            "mods":    (game_id == "valheim" and bool(args.bepinex_path)) or game_id == "minecraft-fabric",
            "config":  game_id in ("valheim", "enshrouded", "minecraft", "minecraft-fabric", "terraria", "soulmask"),
            "console": True,
            "players": game_id in ("valheim", "enshrouded", "minecraft", "minecraft-fabric"),
        },
        "theme": {"name": theme_name if theme_name in ("valheim", "enshrouded", "minecraft") else "valheim"},
    }

    if game_id == "minecraft-fabric":
        theme_name = "minecraft"
        game["theme"]["name"] = theme_name
    elif game_id == "soulmask":
        theme_name = "enshrouded"
        game["theme"]["name"] = theme_name

    # Permissions
    if game_id == "valheim":
        game["permissions"] = [
            "start_server", "stop_server", "restart_server",
            "install_mod", "remove_mod", "manage_config", "console", "manage_users",
        ]
    elif game_id == "enshrouded":
        game["permissions"] = [
            "start_server", "stop_server", "restart_server",
            "manage_config", "console", "manage_users",
        ]
    elif game_id == "minecraft":
        game["permissions"] = [
            "start_server", "stop_server", "restart_server",
            "manage_config", "console", "manage_users",
        ]
    elif game_id == "minecraft-fabric":
        game["permissions"] = [
            "start_server", "stop_server", "restart_server",
            "install_mod", "remove_mod", "manage_config", "console", "manage_users",
        ]
    elif game_id == "terraria":
        game["permissions"] = [
            "start_server", "stop_server", "restart_server",
            "manage_config", "console", "manage_users",
        ]
    elif game_id == "soulmask":
        game["permissions"] = [
            "start_server", "stop_server", "restart_server",
            "manage_config", "console", "manage_users",
        ]
    else:
        game["permissions"] = [
            "start_server", "stop_server", "restart_server",
            "console", "manage_users",
        ]

    # Mods BepInEx
    if game_id == "valheim" and args.bepinex_path:
        game["mods"] = {
            "platform":     "thunderstore",
            "community":    "valheim",
            "bepinex_path": args.bepinex_path,
        }
    elif game_id == "minecraft-fabric":
        game["mods"] = {
            "platform": "modrinth",
            "loader": "fabric",
            "mods_path": f"{args.server_dir}/mods",
            "meta_path": f"{args.server_dir}/.fabric-meta.json",
        }

    # SteamCMD
    if args.steam_appid:
        game["steamcmd"] = {
            "app_id": args.steam_appid,
            "path":   args.steamcmd_path or "",
        }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(game, indent=2, ensure_ascii=False) + "\n")
    print(f"[config_gen] game.json généré : {out}")
    return 0


def cmd_users_json(args):
    game_id = args.game_id

    if game_id == "valheim":
        perms = [
            "start_server", "stop_server", "restart_server",
            "install_mod", "remove_mod", "manage_config", "console", "manage_users",
        ]
    else:
        perms = [
            "start_server", "stop_server", "restart_server",
            "manage_config", "console", "manage_users",
        ]

    data = {args.admin: {"password_hash": args.hash, "permissions": perms}}

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=2) + "\n")
    print(f"[config_gen] users.json généré : {out}")
    return 0


def cmd_enshrouded_cfg(args):
    # Sur redéploiement, récupérer le mot de passe existant si non fourni.
    # Les versions récentes d'Enshrouded stockent le mot de passe dans userGroups[*].password
    # plutôt qu'au niveau racine du JSON.
    password = args.password
    if not password and Path(args.out).is_file():
        try:
            existing = json.loads(Path(args.out).read_text())
            if isinstance(existing.get("userGroups"), list):
                for group in existing["userGroups"]:
                    if group.get("name", "").lower() == "default" and group.get("password"):
                        password = group["password"]
                        break
                if not password and existing["userGroups"]:
                    password = existing["userGroups"][0].get("password", "")
            if not password:
                password = existing.get("password", "")
            if password:
                print(f"[config_gen] Mot de passe récupéré depuis {args.out}")
        except (json.JSONDecodeError, OSError):
            pass

    cfg = {
        "name": "Mon Serveur",
        "saveDirectory": "./savegame",
        "logDirectory": "./logs",
        "ip": "0.0.0.0",
        "queryPort": args.port + 1,
        "slotCount": args.max_players,
        "tags": [],
        "voiceChatMode": "Proximity",
        "enableVoiceChat": False,
        "enableTextChat": False,
        "gameSettingsPreset": "Default",
        "userGroups": [
            {
                "name": "Default",
                "password": password or "",
                "canKickBan": False,
                "canAccessInventories": True,
                "canEditWorld": True,
                "canEditBase": True,
                "canExtendBase": True,
                "reservedSlots": 0,
            }
        ],
        "bannedAccounts": [],
    }
    cfg["name"] = args.name

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(cfg, indent=2) + "\n")
    print(f"[config_gen] enshrouded_server.json généré : {out}")
    return 0


def cmd_patch_bepinex(args):
    script_path = Path(args.script)
    if not script_path.is_file():
        print(f"[config_gen] ERROR: script introuvable : {script_path}", file=sys.stderr)
        return 1

    extra = f" {args.extra_flag}" if args.extra_flag else ""
    new_exec = (
        f'exec ./valheim_server.x86_64'
        f' -name "{args.name}"'
        f' -port {args.port}'
        f' -world "{args.world}"'
        f' -password "{args.password}"'
        f' -savedir "{args.savedir}"'
        f' -public 1{extra}'
    )

    content = script_path.read_text()
    if re.search(r"^exec \./valheim_server", content, re.MULTILINE):
        content = re.sub(
            r"^exec \./valheim_server.*$",
            new_exec,
            content,
            flags=re.MULTILINE,
        )
    else:
        content = content.rstrip("\n") + "\n" + new_exec + "\n"

    script_path.write_text(content)
    print(f"[config_gen] exec injecté dans {script_path} : {new_exec[:80]}...")
    return 0


def cmd_minecraft_props(args):
    props = {
        "allow-nether": "true",
        "difficulty": "easy",
        "enable-command-block": "false",
        "gamemode": "survival",
        "max-players": str(args.max_players),
        "motd": args.name,
        "pvp": "true",
        "server-port": str(args.port),
        "simulation-distance": "10",
        "spawn-animals": "true",
        "spawn-monsters": "true",
        "view-distance": "10",
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Minecraft server properties",
        "# Generated by Game Commander",
    ] + [f"{key}={props[key]}" for key in sorted(props)]
    out.write_text("\n".join(lines) + "\n")
    print(f"[config_gen] server.properties généré : {out}")
    return 0


def cmd_terraria_cfg(args):
    world_file = str(Path(args.world_path) / f"{args.world_name}.wld")
    cfg = {
        "worldpath": args.world_path,
        "worldname": args.world_name,
        "world": world_file,
        "autocreate": str(args.autocreate),
        "difficulty": str(args.difficulty),
        "port": str(args.port),
        "maxplayers": str(args.max_players),
        "password": args.password or "",
        "motd": args.name,
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Terraria server config",
        "# Generated by Game Commander",
    ] + [f"{key}={cfg[key]}" for key in (
        "world", "worldpath", "worldname", "autocreate", "difficulty",
        "port", "maxplayers", "password", "motd"
    )]
    out.write_text("\n".join(lines) + "\n")
    print(f"[config_gen] serverconfig.txt généré : {out}")
    return 0


def cmd_soulmask_cfg(args):
    cfg = {
        "server_name": args.name,
        "max_players": args.max_players,
        "password": args.password or "",
        "admin_password": args.admin_password or "",
        "mode": args.mode,
        "port": args.port,
        "query_port": args.query_port,
        "echo_port": args.echo_port,
        "backup_enabled": args.backup_enabled,
        "saving_enabled": args.saving_enabled,
        "backup_interval": args.backup_interval,
        "log_dir": args.log_dir,
        "saved_dir": args.saved_dir,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(cfg, indent=2) + "\n")
    print(f"[config_gen] soulmask_server.json généré : {out}")
    return 0


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Génération des fichiers de config Game Commander",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # game-json
    p = sub.add_parser("game-json", help="Génère game.json")
    p.add_argument("--out",           required=True)
    p.add_argument("--game-id",       required=True)
    p.add_argument("--game-label",    required=True)
    p.add_argument("--game-binary",   required=True)
    p.add_argument("--game-service",  required=True)
    p.add_argument("--server-dir",    required=True)
    p.add_argument("--data-dir",      default="")
    p.add_argument("--world-name",    default="")
    p.add_argument("--max-players",   required=True, type=int)
    p.add_argument("--port",          required=True, type=int)
    p.add_argument("--url-prefix",    required=True)
    p.add_argument("--flask-port",    required=True, type=int)
    p.add_argument("--admin-user",    required=True)
    p.add_argument("--bepinex-path",  default="")
    p.add_argument("--steam-appid",   default="")
    p.add_argument("--steamcmd-path", default="")

    # users-json
    p = sub.add_parser("users-json", help="Génère users.json")
    p.add_argument("--out",     required=True)
    p.add_argument("--admin",   required=True)
    p.add_argument("--hash",    required=True)
    p.add_argument("--game-id", required=True)

    # enshrouded-cfg
    p = sub.add_parser("enshrouded-cfg", help="Génère enshrouded_server.json")
    p.add_argument("--out",         required=True)
    p.add_argument("--name",        required=True)
    p.add_argument("--password",    default="")
    p.add_argument("--port",        required=True, type=int)
    p.add_argument("--max-players", required=True, type=int)

    # patch-bepinex
    p = sub.add_parser("patch-bepinex", help="Injecte les params dans start_server_bepinex.sh")
    p.add_argument("--script",      required=True)
    p.add_argument("--name",        required=True)
    p.add_argument("--port",        required=True, type=int)
    p.add_argument("--world",       required=True)
    p.add_argument("--password",    required=True)
    p.add_argument("--savedir",     required=True)
    p.add_argument("--extra-flag",  default="")

    # minecraft-props
    p = sub.add_parser("minecraft-props", help="Génère server.properties")
    p.add_argument("--out", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--port", required=True, type=int)
    p.add_argument("--max-players", required=True, type=int)

    # terraria-cfg
    p = sub.add_parser("terraria-cfg", help="Génère serverconfig.txt")
    p.add_argument("--out", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--port", required=True, type=int)
    p.add_argument("--max-players", required=True, type=int)
    p.add_argument("--world-path", required=True)
    p.add_argument("--world-name", default="World1")
    p.add_argument("--password", default="")
    p.add_argument("--autocreate", type=int, default=2)
    p.add_argument("--difficulty", type=int, default=0)

    # soulmask-cfg
    p = sub.add_parser("soulmask-cfg", help="Génère soulmask_server.json")
    p.add_argument("--out", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--port", required=True, type=int)
    p.add_argument("--query-port", required=True, type=int)
    p.add_argument("--echo-port", required=True, type=int)
    p.add_argument("--max-players", required=True, type=int)
    p.add_argument("--password", default="")
    p.add_argument("--admin-password", default="")
    p.add_argument("--mode", choices=["pve", "pvp"], default="pve")
    p.add_argument("--backup-enabled", type=lambda v: str(v).lower() == "true", default=True)
    p.add_argument("--saving-enabled", type=lambda v: str(v).lower() == "true", default=True)
    p.add_argument("--backup-interval", type=int, default=7200)
    p.add_argument("--log-dir", required=True)
    p.add_argument("--saved-dir", required=True)

    args = parser.parse_args()

    dispatch = {
        "game-json":      cmd_game_json,
        "users-json":     cmd_users_json,
        "enshrouded-cfg": cmd_enshrouded_cfg,
        "minecraft-props": cmd_minecraft_props,
        "terraria-cfg":  cmd_terraria_cfg,
        "soulmask-cfg":  cmd_soulmask_cfg,
        "patch-bepinex":  cmd_patch_bepinex,
    }
    sys.exit(dispatch[args.command](args))


if __name__ == "__main__":
    main()
