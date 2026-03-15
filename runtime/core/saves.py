"""
core/saves.py — Navigation sécurisée des dossiers de sauvegarde par jeu.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import zipfile
import re
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


def _app_dir() -> Path:
    return Path(current_app.root_path)


def _deploy_cfg_path() -> Path:
    candidates = [
        _app_dir() / "deploy_config.env",
        _server_dir().parent / "deploy_config.env",
    ]
    for path in candidates:
        if path.is_file():
            return path
    return candidates[0]


def _deploy_cfg_value(key: str, default: str = "") -> str:
    path = _deploy_cfg_path()
    if not path.is_file():
        return default
    pattern = re.compile(rf'^{re.escape(key)}="?(.*?)"?$')
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        m = pattern.match(line.strip())
        if m:
            return m.group(1)
    return default


def _backup_dir() -> Path:
    path = _deploy_cfg_value("BACKUP_DIR")
    if path:
        return Path(path)
    return _server_dir().parent / "gamebackups"


def _backup_script_path() -> Path:
    return _app_dir() / f'backup_{_game()["id"]}.sh'


def _backup_pattern() -> str:
    game_id = _game()["id"]
    if game_id == "valheim":
        world_name = _world_name()
        return f"{world_name}_*.zip" if world_name else "*.zip"
    return f"{game_id}_save_*.zip"


def _backup_label(path: Path) -> str:
    m = re.search(r'(\d{8})_(\d{6})', path.name)
    if not m:
        return path.name
    d, t = m.groups()
    return f"{d[6:8]}/{d[4:6]}/{d[0:4]} {t[0:2]}:{t[2:4]}:{t[4:6]}"


def _strip_named_root(members, names):
    top_levels = {rel.parts[0] for _member, rel in members if rel.parts}
    if len(top_levels) != 1:
        return members
    top = next(iter(top_levels))
    if top not in names:
        return members
    if not all(len(rel.parts) > 1 for _member, rel in members):
        return members
    return [(member, Path(*rel.parts[1:])) for member, rel in members]


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


def list_backups():
    backup_dir = _backup_dir()
    if not backup_dir.exists():
        return {
            "backup_dir": str(backup_dir),
            "entries": [],
        }, None

    entries = []
    for path in sorted(backup_dir.glob(_backup_pattern()), key=lambda p: p.stat().st_mtime, reverse=True):
        stat = path.stat()
        entries.append({
            "name": path.name,
            "label": _backup_label(path),
            "size": stat.st_size,
            "mtime": int(stat.st_mtime),
        })
    return {
        "backup_dir": str(backup_dir),
        "entries": entries,
    }, None


def get_backup_download_target(filename: str):
    if not filename or "/" in filename or "\\" in filename:
        return None, None, "invalid_backup"
    path = (_backup_dir() / filename).resolve()
    root = _backup_dir().resolve()
    if path != root and root not in path.parents:
        return None, None, "invalid_backup"
    if not path.exists() or not path.is_file():
        return None, None, "missing_backup"
    return path, path.name, None


def run_backup():
    script = _backup_script_path()
    if not script.is_file():
        return None, "backup_script_missing"
    result = subprocess.run(["bash", str(script)], capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        return None, (result.stderr or result.stdout).strip() or "backup_failed"
    backups, _err = list_backups()
    latest = backups["entries"][0] if backups["entries"] else None
    return {
        "output": (result.stdout or "").strip(),
        "latest": latest,
    }, None


def _load_backup_members(backup_path: Path):
    with zipfile.ZipFile(backup_path) as zf:
        members = list(_safe_zip_members(zf))
    return _normalize_archive_members(members)


def _backup_restore_operations(backup_path: Path):
    game_id = _game()["id"]
    members = _load_backup_members(backup_path)
    if not members:
        raise ValueError("empty_archive")

    server_dir = _server_dir()
    data_dir = _data_dir()
    operations = []
    collisions = []
    admin_files = {
        "server.properties",
        "ops.json",
        "whitelist.json",
        "banned-players.json",
        "banned-ips.json",
        "usercache.json",
    }

    if game_id == "valheim":
        valid_suffixes = (".db", ".fwl", ".db.old", ".fwl.old")
        if not any(str(rel).lower().endswith(valid_suffixes) for _member, rel in members):
            raise ValueError("invalid_backup_layout")
        root = Path(_find_root("worlds")["path"])
        for member, rel in members:
            dest = (root / rel.name).resolve()
            operations.append((member.filename, dest, rel.name))
        return operations

    if game_id == "enshrouded":
        members = _strip_named_root(members, {"savegame", (server_dir / "savegame").name})
        if not members:
            raise ValueError("invalid_backup_layout")
        root = server_dir / "savegame"
        for member, rel in members:
            dest = (root / rel).resolve()
            operations.append((member.filename, dest, str(rel).replace(os.sep, "/")))
        return operations

    if game_id in {"minecraft", "minecraft-fabric"}:
        top_levels = {rel.parts[0] for _member, rel in members if rel.parts}
        if "world" not in top_levels:
            raise ValueError("invalid_backup_layout")
        for member, rel in members:
            if rel.parts[0] == "world":
                dest = (server_dir / rel).resolve()
            elif len(rel.parts) == 1 and rel.name in admin_files:
                dest = (server_dir / rel.name).resolve()
            else:
                raise ValueError("invalid_backup_layout")
            operations.append((member.filename, dest, str(rel).replace(os.sep, "/")))
        return operations

    if game_id == "terraria":
        members = _strip_named_root(members, {data_dir.name})
        suffixes = {rel.suffix.lower() for _member, rel in members if rel.suffix}
        if not ({".wld", ".twld"} & suffixes):
            raise ValueError("invalid_backup_layout")
        for member, rel in members:
            dest = (data_dir / rel).resolve()
            operations.append((member.filename, dest, str(rel).replace(os.sep, "/")))
        return operations

    if game_id == "soulmask":
        members = _strip_named_root(members, {"Saved"})
        top_levels = {rel.parts[0] for _member, rel in members if rel.parts}
        allowed = {"Logs", "Config", "GameplaySettings", "SaveGames", "Saved", "World", "Worlds"}
        if not top_levels or not (top_levels & allowed):
            raise ValueError("invalid_backup_layout")
        root = server_dir / "WS" / "Saved"
        for member, rel in members:
            dest = (root / rel).resolve()
            operations.append((member.filename, dest, str(rel).replace(os.sep, "/")))
        return operations

    raise ValueError("invalid_backup_layout")


def restore_backup(filename: str):
    backup_path, _download_name, err = get_backup_download_target(filename)
    if err:
        return None, err

    operations = _backup_restore_operations(backup_path)
    written = []
    extracted = []
    collision_count = 0

    with zipfile.ZipFile(backup_path) as zf:
        for member_name, dest, rel_text in operations:
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists():
                collision_count += 1
            with zf.open(member_name) as src, open(dest, "wb") as dst:
                shutil.copyfileobj(src, dst)
            written.append(rel_text)
            extracted.append(rel_text)

    return {
        "count": 1,
        "written": written,
        "extracted": extracted,
        "collision_count": collision_count,
        "restored_backup": filename,
    }, None


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
