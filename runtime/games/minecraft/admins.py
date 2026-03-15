"""
Gestion des rôles serveur Minecraft via les fichiers JSON natifs.

Périmètre :
  - ops.json
  - whitelist.json
  - banned-players.json

Les opérations reposent d'abord sur usercache.json pour retrouver l'UUID
d'un pseudo. On accepte aussi les entrées déjà présentes dans les fichiers.
"""
from __future__ import annotations

import json
from pathlib import Path


def _server_dir() -> Path:
    from flask import current_app
    return Path(current_app.config["GAME"]["server"]["install_dir"])


def _usercache_path() -> Path:
    return _server_dir() / "usercache.json"


def _ops_path() -> Path:
    return _server_dir() / "ops.json"


def _whitelist_path() -> Path:
    return _server_dir() / "whitelist.json"


def _bans_path() -> Path:
    return _server_dir() / "banned-players.json"


def _read_json_array(path: Path):
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    return data if isinstance(data, list) else []


def _write_json_array(path: Path, entries) -> None:
    path.write_text(
        json.dumps(entries, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _normalize_name(name: str) -> str:
    return (name or "").strip()


def _normalize_uuid(value: str) -> str:
    return (value or "").strip().lower()


def _find_usercache_entry(name: str):
    target = _normalize_name(name).lower()
    if not target:
        return None
    for entry in _read_json_array(_usercache_path()):
        if _normalize_name(entry.get("name", "")).lower() == target:
            return {
                "name": _normalize_name(entry.get("name", "")),
                "uuid": _normalize_uuid(entry.get("uuid", "")),
            }
    return None


def _find_existing_entry(entries, name: str):
    target = _normalize_name(name).lower()
    for entry in entries:
        if _normalize_name(entry.get("name", "")).lower() == target:
            return entry
    return None


def _resolve_identity(name: str, entries=None):
    clean = _normalize_name(name)
    if not clean:
        return None, "missing_name"

    existing = _find_existing_entry(entries or [], clean)
    if existing:
        return {
            "name": _normalize_name(existing.get("name", clean)),
            "uuid": _normalize_uuid(existing.get("uuid", "")),
        }, None

    cached = _find_usercache_entry(clean)
    if cached and cached.get("uuid"):
        return cached, None
    return None, "unknown_player"


def _list_simple(path: Path):
    entries = []
    for entry in _read_json_array(path):
        name = _normalize_name(entry.get("name", ""))
        uuid = _normalize_uuid(entry.get("uuid", ""))
        if not name:
            continue
        entries.append({"name": name, "uuid": uuid})
    entries.sort(key=lambda item: item["name"].lower())
    return {"entries": entries}, None


def list_admins():
    return _list_simple(_ops_path())


def list_whitelist():
    return _list_simple(_whitelist_path())


def list_bans():
    return _list_simple(_bans_path())


def add_admin(name: str):
    entries = _read_json_array(_ops_path())
    identity, err = _resolve_identity(name, entries)
    if err:
        return None, err
    existing = _find_existing_entry(entries, identity["name"])
    if existing:
        return {"name": identity["name"], "uuid": identity["uuid"], "already_present": True}, None
    entries.append({
        "uuid": identity["uuid"],
        "name": identity["name"],
        "level": 4,
        "bypassesPlayerLimit": False,
    })
    _write_json_array(_ops_path(), entries)
    return {"name": identity["name"], "uuid": identity["uuid"], "already_present": False}, None


def remove_admin(name: str):
    target = _normalize_name(name).lower()
    if not target:
        return None, "missing_name"
    entries = _read_json_array(_ops_path())
    kept = [entry for entry in entries if _normalize_name(entry.get("name", "")).lower() != target]
    if len(kept) == len(entries):
        return None, "admin_missing"
    _write_json_array(_ops_path(), kept)
    return {"name": _normalize_name(name)}, None


def add_whitelist(name: str):
    entries = _read_json_array(_whitelist_path())
    identity, err = _resolve_identity(name, entries)
    if err:
        return None, err
    existing = _find_existing_entry(entries, identity["name"])
    if existing:
        return {"name": identity["name"], "uuid": identity["uuid"], "already_present": True}, None
    entries.append({
        "uuid": identity["uuid"],
        "name": identity["name"],
    })
    _write_json_array(_whitelist_path(), entries)
    return {"name": identity["name"], "uuid": identity["uuid"], "already_present": False}, None


def remove_whitelist(name: str):
    target = _normalize_name(name).lower()
    if not target:
        return None, "missing_name"
    entries = _read_json_array(_whitelist_path())
    kept = [entry for entry in entries if _normalize_name(entry.get("name", "")).lower() != target]
    if len(kept) == len(entries):
        return None, "whitelist_missing"
    _write_json_array(_whitelist_path(), kept)
    return {"name": _normalize_name(name)}, None


def add_ban(name: str):
    entries = _read_json_array(_bans_path())
    identity, err = _resolve_identity(name, entries)
    if err:
        return None, err
    existing = _find_existing_entry(entries, identity["name"])
    if existing:
        return {"name": identity["name"], "uuid": identity["uuid"], "already_present": True}, None
    entries.append({
        "uuid": identity["uuid"],
        "name": identity["name"],
        "created": "now",
        "source": "Game Commander",
        "expires": "forever",
        "reason": "Banned by an operator.",
    })
    _write_json_array(_bans_path(), entries)
    return {"name": identity["name"], "uuid": identity["uuid"], "already_present": False}, None


def remove_ban(name: str):
    target = _normalize_name(name).lower()
    if not target:
        return None, "missing_name"
    entries = _read_json_array(_bans_path())
    kept = [entry for entry in entries if _normalize_name(entry.get("name", "")).lower() != target]
    if len(kept) == len(entries):
        return None, "ban_missing"
    _write_json_array(_bans_path(), kept)
    return {"name": _normalize_name(name)}, None
