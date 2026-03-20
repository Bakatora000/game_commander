#!/usr/bin/env python3
"""Interactive uninstall orchestrator — replaces lib/uninstall_gc.sh + lib/uninstall_flask.sh + lib/uninstall_orphans.sh."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running as a script: add repo root to sys.path
_here = Path(__file__).resolve().parent.parent
if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))

from shared import console
from shared import uninstall_gc
from shared import uninstall_flask
from shared import uninstall_orphans


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Désinstallation interactive Game Commander",
    )
    parser.add_argument("--script-dir", required=True,
                        help="Répertoire racine de Game Commander")
    parser.add_argument("--dry-run", action="store_true",
                        help="Simuler sans modifier le système")
    parser.add_argument("--yes", action="store_true",
                        help="Répondre oui automatiquement à toutes les questions")
    args = parser.parse_args()

    script_dir = Path(args.script_dir).resolve()
    dry_run: bool = args.dry_run
    assume_yes: bool = args.yes

    if dry_run:
        console.warn("MODE DRY-RUN — aucune modification ne sera effectuée")

    # Section A — Game Commander managed instances
    skipped, handled_dirs = uninstall_gc.section(
        script_dir=script_dir,
        assume_yes=assume_yes,
        dry_run=dry_run,
    )
    if skipped:
        console.info("Désinstallation annulée.")
        print()
        return

    # Section B — Generic Flask/Python apps
    uninstall_flask.section(
        script_dir=script_dir,
        already_handled=handled_dirs,
        assume_yes=assume_yes,
        dry_run=dry_run,
    )

    # Section C — Orphan processes
    uninstall_orphans.section(
        script_dir=script_dir,
        assume_yes=assume_yes,
        dry_run=dry_run,
    )

    print()
    console.hdr("Terminé")
    if dry_run:
        console.warn("DRY-RUN — aucune modification n'a été effectuée")
    print()


if __name__ == "__main__":
    main()
