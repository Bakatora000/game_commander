#!/usr/bin/env python3
"""Shared instance environment parsing and game metadata."""
from __future__ import annotations

from pathlib import Path


GAME_META: dict[str, dict[str, str]] = {
    "valheim": {
        "label": "Valheim",
        "binary": "valheim_server.x86_64",
        "service_prefix": "valheim-server",
    },
    "enshrouded": {
        "label": "Enshrouded",
        "binary": "enshrouded_server.exe",
        "service_prefix": "enshrouded-server",
    },
    "minecraft": {
        "label": "Minecraft Java",
        "binary": "java",
        "service_prefix": "minecraft-server",
    },
    "minecraft-fabric": {
        "label": "Minecraft Fabric",
        "binary": "java",
        "service_prefix": "minecraft-fabric-server",
    },
    "terraria": {
        "label": "Terraria",
        "binary": "TerrariaServer.bin.x86_64",
        "service_prefix": "terraria-server",
    },
    "satisfactory": {
        "label": "Satisfactory",
        "binary": "FactoryServer.sh",
        "service_prefix": "satisfactory-server",
    },
    "soulmask": {
        "label": "Soulmask",
        "binary": "StartServer.sh",
        "service_prefix": "soulmask-server",
    },
}


def parse_env_file(path: str | Path) -> dict[str, str]:
    env_path = Path(path)
    state: dict[str, str] = {}
    if not env_path.is_file():
        return state
    try:
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            state[key] = value.strip().strip('"')
    except Exception:
        return {}
    return state


def game_meta(game_id: str) -> dict[str, str]:
    return GAME_META.get(game_id, {})


def default_game_service(game_id: str, instance_id: str) -> str:
    meta = game_meta(game_id)
    prefix = meta.get("service_prefix") or f"{game_id}-server"
    return f"{prefix}-{instance_id}"


def load_instance_record(path: str | Path) -> dict[str, str]:
    cfg = Path(path).resolve()
    env = parse_env_file(cfg)
    game_id = env.get("GAME_ID", "")
    instance_id = env.get("INSTANCE_ID", "")
    record = {
        "config": str(cfg),
        "instance_id": instance_id,
        "game_id": game_id,
        "app_dir": env.get("APP_DIR", ""),
        "server_dir": env.get("SERVER_DIR", ""),
        "deploy_mode": env.get("DEPLOY_MODE", "managed"),
        "sys_user": env.get("SYS_USER", "gameserver"),
        "game_service": env.get("GAME_SERVICE") or (default_game_service(game_id, instance_id) if game_id and instance_id else ""),
        "game_label": game_meta(game_id).get("label", ""),
        "game_binary": game_meta(game_id).get("binary", ""),
    }
    return record

