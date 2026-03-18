#!/usr/bin/env python3
"""Shared deploy planning helpers for instance paths and port groups."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

GAME_CATALOG: dict[str, dict[str, str]] = {
    "valheim": {"label": "Valheim", "steam_appid": "896660", "game_binary": "valheim_server.x86_64"},
    "enshrouded": {"label": "Enshrouded", "steam_appid": "2278520", "game_binary": "enshrouded_server.exe"},
    "minecraft": {"label": "Minecraft Java", "steam_appid": "", "game_binary": "java"},
    "minecraft-fabric": {"label": "Minecraft Fabric", "steam_appid": "", "game_binary": "java"},
    "terraria": {"label": "Terraria", "steam_appid": "", "game_binary": "TerrariaServer.bin.x86_64"},
    "soulmask": {"label": "Soulmask", "steam_appid": "3017300", "game_binary": "StartServer.sh"},
    "satisfactory": {"label": "Satisfactory", "steam_appid": "1690800", "game_binary": "FactoryServer.sh"},
}


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


def port_owner(port: int) -> str:
    pid = ""
    for proto in ("u", "t"):
        for line in _ss_lines(proto, True):
            if f":{port} " not in line or "pid=" not in line:
                continue
            pid = line.split("pid=", 1)[1].split(",", 1)[0].split(")", 1)[0]
            break
        if pid:
            break
    if not pid:
        return "processus inconnu"
    cmd = _run_stdout(["ps", "-p", pid, "-o", "comm="]) or "commande inconnue"
    return f"PID {pid} ({cmd})"


def game_meta(game_id: str) -> dict[str, str]:
    return dict(GAME_CATALOG.get(game_id, {"label": game_id, "steam_appid": "", "game_binary": ""}))


def next_free_flask_port(port: int) -> int:
    current = port
    while True:
        result = subprocess.run(["ss", "-tlnH", f"sport = :{current}"], capture_output=True, text=True, check=False)
        if f":{current}" not in (result.stdout or ""):
            return current
        current += 1


def nginx_conf_for_domain(domain: str) -> str:
    for path in (
        f"/etc/nginx/conf.d/{domain}.conf",
        f"/etc/nginx/sites-enabled/{domain}.conf",
        f"/etc/nginx/sites-available/{domain}.conf",
    ):
        if Path(path).is_file():
            return path
    return ""


def existing_prefix_owner(domain: str, url_prefix: str) -> tuple[str, str]:
    conf = nginx_conf_for_domain(domain)
    if not conf or not url_prefix:
        return "", ""
    content = Path(conf).read_text(encoding="utf-8", errors="replace")
    marker = f"location {url_prefix} {{"
    idx = content.find(marker)
    if idx < 0:
        return conf, ""
    window = content[idx:idx + 400]
    needle = "proxy_pass http://127.0.0.1:"
    port = ""
    if needle in window:
        port = window.split(needle, 1)[1].split(";", 1)[0].strip()
    return conf, port


def detect_other_valheim_process() -> str:
    result = subprocess.run(["pgrep", "-a", "valheim_server"], capture_output=True, text=True, check=False)
    lines = [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
    return lines[0] if lines else ""


def resolve_ssl_mode(choice: str) -> tuple[bool, str]:
    if choice == "0":
        return False, ""
    if choice == "1":
        return True, "certbot"
    if choice == "2":
        return True, "none"
    return True, "existing"


def admin_password_required(password: str) -> bool:
    return bool(password)


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


def describe_port_conflicts(
    *,
    game_id: str,
    server_port: int,
    query_port: int = 0,
    echo_port: int = 0,
    game_service: str = "",
) -> list[tuple[str, str, int, str]]:
    ignored_pid = _current_service_pid(game_service)
    conflicts: list[tuple[str, str, int, str]] = []
    for spec, proto, label in port_group_specs(game_id):
        port = _port_value(spec, server_port, query_port, echo_port)
        if check_port_conflict(port, proto, ignored_pid):
            conflicts.append((label, proto, port, port_owner(port)))
    return conflicts


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


def _cmd_game_meta(args: argparse.Namespace) -> int:
    meta = game_meta(args.game_id)
    payload = {
        "GAME_LABEL": meta["label"],
        "STEAM_APPID": meta["steam_appid"],
        "GAME_BINARY": meta["game_binary"],
    }
    print(_exports(payload), end="")
    return 0


def _cmd_web_defaults(args: argparse.Namespace) -> int:
    conf, owner = existing_prefix_owner(args.domain, args.url_prefix)
    payload = {
        "FLASK_PORT": str(next_free_flask_port(int(args.flask_port))),
        "NGINX_CONF_FOR_DOMAIN": conf,
        "EXISTING_OWNER": owner,
    }
    print(_exports(payload), end="")
    return 0


def _cmd_valheim_playfab(args: argparse.Namespace) -> int:
    other = detect_other_valheim_process() if args.crossplay == "true" else ""
    payload = {
        "OTHER_VALHEIM": other,
        "GC_FORCE_PLAYFAB": "true" if other else "false",
    }
    print(_exports(payload), end="")
    return 0


def _cmd_ssl_mode(args: argparse.Namespace) -> int:
    accepted, mode = resolve_ssl_mode(args.choice)
    payload = {
        "SSL_ACCEPTED": "true" if accepted else "false",
        "SSL_MODE": mode,
    }
    print(_exports(payload), end="")
    return 0


def _cmd_validate_admin(args: argparse.Namespace) -> int:
    payload = {"ADMIN_PASSWORD_OK": "true" if admin_password_required(args.password) else "false"}
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


def _cmd_describe_conflicts(args: argparse.Namespace) -> int:
    for label, proto, port, owner in describe_port_conflicts(
        game_id=args.game_id,
        server_port=int(args.server_port or 0),
        query_port=int(args.query_port or 0),
        echo_port=int(args.echo_port or 0),
        game_service=args.game_service,
    ):
        sys.stdout.write(f"{label}|{proto}|{port}|{owner}\n")
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
    conflicts = sub.add_parser("describe-conflicts")
    conflicts.add_argument("--game-id", required=True)
    conflicts.add_argument("--server-port", required=True)
    conflicts.add_argument("--query-port", default="0")
    conflicts.add_argument("--echo-port", default="0")
    conflicts.add_argument("--game-service", default="")
    conflicts.set_defaults(func=_cmd_describe_conflicts)
    meta = sub.add_parser("game-meta")
    meta.add_argument("--game-id", required=True)
    meta.set_defaults(func=_cmd_game_meta)
    web = sub.add_parser("web-defaults")
    web.add_argument("--domain", required=True)
    web.add_argument("--url-prefix", required=True)
    web.add_argument("--flask-port", required=True)
    web.set_defaults(func=_cmd_web_defaults)
    valheim = sub.add_parser("valheim-playfab")
    valheim.add_argument("--crossplay", required=True)
    valheim.set_defaults(func=_cmd_valheim_playfab)
    ssl = sub.add_parser("ssl-mode")
    ssl.add_argument("--choice", required=True)
    ssl.set_defaults(func=_cmd_ssl_mode)
    admin = sub.add_parser("validate-admin")
    admin.add_argument("--password", required=True)
    admin.set_defaults(func=_cmd_validate_admin)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
