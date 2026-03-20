#!/usr/bin/env python3
"""Gestion du service systemd de jeu."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def render_game_service(
    *,
    game_label: str,
    service_name: str,
    sys_user: str,
    server_dir: str,
    exec_start: str,
    cpu_affinity_line: str = "",
    cpu_weight_line: str = "",
    on_failure_notify: str = "",
) -> str:
    extra = ""
    if cpu_affinity_line:
        extra += f"{cpu_affinity_line}\n"
    if cpu_weight_line:
        extra += f"{cpu_weight_line}\n"
    on_failure_line = f"OnFailure={on_failure_notify}\n" if on_failure_notify else ""
    return (
        "[Unit]\n"
        f"Description={game_label} Dedicated Server\n"
        "After=network.target\n"
        f"{on_failure_line}"
        "\n"
        "[Service]\n"
        "Type=simple\n"
        f"User={sys_user}\n"
        f"WorkingDirectory={server_dir}\n"
        f"ExecStart={exec_start}\n"
        "Restart=on-failure\n"
        "RestartSec=10\n"
        f"{extra}"
        "SuccessExitStatus=0 130 143\n"
        "StandardOutput=journal\n"
        "StandardError=journal\n"
        f"SyslogIdentifier={service_name}\n"
        "KillSignal=SIGINT\n"
        "KillMode=mixed\n"
        "TimeoutStopSec=60\n"
        "\n"
        "[Install]\n"
        "WantedBy=multi-user.target\n"
    )


def install_crash_notify_template(script_dir: str) -> None:
    """Install the game-commander-crash-notify@.service systemd template (once, globally)."""
    content = (
        "[Unit]\n"
        "Description=Game Commander — notification crash pour %i\n"
        "DefaultDependencies=no\n"
        "\n"
        "[Service]\n"
        "Type=oneshot\n"
        f"ExecStart=/usr/bin/python3 {script_dir}/shared/crash_notify.py --instance %i\n"
        "StandardOutput=journal\n"
        "StandardError=journal\n"
    )
    Path("/etc/systemd/system/game-commander-crash-notify@.service").write_text(
        content, encoding="utf-8"
    )
    subprocess.run(["systemctl", "daemon-reload"], check=False, capture_output=True)


def install_game_service(
    *,
    game_label: str,
    service_name: str,
    sys_user: str,
    server_dir: str,
    exec_start: str,
    cpu_affinity_line: str = "",
    cpu_weight_line: str = "",
    on_failure_notify: str = "",
) -> tuple[bool, str]:
    service_path = Path("/etc/systemd/system") / f"{service_name}.service"
    service_path.write_text(
        render_game_service(
            game_label=game_label,
            service_name=service_name,
            sys_user=sys_user,
            server_dir=server_dir,
            exec_start=exec_start,
            cpu_affinity_line=cpu_affinity_line,
            cpu_weight_line=cpu_weight_line,
            on_failure_notify=on_failure_notify,
        ),
        encoding="utf-8",
    )
    try:
        subprocess.run(["systemctl", "daemon-reload"], check=True, capture_output=True, text=True)
        subprocess.run(["systemctl", "enable", service_name], check=True, capture_output=True, text=True)
        subprocess.run(["systemctl", "start", service_name], check=True, capture_output=True, text=True)
        active = subprocess.run(
            ["systemctl", "is-active", "--quiet", service_name],
            capture_output=True,
            text=True,
        )
        if active.returncode == 0:
            return True, f"Service {service_name} actif"
        return False, f"{service_name} pas encore actif — journalctl -u {service_name} -f"
    except subprocess.CalledProcessError as exc:
        details = (exc.stderr or exc.stdout or str(exc)).strip()
        if details:
            return False, details
        return False, f"Échec service {service_name}"


def _cmd_install(args: argparse.Namespace) -> int:
    ok, message = install_game_service(
        game_label=args.game_label,
        service_name=args.service_name,
        sys_user=args.sys_user,
        server_dir=args.server_dir,
        exec_start=args.exec_start,
        cpu_affinity_line=args.cpu_affinity_line,
        cpu_weight_line=args.cpu_weight_line,
    )
    print(message, file=(sys.stdout if ok else sys.stderr))
    return 0 if ok else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Gestion du service systemd de jeu")
    sub = parser.add_subparsers(dest="command", required=True)
    install = sub.add_parser("install")
    install.add_argument("--game-label", required=True)
    install.add_argument("--service-name", required=True)
    install.add_argument("--sys-user", required=True)
    install.add_argument("--server-dir", required=True)
    install.add_argument("--exec-start", required=True)
    install.add_argument("--cpu-affinity-line", default="")
    install.add_argument("--cpu-weight-line", default="")
    install.set_defaults(func=_cmd_install)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
