#!/usr/bin/env python3
"""CLI rebalance — replaces lib/cmd_rebalance.sh."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

_here = Path(__file__).resolve().parent.parent
if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))

from shared import console, cpuplan

_BOLD  = "\033[1m"
_RESET = "\033[0m"


def main() -> None:
    parser = argparse.ArgumentParser(description="Répartition CPU — Game Commander")
    parser.add_argument("--script-dir", required=True)
    parser.add_argument("--restart", action="store_true",
                        help="Redémarrer les services actifs après application")
    args = parser.parse_args()

    if os.geteuid() != 0:
        console.die("Lancez en root : sudo ./gcctl rebalance")

    console.hdr("Répartition CPU")
    console.info("Calcul de l'affinité par cœur physique")
    if args.restart:
        console.warn("Les services actifs seront redémarrés pour appliquer l'affinité")
    else:
        console.info("Les services actifs conserveront l'ancienne affinité jusqu'au prochain redémarrage")

    core_groups = cpuplan.detect_core_groups()
    instances   = cpuplan.collect_managed_instances()
    plan        = cpuplan.plan_instances(instances, core_groups)

    print()
    print(f"  {_BOLD}Affectation actuelle :{_RESET}")
    if instances:
        for inst in instances:
            cpus = cpuplan.current_affinity_for_service(inst["service"])
            print(f"    {_BOLD}{inst['instance_id']}{_RESET} ({inst['game_id']}) : {cpus}")
    else:
        print("    (aucune instance gérée)")

    print()
    print(f"  {_BOLD}Affectation planifiée :{_RESET}")
    if plan:
        for item in plan:
            print(f"    {_BOLD}{item['instance_id']}{_RESET} ({item['game_id']}) : "
                  f"{item['cpus']}  [{item['weight']}]")
    else:
        print("    (aucune instance à planifier)")
    print()

    for msg in cpuplan.apply_plan(plan, restart_running=args.restart):
        console.ok(msg)


if __name__ == "__main__":
    main()
