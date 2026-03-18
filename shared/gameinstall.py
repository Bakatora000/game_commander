#!/usr/bin/env python3
"""Installation Python des serveurs de jeu simples."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path


def _fetch_json(url: str) -> dict | list:
    with urllib.request.urlopen(url, timeout=20) as response:
        return json.load(response)


def latest_minecraft_server_url(fetch_json=_fetch_json) -> tuple[str, str]:
    manifest = fetch_json("https://launchermeta.mojang.com/mc/game/version_manifest_v2.json")
    latest_id = manifest["latest"]["release"]
    version_meta_url = next(v["url"] for v in manifest["versions"] if v["id"] == latest_id)
    version_meta = fetch_json(version_meta_url)
    return latest_id, version_meta["downloads"]["server"]["url"]


def latest_fabric_server_meta(fetch_json=_fetch_json) -> dict[str, str]:
    manifest = fetch_json("https://launchermeta.mojang.com/mc/game/version_manifest_v2.json")
    mc_version = manifest["latest"]["release"]
    loader_version = fetch_json("https://meta.fabricmc.net/v2/versions/loader")[0]["version"]
    installer_version = fetch_json("https://meta.fabricmc.net/v2/versions/installer")[0]["version"]
    jar_url = f"https://meta.fabricmc.net/v2/versions/loader/{mc_version}/{loader_version}/{installer_version}/server/jar"
    return {
        "minecraft_version": mc_version,
        "loader_version": loader_version,
        "installer_version": installer_version,
        "loader": "fabric",
        "jar_url": jar_url,
    }


def _download_file(url: str, output_path: Path) -> None:
    with urllib.request.urlopen(url, timeout=60) as response, output_path.open("wb") as fh:
        fh.write(response.read())


def _run_steamcmd(*, sys_user: str, steamcmd_path: str, platform: str, install_dir: Path, steam_appid: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            "sudo",
            "-u",
            sys_user,
            steamcmd_path,
            "+@sSteamCmdForcePlatformType",
            platform,
            "+force_install_dir",
            str(install_dir),
            "+login",
            "anonymous",
            "+app_update",
            str(steam_appid),
            "validate",
            "+quit",
        ],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )


def _run_config_gen_minecraft_props(
    *,
    script_dir: str,
    output_path: Path,
    server_name: str,
    server_port: str,
    max_players: str,
) -> None:
    subprocess.run(
        [
            "python3",
            str(Path(script_dir) / "tools" / "config_gen.py"),
            "minecraft-props",
            "--out",
            str(output_path),
            "--name",
            server_name,
            "--port",
            str(server_port),
            "--max-players",
            str(max_players),
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def _chown_paths(sys_user: str, *paths: Path) -> None:
    valid = [str(path) for path in paths if path.exists()]
    if valid:
        subprocess.run(["chown", f"{sys_user}:{sys_user}", *valid], check=False)


def _chown_tree(sys_user: str, path: Path) -> None:
    if path.exists():
        subprocess.run(["chown", "-R", f"{sys_user}:{sys_user}", str(path)], check=False)


def install_minecraft_java(
    *,
    script_dir: str,
    server_dir: str,
    sys_user: str,
    server_name: str,
    server_port: str,
    max_players: str,
) -> list[str]:
    messages: list[str] = []
    server_path = Path(server_dir)
    server_path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["chown", "-R", f"{sys_user}:{sys_user}", str(server_path)], check=False)

    jar_path = server_path / "server.jar"
    if jar_path.is_file():
        messages.append("server.jar déjà présent")
    else:
        version_id, jar_url = latest_minecraft_server_url()
        _download_file(jar_url, jar_path)
        _chown_paths(sys_user, jar_path)
        messages.append(f"Serveur Minecraft Java téléchargé ({version_id})")

    eula_path = server_path / "eula.txt"
    if not eula_path.is_file():
        eula_path.write_text("# EULA acceptée automatiquement par Game Commander\neula=true\n", encoding="utf-8")
        _chown_paths(sys_user, eula_path)
        messages.append("eula.txt généré")

    props_path = server_path / "server.properties"
    if not props_path.is_file():
        _run_config_gen_minecraft_props(
            script_dir=script_dir,
            output_path=props_path,
            server_name=server_name,
            server_port=server_port,
            max_players=max_players,
        )
        _chown_paths(sys_user, props_path)
        messages.append("server.properties généré")
    return messages


def install_minecraft_fabric(
    *,
    script_dir: str,
    server_dir: str,
    sys_user: str,
    server_name: str,
    server_port: str,
    max_players: str,
) -> list[str]:
    messages: list[str] = []
    server_path = Path(server_dir)
    server_path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["chown", "-R", f"{sys_user}:{sys_user}", str(server_path)], check=False)

    jar_path = server_path / "fabric-server-launch.jar"
    meta_path = server_path / ".fabric-meta.json"
    if jar_path.is_file():
        messages.append("Fabric server launcher déjà présent")
    else:
        meta = latest_fabric_server_meta()
        _download_file(meta["jar_url"], jar_path)
        meta_path.write_text(
            json.dumps(
                {
                    "minecraft_version": meta["minecraft_version"],
                    "loader_version": meta["loader_version"],
                    "installer_version": meta["installer_version"],
                    "loader": "fabric",
                },
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )
        _chown_paths(sys_user, jar_path, meta_path)
        messages.append("Serveur Minecraft Fabric téléchargé")

    eula_path = server_path / "eula.txt"
    if not eula_path.is_file():
        eula_path.write_text("# EULA acceptée automatiquement par Game Commander\neula=true\n", encoding="utf-8")
        _chown_paths(sys_user, eula_path)
        messages.append("eula.txt généré")

    mods_path = server_path / "mods"
    mods_path.mkdir(exist_ok=True)
    subprocess.run(["chown", f"{sys_user}:{sys_user}", str(mods_path)], check=False)

    props_path = server_path / "server.properties"
    if not props_path.is_file():
        _run_config_gen_minecraft_props(
            script_dir=script_dir,
            output_path=props_path,
            server_name=server_name,
            server_port=server_port,
            max_players=max_players,
        )
        _chown_paths(sys_user, props_path)
        messages.append("server.properties généré")
    return messages


def install_satisfactory(
    *,
    server_dir: str,
    data_dir: str,
    sys_user: str,
    steamcmd_path: str,
    steam_appid: str,
) -> list[str]:
    messages: list[str] = []
    server_path = Path(server_dir)
    data_path = Path(data_dir)
    server_path.mkdir(parents=True, exist_ok=True)
    data_path.mkdir(parents=True, exist_ok=True)
    _chown_tree(sys_user, server_path)
    _chown_tree(sys_user, data_path)

    result = _run_steamcmd(
        sys_user=sys_user,
        steamcmd_path=steamcmd_path,
        platform="linux",
        install_dir=server_path,
        steam_appid=steam_appid,
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "Échec SteamCMD").strip())

    binary_path = server_path / "FactoryServer.sh"
    if not binary_path.is_file():
        raise RuntimeError(f"Binaire FactoryServer.sh introuvable dans {server_path}")
    try:
        binary_path.chmod(binary_path.stat().st_mode | 0o111)
    except OSError:
        pass
    _chown_tree(sys_user, server_path)
    messages.append("Serveur Satisfactory téléchargé")
    messages.append("Binaire FactoryServer.sh vérifié")
    return messages


def install_valheim(
    *,
    server_dir: str,
    data_dir: str,
    sys_user: str,
    steamcmd_path: str,
    steam_appid: str,
    install_server: bool,
    install_bepinex: bool,
) -> list[str]:
    messages: list[str] = []
    server_path = Path(server_dir)
    data_path = Path(data_dir)
    server_path.mkdir(parents=True, exist_ok=True)
    data_path.mkdir(parents=True, exist_ok=True)
    _chown_tree(sys_user, server_path)
    _chown_tree(sys_user, data_path)

    if install_server:
        result = _run_steamcmd(
            sys_user=sys_user,
            steamcmd_path=steamcmd_path,
            platform="linux",
            install_dir=server_path,
            steam_appid=steam_appid,
        )
        if result.returncode != 0:
            raise RuntimeError((result.stderr or result.stdout or "Échec SteamCMD").strip())
        messages.append("Serveur Valheim téléchargé")

    binary_path = server_path / "valheim_server.x86_64"
    if not binary_path.is_file():
        raise RuntimeError(f"Binaire valheim_server.x86_64 introuvable dans {server_path}")
    try:
        binary_path.chmod(binary_path.stat().st_mode | 0o111)
    except OSError:
        pass
    _chown_tree(sys_user, server_path)
    messages.append("Binaire valheim_server.x86_64 vérifié")

    if install_bepinex:
        bepinex_path = server_path / "BepInEx"
        if bepinex_path.is_dir():
            messages.append("BepInEx déjà présent")
        else:
            with tempfile.TemporaryDirectory() as tmp:
                tmp_path = Path(tmp)
                zip_path = tmp_path / "bep.zip"
                extract_path = tmp_path / "extracted"
                _download_file(
                    "https://thunderstore.io/package/download/denikson/BepInExPack_Valheim/5.4.2202/",
                    zip_path,
                )
                with zipfile.ZipFile(zip_path) as zf:
                    zf.extractall(extract_path)
                src_path = extract_path
                candidate = extract_path / "BepInExPack_Valheim"
                if candidate.is_dir():
                    src_path = candidate
                for entry in src_path.iterdir():
                    dest = server_path / entry.name
                    if dest.exists():
                        if dest.is_dir():
                            shutil.rmtree(dest)
                        else:
                            dest.unlink()
                    if entry.is_dir():
                        shutil.copytree(entry, dest)
                    else:
                        shutil.copy2(entry, dest)
            display_info = server_path / "BepInEx" / "plugins" / "Valheim.DisplayBepInExInfo.dll"
            if display_info.exists():
                display_info.unlink()
            _chown_tree(sys_user, server_path)
            messages.append("BepInEx installé")
    return messages


def _cmd_minecraft(args: argparse.Namespace) -> int:
    try:
        if args.fabric:
            messages = install_minecraft_fabric(
                script_dir=args.script_dir,
                server_dir=args.server_dir,
                sys_user=args.sys_user,
                server_name=args.server_name,
                server_port=args.server_port,
                max_players=args.max_players,
            )
        else:
            messages = install_minecraft_java(
                script_dir=args.script_dir,
                server_dir=args.server_dir,
                sys_user=args.sys_user,
                server_name=args.server_name,
                server_port=args.server_port,
                max_players=args.max_players,
            )
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    for line in messages:
        print(line)
    return 0


def _cmd_satisfactory(args: argparse.Namespace) -> int:
    try:
        messages = install_satisfactory(
            server_dir=args.server_dir,
            data_dir=args.data_dir,
            sys_user=args.sys_user,
            steamcmd_path=args.steamcmd_path,
            steam_appid=args.steam_appid,
        )
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    for line in messages:
        print(line)
    return 0


def _cmd_valheim(args: argparse.Namespace) -> int:
    try:
        messages = install_valheim(
            server_dir=args.server_dir,
            data_dir=args.data_dir,
            sys_user=args.sys_user,
            steamcmd_path=args.steamcmd_path,
            steam_appid=args.steam_appid,
            install_server=not args.skip_server_update,
            install_bepinex=args.install_bepinex,
        )
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    for line in messages:
        print(line)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Game Commander game install helper")
    sub = parser.add_subparsers(dest="command", required=True)

    minecraft = sub.add_parser("minecraft")
    minecraft.add_argument("--script-dir", required=True)
    minecraft.add_argument("--server-dir", required=True)
    minecraft.add_argument("--sys-user", required=True)
    minecraft.add_argument("--server-name", required=True)
    minecraft.add_argument("--server-port", required=True)
    minecraft.add_argument("--max-players", required=True)
    minecraft.add_argument("--fabric", action="store_true")
    minecraft.set_defaults(func=_cmd_minecraft)

    satisfactory = sub.add_parser("satisfactory")
    satisfactory.add_argument("--server-dir", required=True)
    satisfactory.add_argument("--data-dir", required=True)
    satisfactory.add_argument("--sys-user", required=True)
    satisfactory.add_argument("--steamcmd-path", required=True)
    satisfactory.add_argument("--steam-appid", required=True)
    satisfactory.set_defaults(func=_cmd_satisfactory)

    valheim = sub.add_parser("valheim")
    valheim.add_argument("--server-dir", required=True)
    valheim.add_argument("--data-dir", required=True)
    valheim.add_argument("--sys-user", required=True)
    valheim.add_argument("--steamcmd-path", required=True)
    valheim.add_argument("--steam-appid", required=True)
    valheim.add_argument("--skip-server-update", action="store_true")
    valheim.add_argument("--install-bepinex", action="store_true")
    valheim.set_defaults(func=_cmd_valheim)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
