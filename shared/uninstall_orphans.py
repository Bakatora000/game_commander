#!/usr/bin/env python3
"""Interactive Section C — Orphan processes (not managed by systemd or AMP)."""
from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import console

_BOLD   = "\033[1m"
_DIM    = "\033[2m"
_YELLOW = "\033[1;33m"
_RESET  = "\033[0m"

_PROC_ROOT = Path(os.environ.get("PROC_ROOT", "/proc"))

_FLASK_PATTERN = re.compile(
    r"python[0-9.]*\s.*(app|wsgi|main)\.py|gunicorn|uvicorn",
    re.IGNORECASE,
)
_GAME_PATTERN = re.compile(
    r"valheim_server\.x86_64|enshrouded_server|bedrock_server|(?<![a-z])java(?![a-z]).*nogui",
    re.IGNORECASE,
)
_GAME_BINARY = re.compile(
    r"valheim_server\.x86_64|enshrouded_server|bedrock_server|java",
    re.IGNORECASE,
)


@dataclass
class OrphanEntry:
    pid: int
    user: str
    desc: str
    cmd: str


def _is_systemd_managed(pid: int) -> bool:
    cgroup = _PROC_ROOT / str(pid) / "cgroup"
    if not cgroup.is_readable() if hasattr(cgroup, "is_readable") else not cgroup.exists():
        return False
    try:
        text = cgroup.read_text(errors="ignore")
        return bool(re.search(r"\.service($|[^a-zA-Z0-9_])", text))
    except OSError:
        return False


def _is_amp_process(pid: int, depth: int = 0) -> bool:
    if depth >= 8 or pid <= 1:
        return False
    cmdline_path = _PROC_ROOT / str(pid) / "cmdline"
    if not cmdline_path.exists():
        return False
    try:
        cmdline = cmdline_path.read_bytes().replace(b"\x00", b" ").decode(errors="ignore")
    except OSError:
        return False
    if re.search(r"ampdata|cubecoders|ampinstmgr", cmdline, re.IGNORECASE):
        return True
    stat_path = _PROC_ROOT / str(pid) / "stat"
    if not stat_path.exists():
        return False
    try:
        parent_pid = int(stat_path.read_text().split()[3])
    except (OSError, ValueError, IndexError):
        return False
    return _is_amp_process(parent_pid, depth + 1)


def _get_safe_pids() -> set[int]:
    """PIDs of processes managed by active systemd services."""
    result = subprocess.run(
        ["systemctl", "show", "--property=MainPID",
         "--value", "--", "--all"],
        capture_output=True, text=True, check=False,
    )
    safe: set[int] = set()
    for line in result.stdout.splitlines():
        line = line.strip()
        if line and line != "0":
            try:
                safe.add(int(line))
            except ValueError:
                pass
    return safe


def _collect_orphans(script_dir: Path) -> list[OrphanEntry]:
    safe_pids = _get_safe_pids()
    my_pid = os.getpid()

    result = subprocess.run(
        ["ps", "-eo", "pid,user,cmd", "--no-headers"],
        capture_output=True, text=True, check=False,
    )

    entries: list[OrphanEntry] = []
    skip_patterns = re.compile(r"game_commander|uninstall_flask|grep", re.IGNORECASE)

    for line in result.stdout.splitlines():
        if " Z " in line:
            continue
        parts = line.split(None, 2)
        if len(parts) < 3:
            continue
        pid_str, user, cmd = parts[0], parts[1], parts[2].strip()
        try:
            pid = int(pid_str)
        except ValueError:
            continue
        if pid <= 1 or pid == my_pid:
            continue
        if skip_patterns.search(cmd):
            continue
        if pid in safe_pids:
            continue
        if _is_systemd_managed(pid):
            continue
        if _is_amp_process(pid):
            continue

        desc = ""
        if _FLASK_PATTERN.search(cmd):
            wdir = ""
            cwd_link = _PROC_ROOT / str(pid) / "cwd"
            try:
                wdir = str(cwd_link.resolve())
            except OSError:
                pass

            app_name = ""
            if wdir:
                game_json = Path(wdir) / "game.json"
                if game_json.is_file():
                    r = subprocess.run(
                        ["python3", str(script_dir / "shared" / "appfiles.py"),
                         "read-game-json", "--path", str(game_json), "--field", "app-desc"],
                        capture_output=True, text=True, check=False,
                    )
                    if r.returncode == 0:
                        app_name = r.stdout.strip()

            desc = "Flask/Python"
            if app_name:
                desc += f" ({app_name})"
            if wdir:
                desc += f"  [{wdir}]"

        elif _GAME_PATTERN.search(cmd):
            m = _GAME_BINARY.search(cmd)
            binary = m.group(0) if m else "?"
            desc = f"Serveur de jeu ({binary})"
        else:
            continue

        entries.append(OrphanEntry(
            pid=pid,
            user=user,
            desc=desc,
            cmd=cmd[:80],
        ))

    return entries


def section(
    script_dir: Path | str,
    assume_yes: bool = False,
    dry_run: bool = False,
) -> None:
    """Run Section C interactively."""
    script_dir = Path(script_dir)
    console.hdr("C — Processus orphelins en mémoire")

    orphans = _collect_orphans(script_dir)

    if not orphans:
        console.ok("Aucun processus orphelin détecté.")
        return

    print()
    console.warn(f"{len(orphans)} processus orphelin(s) trouvé(s) :")
    print()

    for i, o in enumerate(orphans):
        print(f"  {_BOLD}[C{i+1}]{_RESET}  PID {_BOLD}{o.pid}{_RESET}  — {o.desc}")
        print(f"         Utilisateur : {o.user}")
        print(f"         Commande    : {_DIM}{o.cmd}{_RESET}")
        console.sep()

    sel = console.prompt(
        f"Numéros à terminer (ex: C1 C2), 'all' pour tout, 'skip' pour passer",
        "",
    )
    if not sel or sel.lower() == "skip":
        return

    selected: list[int] = []
    if sel.lower() == "all":
        selected = list(range(len(orphans)))
    else:
        for tok in sel.upper().split():
            tok = tok.lstrip("C")
            try:
                n = int(tok)
                if 1 <= n <= len(orphans):
                    selected.append(n - 1)
                else:
                    console.warn(f"Numéro invalide : {tok} — ignoré")
            except ValueError:
                console.warn(f"Numéro invalide : {tok} — ignoré")

    if not selected:
        return

    print()
    print("  Signal :")
    print(f"    {_BOLD}1{_RESET}) SIGTERM  — arrêt propre (recommandé)")
    print(f"    {_BOLD}2{_RESET}) SIGKILL  — arrêt forcé")
    sig_choice = console.prompt("Choix", "1")
    sig = "-9" if sig_choice == "2" else "-15"

    for idx in selected:
        o = orphans[idx]
        # Check process still alive
        try:
            os.kill(o.pid, 0)
        except ProcessLookupError:
            console.warn(f"PID {o.pid} déjà terminé")
            continue
        except PermissionError:
            pass  # process exists but we can't signal — try anyway

        console.info(f"Envoi signal {sig} → PID {o.pid} ({o.desc})...")
        if not dry_run:
            result = subprocess.run(
                ["kill", sig, str(o.pid)],
                capture_output=True, check=False,
            )
            import time
            time.sleep(2)
            try:
                os.kill(o.pid, 0)
                console.warn(f"PID {o.pid} toujours actif — kill -9 {o.pid} pour forcer")
            except ProcessLookupError:
                console.ok(f"PID {o.pid} terminé")
