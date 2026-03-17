"""
Lecture seule du Hub Game Commander.
Agrège les statuts d'instances et l'état du monitor CPU.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import requests
from flask import current_app


def _manifest_path() -> Path:
    return Path(current_app.config["HUB_MANIFEST"])


def _cpu_monitor_path() -> Path:
    return Path(current_app.config["CPU_MONITOR_STATE"])


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
        name = inst.get("name", "?")
        prefix = inst.get("prefix", "/")
        port = int(inst.get("flask_port") or 0)
        status = _fetch_instance_hub_status(port, prefix) if port else {}
        state = int(status.get("state") or 0)
        players = (status.get("metrics") or {}).get("players") or {"value": 0, "max": 0}
        cards.append(
            {
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
        )
    monitor_status, monitor_meta = _monitor_status(cpu_monitor, cards)
    return {
        "monitor": {
            "status": monitor_status,
            "meta": monitor_meta,
        },
        "instances": cards,
    }
