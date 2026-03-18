#!/usr/bin/env python3
"""Bootstrap non interactif du Hub Admin Game Commander."""

from __future__ import annotations

import argparse
import pwd
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

if __package__ in {None, ""}:
    ROOT_DIR = Path(__file__).resolve().parents[1]
    if str(ROOT_DIR) not in sys.path:
        sys.path.insert(0, str(ROOT_DIR))
    from shared import deploydeps, deployssl, hubsync
else:
    from . import deploydeps, deployssl, hubsync

GC_NGINX_MANIFEST = "/etc/nginx/game-commander-manifest.json"
GC_NGINX_LOC_FILE = "/etc/nginx/game-commander-locations.conf"
GC_NGINX_HUB_FILE = "/etc/nginx/game-commander-hub.html"
GC_NGINX_BACKUP_DIR = "/etc/nginx/backups"
GC_NGINX_HUB_PORT = "5090"
GC_STATE_DIR = "/var/lib/game-commander"


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, check=True, capture_output=True, text=True)


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item and item not in seen:
            ordered.append(item)
            seen.add(item)
    return ordered


def _install_dependencies(*, home_dir: Path, ssl_mode: str) -> tuple[bool, list[str] | str]:
    messages: list[str] = []
    inspect = deploydeps.inspect_dependencies(
        deploy_mode="attach",
        steam_appid="",
        ssl_mode=ssl_mode,
        game_id="hub",
        home_dir=str(home_dir),
    )
    apt_packages = _dedupe(inspect["apt_missing"] + inspect["python_apt_missing"] + inspect["extra_apt_missing"])
    pip_packages = _dedupe(inspect["python_pip_missing"])

    try:
        if apt_packages:
            _run(["apt-get", "update", "-qq"])
            _run(["apt-get", "install", "-y", "-qq", *apt_packages])
            messages.append(f"Dépendances apt installées : {', '.join(apt_packages)}")
        else:
            messages.append("Dépendances apt déjà présentes")

        if pip_packages:
            _run(["pip3", "install", "--break-system-packages", "-q", *pip_packages])
            messages.append(f"Dépendances Python installées : {', '.join(pip_packages)}")
        else:
            messages.append("Dépendances Python déjà présentes")
    except subprocess.CalledProcessError as exc:
        details = (exc.stderr or exc.stdout or str(exc)).strip()
        return False, details or "Échec installation des dépendances"
    return True, messages


def _bootstrap_nginx(*, repo_root: Path, domain: str) -> tuple[bool, list[str] | str]:
    manager = repo_root / "tools" / "nginx_manager.py"
    if not manager.is_file():
        return False, "nginx_manager.py introuvable"
    try:
        _run(
            [
                "python3",
                str(manager),
                "init",
                "--domain",
                domain,
                "--manifest",
                GC_NGINX_MANIFEST,
                "--loc-file",
                GC_NGINX_LOC_FILE,
                "--hub-file",
                GC_NGINX_HUB_FILE,
                "--hub-port",
                GC_NGINX_HUB_PORT,
                "--backup-dir",
                GC_NGINX_BACKUP_DIR,
            ]
        )
        _run(
            [
                "python3",
                str(manager),
                "regenerate",
                "--manifest",
                GC_NGINX_MANIFEST,
                "--out",
                GC_NGINX_LOC_FILE,
                "--hub-file",
                GC_NGINX_HUB_FILE,
                "--hub-port",
                GC_NGINX_HUB_PORT,
            ]
        )
        _run(["nginx", "-t"])
        _run(["systemctl", "reload", "nginx"])
        return True, ["Nginx initialisé pour le Hub", "Nginx reloadé"]
    except subprocess.CalledProcessError as exc:
        details = (exc.stderr or exc.stdout or str(exc)).strip()
        return False, details or "Échec configuration nginx"


def _open_hub_ports() -> list[str]:
    if not shutil.which("ufw"):
        return []
    status = subprocess.run(["ufw", "status"], capture_output=True, text=True, check=False)
    if "Status: active" not in status.stdout:
        return []
    messages: list[str] = []
    for port in ("80/tcp", "443/tcp"):
        subprocess.run(["ufw", "allow", port], capture_output=True, text=True, check=False)
        messages.append(f"UFW : {port} ouvert")
    return messages


def _ensure_state_dir(sys_user: str) -> None:
    pw = pwd.getpwnam(sys_user)
    state_dir = Path(GC_STATE_DIR)
    state_dir.mkdir(parents=True, exist_ok=True)
    state_dir.chmod(0o755)
    state_dir.chown(pw.pw_uid, pw.pw_gid)


def run_bootstrap_hub(
    *,
    repo_root: str | Path,
    sys_user: str,
    domain: str,
    admin_login: str,
    admin_password: str = "",
    ssl_mode: str = "none",
) -> tuple[bool, list[str] | str]:
    repo_root = Path(repo_root).resolve()
    try:
        home_dir = Path(pwd.getpwnam(sys_user).pw_dir)
    except KeyError:
        return False, f"Utilisateur système introuvable : {sys_user}"

    generated_password = ""
    if not admin_password:
        generated_password = secrets.token_urlsafe(12)
        admin_password = generated_password

    all_messages: list[str] = [f"Bootstrap Hub pour {sys_user} sur {domain}"]

    ok, result = _install_dependencies(home_dir=home_dir, ssl_mode=ssl_mode)
    if not ok:
        return False, result
    all_messages.extend(result)

    _ensure_state_dir(sys_user)
    ok, result = hubsync.sync_hub_service_from_values(
        sys_user=sys_user,
        app_dir=str(home_dir / "game-commander-hub"),
        admin_login=admin_login,
        admin_password=admin_password,
        repo_root=repo_root,
    )
    if not ok:
        return False, result
    all_messages.extend(result)

    ok, result = _bootstrap_nginx(repo_root=repo_root, domain=domain)
    if not ok:
        return False, result
    all_messages.extend(result)

    ok, ssl_messages = deployssl.apply_ssl(ssl_mode, domain)
    if not ok:
        return False, ssl_messages
    all_messages.extend(ssl_messages)
    all_messages.extend(_open_hub_ports())

    scheme = "https" if ssl_mode in {"existing", "certbot"} else "http"
    all_messages.append(f"Hub Admin : {scheme}://{domain}/commander")
    all_messages.append(f"Login admin : {admin_login}")
    if generated_password:
        all_messages.append(f"Mot de passe admin généré : {generated_password}")
    return True, all_messages


def _cmd_bootstrap(args: argparse.Namespace) -> int:
    ok, result = run_bootstrap_hub(
        repo_root=args.repo_root,
        sys_user=args.sys_user,
        domain=args.domain,
        admin_login=args.admin_login,
        admin_password=args.admin_password,
        ssl_mode=args.ssl_mode,
    )
    stream = sys.stdout if ok else sys.stderr
    if isinstance(result, str):
        print(result, file=stream)
    else:
        for line in result:
            print(line, file=stream)
    return 0 if ok else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bootstrap non interactif du Hub Admin")
    sub = parser.add_subparsers(dest="command", required=True)
    bootstrap = sub.add_parser("bootstrap")
    bootstrap.add_argument("--repo-root", required=True)
    bootstrap.add_argument("--sys-user", required=True)
    bootstrap.add_argument("--domain", required=True)
    bootstrap.add_argument("--admin-login", default="admin")
    bootstrap.add_argument("--admin-password", default="")
    bootstrap.add_argument("--ssl-mode", default="none", choices=["none", "existing", "certbot"])
    bootstrap.set_defaults(func=_cmd_bootstrap)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
