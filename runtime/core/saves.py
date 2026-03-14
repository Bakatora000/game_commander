"""
core/saves.py — Navigation sécurisée des dossiers de sauvegarde par jeu.
"""
from __future__ import annotations

import os
import tempfile
import zipfile
from pathlib import Path

from flask import after_this_request, current_app


def _game():
    return current_app.config["GAME"]


def _server_dir() -> Path:
    return Path(_game()["server"]["install_dir"])


def _data_dir() -> Path:
    data_dir = _game()["server"].get("data_dir") or _game()["server"]["install_dir"]
    return Path(data_dir)


def _world_name() -> str:
    return _game()["server"].get("world_name") or ""


def get_save_roots():
    game_id = _game()["id"]
    server_dir = _server_dir()
    data_dir = _data_dir()
    world_name = _world_name()

    roots = []
    if game_id == "valheim":
        worlds_local = data_dir / "worlds_local"
        worlds = data_dir / "worlds"
        root_path = worlds_local if worlds_local.exists() else worlds
        roots.append({"id": "worlds", "label": "Mondes", "path": root_path})
        if world_name:
            roots.append({"id": "current_world", "label": f"Monde courant ({world_name})", "path": root_path})
    elif game_id == "enshrouded":
        roots.append({"id": "savegame", "label": "Savegame", "path": server_dir / "savegame"})
    elif game_id == "minecraft":
        roots.append({"id": "world", "label": "Monde", "path": server_dir / "world"})
        roots.append({"id": "playerdata", "label": "Playerdata", "path": server_dir / "world" / "playerdata"})
    elif game_id == "minecraft-fabric":
        roots.append({"id": "world", "label": "Monde", "path": server_dir / "world"})
        roots.append({"id": "playerdata", "label": "Playerdata", "path": server_dir / "world" / "playerdata"})
    elif game_id == "terraria":
        roots.append({"id": "worlds", "label": "Données serveur", "path": data_dir})
    elif game_id == "soulmask":
        roots.append({"id": "saved", "label": "Saved", "path": server_dir / "LinuxServer" / "WS" / "Saved"})

    result = []
    for root in roots:
        root_path = Path(root["path"])
        result.append({
            "id": root["id"],
            "label": root["label"],
            "path": str(root_path),
            "exists": root_path.exists(),
            "is_dir": root_path.is_dir(),
        })
    return result


def _find_root(root_id: str):
    for root in get_save_roots():
        if root["id"] == root_id:
            return root
    return None


def _safe_target(root_path: Path, rel_path: str) -> Path:
    rel = (rel_path or "").strip().lstrip("/")
    target = (root_path / rel).resolve()
    root_resolved = root_path.resolve()
    if target != root_resolved and root_resolved not in target.parents:
        raise ValueError("path_outside_root")
    return target


def list_entries(root_id: str, rel_path: str = ""):
    root = _find_root(root_id)
    if not root:
        return None, "unknown_root"

    root_path = Path(root["path"])
    if not root_path.exists():
        return None, "missing_root"

    target = _safe_target(root_path, rel_path)
    if not target.exists():
        return None, "missing_path"
    if not target.is_dir():
        return None, "not_a_directory"

    entries = []
    for child in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        rel_child = child.relative_to(root_path)
        stat = child.stat()
        entries.append({
            "name": child.name,
            "path": str(rel_child).replace(os.sep, "/"),
            "type": "dir" if child.is_dir() else "file",
            "size": stat.st_size if child.is_file() else None,
            "mtime": int(stat.st_mtime),
        })

    parent = ""
    if target != root_path:
        parent = str(target.relative_to(root_path).parent).replace(os.sep, "/")
        if parent == ".":
            parent = ""

    return {
        "root": root,
        "current_path": str(target.relative_to(root_path)).replace(os.sep, "/") if target != root_path else "",
        "parent_path": parent,
        "entries": entries,
    }, None


def get_download_target(root_id: str, rel_path: str):
    root = _find_root(root_id)
    if not root:
        return None, None, "unknown_root"

    root_path = Path(root["path"])
    if not root_path.exists():
        return None, None, "missing_root"

    target = _safe_target(root_path, rel_path)
    if not target.exists():
        return None, None, "missing_path"

    if target.is_file():
        return target, target.name, None

    tmp = tempfile.NamedTemporaryFile(prefix="gc_save_", suffix=".zip", delete=False)
    tmp_path = Path(tmp.name)
    tmp.close()

    with zipfile.ZipFile(tmp_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for item in target.rglob("*"):
            if item.is_file():
                zf.write(item, arcname=str(item.relative_to(target.parent)))

    @after_this_request
    def _cleanup(response):
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass
        return response

    return tmp_path, f"{target.name}.zip", None
