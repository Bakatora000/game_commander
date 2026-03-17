"""
Lecture seule du Hub Game Commander.
Agrège les statuts d'instances et l'état du monitor CPU.
"""
from __future__ import annotations

import json
import os
import pwd
import sys
import time
from datetime import datetime
from pathlib import Path

import requests
from flask import current_app

MAIN_SCRIPT_ENV = os.environ.get("GC_HUB_MAIN_SCRIPT", "/home/vhserver/gc/game_commander.sh")
ROOT_DIR = Path(MAIN_SCRIPT_ENV).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from shared import hostctl, hostops, instanceenv


def _manifest_path() -> Path:
    return Path(current_app.config["HUB_MANIFEST"])


def _cpu_monitor_path() -> Path:
    return Path(current_app.config["CPU_MONITOR_STATE"])


def _main_script_path() -> Path:
    return Path(current_app.config["MAIN_SCRIPT"])


def _host_cli_path() -> Path:
    return Path(current_app.config["HOST_CLI"])


def _action_log_dir() -> Path:
    return Path(current_app.config.get("ACTION_LOG_DIR") or (Path(current_app.root_path).parent / "action-logs"))


def _global_log_path() -> Path:
    return _action_log_dir() / "hub-actions.log"


def _append_action_log(instance_name: str, action: str, ok: bool, message: str) -> None:
    log_dir = _action_log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    status = "OK" if ok else "ERR"
    content = (message or "").strip() or "(aucun détail)"
    with _global_log_path().open("a", encoding="utf-8") as fh:
        fh.write(f"[{timestamp}] {status} {instance_name} {action}\n")
        for line in content.splitlines():
            fh.write(f"  {line}\n")
        fh.write("\n")


def get_global_console(max_lines: int = 240) -> list[str]:
    path = _global_log_path()
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return lines[-max_lines:]


def _load_manifest() -> dict:
    path = _manifest_path()
    if not path.is_file():
        return {"instances": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"instances": []}


def _load_cpu_monitor() -> dict:
    path = _cpu_monitor_path()
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _instance_app_dir(instance_name: str) -> Path:
    return Path.home() / f"game-commander-{instance_name}"


def _instance_config_file(instance_name: str) -> Path:
    resolved = hostctl.resolve_instance_config(instance_name)
    if resolved:
        return resolved
    return _instance_app_dir(instance_name) / "deploy_config.env"


def _load_instance_env(instance_name: str) -> dict:
    env_path = _instance_config_file(instance_name)
    return instanceenv.parse_env_file(env_path)


def _instance_entry(instance_name: str) -> dict | None:
    for item in _load_manifest().get("instances", []):
        if item.get("name") == instance_name:
            return item
    return None


def _instance_service(instance_name: str) -> str | None:
    return _load_instance_env(instance_name).get("GAME_SERVICE")


def _default_sys_user() -> str:
    return pwd.getpwuid(_main_script_path().stat().st_uid).pw_name


def _build_instance_card(inst: dict, cpu_monitor: dict, alerts_by_instance: dict, cpu_instances: dict) -> dict:
    name = inst.get("name", "?")
    prefix = inst.get("prefix", "/")
    port = int(inst.get("flask_port") or 0)
    status = _fetch_instance_hub_status(port, prefix) if port else {}
    state = int(status.get("state") or 0)
    players = (status.get("metrics") or {}).get("players") or {"value": 0, "max": 0}
    return {
        "name": name,
        "game": inst.get("game", "?"),
        "prefix": prefix,
        "state": state,
        "players": players,
        "cpu_alert": alerts_by_instance.get(name),
        "cpu_monitor": {
            "updated_at": cpu_monitor.get("updated_at"),
            "instance": cpu_instances.get(name),
        } if cpu_instances.get(name) else None,
    }


def _fetch_instance_hub_status(port: int, prefix: str) -> dict:
    try:
        response = requests.get(
            f"http://127.0.0.1:{port}{prefix}/api/hub-status",
            timeout=1.5,
        )
        if not response.ok:
            return {}
        return response.json()
    except Exception:
        return {}


