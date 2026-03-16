"""
games/enshrouded/worlds.py
Détection lecture seule des mondes/slots Enshrouded présents dans savegame/.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from flask import current_app


_WORLD_ID_RE = re.compile(r"^[0-9a-f]{8}$")
_KNOWN_WORLD_IDS = {
    "3ad85aea": "World 1",
    "3bd85c7d": "World 2",
}


def _game():
    return current_app.config["GAME"]


def _server_dir() -> Path:
    return Path(_game()["server"]["install_dir"])


def _save_root() -> Path:
    cfg = _server_dir() / "enshrouded_server.json"
    if cfg.exists():
        try:
            data = json.loads(cfg.read_text(encoding="utf-8"))
            save_dir = str(data.get("saveDirectory") or "./savegame").strip()
            path = Path(save_dir)
            return path if path.is_absolute() else (_server_dir() / path)
        except Exception:
            pass
    return _server_dir() / "savegame"


def _slot_label(world_id: str) -> str:
    known = _KNOWN_WORLD_IDS.get(world_id.lower())
    if known:
        return f"{known} ({world_id})"
    return f"Monde ({world_id})"


def _read_index(world_id: str):
    index_path = _save_root() / f"{world_id}-index"
    if not index_path.exists():
        return None
    try:
        return json.loads(index_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def list_worlds():
    root = _save_root()
    worlds = {}
    if root.exists():
        for child in root.iterdir():
            if not child.is_file():
                continue
            name = child.name
            if name.startswith("characters"):
                continue
            base = None
            if _WORLD_ID_RE.match(name):
                base = name
            elif name.endswith("-index") and _WORLD_ID_RE.match(name[:-6]):
                base = name[:-6]
            elif "_info" in name:
                prefix = name.split("_info", 1)[0]
                if _WORLD_ID_RE.match(prefix):
                    base = prefix
            elif "-" in name:
                prefix = name.split("-", 1)[0]
                if _WORLD_ID_RE.match(prefix):
                    base = prefix
            if not base:
                continue
            worlds.setdefault(base, {"id": base, "files": 0, "has_info": False})
            worlds[base]["files"] += 1
            if "_info" in name:
                worlds[base]["has_info"] = True

    entries = []
    for world_id in sorted(worlds):
        meta = worlds[world_id]
        index_data = _read_index(world_id) or {}
        entries.append({
            "id": world_id,
            "label": _slot_label(world_id),
            "files": meta["files"],
            "has_info": meta["has_info"],
            "latest": index_data.get("latest"),
            "deleted": bool(index_data.get("deleted", False)),
            "timestamp": index_data.get("time"),
        })

    return {
        "save_root": str(root),
        "worlds": entries,
    }, None
