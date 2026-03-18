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


def render_enshrouded_start_script(*, server_dir: str, home_dir: str) -> str:
    return (
        "#!/usr/bin/env bash\n"
        "export WINEDEBUG=-all\n"
        f'export WINEPREFIX="{home_dir}/.wine"\n'
        f'cd "{server_dir}"\n'
        "exec xvfb-run --auto-servernum wine64 ./enshrouded_server.exe\n"
    )


def render_terraria_start_script(*, server_dir: str) -> str:
    return (
        "#!/usr/bin/env bash\n"
        f'cd "{server_dir}"\n'
        f'CFG="{server_dir}/serverconfig.txt"\n'
        "cfg_get() {\n"
        '    local key="$1"\n'
        '    sed -n "s/^${key}=//p" "$CFG" | head -1\n'
        "}\n"
        'WORLD="$(cfg_get world)"\n'
        'WORLDPATH="$(cfg_get worldpath)"\n'
        'WORLDNAME="$(cfg_get worldname)"\n'
        'AUTOCREATE="$(cfg_get autocreate)"\n'
        'DIFFICULTY="$(cfg_get difficulty)"\n'
        'PORT="$(cfg_get port)"\n'
        'MAXPLAYERS="$(cfg_get maxplayers)"\n'
        'PASSWORD="$(cfg_get password)"\n'
        'MOTD="$(cfg_get motd)"\n'
        f'[[ -z "$WORLD" && -n "$WORLDPATH" && -n "$WORLDNAME" ]] && WORLD="$WORLDPATH/$WORLDNAME.wld"\n'
        f'mkdir -p "$WORLDPATH" "{server_dir}/logs"\n'
        "ARGS=(\n"
        '    -world "$WORLD"\n'
        '    -autocreate "${AUTOCREATE:-2}"\n'
        '    -worldname "$WORLDNAME"\n'
        '    -difficulty "${DIFFICULTY:-0}"\n'
        '    -port "${PORT:-7777}"\n'
        '    -maxplayers "${MAXPLAYERS:-8}"\n'
        '    -motd "$MOTD"\n'
        f'    -logpath "{server_dir}/logs"\n'
        ")\n"
        '[[ -n "$PASSWORD" ]] && ARGS+=(-password "$PASSWORD")\n'
        'exec ./TerrariaServer.bin.x86_64 "${ARGS[@]}"\n'
    )


def render_terraria_wrapper_script(*, start_script: str) -> str:
    return (
        "#!/usr/bin/env bash\n"
        f'exec /usr/bin/script -qefc "{start_script}" /dev/null\n'
    )


def render_soulmask_start_script(*, server_dir: str, cfg_path: str) -> str:
    return (
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f'cd "{server_dir}"\n'
        f'CFG="{cfg_path}"\n'
        "json_get() {\n"
        '    jq -r "$1" "$CFG"\n'
        "}\n"
        'SERVER_NAME="$(json_get \'.server_name\')"\n'
        'MAX_PLAYERS="$(json_get \'.max_players\')"\n'
        'PASSWORD="$(json_get \'.password\')"\n'
        'ADMIN_PASSWORD="$(json_get \'.admin_password\')"\n'
        'MODE="$(json_get \'.mode\')"\n'
        'PORT="$(json_get \'.port\')"\n'
        'QUERY_PORT="$(json_get \'.query_port\')"\n'
        'ECHO_PORT="$(json_get \'.echo_port\')"\n'
        'BACKUP_ENABLED="$(json_get \'.backup_enabled\')"\n'
        'SAVING_ENABLED="$(json_get \'.saving_enabled\')"\n'
        'BACKUP_INTERVAL="$(json_get \'.backup_interval\')"\n'
        "ARGS=(\n"
        '  "-SteamServerName=${SERVER_NAME}"\n'
        '  "-MaxPlayers=${MAX_PLAYERS}"\n'
        '  "-Port=${PORT}"\n'
        '  "-QueryPort=${QUERY_PORT}"\n'
        ")\n"
        '[[ -n "$PASSWORD" && "$PASSWORD" != "null" ]] && ARGS+=("-PSW=${PASSWORD}")\n'
        '[[ -n "$ADMIN_PASSWORD" && "$ADMIN_PASSWORD" != "null" ]] && ARGS+=("-adminpsw=${ADMIN_PASSWORD}")\n'
        '[[ "$MODE" == "pvp" ]] && ARGS+=(-pvp) || ARGS+=(-pve)\n'
        '[[ "$BACKUP_ENABLED" == "true" ]] && ARGS+=(-backup)\n'
        '[[ "$SAVING_ENABLED" == "true" ]] && ARGS+=(-saving)\n'
        '[[ -n "$BACKUP_INTERVAL" && "$BACKUP_INTERVAL" != "null" ]] && ARGS+=("-backupinterval=${BACKUP_INTERVAL}")\n'
        'exec ./WSServer.sh Level01_Main -server "${ARGS[@]}" -log -UTF8Output -MULTIHOME=0.0.0.0 "-EchoPort=${ECHO_PORT}" -forcepassthrough\n'
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


def _cmd_enshrouded(args: argparse.Namespace) -> int:
    content = render_enshrouded_start_script(
        server_dir=args.server_dir,
        home_dir=args.home_dir,
    )
    write_start_script(out_path=args.out, content=content, sys_user=args.sys_user)
    print(args.out)
    return 0


def _cmd_terraria(args: argparse.Namespace) -> int:
    content = render_terraria_start_script(server_dir=args.server_dir)
    write_start_script(out_path=args.out, content=content, sys_user=args.sys_user)
    if args.wrapper_out:
        wrapper = render_terraria_wrapper_script(start_script=args.out)
        write_start_script(out_path=args.wrapper_out, content=wrapper, sys_user=args.sys_user)
    print(args.out)
    return 0


def _cmd_soulmask(args: argparse.Namespace) -> int:
    content = render_soulmask_start_script(server_dir=args.server_dir, cfg_path=args.cfg_path)
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

    enshrouded = sub.add_parser("enshrouded")
    enshrouded.add_argument("--out", required=True)
    enshrouded.add_argument("--server-dir", required=True)
    enshrouded.add_argument("--home-dir", required=True)
    enshrouded.add_argument("--sys-user", required=True)
    enshrouded.set_defaults(func=_cmd_enshrouded)

    terraria = sub.add_parser("terraria")
    terraria.add_argument("--out", required=True)
    terraria.add_argument("--wrapper-out")
    terraria.add_argument("--server-dir", required=True)
    terraria.add_argument("--sys-user", required=True)
    terraria.set_defaults(func=_cmd_terraria)

    soulmask = sub.add_parser("soulmask")
    soulmask.add_argument("--out", required=True)
    soulmask.add_argument("--server-dir", required=True)
    soulmask.add_argument("--cfg-path", required=True)
    soulmask.add_argument("--sys-user", required=True)
    soulmask.set_defaults(func=_cmd_soulmask)

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
