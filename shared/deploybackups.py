#!/usr/bin/env python3
"""Helpers Python pour l'étape de sauvegardes automatiques du deploy."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


def effective_backup_dir(backup_dir: str, instance_id: str = "") -> Path:
    path = Path(backup_dir)
    if instance_id and path.name != instance_id:
        return path / instance_id
    return path


def world_dir_for_game(game_id: str, server_dir: str, data_dir: str, world_name: str = "") -> str:
    if game_id == "valheim":
        worlds_local = Path(data_dir) / "worlds_local"
        return str(worlds_local if worlds_local.is_dir() else Path(data_dir) / "worlds")
    if game_id == "enshrouded":
        return str(Path(server_dir) / "savegame")
    if game_id in {"minecraft", "minecraft-fabric"}:
        return str(Path(server_dir) / "world")
    if game_id == "terraria":
        return data_dir
    if game_id == "satisfactory":
        return str(Path(data_dir) / ".config" / "Epic" / "FactoryGame" / "Saved" / "SaveGames")
    if game_id == "soulmask":
        return str(Path(server_dir) / "WS" / "Saved")
    raise ValueError(f"Jeu non supporté: {game_id}")


def render_backup_script(
    *,
    game_id: str,
    backup_dir: str,
    world_dir: str,
    world_name: str = "",
    server_dir: str = "",
) -> str:
    if game_id == "valheim":
        return f"""#!/usr/bin/env bash
BACKUP_DIR="{backup_dir}"
WORLD_DIR="{world_dir}"
WORLD_NAME="{world_name}"
RETENTION=7
TS=$(date +%Y%m%d_%H%M%S)
ARC="${{BACKUP_DIR}}/${{WORLD_NAME}}_${{TS}}.zip"
FILES=()
for f in "${{WORLD_DIR}}/${{WORLD_NAME}}.db" "${{WORLD_DIR}}/${{WORLD_NAME}}.fwl" \\
          "${{WORLD_DIR}}/${{WORLD_NAME}}.db.old" "${{WORLD_DIR}}/${{WORLD_NAME}}.fwl.old"; do
    [[ -f "$f" ]] && FILES+=("$f")
