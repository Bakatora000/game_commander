#!/usr/bin/env python3
"""Sudoers helpers for Game Commander deploy flows."""
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


def render_instance_sudoers(sys_user: str, game_label: str, instance_id: str, game_service: str, bepinex_path: str = "") -> str:
    lines = [
        f"# Game Commander — {game_label} ({instance_id})",
        f"{sys_user} ALL=(ALL) NOPASSWD: /usr/bin/systemctl start {game_service}",
        f"{sys_user} ALL=(ALL) NOPASSWD: /usr/bin/systemctl stop {game_service}",
        f"{sys_user} ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart {game_service}",
    ]
    if bepinex_path:
        lines.extend(
            [
                f"{sys_user} ALL=(ALL) NOPASSWD: /usr/bin/chown -R {sys_user} {bepinex_path}",
                f"{sys_user} ALL=(ALL) NOPASSWD: /usr/bin/chmod -R 755 {bepinex_path}",
                f"{sys_user} ALL=(ALL) NOPASSWD: /usr/bin/find {bepinex_path} -type d",
                f"{sys_user} ALL=(ALL) NOPASSWD: /bin/rm -rf {bepinex_path}/plugins/*",
                f"{sys_user} ALL=(ALL) NOPASSWD: /bin/rm -f {bepinex_path}/plugins/*",
            ]
        )
    return "\n".join(lines) + "\n"


def write_instance_sudoers(
    sys_user: str,
    game_label: str,
    instance_id: str,
    game_service: str,
    bepinex_path: str = "",
) -> tuple[bool, str]:
    sudoers_file = Path(f"/etc/sudoers.d/game-commander-{instance_id}")
    sudoers_file.write_text(
        render_instance_sudoers(sys_user, game_label, instance_id, game_service, bepinex_path),
        encoding="utf-8",
    )
    sudoers_file.chmod(0o440)
    result = subprocess.run(["visudo", "-cf", str(sudoers_file)], capture_output=True, text=True, check=False)
    if result.returncode == 0:
        return True, f"Sudoers : {sudoers_file}"
    sudoers_file.unlink(missing_ok=True)
    message = (result.stderr or result.stdout or "").strip()
    return False, message or "Sudoers invalide"


def _cmd_write(args: argparse.Namespace) -> int:
    ok, message = write_instance_sudoers(
        sys_user=args.sys_user,
        game_label=args.game_label,
        instance_id=args.instance_id,
        game_service=args.game_service,
        bepinex_path=args.bepinex_path,
    )
    print(message)
    return 0 if ok else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Game Commander deploy sudoers helper")
    sub = parser.add_subparsers(dest="command", required=True)
    write = sub.add_parser("write-instance")
    write.add_argument("--sys-user", required=True)
    write.add_argument("--game-label", required=True)
    write.add_argument("--instance-id", required=True)
    write.add_argument("--game-service", required=True)
    write.add_argument("--bepinex-path", default="")
    write.set_defaults(func=_cmd_write)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
