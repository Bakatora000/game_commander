#!/usr/bin/env python3
"""Shared deploy planning helpers for instance paths and port groups."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def _run_stdout(cmd: list[str]) -> str:
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    return (result.stdout or "").strip()


def suggest_instance_id(game_id: str, home_dir: str | Path) -> str:
    base = str(game_id or "").strip() or "instance"
    home = Path(home_dir)
    candidate = base
    index = 2
    while (home / f"game-commander-{candidate}").exists() or _service_exists(f"game-commander-{candidate}"):
        candidate = f"{base}{index}"
        index += 1
    return candidate


def _service_exists(service_name: str) -> bool:
    output = _run_stdout(["systemctl", "list-units", "--full", "--all", f"{service_name}.service"])
    return f"{service_name}.service" in output


def apply_instance_defaults(
    *,
    game_id: str,
    instance_id: str,
    home_dir: str | Path,
    src_dir: str | Path,
    server_dir: str = "",
    data_dir: str = "",
    backup_dir: str = "",
    app_dir: str = "",
    game_service: str = "",
) -> dict[str, str]:
    iid = instance_id or suggest_instance_id(game_id, home_dir)
    home = Path(home_dir)
    resolved = {
        "INSTANCE_ID": iid,
        "SERVER_DIR": server_dir or str(home / f"{iid}_server"),
        "DATA_DIR": data_dir or str(home / f"{iid}_data"),
        "BACKUP_DIR": backup_dir or str(home / "gamebackups"),
        "APP_DIR": app_dir or str(home / f"game-commander-{iid}"),
        "SRC_DIR": str(src_dir),
        "GAME_SERVICE": game_service or f"{game_id}-server-{iid}",
        "GC_SERVICE": f"game-commander-{iid}",
    }
    if game_id == "enshrouded":
        resolved["DATA_DIR"] = resolved["SERVER_DIR"]
    return resolved


def _current_service_pid(game_service: str) -> str:
    if not game_service:
        return ""
    lines = _run_stdout(["systemctl", "show", game_service, "--property", "MainPID", "--value"]).splitlines()
    return lines[0] if lines else ""


def _ss_lines(proto: str, with_pids: bool) -> list[str]:
    args = ["ss", f"-{proto}ln{'p' if with_pids else ''}H"]
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    return (result.stdout or "").splitlines()


def port_group_specs(game_id: str) -> list[tuple[str, str, str]]:
    match game_id:
        case "minecraft" | "minecraft-fabric" | "terraria":
            return [("SERVER_PORT", "t", "Port principal")]
        case "satisfactory":
            return [
                ("SERVER_PORT", "t", "Port de jeu (TCP)"),
                ("SERVER_PORT", "u", "Port de jeu (UDP)"),
                ("QUERY_PORT", "t", "Port fiable / join"),
            ]
        case "soulmask":
            return [
                ("SERVER_PORT", "u", "Port de jeu"),
                ("QUERY_PORT", "u", "Port requête"),
                ("ECHO_PORT", "t", "Port Echo"),
            ]
        case "valheim":
            return [("SERVER_PORT", "u", "Port principal"), ("SERVER_PORT_PLUS1", "u", "Port query")]
        case "enshrouded":
            return [("SERVER_PORT", "u", "Port principal"), ("SERVER_PORT_PLUS1", "u", "Port requête")]
    return []


def port_group_step(game_id: str) -> int:
    return 2 if game_id in {"valheim", "enshrouded"} else 1


def _port_value(spec: str, server_port: int, query_port: int, echo_port: int) -> int:
    if spec == "SERVER_PORT":
        return server_port
    if spec == "QUERY_PORT":
        return query_port
    if spec == "ECHO_PORT":
        return echo_port
    if spec == "SERVER_PORT_PLUS1":
        return server_port + 1
    return 0


def first_port_group_conflict(
    *,
    game_id: str,
    server_port: int,
    query_port: int = 0,
    echo_port: int = 0,
    game_service: str = "",
) -> tuple[str, str, str, int] | None:
    ignored_pid = _current_service_pid(game_service)
    for spec, proto, label in port_group_specs(game_id):
        port = _port_value(spec, server_port, query_port, echo_port)
        if check_port_conflict(port, proto, ignored_pid):
            return spec, proto, label, port
    return None


def check_port_conflict(port: int, proto: str, ignored_pid: str = "") -> bool:
    for line in _ss_lines(proto, True):
        if f":{port} " not in line:
            continue
        if ignored_pid:
            marker = "pid="
            if marker in line:
                pid = line.split(marker, 1)[1].split(",", 1)[0].split(")", 1)[0]
                if pid == ignored_pid:
                    continue
        return True
    for line in _ss_lines(proto, False):
        if f":{port} " in line:
            return True
    return False


def suggest_free_port_group(
    *,
    game_id: str,
    server_port: int,
    query_port: int = 0,
    echo_port: int = 0,
    game_service: str = "",
) -> dict[str, str]:
    first = first_port_group_conflict(
        game_id=game_id,
        server_port=server_port,
        query_port=query_port,
        echo_port=echo_port,
        game_service=game_service,
    )
    step = port_group_step(game_id)
    while first_port_group_conflict(
        game_id=game_id,
        server_port=server_port,
        query_port=query_port,
        echo_port=echo_port,
        game_service=game_service,
    ):
        server_port += step
        if query_port:
            query_port += step
        if echo_port:
            echo_port += step
    result = {
        "SERVER_PORT": str(server_port),
        "QUERY_PORT": str(query_port),
        "ECHO_PORT": str(echo_port),
        "CONFLICT_SPEC": "",
        "CONFLICT_PROTO": "",
        "CONFLICT_LABEL": "",
        "CONFLICT_PORT": "",
    }
    if first:
        spec, proto, label, port = first
        result.update(
            {
                "CONFLICT_SPEC": spec,
                "CONFLICT_PROTO": proto,
                "CONFLICT_LABEL": label,
                "CONFLICT_PORT": str(port),
            }
        )
    return result


def _exports(payload: dict[str, str]) -> str:
    return "".join(f'{k}="{v}"\n' for k, v in payload.items())


def _cmd_instance_defaults(args: argparse.Namespace) -> int:
    payload = apply_instance_defaults(
        game_id=args.game_id,
        instance_id=args.instance_id,
        home_dir=args.home_dir,
        src_dir=args.src_dir,
        server_dir=args.server_dir,
        data_dir=args.data_dir,
        backup_dir=args.backup_dir,
        app_dir=args.app_dir,
        game_service=args.game_service,
    )
    print(_exports(payload), end="")
    return 0


def _cmd_suggest_ports(args: argparse.Namespace) -> int:
    payload = suggest_free_port_group(
        game_id=args.game_id,
        server_port=int(args.server_port or 0),
        query_port=int(args.query_port or 0),
        echo_port=int(args.echo_port or 0),
        game_service=args.game_service,
    )
    print(_exports(payload), end="")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Game Commander deploy planning helpers")
    sub = parser.add_subparsers(dest="command", required=True)
    inst = sub.add_parser("instance-defaults")
    inst.add_argument("--game-id", required=True)
    inst.add_argument("--instance-id", default="")
    inst.add_argument("--home-dir", required=True)
    inst.add_argument("--src-dir", required=True)
    inst.add_argument("--server-dir", default="")
    inst.add_argument("--data-dir", default="")
    inst.add_argument("--backup-dir", default="")
    inst.add_argument("--app-dir", default="")
    inst.add_argument("--game-service", default="")
    inst.set_defaults(func=_cmd_instance_defaults)
    ports = sub.add_parser("suggest-ports")
    ports.add_argument("--game-id", required=True)
    ports.add_argument("--server-port", required=True)
    ports.add_argument("--query-port", default="0")
    ports.add_argument("--echo-port", default="0")
    ports.add_argument("--game-service", default="")
    ports.set_defaults(func=_cmd_suggest_ports)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
