"""
games/terraria/worlds.py
Détection et sélection du monde Terraria actif.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from flask import current_app

from . import config as terraria_config


def _game():
    return current_app.config["GAME"]


def _server_dir() -> Path:
    return Path(_game()["server"]["install_dir"])


def _data_dir() -> Path:
    data_dir = _game()["server"].get("data_dir") or _game()["server"]["install_dir"]
    return Path(data_dir)


def _app_dir() -> Path:
    return Path(current_app.root_path)


def _safe_world_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", (name or "").strip()).strip("-")


def _replace_or_append_line(path: Path, pattern: str, new_line: str):
    lines = []
    matched = False
    if path.exists():
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    out = []
    rx = re.compile(pattern)
    for line in lines:
        if rx.match(line):
            out.append(new_line)
            matched = True
        else:
            out.append(line)
    if not matched:
        out.append(new_line)
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def _known_worlds():
    root = _data_dir()
    worlds = {}
    if root.exists():
        for child in root.iterdir():
            if not child.is_file():
                continue
            lower = child.name.lower()
            if lower.endswith(".wld"):
                worlds[child.stem] = True
    current, _err = terraria_config.read_config()
    current_world = (current.get("worldname") or "").strip() if current else ""
    if current_world:
        worlds.setdefault(current_world, False)
    return [{"name": name, "exists": exists} for name, exists in sorted(worlds.items(), key=lambda it: it[0].lower())]


def list_worlds():
    current, err = terraria_config.read_config()
    if err:
        return None, err
    current_world = (current.get("worldname") or "").strip()
    entries = []
    for item in _known_worlds():
        entries.append({
            "name": item["name"],
            "selected": item["name"] == current_world,
            "exists": item["exists"],
            "label": item["name"] if item["exists"] else f'{item["name"]} (absent)',
        })
    return {
        "current_world": current_world,
        "world_root": str(_data_dir()),
        "worlds": entries,
    }, None


def _update_game_json(world_name: str):
    path = _app_dir() / "game.json"
    if not path.exists():
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    data.setdefault("server", {})["world_name"] = world_name
    path.write_text(json.dumps(data, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def _update_deploy_config(world_name: str):
    path = _app_dir() / "deploy_config.env"
    _replace_or_append_line(path, r"^WORLD_NAME=.*$", f'WORLD_NAME="{world_name}"')


def _update_backup_script(world_name: str):
    path = _app_dir() / "backup_terraria.sh"
    if not path.exists():
        return
    _replace_or_append_line(path, r'^WORLD_NAME(\s*=\s*|=)".*"$', f'WORLD_NAME = "{world_name}"')


def select_world(world_name: str):
    world_name = (world_name or "").strip()
    if not world_name:
        return None, "missing_world"
    known = {item["name"] for item in _known_worlds()}
    if world_name not in known:
        return None, "unknown_world"

    current, err = terraria_config.read_config()
    if err:
        return None, err
    ok, err = terraria_config.write_config({
        **current,
        "worldname": world_name,
    })
    if not ok:
        return None, err

    _game()["server"]["world_name"] = world_name
    _update_game_json(world_name)
    _update_deploy_config(world_name)
    _update_backup_script(world_name)
    return {
        "world_name": world_name,
    }, None