def _monitor_status(cpu_monitor: dict, instances: list[dict]) -> tuple[str, str]:
    monitored_count = sum(1 for inst in instances if inst.get("cpu_monitor"))
    if monitored_count == 0:
        return "Monitor indisponible", "Aucune donnée CPU détaillée reçue depuis les instances."
    updated_at = cpu_monitor.get("updated_at", 0) or 0
    age_seconds = max(0, int(time.time() - updated_at)) if updated_at else None
    if any(inst.get("cpu_alert") for inst in instances):
        base = "Alerte"
    elif age_seconds is not None and age_seconds <= 180:
        base = "Stable"
    else:
        base = "Données anciennes"
    if age_seconds is None:
        meta = f"{monitored_count} instance(s) suivie(s)"
    elif age_seconds < 90:
        meta = f"{monitored_count} instance(s) suivie(s) · mise à jour il y a moins de 2 min"
    else:
        meta = f"{monitored_count} instance(s) suivie(s) · mise à jour il y a {round(age_seconds / 60)} min"
    return base, meta


def get_hub_payload() -> dict:
    manifest = _load_manifest()
    cpu_monitor = _load_cpu_monitor()
    alerts_by_instance = cpu_monitor.get("alerts_by_instance") or {}
    cpu_instances = cpu_monitor.get("instances") or {}
    cards = []
    for inst in sorted(manifest.get("instances", []), key=lambda item: ((item.get("game") or "").lower(), (item.get("name") or "").lower())):
        cards.append(_build_instance_card(inst, cpu_monitor, alerts_by_instance, cpu_instances))
    monitor_status, monitor_meta = _monitor_status(cpu_monitor, cards)
    return {
        "monitor": {
            "status": monitor_status,
            "meta": monitor_meta,
        },
        "instances": cards,
    }


def run_instance_service_action(instance_name: str, action: str) -> tuple[bool, str, dict | None]:
    if action not in {"start", "stop", "restart"}:
        return False, "Action service non autorisée", None
    instance = _instance_entry(instance_name)
    if not instance:
        return False, "Instance introuvable", None
    service = _instance_service(instance_name)
    if not service:
        return False, "Service introuvable pour cette instance", None
    host_cli = _host_cli_path()
    if not host_cli.is_file():
        return False, "CLI hôte introuvable", None
    ok, message = hostops.run_command(
        ["sudo", "/usr/bin/python3", str(host_cli), "service-action", "--service", service, "--action", action],
        timeout=120,
    )
    _append_action_log(instance_name, action, ok, message or hostops.service_action_success_message(action, instance_name))
    payload = get_hub_payload()
    card = next((item for item in payload["instances"] if item.get("name") == instance_name), None)
    if ok:
        return True, hostops.service_action_success_message(action, instance_name), card
    return False, message or f"Échec {action}", card


def run_instance_update(instance_name: str) -> tuple[bool, str, dict | None]:
    instance = _instance_entry(instance_name)
    if not instance:
        return False, "Instance introuvable", None
    script_path = _main_script_path()
    if not script_path.is_file():
        return False, "Script principal introuvable", None
    host_cli = _host_cli_path()
    if not host_cli.is_file():
        return False, "CLI hôte introuvable", None
    ok, message = hostops.run_command(
        ["sudo", "/usr/bin/python3", str(host_cli), "update-instance", "--main-script", str(script_path), "--instance", instance_name, "--skip-hub-sync"],
        timeout=900,
    )
    _append_action_log(instance_name, "update", ok, message or f"Instance {instance_name} mise à jour")
    payload = get_hub_payload()
    card = next((item for item in payload["instances"] if item.get("name") == instance_name), None)
    if ok:
        return True, f"Instance {instance_name} mise à jour", card
    return False, message or "Échec update", card


def run_instance_redeploy(instance_name: str) -> tuple[bool, str, dict | None]:
    instance = _instance_entry(instance_name)
    if not instance:
        return False, "Instance introuvable", None
    script_path = _main_script_path()
    if not script_path.is_file():
        return False, "Script principal introuvable", None
    host_cli = _host_cli_path()
    if not host_cli.is_file():
        return False, "CLI hôte introuvable", None
    config_file = _instance_config_file(instance_name)
    if not config_file.is_file():
        return False, "deploy_config.env introuvable pour cette instance", None
    ok, message = hostops.run_command(
        ["sudo", "/usr/bin/python3", str(host_cli), "redeploy-instance", "--main-script", str(script_path), "--config", str(config_file)],
        timeout=1200,
    )
    _append_action_log(instance_name, "redeploy", ok, message or f"Instance {instance_name} redéployée")
    payload = get_hub_payload()
    card = next((item for item in payload["instances"] if item.get("name") == instance_name), None)
    if ok:
        return True, f"Instance {instance_name} redéployée", card
    return False, message or "Échec redéploiement", card


