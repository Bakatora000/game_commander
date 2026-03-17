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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Génération de scripts de démarrage Game Commander")
    sub = parser.add_subparsers(dest="command", required=True)

    minecraft = sub.add_parser("minecraft")
    minecraft.add_argument("--out", required=True)
    minecraft.add_argument("--server-dir", required=True)
    minecraft.add_argument("--sys-user", required=True)
    minecraft.add_argument("--fabric", action="store_true")
    minecraft.set_defaults(func=_cmd_minecraft)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
