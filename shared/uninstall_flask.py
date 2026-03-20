#!/usr/bin/env python3
"""Interactive Section B — Generic Flask/Python applications (systemd)."""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import console

_BOLD   = "\033[1m"
_DIM    = "\033[2m"
_GREEN  = "\033[0;32m"
_YELLOW = "\033[1;33m"
_RED    = "\033[0;31m"
_RESET  = "\033[0m"


@dataclass
class FlaskEntry:
    svc: str           # service name (without .service)
    state: str
    work_dir: str
    svc_user: str
    port: str
    nginx_file: str    # path to nginx conf or ""


def _nginx_remove_block(nginx: Path, port: str,
                        script_dir: Path, dry_run: bool) -> None:
    """Remove a port block from an nginx conf or delete the whole file."""
    try:
        content = nginx.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return

    loc_count = content.count("\n    location ")
    has_port = f"127.0.0.1:{port}" in content

    if not has_port:
        return

    if loc_count <= 2:
        if console.ask_yn(
            f"Supprimer vhost Nginx : {_BOLD}{nginx}{_RESET} (seule instance) ?"
        ):
            if not dry_run:
                nginx.unlink()
            console.ok("Vhost supprimé")
            _nginx_reload(dry_run)
    else:
        if console.ask_yn(
            f"Retirer le bloc port {port} du vhost {_BOLD}{nginx}{_RESET} (partagé) ?"
        ):
            if not dry_run:
                backup = nginx.with_name(
                    nginx.name + "." +
                    subprocess.run(["date", "+%Y%m%d%H%M%S"],
                                   capture_output=True, text=True).stdout.strip()
                )
                try:
                    import shutil
                    shutil.copy2(nginx, backup)
                except OSError:
                    pass
                subprocess.run(
                    ["python3", str(script_dir / "shared" / "deploynginx.py"),
                     "remove-legacy-block", "--nginx-file", str(nginx), "--port", port],
                    capture_output=True, check=False,
                )
            console.ok(f"Bloc port {port} retiré")
            _nginx_reload(dry_run)


def _nginx_reload(dry_run: bool) -> None:
    if dry_run:
        return
    r = subprocess.run(["nginx", "-t"], capture_output=True, check=False)
    if r.returncode == 0:
        subprocess.run(["systemctl", "reload", "nginx"],
                       capture_output=True, check=False)


def _remove_sudoers(work_dir: str, svc: str,
                    assume_yes: bool, dry_run: bool) -> None:
    for sf in Path("/etc/sudoers.d").iterdir() if Path("/etc/sudoers.d").is_dir() else []:
        if not sf.is_file():
            continue
        try:
            text = sf.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if work_dir not in text and svc not in text:
            continue
        if console.ask_yn(
            f"Supprimer sudoers : {_BOLD}{sf}{_RESET} ?",
            assume_yes=assume_yes,
        ):
            if not dry_run:
                sf.unlink()
            console.ok("Sudoers supprimé")


def _collect_flask_services(already_handled: list[str], script_dir: Path) -> list[FlaskEntry]:
    """Scan all systemd unit files for Flask/Python services not already handled."""
    result = subprocess.run(
        ["systemctl", "list-unit-files", "--type=service", "--no-legend"],
        capture_output=True, text=True, check=False,
    )
    entries: list[FlaskEntry] = []

    for line in result.stdout.splitlines():
        svc = line.split()[0] if line.split() else ""
        if not svc or "@" in svc:
            continue

        unit_file = Path(f"/etc/systemd/system/{svc}")
        if not unit_file.is_file():
            unit_file = Path(f"/lib/systemd/system/{svc}")
        if not unit_file.is_file():
            continue

        try:
            unit_text = unit_file.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        exec_line = next(
            (l for l in unit_text.splitlines() if l.upper().startswith("EXECSTART=")),
            "",
        )
        import re
        if not re.search(r"python|gunicorn|uvicorn|flask", exec_line, re.IGNORECASE):
            continue

        work_dir = ""
        for l in unit_text.splitlines():
            if l.startswith("WorkingDirectory="):
                work_dir = l.split("=", 1)[1].strip()
                break
        if not work_dir:
            continue

        if work_dir in already_handled:
            continue

        work_path = Path(work_dir)
        is_flask = (
            (work_path / "app.py").is_file()
            or (work_path / "wsgi.py").is_file()
            or _has_flask_in_requirements(work_path)
        )
        if not is_flask:
            continue

        svc_name = svc.removesuffix(".service")
        state_result = subprocess.run(
            ["systemctl", "is-active", svc_name],
            capture_output=True, text=True, check=False,
        )
        state = state_result.stdout.strip() or "inactive"

        svc_user = "root"
        for l in unit_text.splitlines():
            if l.startswith("User="):
                svc_user = l.split("=", 1)[1].strip()
                break

        port = _detect_port(work_path, script_dir)
        nginx_file = _find_nginx_for_port(port) if port and port != "?" else ""

        entries.append(FlaskEntry(
            svc=svc_name,
            state=state,
            work_dir=work_dir,
            svc_user=svc_user,
            port=port or "?",
            nginx_file=nginx_file,
        ))

    return entries


