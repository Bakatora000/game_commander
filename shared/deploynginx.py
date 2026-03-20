#!/usr/bin/env python3
"""Étape Nginx commune pour deploy/redeploy."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path


GC_NGINX_MANIFEST = "/etc/nginx/game-commander-manifest.json"
GC_NGINX_LOC_FILE = "/etc/nginx/game-commander-locations.conf"
GC_NGINX_HUB_FILE = "/etc/nginx/game-commander-hub.html"
GC_NGINX_BACKUP_DIR = "/etc/nginx/backups"
GC_NGINX_HUB_PORT = "5090"


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=True, capture_output=True, text=True)


def run_deploy_nginx(
    *,
    script_dir: str,
    domain: str,
    instance_id: str,
    url_prefix: str,
    flask_port: str,
    game_label: str,
) -> tuple[bool, str]:
    manager = str(Path(script_dir) / "tools" / "nginx_manager.py")
    try:
        _run([
            "python3", manager, "init",
            "--domain", domain,
            "--manifest", GC_NGINX_MANIFEST,
            "--loc-file", GC_NGINX_LOC_FILE,
            "--hub-file", GC_NGINX_HUB_FILE,
            "--hub-port", GC_NGINX_HUB_PORT,
            "--backup-dir", GC_NGINX_BACKUP_DIR,
        ])
        _run([
            "python3", manager, "manifest-add",
            "--manifest", GC_NGINX_MANIFEST,
            "--instance-id", instance_id,
            "--prefix", url_prefix,
            "--port", str(flask_port),
            "--game", game_label,
        ])
        _run([
            "python3", manager, "regenerate",
            "--manifest", GC_NGINX_MANIFEST,
            "--out", GC_NGINX_LOC_FILE,
            "--hub-file", GC_NGINX_HUB_FILE,
            "--hub-port", GC_NGINX_HUB_PORT,
        ])
        _run(["nginx", "-t"])
        _run(["systemctl", "reload", "nginx"])
        return True, "Nginx reloadé"
    except subprocess.CalledProcessError as exc:
        details = (exc.stderr or exc.stdout or str(exc)).strip()
        if details:
            return False, details
        return False, "Erreur config Nginx — vérifiez avec : nginx -t"


def remove_legacy_nginx_block(nginx_file: str | Path, port: str) -> bool:
    """Remove a Game Commander proxy block for *port* from a legacy nginx vhost file.

    Returns True if the file was modified, False if the pattern was not found.
    """
    path = Path(nginx_file)
    content = path.read_text(encoding="utf-8")
    pattern = (
        r"\n?[ \t]*# ── Game Commander[^\n]*\n"
        r".*?"
        r"location [^\{]+\{"
        r"[^}]*proxy_pass[^}]*" + re.escape(port) + r"[^}]*\}"
        r"[^\n]*\n?"
        r"[ \t]*location [^\{]+/static[^}]*\}[ \t]*\n?"
        r"[ \t]*# ─+\n?"
    )
    new_content, count = re.subn(pattern, "\n", content, flags=re.DOTALL)
    if count == 0:
        return False
    path.write_text(new_content, encoding="utf-8")
    return True


def _cmd_remove_legacy_block(args: argparse.Namespace) -> int:
    modified = remove_legacy_nginx_block(args.nginx_file, args.port)
    if not modified:
        print(f"Bloc port {args.port} introuvable dans {args.nginx_file}", file=sys.stderr)
        return 1
    return 0


def _cmd_apply(args: argparse.Namespace) -> int:
    ok, message = run_deploy_nginx(
        script_dir=args.script_dir,
        domain=args.domain,
        instance_id=args.instance_id,
        url_prefix=args.url_prefix,
        flask_port=args.flask_port,
        game_label=args.game_label,
    )
    print(message, file=(sys.stdout if ok else sys.stderr))
    return 0 if ok else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Étape Nginx commune Game Commander")
    sub = parser.add_subparsers(dest="command", required=True)
    apply_cmd = sub.add_parser("apply", help="Initialiser et recharger nginx pour une instance")
    apply_cmd.add_argument("--script-dir", required=True)
    apply_cmd.add_argument("--domain", required=True)
    apply_cmd.add_argument("--instance-id", required=True)
    apply_cmd.add_argument("--url-prefix", required=True)
    apply_cmd.add_argument("--flask-port", required=True)
    apply_cmd.add_argument("--game-label", required=True)
    apply_cmd.set_defaults(func=_cmd_apply)
    rlb = sub.add_parser("remove-legacy-block")
    rlb.add_argument("--nginx-file", required=True)
    rlb.add_argument("--port", required=True)
    rlb.set_defaults(func=_cmd_remove_legacy_block)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
