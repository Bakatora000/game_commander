#!/usr/bin/env python3
"""Shared CPU affinity planning for Game Commander host actions."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from . import hostctl, instanceenv

_BOLD = "\033[1m"
_DIM = "\033[2m"
_RESET = "\033[0m"

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
        if record.get("deploy_mode", "managed") != "managed":
            continue
        managed.append(
            {
                "instance_id": record["instance_id"],
                "game_id": record["game_id"],
                "service": record.get("game_service") or instanceenv.default_game_service(record["game_id"], record["instance_id"]),
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


# ── High-level helpers called by CLI ─────────────────────────────────────────

def affinity_line_for_instance(instance_id: str, game_id: str, service_name: str) -> str:
    """Return 'CPUAffinity=X Y Z' for the instance within the global plan, or ''."""
    core_groups = detect_core_groups()
    if not core_groups:
        return ""
    instances = collect_managed_instances()
    if not any(inst["instance_id"] == instance_id for inst in instances):
        instances.append({"instance_id": instance_id, "game_id": game_id, "service": service_name})
    plan = plan_instances(instances, core_groups)
    for item in plan:
        if item["instance_id"] == instance_id and item["service"] == service_name:
            return f"CPUAffinity={item['cpus']}"
    return ""


def install_cpu_monitor(script_dir: str | Path, state_file: str | None = None) -> list[str]:
    script_path = Path(script_dir) / "tools" / "cpu_monitor.py"
    if not script_path.is_file():
        return [f"Monitor CPU introuvable : {script_path}"]
    state = state_file or "/var/lib/game-commander/cpu-monitor.json"
    Path(state).parent.mkdir(parents=True, exist_ok=True)
    Path("/etc/systemd/system/game-commander-cpu-monitor.service").write_text(
        "[Unit]\n"
        "Description=Game Commander — CPU imbalance monitor\n"
        "After=network.target\n\n"
        "[Service]\n"
        "Type=oneshot\n"
        f"ExecStart=/usr/bin/python3 {script_path} --state-file {state}\n",
        encoding="utf-8",
    )
    Path("/etc/systemd/system/game-commander-cpu-monitor.timer").write_text(
        "[Unit]\n"
        "Description=Game Commander — CPU imbalance monitor (timer)\n\n"
        "[Timer]\n"
        "OnBootSec=2min\n"
        "OnUnitActiveSec=1min\n"
        "RandomizedDelaySec=10s\n"
        "Persistent=true\n\n"
        "[Install]\n"
        "WantedBy=timers.target\n",
        encoding="utf-8",
    )
    subprocess.run(["systemctl", "daemon-reload"], check=False, capture_output=True)
    subprocess.run(
        ["systemctl", "enable", "--now", "game-commander-cpu-monitor.timer"],
        check=False, capture_output=True,
    )
    subprocess.run(
        ["systemctl", "start", "game-commander-cpu-monitor.service"],
        check=False, capture_output=True,
    )
    return ["Monitor CPU installé"]


# ── CLI ───────────────────────────────────────────────────────────────────────

def _cmd_affinity_line(args: argparse.Namespace) -> int:
    line = affinity_line_for_instance(args.instance_id, args.game_id, args.game_service)
    if line:
        print(line)
    return 0


def _cmd_cpu_weight(args: argparse.Namespace) -> int:
    print(cpu_weight_for_game(args.game_id))
    return 0


def _cmd_show_current(args: argparse.Namespace) -> int:
    instances = collect_managed_instances()
    if not instances:
        print("  (aucune instance gérée)")
        return 0
    for inst in instances:
        cpus = current_affinity_for_service(inst["service"])
        print(f"  {_BOLD}{inst['instance_id']}{_RESET} ({inst['game_id']}) : {cpus}")
    return 0


def _cmd_show_plan(args: argparse.Namespace) -> int:
    core_groups = detect_core_groups()
    if not core_groups:
        print("  (topologie CPU introuvable)", file=sys.stderr)
        return 1
    instances = collect_managed_instances()
    plan = plan_instances(instances, core_groups)
    if not plan:
        print("  (aucune instance à planifier)")
        return 0
    for item in plan:
        print(
            f"  {_BOLD}{item['instance_id']}{_RESET} ({item['game_id']}) : "
            f"{item['cpus']}  {_DIM}[poids {item['weight']}]{_RESET}"
        )
    return 0


def _cmd_apply(args: argparse.Namespace) -> int:
    core_groups = detect_core_groups()
    if not core_groups:
        print("Topologie CPU introuvable — aucune affinité appliquée", file=sys.stderr)
        return 1
    instances = collect_managed_instances()
    if not instances:
        print("Aucune instance gérée trouvée", file=sys.stderr)
        return 1
    plan = plan_instances(instances, core_groups)
    messages = apply_plan(plan, restart_running=args.restart)
    for msg in messages:
        print(msg)
    if messages:
        print("Répartition CPU recalculée")
    return 0


def _cmd_install_monitor(args: argparse.Namespace) -> int:
    messages = install_cpu_monitor(args.script_dir, args.state_file or None)
    for msg in messages:
        print(msg)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Game Commander CPU affinity helper")
    sub = parser.add_subparsers(dest="command", required=True)

    al = sub.add_parser("affinity-line")
    al.add_argument("--instance-id", required=True)
    al.add_argument("--game-id", required=True)
    al.add_argument("--game-service", required=True)
    al.set_defaults(func=_cmd_affinity_line)

    cw = sub.add_parser("cpu-weight")
    cw.add_argument("--game-id", required=True)
    cw.set_defaults(func=_cmd_cpu_weight)

    sc = sub.add_parser("show-current")
    sc.set_defaults(func=_cmd_show_current)

    sp = sub.add_parser("show-plan")
    sp.set_defaults(func=_cmd_show_plan)

    ap = sub.add_parser("apply")
    ap.add_argument("--restart", action="store_true")
    ap.set_defaults(func=_cmd_apply)

    im = sub.add_parser("install-monitor")
    im.add_argument("--script-dir", required=True)
    im.add_argument("--state-file", default="")
    im.set_defaults(func=_cmd_install_monitor)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
