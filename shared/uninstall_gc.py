#!/usr/bin/env python3
"""Interactive Section A — Game Commander managed instances."""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import console, hostctl, instanceenv, sysutil

_NGINX_MANIFEST = Path("/etc/nginx/game-commander-manifest.json")
_NGINX_LOC_FILE = Path("/etc/nginx/game-commander-locations.conf")
_NGINX_HUB_FILE = Path("/etc/nginx/game-commander-hub.html")
_NGINX_HUB_PORT = "5090"

_BOLD = "\033[1m"
_DIM  = "\033[2m"
_GREEN  = "\033[0;32m"
_YELLOW = "\033[1;33m"
_RED    = "\033[0;31m"
_RESET  = "\033[0m"


@dataclass
class InstanceEntry:
    cfg: Path
    game_id: str
    instance_id: str
    sys_user: str
    app_dir: str
    server_dir: str
    data_dir: str
    backup_dir: str
    domain: str
    flask_port: str
    server_name: str
    url_prefix: str
    gc_service: str
    game_service: str


def _load_entries() -> list[InstanceEntry]:
    entries: list[InstanceEntry] = []
    for cfg in hostctl.discover_instance_configs():
        env = instanceenv.parse_env_file(cfg)
        game_id = env.get("GAME_ID", "?")
        instance_id = env.get("INSTANCE_ID") or game_id
        entries.append(InstanceEntry(
            cfg=cfg,
            game_id=game_id,
            instance_id=instance_id,
            sys_user=env.get("SYS_USER", ""),
            app_dir=env.get("APP_DIR", ""),
            server_dir=env.get("SERVER_DIR", ""),
            data_dir=env.get("DATA_DIR", ""),
            backup_dir=env.get("BACKUP_DIR", ""),
            domain=env.get("DOMAIN", ""),
            flask_port=env.get("FLASK_PORT", ""),
            server_name=env.get("SERVER_NAME", ""),
            url_prefix=env.get("URL_PREFIX", ""),
            gc_service=f"game-commander-{instance_id}",
            game_service=env.get("GAME_SERVICE") or f"{game_id}-server-{instance_id}",
        ))
    return entries


def _nginx_run(manager: Path, *args: str) -> bool:
    result = subprocess.run(
        ["python3", str(manager), *args],
        capture_output=True, text=True, check=False,
    )
    return result.returncode == 0


def _nginx_manifest_in_manifest(manager: Path, instance_id: str) -> bool:
    return _nginx_run(manager, "manifest-check",
                      "--manifest", str(_NGINX_MANIFEST),
                      "--instance-id", instance_id)


def _nginx_remove_manifest(manager: Path, instance_id: str, dry_run: bool) -> None:
    if dry_run:
        console.info(f"[dry-run] retrait manifest nginx {instance_id}")
        return
    _nginx_run(manager, "manifest-remove",
               "--manifest", str(_NGINX_MANIFEST),
               "--instance-id", instance_id)
    _nginx_run(manager, "regenerate",
               "--manifest", str(_NGINX_MANIFEST),
               "--out", str(_NGINX_LOC_FILE),
               "--hub-file", str(_NGINX_HUB_FILE),
               "--hub-port", _NGINX_HUB_PORT)
    r = subprocess.run(["nginx", "-t"], capture_output=True, check=False)
    if r.returncode == 0:
        subprocess.run(["systemctl", "reload", "nginx"], capture_output=True, check=False)
        console.ok("Nginx reloadé")
    else:
        console.warn("Vérifiez nginx manuellement : nginx -t")


def _nginx_remove_legacy_block(manager: Path, nginx_conf: Path,
                                url_prefix: str, instance_id: str,
                                dry_run: bool) -> None:
    if dry_run:
        console.info(f"[dry-run] retrait bloc nginx {url_prefix}")
        return
    result = subprocess.run(
        ["python3", str(manager), "remove",
         "--conf", str(nginx_conf),
         "--instance-id", instance_id,
         "--prefix", url_prefix],
        capture_output=True, text=True, check=False,
    )
    if result.returncode == 0:
        console.ok(f"Bloc {url_prefix} retiré du vhost")
    else:
        console.warn("Échec suppression bloc nginx — vérifiez manuellement")
    r = subprocess.run(["nginx", "-t"], capture_output=True, check=False)
    if r.returncode == 0:
        subprocess.run(["systemctl", "reload", "nginx"], capture_output=True, check=False)


