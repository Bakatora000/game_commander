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


def render_valheim_start_script(
    *,
    server_dir: str,
    data_dir: str,
    server_name: str,
    server_port: str,
    world_name: str,
    server_password: str,
    crossplay_flag: str,
    bepinex: bool,
) -> str:
    if bepinex:
        return (
            "#!/usr/bin/env bash\n"
            "export DOORSTOP_ENABLE=TRUE\n"
            "export DOORSTOP_INVOKE_DLL_PATH=./BepInEx/core/BepInEx.Preloader.dll\n"
            "export DOORSTOP_CORLIB_OVERRIDE_PATH=./unstripped_corlib\n"
            'export LD_LIBRARY_PATH="./doorstop_libs:$LD_LIBRARY_PATH"\n'
            'export LD_PRELOAD="libdoorstop_x64.so:$LD_PRELOAD"\n'
            'export LD_LIBRARY_PATH="./linux64:$LD_LIBRARY_PATH"\n'
            "export SteamAppId=892970\n"
            f'cd "{server_dir}"\n'
            "exec ./valheim_server.x86_64 \\\n"
            f'    -name "{server_name}" \\\n'
            f"    -port {server_port} \\\n"
            f'    -world "{world_name}" \\\n'
            f'    -password "{server_password}" \\\n'
            f'    -savedir "{data_dir}" \\\n'
            "    -public 1 \\\n"
            f"    {crossplay_flag}\n"
        )
    return (
        "#!/usr/bin/env bash\n"
        "export SteamAppId=892970\n"
        f'export LD_LIBRARY_PATH="{server_dir}/linux64:$LD_LIBRARY_PATH"\n'
        f'cd "{server_dir}"\n'
        "exec ./valheim_server.x86_64 \\\n"
        f'    -name "{server_name}" \\\n'
        f"    -port {server_port} \\\n"
        f'    -world "{world_name}" \\\n'
        f'    -password "{server_password}" \\\n'
        f'    -savedir "{data_dir}" \\\n'
        "    -public 1 \\\n"
        f"    {crossplay_flag}\n"
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


def _cmd_valheim(args: argparse.Namespace) -> int:
    content = render_valheim_start_script(
        server_dir=args.server_dir,
        data_dir=args.data_dir,
        server_name=args.server_name,
        server_port=args.server_port,
        world_name=args.world_name,
        server_password=args.server_password,
        crossplay_flag=args.crossplay_flag,
        bepinex=args.bepinex,
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

    valheim = sub.add_parser("valheim")
    valheim.add_argument("--out", required=True)
    valheim.add_argument("--server-dir", required=True)
    valheim.add_argument("--data-dir", required=True)
    valheim.add_argument("--server-name", required=True)
    valheim.add_argument("--server-port", required=True)
    valheim.add_argument("--world-name", required=True)
    valheim.add_argument("--server-password", required=True)
    valheim.add_argument("--crossplay-flag", default="")
    valheim.add_argument("--sys-user", required=True)
    valheim.add_argument("--bepinex", action="store_true")
    valheim.set_defaults(func=_cmd_valheim)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