done
[[ ${{#FILES[@]}} -eq 0 ]] && {{ echo "[$(date)] WARN: aucun fichier monde" >&2; exit 1; }}
mkdir -p "$BACKUP_DIR"
zip -j "$ARC" "${{FILES[@]}}" -q \\
    && echo "[$(date)] OK: $(basename "$ARC") ($(du -sh "$ARC"|cut -f1))" \\
    || {{ echo "[$(date)] ERROR: zip échoué" >&2; exit 1; }}
find "$BACKUP_DIR" -name "${{WORLD_NAME}}_*.zip" -mtime +${{RETENTION}} -delete
"""
    if game_id in {"minecraft", "minecraft-fabric"}:
        return f"""#!/usr/bin/env bash
BACKUP_DIR="{backup_dir}"
SERVER_DIR="{server_dir}"
WORLD_DIR="{world_dir}"
PREFIX="{game_id}"
RETENTION=7
TS=$(date +%Y%m%d_%H%M%S)
ARC="${{BACKUP_DIR}}/${{PREFIX}}_save_${{TS}}.zip"
[[ ! -d "$WORLD_DIR" ]] && {{ echo "[$(date)] WARN: $WORLD_DIR introuvable" >&2; exit 1; }}
mkdir -p "$BACKUP_DIR"
FILES=("$(basename "$WORLD_DIR")")
for f in server.properties ops.json whitelist.json banned-players.json banned-ips.json usercache.json; do
    [[ -f "$SERVER_DIR/$f" ]] && FILES+=("$f")
done
(
    cd "$SERVER_DIR"
    zip -r "$ARC" "${{FILES[@]}}" -q
) && echo "[$(date)] OK: $(basename "$ARC") ($(du -sh "$ARC"|cut -f1))" \\
  || {{ echo "[$(date)] ERROR" >&2; exit 1; }}
find "$BACKUP_DIR" -name "${{PREFIX}}_save_*.zip" -mtime +${{RETENTION}} -delete
"""
    return f"""#!/usr/bin/env bash
BACKUP_DIR="{backup_dir}"
WORLD_DIR="{world_dir}"
PREFIX="{game_id}"
RETENTION=7
TS=$(date +%Y%m%d_%H%M%S)
ARC="${{BACKUP_DIR}}/${{PREFIX}}_save_${{TS}}.zip"
[[ ! -d "$WORLD_DIR" ]] && {{ echo "[$(date)] WARN: $WORLD_DIR introuvable" >&2; exit 1; }}
mkdir -p "$BACKUP_DIR"
ROOT_PARENT="$(dirname "$WORLD_DIR")"
ROOT_NAME="$(basename "$WORLD_DIR")"
(
    cd "$ROOT_PARENT"
    zip -r "$ARC" "$ROOT_NAME" -q
) \\
    && echo "[$(date)] OK: $(basename "$ARC") ($(du -sh "$ARC"|cut -f1))" \\
    || {{ echo "[$(date)] ERROR" >&2; exit 1; }}
find "$BACKUP_DIR" -name "${{PREFIX}}_save_*.zip" -mtime +${{RETENTION}} -delete
"""


def install_backup_assets(
    *,
    sys_user: str,
    app_dir: str,
    backup_dir: str,
    instance_id: str,
    game_id: str,
    server_dir: str,
    data_dir: str,
    world_name: str,
    skip_backup_test: bool = False,
) -> tuple[bool, list[str]]:
    messages: list[str] = []
    app_path = Path(app_dir)
    effective_dir = effective_backup_dir(backup_dir, instance_id)
    world_dir = world_dir_for_game(game_id, server_dir, data_dir, world_name)

    app_path.mkdir(parents=True, exist_ok=True)
    effective_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(["chown", f"{sys_user}:{sys_user}", str(app_path)], check=False)
    subprocess.run(["chown", f"{sys_user}:{sys_user}", str(effective_dir)], check=False)

    backup_script = app_path / f"backup_{game_id}.sh"
    backup_script.write_text(
        render_backup_script(
            game_id=game_id,
            backup_dir=str(effective_dir),
            world_dir=world_dir,
            world_name=world_name,
            server_dir=server_dir,
        ),
        encoding="utf-8",
    )
    backup_script.chmod(0o755)
    try:
        uid = int(subprocess.check_output(["id", "-u", sys_user], text=True).strip())
        gid = int(subprocess.check_output(["id", "-g", sys_user], text=True).strip())
        os.chown(backup_script, uid, gid)
    except Exception:
        pass
    messages.append(f"Script de sauvegarde : {backup_script}")

    if skip_backup_test:
        messages.append("Test sauvegarde ignoré pour cette mise à jour")
    else:
        test_run = subprocess.run(
            ["sudo", "-u", sys_user, "bash", str(backup_script)],
            capture_output=True,
            text=True,
            check=False,
        )
        if test_run.returncode == 0:
            messages.append("Test sauvegarde réussi")
        else:
            messages.append("Test sauvegarde : aucun fichier trouvé (normal avant le premier lancement)")

    cron_line = f"0 3 * * * {backup_script} >> {app_path}/backup_{game_id}.log 2>&1"
    existing = subprocess.run(["crontab", "-u", sys_user, "-l"], capture_output=True, text=True, check=False).stdout
    if cron_line in existing:
        messages.append("Cron déjà configuré")
    else:
        merged = existing.rstrip("\n")
        merged = f"{merged}\n{cron_line}\n" if merged else f"{cron_line}\n"
        cron_apply = subprocess.run(["crontab", "-u", sys_user, "-"], input=merged, text=True, capture_output=True, check=False)
        if cron_apply.returncode != 0:
            detail = (cron_apply.stderr or cron_apply.stdout or "").strip()
            return False, messages + [detail or "Échec configuration cron"]
        messages.append("Cron : 3h00 quotidien")
    return True, messages


def _cmd_install(args: argparse.Namespace) -> int:
    ok, messages = install_backup_assets(
        sys_user=args.sys_user,
        app_dir=args.app_dir,
        backup_dir=args.backup_dir,
        instance_id=args.instance_id,
        game_id=args.game_id,
        server_dir=args.server_dir,
        data_dir=args.data_dir,
        world_name=args.world_name,
        skip_backup_test=args.skip_backup_test,
    )
    stream = sys.stdout if ok else sys.stderr
    for line in messages:
        print(line, file=stream)
    return 0 if ok else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Game Commander deploy backups helper")
    sub = parser.add_subparsers(dest="command", required=True)
    install = sub.add_parser("install")
    install.add_argument("--sys-user", required=True)
    install.add_argument("--app-dir", required=True)
    install.add_argument("--backup-dir", required=True)
    install.add_argument("--instance-id", default="")
    install.add_argument("--game-id", required=True)
    install.add_argument("--server-dir", required=True)
    install.add_argument("--data-dir", required=True)
    install.add_argument("--world-name", default="")
    install.add_argument("--skip-backup-test", action="store_true")
    install.set_defaults(func=_cmd_install)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
