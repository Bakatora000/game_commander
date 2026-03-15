"""
games/valheim/admins.py
Gestion de adminlist.txt / bannedlist.txt / permittedlist.txt pour Valheim.
"""
from __future__ import annotations

import re
from pathlib import Path

from flask import current_app


def _data_dir() -> Path:
    data_dir = current_app.config["GAME"]["server"].get("data_dir") or current_app.config["GAME"]["server"]["install_dir"]
    return Path(data_dir)


def _adminlist_path() -> Path:
    return _data_dir() / "adminlist.txt"


def _banlist_path() -> Path:
    return _data_dir() / "bannedlist.txt"


def _whitelist_path() -> Path:
    return _data_dir() / "permittedlist.txt"


def _normalize_steamid(steamid: str) -> str:
    value = (steamid or "").strip()
    if not re.fullmatch(r"\d{15,20}", value):
        return ""
    return value


def _list_entries(path: Path):
    entries = []
    if path.exists():
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            s = line.strip()
            if not s or s.startswith("//") or s.startswith("#"):
                continue
            sid = _normalize_steamid(s)
            if sid:
                entries.append(sid)
    return {"entries": [{"steamid": sid} for sid in entries]}, None


def _add_entry(path: Path, steamid: str, header: str):
    steamid = _normalize_steamid(steamid)
    if not steamid:
        return None, "invalid_steamid"
    existing, _ = _list_entries(path)
    ids = [entry["steamid"] for entry in existing["entries"]]
    if steamid in ids:
        return {"steamid": steamid, "already_present": True}, None
    lines = []
    if path.exists():
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    if not lines:
        lines = [header]
    lines.append(steamid)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"steamid": steamid, "already_present": False}, None


def _remove_entry(path: Path, steamid: str, missing_error: str):
    steamid = _normalize_steamid(steamid)
    if not steamid:
        return None, "invalid_steamid"
    if not path.exists():
        return None, missing_error
    kept = []
    removed = False
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.strip() == steamid:
            removed = True
            continue
        kept.append(line)
    path.write_text("\n".join(kept).rstrip() + "\n", encoding="utf-8")
    return {"steamid": steamid, "removed": removed}, None


def list_admins():
    return _list_entries(_adminlist_path())


def add_admin(steamid: str):
    return _add_entry(_adminlist_path(), steamid, "// List admin players ID  ONE per line")


def remove_admin(steamid: str):
    return _remove_entry(_adminlist_path(), steamid, "adminlist_missing")


def list_bans():
    return _list_entries(_banlist_path())


def add_ban(steamid: str):
    return _add_entry(_banlist_path(), steamid, "// List banned players ID  ONE per line")


def remove_ban(steamid: str):
    return _remove_entry(_banlist_path(), steamid, "banlist_missing")


def list_whitelist():
    return _list_entries(_whitelist_path())


def add_whitelist(steamid: str):
    return _add_entry(_whitelist_path(), steamid, "// List permitted players ID  ONE per line")


def remove_whitelist(steamid: str):
    return _remove_entry(_whitelist_path(), steamid, "whitelist_missing")