def _has_flask_in_requirements(work_path: Path) -> bool:
    req = work_path / "requirements.txt"
    if not req.is_file():
        return False
    try:
        text = req.read_text(encoding="utf-8", errors="ignore")
        import re
        return bool(re.search(r"flask|gunicorn", text, re.IGNORECASE))
    except OSError:
        return False


def _detect_port(work_path: Path, script_dir: Path) -> str:
    game_json = work_path / "game.json"
    if game_json.is_file():
        r = subprocess.run(
            ["python3", str(script_dir / "shared" / "appfiles.py"),
             "read-game-json", "--path", str(game_json), "--field", "flask-port"],
            capture_output=True, text=True, check=False,
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()

    app_py = work_path / "app.py"
    if app_py.is_file():
        import re
        try:
            text = app_py.read_text(encoding="utf-8", errors="ignore")
            m = re.search(r"port\s*=\s*(\d+)", text)
            if m:
                return m.group(1)
        except OSError:
            pass
    return ""


def _find_nginx_for_port(port: str) -> str:
    for search_dir in (Path("/etc/nginx/conf.d"), Path("/etc/nginx/sites-enabled")):
        if not search_dir.is_dir():
            continue
        for f in search_dir.iterdir():
            try:
                if f"127.0.0.1:{port}" in f.read_text(encoding="utf-8", errors="ignore"):
                    return str(f)
            except OSError:
                continue
    return ""


def _state_badge(state: str) -> str:
    if state == "active":
        return f"{_GREEN}● actif{_RESET}"
    if state == "failed":
        return f"{_RED}✗ échoué{_RESET}"
    return f"{_DIM}○ inactif{_RESET}"


def _process_entry(entry: FlaskEntry, action: str,
                   script_dir: Path, assume_yes: bool, dry_run: bool) -> None:
    from . import sysutil
    print()
    console.hdr(f"Traitement : {entry.svc}")

    for msg in sysutil.stop_and_disable(entry.svc, dry_run=dry_run):
        console.info(msg)

    if action == "2":
        if entry.nginx_file and Path(entry.nginx_file).is_file():
            _nginx_remove_block(Path(entry.nginx_file), entry.port, script_dir, dry_run)
        _remove_sudoers(entry.work_dir, entry.svc, assume_yes, dry_run)
        _remove_dir(entry.work_dir, dry_run)

    console.ok(f"Terminé : {entry.svc}")


def _remove_dir(work_dir: str, dry_run: bool) -> None:
    import shutil
    p = Path(work_dir)
    if not p.is_dir():
        return
    r = subprocess.run(["du", "-sh", work_dir], capture_output=True, text=True, check=False)
    size = r.stdout.split()[0] if r.stdout else "?"
    if console.ask_yn(f"Supprimer répertoire application : {_BOLD}{work_dir}{_RESET} ({size}) ?"):
        if not dry_run:
            shutil.rmtree(p, ignore_errors=True)
        console.ok(f"Supprimé : {work_dir}")
    else:
        console.info(f"Conservé : {work_dir}")


def section(
    script_dir: Path | str,
    already_handled: list[str] | None = None,
    assume_yes: bool = False,
    dry_run: bool = False,
) -> None:
    """Run Section B interactively."""
    script_dir = Path(script_dir)
    console.hdr("B — Recherche applications Flask génériques (systemd)")

    entries = _collect_flask_services(already_handled or [], script_dir)

    if not entries:
        console.info("Aucune application Flask générique trouvée.")
        return

    print()
    for i, e in enumerate(entries):
        r = subprocess.run(["du", "-sh", e.work_dir],
                           capture_output=True, text=True, check=False)
        size = r.stdout.split()[0] if r.stdout else "?"
        print(f"  {_BOLD}[B{i+1}]{_RESET}  {e.svc}")
        print(f"         État       : {_state_badge(e.state)}")
        print(f"         Répertoire : {e.work_dir}  {size}")
        print(f"         Utilisateur: {e.svc_user}")
        print(f"         Port       : {e.port}")
        if e.nginx_file:
            print(f"         Nginx      : {e.nginx_file}")
        console.sep()

    sel = console.prompt(
        f"Entrez les numéros à traiter (ex: B1 B2), 'all' pour tout, 'skip' pour passer",
        "",
    )
    if not sel or sel.lower() == "skip":
        return

    selected: list[int] = []
    if sel.lower() == "all":
        selected = list(range(len(entries)))
    else:
        for tok in sel.upper().split():
            tok = tok.lstrip("B")
            try:
                n = int(tok)
                if 1 <= n <= len(entries):
                    selected.append(n - 1)
                else:
                    console.warn(f"Numéro invalide : {tok} — ignoré")
            except ValueError:
                console.warn(f"Numéro invalide : {tok} — ignoré")

    if not selected:
        return

    print()
    print("  Que souhaitez-vous faire ?")
    print(f"    {_BOLD}1{_RESET}) Stopper uniquement")
    print(f"    {_BOLD}2{_RESET}) Désinstaller complètement")
    action = console.prompt("Choix", "2")

    for idx in selected:
        _process_entry(entries[idx], action, script_dir, assume_yes, dry_run)