def _remove_nginx(entry: InstanceEntry, script_dir: Path,
                  assume_yes: bool, dry_run: bool) -> None:
    manager = script_dir / "tools" / "nginx_manager.py"

    if _NGINX_MANIFEST.is_file() and _nginx_manifest_in_manifest(manager, entry.instance_id):
        label = entry.url_prefix or entry.instance_id
        if console.ask_yn(f"Retirer {_BOLD}{label}{_RESET} du vhost Nginx (manifest) ?",
                          assume_yes=assume_yes):
            _nginx_remove_manifest(manager, entry.instance_id, dry_run)
        return

    # Legacy path: find the nginx conf by domain or port
    nginx_conf: Path | None = None
    for candidate in (
        Path(f"/etc/nginx/conf.d/{entry.domain or '___'}.conf"),
        Path(f"/etc/nginx/sites-enabled/{entry.domain or '___'}.conf"),
        Path(f"/etc/nginx/sites-available/{entry.domain or '___'}.conf"),
    ):
        if candidate.is_file():
            nginx_conf = candidate
            break

    if nginx_conf is None and entry.flask_port:
        for search_dir in (Path("/etc/nginx/conf.d"), Path("/etc/nginx/sites-enabled")):
            if not search_dir.is_dir():
                continue
            for f in search_dir.iterdir():
                try:
                    if f"127.0.0.1:{entry.flask_port}" in f.read_text(encoding="utf-8", errors="ignore"):
                        nginx_conf = f
                        break
                except OSError:
                    continue
            if nginx_conf:
                break

    if not nginx_conf or not nginx_conf.is_file():
        return

    try:
        content = nginx_conf.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return

    loc_count = content.count("\n    location ")
    has_our_block = bool(entry.url_prefix and entry.url_prefix in content)

    if loc_count <= 2 and has_our_block:
        if console.ask_yn(
            f"Supprimer vhost Nginx : {_BOLD}{nginx_conf}{_RESET} (seule instance) ?",
            assume_yes=assume_yes,
        ):
            if not dry_run:
                nginx_conf.unlink()
            console.ok("Vhost Nginx supprimé")
            r = subprocess.run(["nginx", "-t"], capture_output=True, check=False)
            if r.returncode == 0:
                subprocess.run(["systemctl", "reload", "nginx"], capture_output=True, check=False)
    elif has_our_block:
        if console.ask_yn(
            f"Retirer le bloc {_BOLD}{entry.url_prefix}{_RESET} "
            f"du vhost {_BOLD}{nginx_conf}{_RESET} (partagé) ?",
            assume_yes=assume_yes,
        ):
            _nginx_remove_legacy_block(manager, nginx_conf,
                                       entry.url_prefix, entry.instance_id, dry_run)
    else:
        console.warn(f"Bloc {entry.url_prefix or entry.instance_id} non trouvé dans "
                     f"{nginx_conf} — vérifiez manuellement")


def _remove_sudoers(entry: InstanceEntry, assume_yes: bool, dry_run: bool) -> None:
    for sf in (
        Path(f"/etc/sudoers.d/game-commander-{entry.game_id}"),
        Path(f"/etc/sudoers.d/game-commander-{entry.instance_id}"),
        Path(f"/etc/sudoers.d/{entry.gc_service}"),
    ):
        if not sf.is_file():
            continue
        if console.ask_yn(f"Supprimer sudoers : {_BOLD}{sf}{_RESET} ?",
                          assume_yes=assume_yes):
            if not dry_run:
                sf.unlink()
            console.ok("Sudoers supprimé")


