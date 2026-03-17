#!/usr/bin/env python3
"""Helpers Python pour la copie du runtime Game Commander d'instance."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


EXCLUDES = {"__pycache__", "metrics.log", "users.json", "game.json", "deploy_config.env"}


def resolve_runtime_src_dir(src_dir: str | Path) -> Path:
    src = Path(src_dir)
    if (src / "runtime" / "app.py").is_file():
        return src / "runtime"
    if (src / "app.py").is_file():
        return src
    raise FileNotFoundError(f"Sources runtime introuvables dans {src}")


def copy_runtime_tree(runtime_src: str | Path, app_dir: str | Path) -> None:
    src = Path(runtime_src)
    dst = Path(app_dir)
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        if item.name in EXCLUDES or item.name.endswith(".pyc"):
            continue
        target = dst / item.name
        if item.is_dir():
            shutil.copytree(
                item,
                target,
                dirs_exist_ok=True,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
        else:
            shutil.copy2(item, target)


def ensure_metrics_file(app_dir: str | Path, sys_user: str) -> str:
    metrics = Path(app_dir) / "metrics.log"
    if not metrics.exists():
        metrics.touch()
        subprocess.run(["chown", f"{sys_user}:{sys_user}", str(metrics)], check=False)
        subprocess.run(["chmod", "640", str(metrics)], check=False)
        return "metrics.log créé"
    return "metrics.log conservé"


def ensure_users_json(
    *,
    app_dir: str,
    admin_login: str,
    admin_password: str,
    game_id: str,
    script_dir: str,
    sys_user: str,
) -> str:
    users_file = Path(app_dir) / "users.json"
    if users_file.is_file():
        return "users.json existant conservé"
    admin_hash = subprocess.check_output(
        [
            "python3",
            "-c",
            "import bcrypt,sys; print(bcrypt.hashpw(sys.argv[1].encode(), bcrypt.gensalt()).decode())",
            admin_password,
        ],
        text=True,
    ).strip()
    subprocess.run(
        [
            "python3",
            str(Path(script_dir) / "tools" / "config_gen.py"),
            "users-json",
            "--out",
            str(users_file),
            "--admin",
            admin_login,
            "--hash",
            admin_hash,
            "--game-id",
            game_id,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(["chmod", "600", str(users_file)], check=False)
    subprocess.run(["chown", f"{sys_user}:{sys_user}", str(users_file)], check=False)
    return f"users.json créé — admin : {admin_login}"


def write_game_json(
    *,
    app_dir: str,
    script_dir: str,
    game_id: str,
    game_label: str,
    game_binary: str,
    game_service: str,
    server_dir: str,
    data_dir: str,
    world_name: str,
    max_players: str,
    server_port: str,
    url_prefix: str,
    flask_port: str,
    admin_login: str,
    bepinex_path: str,
    steam_appid: str,
    steamcmd_path: str,
    query_port: str = "",
    echo_port: str = "",
) -> str:
    cmd = [
        "python3",
        str(Path(script_dir) / "tools" / "config_gen.py"),
        "game-json",
        "--out", str(Path(app_dir) / "game.json"),
        "--game-id", game_id,
        "--game-label", game_label,
        "--game-binary", game_binary,
        "--game-service", game_service,
        "--server-dir", server_dir,
        "--data-dir", data_dir or server_dir,
        "--world-name", world_name or "",
        "--max-players", str(max_players),
        "--port", str(server_port),
        "--url-prefix", url_prefix,
        "--flask-port", str(flask_port),
        "--admin-user", admin_login,
        "--bepinex-path", bepinex_path or "",
        "--steam-appid", steam_appid or "",
        "--steamcmd-path", steamcmd_path or "",
    ]
    if query_port:
        cmd.extend(["--query-port", str(query_port)])
    if echo_port:
        cmd.extend(["--echo-port", str(echo_port)])
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    return "game.json généré"


def install_app_files(
    *,
    deploy_app: bool,
    src_dir: str,
    app_dir: str,
    sys_user: str,
    script_dir: str,
    game_id: str,
    game_label: str,
    game_binary: str,
    game_service: str,
    server_dir: str,
    data_dir: str,
    world_name: str,
    max_players: str,
    server_port: str,
    query_port: str,
    echo_port: str,
    url_prefix: str,
    flask_port: str,
    admin_login: str,
    admin_password: str,
    bepinex: bool,
    steam_appid: str,
    steamcmd_path: str,
) -> tuple[bool, list[str]]:
    messages: list[str] = []
    app_path = Path(app_dir)
    if not deploy_app:
        messages.append("Sources introuvables — Game Commander ignoré")
        ensure_metrics_file(app_path, sys_user)
        return True, messages

    runtime_src = resolve_runtime_src_dir(src_dir)
    app_path.mkdir(parents=True, exist_ok=True)
    copy_runtime_tree(runtime_src, app_path)
    subprocess.run(["chown", "-R", f"{sys_user}:{sys_user}", str(app_path)], check=False)
    messages.append(f"Fichiers Game Commander copiés dans {app_path}")

    gc_bepinex_path = f"{server_dir}/BepInEx" if game_id == "valheim" and bepinex else ""
    messages.append(
        write_game_json(
            app_dir=app_dir,
            script_dir=script_dir,
            game_id=game_id,
            game_label=game_label,
            game_binary=game_binary,
            game_service=game_service,
            server_dir=server_dir,
            data_dir=data_dir or server_dir,
            world_name=world_name,
            max_players=max_players,
            server_port=server_port,
            url_prefix=url_prefix,
            flask_port=flask_port,
            admin_login=admin_login,
            bepinex_path=gc_bepinex_path,
            steam_appid=steam_appid,
            steamcmd_path=steamcmd_path,
            query_port=query_port,
            echo_port=echo_port,
        )
    )
    messages.append(
        ensure_users_json(
            app_dir=app_dir,
            admin_login=admin_login,
            admin_password=admin_password,
            game_id=game_id,
            script_dir=script_dir,
            sys_user=sys_user,
        )
    )
    messages.append(ensure_metrics_file(app_path, sys_user))
    return True, messages


def _cmd_install(args: argparse.Namespace) -> int:
    ok, messages = install_app_files(
        deploy_app=args.deploy_app,
        src_dir=args.src_dir,
        app_dir=args.app_dir,
        sys_user=args.sys_user,
        script_dir=args.script_dir,
        game_id=args.game_id,
        game_label=args.game_label,
        game_binary=args.game_binary,
        game_service=args.game_service,
        server_dir=args.server_dir,
        data_dir=args.data_dir,
        world_name=args.world_name,
        max_players=args.max_players,
        server_port=args.server_port,
        query_port=args.query_port,
        echo_port=args.echo_port,
        url_prefix=args.url_prefix,
        flask_port=args.flask_port,
        admin_login=args.admin_login,
        admin_password=args.admin_password,
        bepinex=args.bepinex,
        steam_appid=args.steam_appid,
        steamcmd_path=args.steamcmd_path,
    )
    stream = sys.stdout if ok else sys.stderr
    for line in messages:
        print(line, file=stream)
    return 0 if ok else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Game Commander deploy app files helper")
    sub = parser.add_subparsers(dest="command", required=True)
    install = sub.add_parser("install")
    install.add_argument("--deploy-app", action="store_true")
    install.add_argument("--src-dir", required=True)
    install.add_argument("--app-dir", required=True)
    install.add_argument("--sys-user", required=True)
    install.add_argument("--script-dir", required=True)
    install.add_argument("--game-id", required=True)
    install.add_argument("--game-label", required=True)
    install.add_argument("--game-binary", required=True)
    install.add_argument("--game-service", required=True)
    install.add_argument("--server-dir", required=True)
    install.add_argument("--data-dir", required=True)
    install.add_argument("--world-name", default="")
    install.add_argument("--max-players", required=True)
    install.add_argument("--server-port", required=True)
    install.add_argument("--query-port", default="")
    install.add_argument("--echo-port", default="")
    install.add_argument("--url-prefix", required=True)
    install.add_argument("--flask-port", required=True)
    install.add_argument("--admin-login", required=True)
    install.add_argument("--admin-password", required=True)
    install.add_argument("--steam-appid", default="")
    install.add_argument("--steamcmd-path", default="")
    install.add_argument("--bepinex", action="store_true")
    install.set_defaults(func=_cmd_install)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
