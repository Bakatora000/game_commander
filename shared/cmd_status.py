#!/usr/bin/env python3
"""CLI status — replaces lib/cmd_status.sh."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_here = Path(__file__).resolve().parent.parent
if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))

from shared import console, hostctl, instanceenv, sysutil

_BOLD   = "\033[1m"
_DIM    = "\033[2m"
_GREEN  = "\033[0;32m"
_RED    = "\033[0;31m"
_RESET  = "\033[0m"


def _state_badge(state: str) -> str:
    if state == "active":
        return f"{_GREEN}● actif{_RESET}"
    if state == "failed":
        return f"{_RED}✗ échoué{_RESET}"
    return f"{_DIM}○ inactif{_RESET}"


def main() -> None:
    parser = argparse.ArgumentParser(description="État des instances Game Commander")
    parser.add_argument("--script-dir", required=True)
    parser.parse_args()

    console.hdr("Instances Game Commander")

    configs = hostctl.discover_instance_configs()
    if not configs:
        console.info("Aucune instance Game Commander trouvée.")
        return

    print()
    for cfg in configs:
        env = instanceenv.parse_env_file(cfg)
        game_id     = env.get("GAME_ID", "?")
        instance_id = env.get("INSTANCE_ID") or game_id
        gc_service  = f"game-commander-{instance_id}"
        game_service = env.get("GAME_SERVICE") or f"{game_id}-server-{instance_id}"

        gc_state   = sysutil.service_state(gc_service)
        game_state = sysutil.service_state(game_service)

        print(f"  {_BOLD}{instance_id}{_RESET}  ({game_id.upper()})")
        print(f"     Serveur jeu  : {game_service}  →  {_state_badge(game_state)}")
        print(f"     Game Cmd web : {gc_service}   →  {_state_badge(gc_state)}")
        server_name = env.get("SERVER_NAME", "")
        domain      = env.get("DOMAIN", "")
        flask_port  = env.get("FLASK_PORT", "?")
        url_prefix  = env.get("URL_PREFIX", "")
        if server_name:
            print(f"     Nom          : {server_name}")
        if domain:
            print(f"     URL          : https://{domain}{url_prefix}  (port {flask_port})")
        print(f"     Config       : {cfg}")
        console.sep()


if __name__ == "__main__":
    main()
