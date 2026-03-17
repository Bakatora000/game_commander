#!/usr/bin/env python3
"""
cpu_monitor.py — Détecte les déséquilibres CPU durables entre instances.

Le monitor reste volontairement prudent :
- il n'alerte que s'il existe un meilleur plan d'affinité connu
- il attend plusieurs échantillons consécutifs avant de remonter une alerte
- il n'essaie jamais de déplacer automatiquement les processus
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import psutil


HEAVY_GAMES = {"soulmask", "enshrouded"}
DEFAULT_SCAN_ROOTS = ["/home", "/opt", "/root"]
SAMPLES_FOR_ALERT = 10


def scan_roots() -> list[Path]:
    raw = os.environ.get("GC_DEPLOY_SCAN_ROOTS", "").strip()
    roots = raw.split() if raw else DEFAULT_SCAN_ROOTS
    return [Path(p) for p in roots]


def parse_env_file(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    try:
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line or "=" not in line or line.startswith("#"):
                continue
            key, value = line.split("=", 1)
            data[key] = value.strip().strip('"')
    except OSError:
        return {}
    return data


def collect_instances() -> list[dict]:
    instances: list[dict] = []
    seen: set[Path] = set()
    for root in scan_roots():
        if not root.is_dir():
            continue
        for cfg in sorted(root.glob("**/deploy_config.env")):
            if cfg in seen:
                continue
            seen.add(cfg)
            try:
                if len(cfg.relative_to(root).parts) > 5:
                    continue
            except Exception:
                continue
            env = parse_env_file(cfg)
            if not env.get("GAME_ID") or not env.get("INSTANCE_ID"):
                continue
            if env.get("DEPLOY_MODE", "managed") != "managed":
                continue
            instances.append(
                {
                    "instance_id": env["INSTANCE_ID"],
                    "game_id": env["GAME_ID"],
                    "service": env.get("GAME_SERVICE") or f'{env["GAME_ID"]}-server-{env["INSTANCE_ID"]}',
                }
            )
    return instances


def detect_core_groups() -> list[str]:
    sysfs_root = Path(os.environ.get("GC_CPU_SYSFS_ROOT", "/sys/devices/system/cpu"))
    seen: set[str] = set()
    groups: list[str] = []
    for path in sorted(sysfs_root.glob("cpu[0-9]*/topology/thread_siblings_list")):
        try:
            raw = path.read_text().strip()
        except OSError:
            continue
        cpus: list[int] = []
        for part in raw.replace(",", " ").split():
            if "-" in part:
                start, end = part.split("-", 1)
                cpus.extend(range(int(start), int(end) + 1))
            else:
                cpus.append(int(part))
        group = " ".join(str(v) for v in sorted(set(cpus)))
        if group and group not in seen:
            seen.add(group)
            groups.append(group)
    return groups


def weight_for_game(game_id: str) -> int:
    if game_id in {"soulmask", "enshrouded"}:
        return 4
    if game_id == "satisfactory":
        return 3
    if game_id in {"valheim", "minecraft", "minecraft-fabric"}:
        return 2
    if game_id == "terraria":
        return 1
    return 2


def is_heavy_idle_game(game_id: str) -> bool:
    return game_id in HEAVY_GAMES


def plan_affinities(instances: list[dict], core_groups: list[str]) -> dict[str, str]:
    if not core_groups:
        return {}
    loads = [0 for _ in core_groups]
    heavy = [0 for _ in core_groups]
    planned: dict[str, str] = {}
    ranked = sorted(
        instances,
        key=lambda inst: (-weight_for_game(inst["game_id"]), inst["instance_id"]),
    )
    for inst in ranked:
        best_idx = -1
        best_score = 10**9
        for idx, _group in enumerate(core_groups):
            score = loads[idx]
            if is_heavy_idle_game(inst["game_id"]) and heavy[idx] > 0:
                score += 1000
            if score < best_score:
                best_idx = idx
                best_score = score
        if best_idx < 0:
            continue
        loads[best_idx] += weight_for_game(inst["game_id"])
        if is_heavy_idle_game(inst["game_id"]):
            heavy[best_idx] = 1
        planned[inst["instance_id"]] = core_groups[best_idx]
    return planned


def service_main_pid(service: str) -> int:
    try:
        result = subprocess.run(
            ["systemctl", "show", service, "--property=MainPID"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        for line in result.stdout.splitlines():
            if line.startswith("MainPID="):
                return int(line.split("=", 1)[1].strip() or "0")
    except Exception:
        return 0
    return 0


def collect_process_tree(pid: int) -> list[psutil.Process]:
    if pid <= 0:
        return []
    try:
        root = psutil.Process(pid)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return []
    procs = [root]
    try:
        procs.extend(root.children(recursive=True))
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    dedup: dict[int, psutil.Process] = {}
    for proc in procs:
        dedup[proc.pid] = proc
    return list(dedup.values())


def affinity_string_for_process(proc: psutil.Process) -> str:
    try:
        return " ".join(str(cpu) for cpu in sorted(proc.cpu_affinity()))
    except Exception:
        return "-"


def measure_instances(instances: list[dict], interval: float = 0.25) -> list[dict]:
    active: list[dict] = []
    measurements: list[tuple[dict, psutil.Process, list[psutil.Process]]] = []
    for inst in instances:
        pid = service_main_pid(inst["service"])
        if pid <= 0:
            continue
        try:
            main_proc = psutil.Process(pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        tree = collect_process_tree(pid)
        if not tree:
            continue
        for proc in tree:
            try:
                proc.cpu_percent(interval=None)
            except Exception:
                pass
        measurements.append((inst, main_proc, tree))
    if not measurements:
        return active

    time.sleep(interval)

    for inst, main_proc, tree in measurements:
        cpu_total = 0.0
        for proc in tree:
            try:
                cpu_total += proc.cpu_percent(interval=None)
            except Exception:
                pass
        active.append(
            {
                **inst,
                "pid": main_proc.pid,
                "cpu_percent": round(cpu_total, 1),
                "affinity": affinity_string_for_process(main_proc),
            }
        )
    return active


def load_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def detect_imbalance(active_instances: list[dict], planned: dict[str, str]) -> dict | None:
    groups: dict[str, dict] = {}
    for inst in active_instances:
        affinity = inst.get("affinity") or "-"
        groups.setdefault(affinity, {"cpu_percent": 0.0, "instances": []})
        groups[affinity]["cpu_percent"] += inst["cpu_percent"]
        groups[affinity]["instances"].append(inst["instance_id"])

    if len(groups) < 2:
        return None

    normalized: list[tuple[str, float, float]] = []
    for affinity, payload in groups.items():
        cpu_count = max(1, len(affinity.split())) if affinity != "-" else 1
        normalized.append((affinity, payload["cpu_percent"], payload["cpu_percent"] / (cpu_count * 100.0)))
    normalized.sort(key=lambda item: item[2], reverse=True)
    max_affinity, max_cpu, max_norm = normalized[0]
    _min_affinity, _min_cpu, min_norm = normalized[-1]

    changed = []
    for inst in active_instances:
        planned_affinity = planned.get(inst["instance_id"])
        if planned_affinity and planned_affinity != inst.get("affinity"):
            changed.append(inst)

    if not changed:
        return None

    if max_norm < 0.40 or (max_norm - min_norm) < 0.30:
        return None

    offenders = [inst for inst in changed if inst.get("affinity") == max_affinity]
    if not offenders:
        offenders = changed

    return {
        "overloaded_affinity": max_affinity,
        "cpu_percent": round(max_cpu, 1),
        "normalized_load": round(max_norm, 2),
        "instances": sorted(inst["instance_id"] for inst in offenders),
        "changes": {
            inst["instance_id"]: {
                "current": inst.get("affinity") or "-",
                "planned": planned.get(inst["instance_id"], inst.get("affinity") or "-"),
            }
            for inst in changed
        },
    }


def build_state(path: Path) -> dict:
    previous = load_json(path)
    previous_monitor = previous.get("monitor", {}) if isinstance(previous, dict) else {}

    instances = collect_instances()
    core_groups = detect_core_groups()
    planned = plan_affinities(instances, core_groups)
    active_instances = measure_instances(instances)
    imbalance = detect_imbalance(active_instances, planned)

    monitor = {"signature": "", "consecutive_runs": 0}
    alerts_by_instance: dict[str, dict] = {}

    if imbalance:
        changes = imbalance["changes"]
        signature = "|".join(
            f'{instance_id}:{payload["current"]}>{payload["planned"]}'
            for instance_id, payload in sorted(changes.items())
        )
        consecutive = previous_monitor.get("consecutive_runs", 0) + 1 if previous_monitor.get("signature") == signature else 1
        monitor = {"signature": signature, "consecutive_runs": consecutive}
        if consecutive >= SAMPLES_FOR_ALERT:
            for instance_id in imbalance["instances"]:
                alerts_by_instance[instance_id] = {
                    "level": "warning",
                    "message": "Déséquilibre CPU durable — rebalance --restart conseillé",
                    "current": changes.get(instance_id, {}).get("current", "-"),
                    "planned": changes.get(instance_id, {}).get("planned", "-"),
                    "samples": consecutive,
                }

    return {
        "version": 1,
        "updated_at": int(time.time()),
        "samples_for_alert": SAMPLES_FOR_ALERT,
        "instances": {
            inst["instance_id"]: {
                "game_id": inst["game_id"],
                "service": inst["service"],
                "cpu_percent": inst["cpu_percent"],
                "affinity": inst["affinity"],
                "planned_affinity": planned.get(inst["instance_id"], inst["affinity"]),
            }
            for inst in active_instances
        },
        "monitor": monitor,
        "alerts_by_instance": alerts_by_instance,
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Monitor passif de déséquilibre CPU Game Commander")
    parser.add_argument("--state-file", default="/var/lib/game-commander/cpu-monitor.json")
    args = parser.parse_args(argv)

    state_path = Path(args.state_file)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state = build_state(state_path)
    state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
