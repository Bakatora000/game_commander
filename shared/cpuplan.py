#!/usr/bin/env python3
"""Shared CPU affinity planning for Game Commander host actions."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from . import hostctl

HEAVY_GAMES = {"soulmask", "enshrouded"}
SYSTEMD_DIR = Path("/etc/systemd/system")


def sysfs_root() -> Path:
    return Path(os.environ.get("GC_CPU_SYSFS_ROOT", "/sys/devices/system/cpu"))


def detect_core_groups() -> list[str]:
    root = sysfs_root()
    seen: set[str] = set()
    groups: list[str] = []
    for path in sorted(root.glob("cpu[0-9]*/topology/thread_siblings_list")):
        try:
            raw = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        cpus: list[int] = []
        for part in raw.replace(",", " ").split():
            if "-" in part:
                start, end = part.split("-", 1)
                cpus.extend(range(int(start), int(end) + 1))
            else:
                cpus.append(int(part))
        group = " ".join(str(cpu) for cpu in sorted(set(cpus)))
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


def cpu_weight_for_game(game_id: str) -> int:
    return weight_for_game(game_id) * 100


def is_heavy_idle_game(game_id: str) -> bool:
    return game_id in HEAVY_GAMES


def collect_managed_instances() -> list[dict[str, str]]:
    records = hostctl.discover_instance_records()
    managed: list[dict[str, str]] = []
    for record in records:
        env = hostctl.parse_env_file(record["config"])
        if env.get("DEPLOY_MODE", "managed") != "managed":
            continue
        managed.append(
            {
                "instance_id": record["instance_id"],
                "game_id": record["game_id"],
                "service": env.get("GAME_SERVICE") or f'{record["game_id"]}-server-{record["instance_id"]}',
            }
        )
    return managed


def plan_instances(instances: list[dict[str, str]], core_groups: list[str]) -> list[dict[str, str | int]]:
    if not core_groups:
        return []
    loads = [0 for _ in core_groups]
    heavy = [0 for _ in core_groups]
    ranked = sorted(instances, key=lambda inst: (-weight_for_game(inst["game_id"]), inst["instance_id"]))
    planned: list[dict[str, str | int]] = []
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
        planned.append(
            {
                "instance_id": inst["instance_id"],
                "game_id": inst["game_id"],
                "service": inst["service"],
                "cpus": core_groups[best_idx],
                "weight": weight_for_game(inst["game_id"]),
            }
        )
    return planned


def current_affinity_for_service(service_name: str) -> str:
    dropin = SYSTEMD_DIR / f"{service_name}.service.d" / "10-cpu-affinity.conf"
    if not dropin.is_file():
        return "-"
    try:
        for line in dropin.read_text(encoding="utf-8").splitlines():
            if line.startswith("CPUAffinity="):
                return line.split("=", 1)[1].strip() or "-"
    except OSError:
        return "-"
    return "-"


def service_active(service_name: str) -> bool:
    result = subprocess.run(
        ["systemctl", "is-active", "--quiet", service_name],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def apply_plan(plan: list[dict[str, str | int]], restart_running: bool = False) -> list[str]:
    messages: list[str] = []
    changed = False
    for item in plan:
        service_name = str(item["service"])
        cpus = str(item["cpus"])
        game_id = str(item["game_id"])
        instance_id = str(item["instance_id"])
        cpu_weight = cpu_weight_for_game(game_id)
        dropin_dir = SYSTEMD_DIR / f"{service_name}.service.d"
        dropin_dir.mkdir(parents=True, exist_ok=True)
        dropin = dropin_dir / "10-cpu-affinity.conf"
        dropin.write_text(
            "[Service]\n"
            f"CPUAffinity={cpus}\n"
            f"CPUWeight={cpu_weight}\n",
            encoding="utf-8",
        )
        changed = True
        messages.append(f"CPU {instance_id} ({game_id}) -> {cpus} [poids {cpu_weight}]")
        if restart_running and service_active(service_name):
            subprocess.run(["systemctl", "restart", service_name], check=False)
    if changed:
        subprocess.run(["systemctl", "daemon-reload"], check=False)
    return messages

