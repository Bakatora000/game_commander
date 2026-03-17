"""
Lecture seule du Hub Game Commander.
Agrège les statuts d'instances et l'état du monitor CPU.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

import requests
from flask import current_app


def _manifest_path() -> Path:
    return Path(current_app.config["HUB_MANIFEST"])


def _cpu_monitor_path() -> Path:
    return Path(current_app.config["CPU_MONITOR_STATE"])


def _main_script_path() -> Path:
    return Path(current_app.config["MAIN_SCRIPT"])


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
    return _instance_app_dir(instance_name) / "deploy_config.env"


def _load_instance_env(instance_name: str) -> dict:
    env_path = _instance_config_file(instance_name)
    if not env_path.is_file():
        return {}
    state = {}
    try:
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            state[key] = value.strip().strip('"')
    except Exception:
        return {}
    return state


def _instance_entry(instance_name: str) -> dict | None:
    for item in _load_manifest().get("instances", []):
        if item.get("name") == instance_name:
            return item
    return None


def _instance_service(instance_name: str) -> str | None:
    return _load_instance_env(instance_name).get("GAME_SERVICE")


def _run_command(cmd: list[str], timeout: int = 300) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
    except Exception as exc:
        return False, str(exc)
    if result.returncode == 0:
        return True, (result.stdout or "").strip()
    message = (result.stderr or result.stdout or "").strip()
    return False, message or f"Commande échouée ({result.returncode})"


def _service_action_success_message(action: str, instance_name: str) -> str:
    labels = {
        "start": f"Démarrage lancé pour {instance_name}",
        "stop": f"Arrêt lancé pour {instance_name}",
        "restart": f"Redémarrage lancé pour {instance_name}",
    }
    return labels.get(action, "Action lancée")


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
    ok, message = _run_command(["sudo", "/usr/bin/systemctl", action, service], timeout=120)
    payload = get_hub_payload()
    card = next((item for item in payload["instances"] if item.get("name") == instance_name), None)
    if ok:
        return True, _service_action_success_message(action, instance_name), card
    return False, message or f"Échec {action}", card


def run_instance_update(instance_name: str) -> tuple[bool, str, dict | None]:
    instance = _instance_entry(instance_name)
    if not instance:
        return False, "Instance introuvable", None
    script_path = _main_script_path()
    if not script_path.is_file():
        return False, "Script principal introuvable", None
    ok, message = _run_command(
        ["sudo", "/bin/bash", str(script_path), "update", "--instance", instance_name],
        timeout=900,
    )
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
    config_file = _instance_config_file(instance_name)
    if not config_file.is_file():
        return False, "deploy_config.env introuvable pour cette instance", None
    ok, message = _run_command(
        ["sudo", "/bin/bash", str(script_path), "deploy", "--config", str(config_file)],
        timeout=1200,
    )
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
    ok, message = _run_command(
        [
            "sudo", "/bin/bash", str(script_path),
            "uninstall", "--instance", instance_name, "--full", "--yes",
        ],
        timeout=1200,
    )
    payload = get_hub_payload()
    if ok:
        return True, f"Instance {instance_name} désinstallée", payload
    return False, message or "Échec désinstallation", payload


def run_rebalance(restart: bool = False) -> tuple[bool, str, dict]:
    script_path = _main_script_path()
    if not script_path.is_file():
        return False, "Script principal introuvable", get_hub_payload()
    cmd = ["sudo", "/bin/bash", str(script_path), "rebalance"]
    if restart:
        cmd.append("--restart")
    ok, message = _run_command(cmd, timeout=900)
    payload = get_hub_payload()
    if ok:
        label = "Rebalance appliqué" if restart else "Rebalance recalculé"
        return True, label, payload
    return False, message or "Échec rebalance", payload
