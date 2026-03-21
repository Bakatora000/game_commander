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
    import os
    parser = argparse.ArgumentParser(
        description="Désinstallation interactive Game Commander",
    )
    parser.add_argument("--script-dir", required=True,
                        help="Répertoire racine de Game Commander")
    parser.add_argument("--dry-run", action="store_true",
                        help="Simuler sans modifier le système")
    parser.add_argument("--yes", action="store_true",
                        help="Répondre oui automatiquement à toutes les questions")
    # Non-interactive targeted uninstall
    parser.add_argument("--instance", default="",
                        help="Désinstaller une instance précise (non interactif)")
    parser.add_argument("--config", default="",
                        help="Chemin vers deploy_config.env (résout --instance si omis)")
    args = parser.parse_args()

    script_dir = Path(args.script_dir).resolve()
    dry_run: bool = args.dry_run
    assume_yes: bool = args.yes

    if os.geteuid() != 0:
        console.die("Ce script doit être exécuté en root (sudo)")

    if dry_run:
        console.warn("MODE DRY-RUN — aucune modification ne sera effectuée")

    # ── Non-interactive targeted path ─────────────────────────────────────────
    if args.instance or args.config:
        import subprocess
        instance = args.instance
        if args.config and not instance:
            r = subprocess.run(
                ["python3", str(script_dir / "tools" / "host_cli.py"),
                 "list-instances"],
                capture_output=True, text=True, check=False,
            )
            for line in r.stdout.splitlines():
                parts = line.split()
                if len(parts) >= 3 and parts[2] == args.config:
                    instance = parts[0]
                    break
        if not instance:
            console.die("Identifiant d'instance introuvable")
        r = subprocess.run(
            ["python3", str(script_dir / "tools" / "host_cli.py"),
             "uninstall-instance",
             "--repo-root", str(script_dir),
             "--instance", instance],
            check=False,
        )
        if r.returncode != 0:
            console.die(f"Désinstallation échouée pour {instance}")
        print()
        console.hdr("Terminé")
        if dry_run:
            console.warn("DRY-RUN — aucune modification n'a été effectuée")
        print()
        return

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
