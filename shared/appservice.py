#!/usr/bin/env python3
"""Gestion du service systemd Game Commander d'instance."""

from __future__ import annotations

import argparse
import secrets
import subprocess
import sys
from pathlib import Path


def render_gc_service(*, game_label: str, game_service: str, sys_user: str, app_dir: str, gc_secret: str) -> str:
    return (
        "[Unit]\n"
        f"Description=Game Commander — {game_label}\n"
        "After=network.target\n"
        f"Wants={game_service}.service\n"
        "\n"
        "[Service]\n"
        "Type=simple\n"
        f"User={sys_user}\n"
        f"WorkingDirectory={app_dir}\n"
        f'Environment="GAME_COMMANDER_SECRET={gc_secret}"\n'
        f"ExecStart=/usr/bin/python3 {app_dir}/app.py\n"
        "Restart=on-failure\n"
        "RestartSec=5\n"
        "StandardOutput=journal\n"
        "StandardError=journal\n"
        "\n"
        "[Install]\n"
        "WantedBy=multi-user.target\n"
    )


def write_gc_service(
    *,
    service_name: str,
    game_label: str,
    game_service: str,
    sys_user: str,
    app_dir: str,
    gc_secret: str | None = None,
) -> str:
    secret = gc_secret or secrets.token_hex(32)
    service_path = Path("/etc/systemd/system") / f"{service_name}.service"
    content = render_gc_service(
        game_label=game_label,
        game_service=game_service,
        sys_user=sys_user,
        app_dir=app_dir,
        gc_secret=secret,
    )
    service_path.write_text(content)
    return secret


def install_gc_service(
    *,
    service_name: str,
    game_label: str,
    game_service: str,
    sys_user: str,
    app_dir: str,
    gc_secret: str | None = None,
) -> tuple[bool, str]:
    try:
        write_gc_service(
            service_name=service_name,
            game_label=game_label,
            game_service=game_service,
            sys_user=sys_user,
            app_dir=app_dir,
            gc_secret=gc_secret,
        )
        subprocess.run(["systemctl", "daemon-reload"], check=True, capture_output=True, text=True)
        subprocess.run(["systemctl", "enable", service_name], check=True, capture_output=True, text=True)
        subprocess.run(["systemctl", "restart", service_name], check=True, capture_output=True, text=True)
        active = subprocess.run(
            ["systemctl", "is-active", "--quiet", service_name],
            capture_output=True,
            text=True,
        )
        if active.returncode == 0:
            return True, f"Service {service_name} actif"
        return False, f"{service_name} inactif — journalctl -u {service_name} -n 30"
    except subprocess.CalledProcessError as exc:
        details = (exc.stderr or exc.stdout or str(exc)).strip()
        if details:
            return False, details
        return False, f"Échec installation service {service_name}"


def _cmd_install(args: argparse.Namespace) -> int:
    ok, message = install_gc_service(
        service_name=args.service_name,
        game_label=args.game_label,
        game_service=args.game_service,
        sys_user=args.sys_user,
        app_dir=args.app_dir,
    )
    if ok:
        print(message)
        return 0
    print(message, file=sys.stderr)
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Gestion du service Game Commander d'instance")
    sub = parser.add_subparsers(dest="command", required=True)

    install = sub.add_parser("install", help="Écrire et démarrer le service systemd")
    install.add_argument("--service-name", required=True)
    install.add_argument("--game-label", required=True)
    install.add_argument("--game-service", required=True)
    install.add_argument("--sys-user", required=True)
    install.add_argument("--app-dir", required=True)
    install.set_defaults(func=_cmd_install)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
