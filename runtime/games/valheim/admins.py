"""
games/valheim/admins.py
Gestion de adminlist.txt pour Valheim.
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


def _normalize_steamid(steamid: str) -> str:
    value = (steamid or "").strip()
    if not re.fullmatch(r"\d{15,20}", value):
        return ""
    return value


def list_admins():
    path = _adminlist_path()
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


def add_admin(steamid: str):
    steamid = _normalize_steamid(steamid)
    if not steamid:
        return None, "invalid_steamid"
    path = _adminlist_path()
    existing, _ = list_admins()
    ids = [entry["steamid"] for entry in existing["entries"]]
    if steamid in ids:
        return {"steamid": steamid, "already_present": True}, None
    lines = []
    if path.exists():
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    if not lines:
        lines = ["// List admin players ID  ONE per line"]
    lines.append(steamid)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"steamid": steamid, "already_present": False}, None


def remove_admin(steamid: str):
    steamid = _normalize_steamid(steamid)
    if not steamid:
        return None, "invalid_steamid"
    path = _adminlist_path()
    if not path.exists():
        return None, "adminlist_missing"
    kept = []
    removed = False
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.strip() == steamid:
            removed = True
            continue
        kept.append(line)
    path.write_text("\n".join(kept).rstrip() + "\n", encoding="utf-8")
    return {"steamid": steamid, "removed": removed}, None
