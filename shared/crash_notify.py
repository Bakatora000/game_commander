#!/usr/bin/env python3
"""Notification Discord lors d'un crash ou échec de service systemd.

Invoked by systemd OnFailure= via game-commander-crash-notify@.service.
Always exits 0 — notification failure must not mask the original crash.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_here = Path(__file__).resolve().parent.parent
if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))

from shared import discordnotify


def main() -> int:
    parser = argparse.ArgumentParser(description="Notification crash Discord")
    parser.add_argument("--instance", default="", help="Instance ID")
    parser.add_argument("--game", default="", help="Game ID")
    parser.add_argument("--service", default="", help="Systemd service name")
    parser.add_argument("--details", default="", help="Informations complémentaires")
    args = parser.parse_args()

    ok, msg = discordnotify.notify_event(
        event="crash",
        ok=False,
        instance_id=args.instance,
        game_id=args.game,
        service=args.service,
        source="systemd",
        details=args.details,
    )
    if not ok and msg not in ("disabled", "no-route"):
        print(f"Avertissement: notification crash non envoyée: {msg}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
