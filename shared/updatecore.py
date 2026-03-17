#!/usr/bin/env python3
"""Native core update logic for Game Commander instances."""
from __future__ import annotations

import os
import pwd
import subprocess
import sys
from pathlib import Path

from . import instanceenv


def runtime_src_dir(repo_root: str | Path) -> Path | None:
    root = Path(repo_root)
    candidate = root / "runtime"
    if (candidate / "app.py").is_file():
        return candidate
    if (root / "app.py").is_file():
        return root
    return None


def _chown_path(path: Path, sys_user: str) -> None:
    pw = pwd.getpwnam(sys_user)
    uid, gid = pw.pw_uid, pw.pw_gid
    if path.is_dir():
        for root, dirs, files in os.walk(path):
            os.chown(root, uid, gid)
            for name in dirs:
                os.chown(os.path.join(root, name), uid, gid)
            for name in files:
                os.chown(os.path.join(root, name), uid, gid)
    elif path.exists():
        os.chown(path, uid, gid)


def _run(cmd: list[str], timeout: int = 300) -> tuple[bool, str]:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    except Exception as exc:
        return False, str(exc)
    if result.returncode == 0:
        return True, (result.stdout or "").strip()
    return False, (result.stderr or result.stdout or "").strip() or f"Commande échouée ({result.returncode})"


def _game_json_args(env: dict[str, str], repo_root: Path) -> list[str]:
    game_id = env["GAME_ID"]
    instance_id = env["INSTANCE_ID"]
    meta = instanceenv.game_meta(game_id)
    server_dir = env.get("SERVER_DIR", "")
    data_dir = env.get("DATA_DIR") or server_dir
    query_port = env.get("QUERY_PORT", "")
    echo_port = env.get("ECHO_PORT", "")
    bepinex_path = ""
    if game_id == "valheim" and env.get("BEPINEX", "false") == "true":
        bepinex_path = f"{server_dir}/BepInEx"
    args = [
        sys.executable, str(repo_root / "tools" / "config_gen.py"), "game-json",
        "--out", env["APP_DIR"] + "/game.json",
        "--game-id", game_id,
        "--game-label", meta.get("label", game_id),
        "--game-binary", meta.get("binary", ""),
        "--game-service", env.get("GAME_SERVICE") or instanceenv.default_game_service(game_id, instance_id),
        "--server-dir", server_dir,
        "--data-dir", data_dir,
        "--world-name", env.get("WORLD_NAME", ""),
        "--max-players", env.get("MAX_PLAYERS", "20"),
        "--port", env.get("SERVER_PORT", ""),
        "--url-prefix", env.get("URL_PREFIX", ""),
        "--flask-port", env.get("FLASK_PORT", ""),
        "--admin-user", env.get("ADMIN_LOGIN", "admin"),
        "--bepinex-path", bepinex_path,
        "--steam-appid", env.get("STEAM_APPID", ""),
        "--steamcmd-path", env.get("STEAMCMD_PATH", ""),
    ]
    if query_port:
        args.extend(["--query-port", query_port])
    if echo_port:
        args.extend(["--echo-port", echo_port])
    return args


def run_core_update(config_file: str | Path, repo_root: str | Path) -> tuple[bool, list[str] | str]:
    cfg = Path(config_file)
    env = instanceenv.parse_env_file(cfg)
    game_id = env.get("GAME_ID", "")
    instance_id = env.get("INSTANCE_ID", "")
    app_dir = Path(env.get("APP_DIR", ""))
    sys_user = env.get("SYS_USER", "gameserver")
    if not game_id or not instance_id or not app_dir:
        return False, "Config d'instance incomplète"
    if not app_dir.is_dir():
        return False, f"APP_DIR introuvable : {app_dir}"
    runtime_src = runtime_src_dir(repo_root)
    if not runtime_src:
        return False, "Sources runtime introuvables"

    messages: list[str] = [f"Mise à jour de {instance_id} ({game_id})"]
    ok, message = _run(
        [
            "rsync", "-a", "--delete",
            "--exclude=__pycache__", "--exclude=*.pyc",
            "--exclude=metrics.log", "--exclude=users.json",
            "--exclude=game.json", "--exclude=deploy_config.env",
            f"{runtime_src}/", f"{app_dir}/",
        ],
        timeout=300,
    )
    if not ok:
        return False, message or "Échec synchronisation runtime"
    _chown_path(app_dir, sys_user)
    messages.append("Runtime synchronisé")

    ok, message = _run(_game_json_args(env, Path(repo_root)), timeout=120)
    if not ok:
        return False, message or "Échec génération game.json"
    _chown_path(app_dir / "game.json", sys_user)
    messages.append("game.json régénéré")

    metrics = app_dir / "metrics.log"
    if not metrics.exists():
        metrics.touch()
    _chown_path(metrics, sys_user)
    try:
        metrics.chmod(0o640)
    except OSError:
        pass
    messages.append("metrics.log vérifié")

    return True, messages

