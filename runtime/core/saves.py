"""
core/saves.py — Navigation sécurisée des dossiers de sauvegarde par jeu.
"""
from __future__ import annotations

import os
import shutil
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
        roots.append({"id": "saved", "label": "Saved", "path": server_dir / "WS" / "Saved"})

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


def _safe_zip_members(zf: zipfile.ZipFile):
    for member in zf.infolist():
        name = member.filename.replace("\\", "/")
        if not name or name.endswith("/"):
            continue
        parts = [p for p in name.split("/") if p and p != "."]
        if any(p == ".." for p in parts):
            raise ValueError("invalid_archive_path")
        yield member, Path(*parts)


def _normalize_archive_members(members):
    rel_paths = [rel for _member, rel in members]
    if not rel_paths:
        raise ValueError("empty_archive")

    common_parts = list(rel_paths[0].parts)
    for rel in rel_paths[1:]:
        max_len = min(len(common_parts), len(rel.parts))
        i = 0
        while i < max_len and common_parts[i] == rel.parts[i]:
            i += 1
        common_parts = common_parts[:i]
        if not common_parts:
            break

    strip_count = 0
    if common_parts and all(len(rel.parts) > len(common_parts) for rel in rel_paths):
        strip_count = len(common_parts)

    normalized = []
    for member, rel in members:
        if strip_count:
            rel = Path(*rel.parts[strip_count:])
        if not rel.parts:
            continue
        normalized.append((member, rel))
    return normalized


def _validate_archive_layout(root_id: str, rel_path: str, members):
    if rel_path:
        raise ValueError("archive_upload_requires_root")

    game_id = _game()["id"]
    rel_paths = [rel for _member, rel in members]
    names = {rel.name for rel in rel_paths}
    suffixes = {rel.suffix.lower() for rel in rel_paths if rel.suffix}
    top_levels = {rel.parts[0] for rel in rel_paths if rel.parts}

    if game_id == "valheim":
        if root_id not in {"worlds", "current_world"} or not ({".db", ".fwl"} & suffixes):
            raise ValueError("invalid_archive_layout")
        return

    if game_id in {"minecraft", "minecraft-fabric"}:
        if root_id == "world":
            if "level.dat" not in names:
                raise ValueError("invalid_archive_layout")
            return
        if root_id == "playerdata":
            if ".dat" not in suffixes:
                raise ValueError("invalid_archive_layout")
            return

    if game_id == "terraria":
        if root_id != "worlds" or not ({".wld", ".twld"} & suffixes):
            raise ValueError("invalid_archive_layout")
        return

    if game_id == "enshrouded":
        if root_id != "savegame" or not rel_paths:
            raise ValueError("invalid_archive_layout")
        return

    if game_id == "soulmask":
        allowed = {"Logs", "Config", "SaveGames", "Saved", "World", "Worlds"}
        if root_id != "saved" or not top_levels or not (top_levels & allowed):
            raise ValueError("invalid_archive_layout")
        return

    raise ValueError("invalid_archive_layout")


def analyze_uploads(root_id: str, rel_path: str, files, extract_archives: bool = True):
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

    operations = []
    collisions = []
    added = []
    uploaded = []

    for storage in files:
        filename = Path((storage.filename or "").strip()).name
        if not filename:
            continue

        if extract_archives and filename.lower().endswith(".zip"):
            tmp = tempfile.NamedTemporaryFile(prefix="gc_upload_", suffix=".zip", delete=False)
            tmp_path = Path(tmp.name)
            tmp.close()
            try:
                storage.save(tmp_path)
                with zipfile.ZipFile(tmp_path) as zf:
                    members = list(_safe_zip_members(zf))
                    normalized = _normalize_archive_members(members)
                    _validate_archive_layout(root_id, rel_path, normalized)
                    for member, rel_member in normalized:
                        dest = (target / rel_member).resolve()
                        root_resolved = target.resolve()
                        if dest != root_resolved and root_resolved not in dest.parents:
                            raise ValueError("invalid_archive_path")
                        rel_text = str(rel_member).replace(os.sep, "/")
                        operations.append({
                            "kind": "archive_member",
                            "source_name": filename,
                            "zip_member": member.filename,
                            "relative_path": rel_text,
                            "target_path": str(dest),
                            "exists": dest.exists(),
                            "tmp_archive": str(tmp_path),
                        })
                        (collisions if dest.exists() else added).append(rel_text)
                uploaded.append(filename)
            except Exception:
                tmp_path.unlink(missing_ok=True)
                raise
            continue

        dest = (target / filename).resolve()
        root_resolved = target.resolve()
        if dest != root_resolved and root_resolved not in dest.parents:
            raise ValueError("invalid_upload_path")
        tmp = tempfile.NamedTemporaryFile(prefix="gc_upload_", suffix=Path(filename).suffix, delete=False)
        tmp_path = Path(tmp.name)
        tmp.close()
        storage.save(tmp_path)
        operations.append({
            "kind": "file",
            "source_name": filename,
            "relative_path": filename,
            "target_path": str(dest),
            "exists": dest.exists(),
            "tmp_file": str(tmp_path),
        })
        (collisions if dest.exists() else added).append(filename)
        uploaded.append(filename)

    return {
        "root": root,
        "current_path": str(target.relative_to(root_path)).replace(os.sep, "/") if target != root_path else "",
        "uploaded": uploaded,
        "count": len(uploaded),
        "operations": operations,
        "collisions": collisions,
        "added": added,
        "collision_count": len(collisions),
        "write_count": len(operations),
    }, None


def cleanup_upload_analysis(data):
    for op in data.get("operations", []):
        tmp_archive = op.get("tmp_archive")
        if tmp_archive:
            Path(tmp_archive).unlink(missing_ok=True)


def save_uploads(analysis):
    extracted = []
    written = []
    archive_handles = {}
    try:
        for op in analysis.get("operations", []):
            dest = Path(op["target_path"])
            dest.parent.mkdir(parents=True, exist_ok=True)
            if op["kind"] == "archive_member":
                archive_path = op["tmp_archive"]
                zf = archive_handles.get(archive_path)
                if zf is None:
                    zf = zipfile.ZipFile(archive_path)
                    archive_handles[archive_path] = zf
                with zf.open(op["zip_member"]) as src, open(dest, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                extracted.append(op["relative_path"])
            else:
                # Le FileStorage original n'est plus fiable ici ; l'appelant doit convertir
                # les fichiers simples en opérations avec source temporaire.
                src_path = op.get("tmp_file")
                if not src_path:
                    raise ValueError("missing_temp_file")
                shutil.copyfile(src_path, dest)
            written.append(op["relative_path"])
    finally:
        for zf in archive_handles.values():
            zf.close()
        for op in analysis.get("operations", []):
            if op.get("tmp_archive"):
                Path(op["tmp_archive"]).unlink(missing_ok=True)
            if op.get("tmp_file"):
                Path(op["tmp_file"]).unlink(missing_ok=True)

    return {
        "uploaded": analysis.get("uploaded", []),
        "extracted": extracted,
        "count": analysis.get("count", 0),
        "written": written,
        "collision_count": analysis.get("collision_count", 0),
    }
