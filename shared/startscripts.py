#!/usr/bin/env python3
"""Génération des scripts de démarrage simples pour certains jeux."""

from __future__ import annotations

import argparse
import os
import pwd
import sys
from pathlib import Path


def render_minecraft_start_script(*, server_dir: str, jar_name: str) -> str:
    return (
        "#!/usr/bin/env bash\n"
        f'cd "{server_dir}"\n'
        f"exec /usr/bin/java -Xms1G -Xmx2G -jar {jar_name} nogui\n"
    )


def render_satisfactory_start_script(*, server_dir: str, data_dir: str, server_port: str, reliable_port: str) -> str:
    return (
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f'export HOME="{data_dir}"\n'
        f'export XDG_CONFIG_HOME="{data_dir}/.config"\n'
        f'mkdir -p "{data_dir}/.config/Epic/FactoryGame/Saved/SaveGames/server"\n'
        f'cd "{server_dir}"\n'
        f'exec ./FactoryServer.sh -Port="{server_port}" -ReliablePort="{reliable_port}" -unattended -log\n'
    )


def write_start_script(*, out_path: str, content: str, sys_user: str) -> None:
    path = Path(out_path)
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)
    pw = pwd.getpwnam(sys_user)
    os.chown(path, pw.pw_uid, pw.pw_gid)


def _cmd_minecraft(args: argparse.Namespace) -> int:
    jar_name = "fabric-server-launch.jar" if args.fabric else "server.jar"
    content = render_minecraft_start_script(server_dir=args.server_dir, jar_name=jar_name)
    write_start_script(out_path=args.out, content=content, sys_user=args.sys_user)
    print(args.out)
    return 0


def _cmd_satisfactory(args: argparse.Namespace) -> int:
    content = render_satisfactory_start_script(
        server_dir=args.server_dir,
        data_dir=args.data_dir,
        server_port=args.server_port,
        reliable_port=args.reliable_port,
    )
    write_start_script(out_path=args.out, content=content, sys_user=args.sys_user)
    print(args.out)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Génération de scripts de démarrage Game Commander")
    sub = parser.add_subparsers(dest="command", required=True)

    minecraft = sub.add_parser("minecraft")
    minecraft.add_argument("--out", required=True)
    minecraft.add_argument("--server-dir", required=True)
    minecraft.add_argument("--sys-user", required=True)
    minecraft.add_argument("--fabric", action="store_true")
    minecraft.set_defaults(func=_cmd_minecraft)

    satisfactory = sub.add_parser("satisfactory")
    satisfactory.add_argument("--out", required=True)
    satisfactory.add_argument("--server-dir", required=True)
    satisfactory.add_argument("--data-dir", required=True)
    satisfactory.add_argument("--server-port", required=True)
    satisfactory.add_argument("--reliable-port", required=True)
    satisfactory.add_argument("--sys-user", required=True)
    satisfactory.set_defaults(func=_cmd_satisfactory)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
