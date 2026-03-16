"""
Gestion de la banlist Terraria vanilla.

Format géré:
// PlayerName
1.2.3.4
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import psutil

from . import config as terraria_config


def _service_name() -> str:
    from flask import current_app
    return current_app.config["GAME"]["server"]["service"]


def _current_session_since():
    try:
        result = subprocess.run(
            ['systemctl', 'show', _service_name(), '--property=MainPID'],
            capture_output=True, text=True, timeout=3
        )
        pid = 0
        for line in result.stdout.splitlines():
            if line.startswith('MainPID='):
                pid = int(line.split('=', 1)[1].strip() or '0')
                break
        if pid <= 0:
            return None
        started = psutil.Process(pid).create_time()
        return f"@{max(int(started) - 5, 0)}"
    except Exception:
        return None


def _journal_lines():
    cmd = ['journalctl', '-u', _service_name(), '--no-pager', '-o', 'cat']
    since_arg = _current_session_since()
    if since_arg:
        cmd.extend(['--since', since_arg])
    else:
        cmd.extend(['--since', '1 hour ago'])
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        return result.stdout.splitlines()
    except Exception:
        return []


def _banlist_path() -> Path:
    data, _err = terraria_config.read_config()
    filename = (data.get("banlist") or "banlist.txt").strip() if data else "banlist.txt"
    path = Path(filename)
    if path.is_absolute():
        return path
    from flask import current_app
    server_dir = Path(current_app.config["GAME"]["server"]["install_dir"])
    return server_dir / filename


def _normalize_name(name: str) -> str:
    return (name or "").strip()


def _read_raw_lines():
    path = _banlist_path()
    if not path.exists():
        return []
    try:
        return path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return []


def _write_raw_lines(lines):
    path = _banlist_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "\n".join(lines).strip()
    path.write_text((payload + "\n") if payload else "", encoding="utf-8")


def _parse_entries():
    lines = _read_raw_lines()
    entries = []
    i = 0
    while i < len(lines):
        raw = (lines[i] or "").strip()
        if not raw:
            i += 1
            continue
        if raw.startswith("//"):
            name = raw[2:].strip()
            ip = ""
            if i + 1 < len(lines):
                nxt = (lines[i + 1] or "").strip()
                if nxt and not nxt.startswith("//"):
                    ip = nxt
                    i += 1
            entries.append({"name": name, "ip": ip})
        else:
            entries.append({"name": raw, "ip": ""})
        i += 1
    return entries


def _find_recent_ip(name: str) -> str:
    target = _normalize_name(name)
    if not target:
        return ""
    pending_ip = ""
    for line in _journal_lines():
        line = line.strip()
        if line.endswith("is connecting...") and ":" in line:
            pending_ip = line.split(":", 1)[0].strip()
            continue
        if line == f"{target} has joined.":
            return pending_ip
    return ""


def list_bans():
    entries = sorted(_parse_entries(), key=lambda item: item["name"].lower())
    return {"entries": entries}, None


def add_ban(name: str, ip: str = ""):
    clean = _normalize_name(name)
    if not clean:
        return None, "missing_name"
    entries = _parse_entries()
    for entry in entries:
        if entry["name"].lower() == clean.lower():
            return {"name": clean, "ip": entry.get("ip", ""), "already_present": True}, None

    ip = (ip or "").strip() or _find_recent_ip(clean)
    if not ip:
        return None, "missing_ip"

    lines = _read_raw_lines()
    if lines and (lines[-1] or "").strip():
        lines.append("")
    lines.append(f"// {clean}")
    lines.append(ip)
    _write_raw_lines(lines)
    return {"name": clean, "ip": ip, "already_present": False}, None


def remove_ban(name: str):
    clean = _normalize_name(name)
    if not clean:
        return None, "missing_name"
    lines = _read_raw_lines()
    out = []
    removed = False
    i = 0
    while i < len(lines):
        raw = lines[i]
        stripped = (raw or "").strip()
        if stripped.startswith("//") and stripped[2:].strip().lower() == clean.lower():
            removed = True
            if i + 1 < len(lines):
                nxt = (lines[i + 1] or "").strip()
                if nxt and not nxt.startswith("//"):
                    i += 2
                    continue
            i += 1
            continue
        if stripped.lower() == clean.lower():
            removed = True
            i += 1
            continue
        out.append(raw)
        i += 1
    if not removed:
        return None, "ban_missing"
    while out and not (out[-1] or "").strip():
        out.pop()
    _write_raw_lines(out)
    return {"name": clean}, None