def run_instance_uninstall(instance_name: str) -> tuple[bool, str, dict]:
    instance = _instance_entry(instance_name)
    if not instance:
        return False, "Instance introuvable", get_hub_payload()
    script_path = _main_script_path()
    if not script_path.is_file():
        return False, "Script principal introuvable", get_hub_payload()
    host_cli = _host_cli_path()
    if not host_cli.is_file():
        return False, "CLI hôte introuvable", get_hub_payload()
    ok, message = hostops.run_command(
        ["sudo", "/usr/bin/python3", str(host_cli), "uninstall-instance", "--main-script", str(script_path), "--instance", instance_name],
        timeout=1200,
    )
    _append_action_log(instance_name, "uninstall", ok, message or f"Instance {instance_name} désinstallée")
    payload = get_hub_payload()
    if ok:
        return True, f"Instance {instance_name} désinstallée", payload
    return False, message or "Échec désinstallation", payload


def run_instance_deploy(data: dict) -> tuple[bool, str, dict]:
    game_id = (data.get("game_id") or "").strip()
    instance_name = (data.get("instance") or "").strip()
    domain = (data.get("domain") or "").strip()
    admin_password = data.get("admin_password") or ""
    if not game_id or not instance_name or not domain or not admin_password:
        return False, "Jeu, identifiant, domaine et mot de passe admin sont requis", get_hub_payload()
    if _instance_entry(instance_name) or _instance_config_file(instance_name).is_file():
        return False, "Une instance avec cet identifiant existe déjà", get_hub_payload()
    script_path = _main_script_path()
    if not script_path.is_file():
        return False, "Script principal introuvable", get_hub_payload()
    host_cli = _host_cli_path()
    if not host_cli.is_file():
        return False, "CLI hôte introuvable", get_hub_payload()
    cmd = [
        "sudo", "/usr/bin/python3", str(host_cli), "deploy-instance",
        "--main-script", str(script_path),
        "--game-id", game_id,
        "--instance", instance_name,
        "--domain", domain,
        "--admin-login", (data.get("admin_login") or "admin").strip() or "admin",
        "--admin-password", admin_password,
        "--sys-user", (data.get("sys_user") or _default_sys_user()).strip() or _default_sys_user(),
    ]
    if data.get("server_name"):
        cmd.extend(["--server-name", str(data.get("server_name"))])
    if data.get("server_password"):
        cmd.extend(["--server-password", str(data.get("server_password"))])
    if data.get("server_port"):
        cmd.extend(["--server-port", str(data.get("server_port"))])
    if data.get("max_players"):
        cmd.extend(["--max-players", str(data.get("max_players"))])
    ok, message = hostops.run_command(cmd, timeout=1800)
    _append_action_log(instance_name, "deploy", ok, message or f"Instance {instance_name} déployée")
    payload = get_hub_payload()
    if ok:
        return True, f"Instance {instance_name} déployée", payload
    return False, message or "Échec déploiement", payload


def run_rebalance(restart: bool = False) -> tuple[bool, str, dict]:
    script_path = _main_script_path()
    if not script_path.is_file():
        return False, "Script principal introuvable", get_hub_payload()
    host_cli = _host_cli_path()
    if not host_cli.is_file():
        return False, "CLI hôte introuvable", get_hub_payload()
    cmd = ["sudo", "/usr/bin/python3", str(host_cli), "rebalance", "--main-script", str(script_path)]
    if restart:
        cmd.append("--restart")
    ok, message = hostops.run_command(cmd, timeout=900)
    payload = get_hub_payload()
    if ok:
        label = "Rebalance appliqué" if restart else "Rebalance recalculé"
        return True, label, payload
    return False, message or "Échec rebalance", payload