def _remove_cron(entry: InstanceEntry, dry_run: bool) -> None:
    if not entry.sys_user or not entry.app_dir:
        return
    result = subprocess.run(
        ["crontab", "-u", entry.sys_user, "-l"],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        return
    lines = result.stdout.splitlines()
    matching = [l for l in lines if entry.app_dir in l]
    if not matching:
        return
    if dry_run:
        console.info(f"[dry-run] suppression cron {entry.sys_user}")
        return
    filtered = "\n".join(l for l in lines if entry.app_dir not in l) + "\n"
    subprocess.run(
        ["crontab", "-u", entry.sys_user, "-"],
        input=filtered, text=True, check=False, capture_output=True,
    )
    console.ok("Entrée cron supprimée")


def _du(path: Path) -> str:
    r = subprocess.run(["du", "-sh", str(path)], capture_output=True, text=True, check=False)
    return r.stdout.split()[0] if r.stdout else "?"


def _remove_dir_interactive(path_str: str, label: str,
                             assume_yes: bool, dry_run: bool) -> None:
    path = Path(path_str)
    if not path.is_dir():
        return
    size = _du(path)
    if console.ask_yn(
        f"Supprimer {label} : {_BOLD}{path}{_RESET}{_YELLOW} ({size}) ?",
        assume_yes=assume_yes,
    ):
        if not dry_run:
            shutil.rmtree(path, ignore_errors=True)
        console.ok(f"Supprimé : {path}")
    else:
        console.info(f"Conservé : {path}")


def _remove_dirs(entry: InstanceEntry, assume_yes: bool, dry_run: bool) -> None:
    cfg_str = str(entry.cfg)

    for path_str, label in (
        (entry.app_dir, "répertoire Game Commander"),
        (entry.server_dir, "répertoire serveur jeu"),
    ):
        if not path_str:
            continue
        others = sysutil.shared_by_others(path_str, cfg_str)
        if others:
            console.warn(f"Dossier partagé — NON supprimé : {path_str}")
            console.warn(f"  Référencé aussi par : {', '.join(others)}")
        else:
            _remove_dir_interactive(path_str, label, assume_yes, dry_run)

    if entry.data_dir and entry.data_dir != entry.server_dir:
        others = sysutil.shared_by_others(entry.data_dir, cfg_str)
        if others:
            console.warn(f"Dossier partagé — NON supprimé : {entry.data_dir}")
        else:
            _remove_dir_interactive(entry.data_dir, "répertoire données jeu", assume_yes, dry_run)

    if entry.sys_user:
        import pwd
        try:
            home_dir = Path(pwd.getpwnam(entry.sys_user).pw_dir)
        except KeyError:
            home_dir = None
        if home_dir:
            steamcmd_dir = home_dir / "steamcmd"
            if steamcmd_dir.is_dir():
                others = sysutil.shared_by_others(str(steamcmd_dir), cfg_str)
                if others:
                    console.info(f"SteamCMD conservé — utilisé aussi par : {', '.join(others)}")
                else:
                    _remove_dir_interactive(str(steamcmd_dir), "SteamCMD", assume_yes, dry_run)

    if entry.backup_dir and Path(entry.backup_dir).is_dir():
        others = sysutil.shared_by_others(entry.backup_dir, cfg_str)
        if others:
            console.info(f"Sauvegardes conservées — utilisées aussi par : {', '.join(others)}")
        else:
            _remove_dir_interactive(entry.backup_dir, "répertoire sauvegardes", assume_yes, dry_run)


def _maybe_remove_wine(entry: InstanceEntry, assume_yes: bool, dry_run: bool) -> None:
    if entry.game_id != "enshrouded":
        return
    remaining = len([
        cfg for cfg in hostctl.discover_instance_configs()
        if instanceenv.parse_env_file(cfg).get("GAME_ID") == "enshrouded"
    ])
    amp_result = subprocess.run(
        ["find", "/home", "/root", "/opt", "-maxdepth", "6",
         "-name", "instances.json", "-path", "*/.ampdata/*"],
        capture_output=True, text=True, check=False,
    )
    amp_enshrouded = sum(
        1 for f in amp_result.stdout.splitlines()
        if f and '"Enshrouded"' in Path(f).read_text(errors="ignore") if Path(f).is_file()
    )
    if remaining == 0 and amp_enshrouded == 0:
        if console.ask_yn("Plus aucune instance Enshrouded — désinstaller Wine64/Xvfb ?",
                          assume_yes=assume_yes):
            if not dry_run:
                subprocess.run(["apt-get", "remove", "-y", "wine64", "xvfb"],
                               check=False, capture_output=True)
                subprocess.run(["apt-get", "autoremove", "-y"],
                               check=False, capture_output=True)
            console.ok("Wine64/Xvfb désinstallés")
    else:
        if remaining > 0:
            console.info(f"Wine conservé — {remaining} autre(s) instance(s) Enshrouded (Game Commander)")
        if amp_enshrouded > 0:
            console.info(f"Wine conservé — {amp_enshrouded} instance(s) Enshrouded détectée(s) dans AMP")


def _process_entry(entry: InstanceEntry, action: str,
                   script_dir: Path, assume_yes: bool, dry_run: bool) -> None:
    print()
    console.hdr(f"Traitement : {entry.instance_id}")

    for msg in sysutil.stop_and_disable(entry.game_service, dry_run=dry_run):
        console.info(msg)
    for msg in sysutil.stop_and_disable(entry.gc_service, dry_run=dry_run):
        console.info(msg)

    if action == "2":
        _remove_nginx(entry, script_dir, assume_yes, dry_run)
        _remove_sudoers(entry, assume_yes, dry_run)
        _remove_cron(entry, dry_run)
        _remove_dirs(entry, assume_yes, dry_run)

        if not dry_run and entry.cfg.is_file():
            entry.cfg.unlink()

    console.ok(f"Terminé : {entry.instance_id}")
    _maybe_remove_wine(entry, assume_yes, dry_run)


def _state_badge(state: str) -> str:
    if state == "active":
        return f"{_GREEN}● actif{_RESET}"
    if state == "failed":
        return f"{_RED}✗ échoué{_RESET}"
    return f"{_DIM}○ inactif{_RESET}"


def section(
    script_dir: Path | str,
    assume_yes: bool = False,
    dry_run: bool = False,
) -> tuple[bool, list[str]]:
    """Run Section A interactively. Returns (skipped, handled_app_dirs)."""
    script_dir = Path(script_dir)
    console.hdr("A — Recherche installations Game Commander")

    entries = _load_entries()
    if not entries:
        console.info("Aucune installation Game Commander trouvée.")
        return False, []

    print()
    for i, e in enumerate(entries):
        gc_state = sysutil.service_state(e.gc_service)
        game_state = sysutil.service_state(e.game_service)
        print(f"  {_BOLD}[A{i+1}]{_RESET}  {_BOLD}{e.instance_id}{_RESET}  ({e.game_id.upper()})")
        print(f"         Config       : {e.cfg}")
        print(f"         Serveur jeu  : {e.game_service}  →  {_state_badge(game_state)}")
        print(f"         Game Cmd web : {e.gc_service}    →  {_state_badge(gc_state)}")
        if e.server_name:
            print(f"         Nom          : {e.server_name}")
        if e.domain:
            print(f"         Domaine      : {e.domain}  (port {e.flask_port or '?'})")
        if e.sys_user:
            print(f"         Utilisateur  : {e.sys_user}")
        if e.server_dir and Path(e.server_dir).is_dir():
            print(f"         Dossier jeu  : {e.server_dir}  {_du(Path(e.server_dir))}")
        if e.data_dir and e.data_dir != e.server_dir and Path(e.data_dir).is_dir():
            print(f"         Dossier data : {e.data_dir}  {_du(Path(e.data_dir))}")
        if e.app_dir and Path(e.app_dir).is_dir():
            print(f"         Dossier app  : {e.app_dir}  {_du(Path(e.app_dir))}")
        console.sep()

    sel = console.prompt(
        f"Entrez les numéros à traiter (ex: A1 A2), 'all' pour tout, 'skip' pour passer",
        "",
    )
    if not sel or sel.lower() == "skip":
        return True, []

    selected: list[int] = []
    if sel.lower() == "all":
        selected = list(range(len(entries)))
    else:
        for tok in sel.upper().split():
            tok = tok.lstrip("A")
            try:
                n = int(tok)
                if 1 <= n <= len(entries):
                    selected.append(n - 1)
                else:
                    console.warn(f"Numéro invalide : {tok} — ignoré")
            except ValueError:
                console.warn(f"Numéro invalide : {tok} — ignoré")

    if not selected:
        return False, []

    print()
    print("  Que souhaitez-vous faire ?")
    print(f"    {_BOLD}1{_RESET}) Stopper les services (fichiers conservés)")
    print(f"    {_BOLD}2{_RESET}) Désinstaller complètement (services + fichiers)")
    action = console.prompt("Choix", "2")

    handled_dirs: list[str] = []
    for idx in selected:
        e = entries[idx]
        if e.app_dir:
            handled_dirs.append(e.app_dir)
        _process_entry(e, action, script_dir, assume_yes, dry_run)

    return False, handled_dirs
