"""
games/valheim/worlds.py
Gestion du monde Valheim actif pour une instance.
"""
from __future__ import annotations

import json
import shutil
import re
from pathlib import Path

from flask import current_app


def _game():
    return current_app.config["GAME"]


def _server_dir() -> Path:
    return Path(_game()["server"]["install_dir"])


def _data_dir() -> Path:
    data_dir = _game()["server"].get("data_dir") or _game()["server"]["install_dir"]
    return Path(data_dir)


def _app_dir() -> Path:
    return Path(current_app.root_path)


def _world_root() -> Path:
    data_dir = _data_dir()
    worlds_local = data_dir / "worlds_local"
    worlds = data_dir / "worlds"
    return worlds_local if worlds_local.exists() else worlds


def _safe_world_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", (name or "").strip()).strip("-")


def _known_worlds():
    root = _world_root()
    worlds = {}
    if root.exists():
        for child in root.iterdir():
            if not child.is_file():
                continue
            lower = child.name.lower()
            for suffix in (".db.old", ".fwl.old", ".db", ".fwl"):
                if lower.endswith(suffix):
                    worlds[child.name[: -len(suffix)]] = True
                    break
    current = (_game()["server"].get("world_name") or "").strip()
    if current:
        worlds.setdefault(current, False)
    return [{"name": name, "exists": exists} for name, exists in sorted(worlds.items(), key=lambda it: it[0].lower())]


def list_worlds():
    current = (_game()["server"].get("world_name") or "").strip()
    entries = []
    for item in _known_worlds():
        entries.append({
            "name": item["name"],
            "selected": item["name"] == current,
            "exists": item["exists"],
            "label": item["name"] if item["exists"] else f'{item["name"]} (absent)',
        })
    return {
        "current_world": current,
        "worlds": entries,
    }, None


def _migrate_legacy_world_modifiers(previous_world: str):
    if not previous_world:
        return
    install_dir = _server_dir()
    legacy = install_dir / "world_modifiers.json"
    if not legacy.exists():
        return
    safe = _safe_world_name(previous_world) or "world"
    target = install_dir / f"world_modifiers.{safe}.json"
    if target.exists():
        return
    shutil.copy2(legacy, target)


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


def _update_start_script(world_name: str):
    for name in ("start_server_bepinex.sh", "start_server.sh"):
        path = _server_dir() / name
        if not path.exists():
            continue
        content = path.read_text(encoding="utf-8", errors="ignore")
        updated = re.sub(
            r'(\s-world\s+")([^"]*)(")',
            lambda m: f'{m.group(1)}{world_name}{m.group(3)}',
            content,
            count=1,
        )
        if updated == content:
            updated = re.sub(
                r'(\s-world\s+)(\S+)',
                lambda m: f'{m.group(1)}"{world_name}"',
                content,
                count=1,
            )
        path.write_text(updated, encoding="utf-8")


def _update_backup_script(world_name: str):
    path = _app_dir() / "backup_valheim.sh"
    if not path.exists():
        return
    _replace_or_append_line(path, r'^WORLD_NAME=".*"$', f'WORLD_NAME="{world_name}"')


def select_world(world_name: str):
    world_name = (world_name or "").strip()
    if not world_name:
        return None, "missing_world"
    known = {item["name"] for item in _known_worlds()}
    if world_name not in known:
        return None, "unknown_world"

    previous_world = (_game()["server"].get("world_name") or "").strip()
    _migrate_legacy_world_modifiers(previous_world)
    _game()["server"]["world_name"] = world_name
    _update_game_json(world_name)
    _update_deploy_config(world_name)
    _update_start_script(world_name)
    _update_backup_script(world_name)

    return {
        "world_name": world_name,
    }, None
