#!/usr/bin/env python3
"""
Main entry point — replaces game_commander.sh menu + dispatch logic.

Usage:
    python3 shared/cmd_main.py --script-dir /path/to/gc [command] [args...]
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

_here = Path(__file__).resolve().parent.parent
if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))

from shared import console

_BOLD  = "\033[1m"
_CYAN  = "\033[0;36m"
_DIM   = "\033[2m"
_RESET = "\033[0m"
_YELLOW = "\033[0;33m"

COMMANDS = ("deploy", "attach", "uninstall", "status", "update", "rebalance", "bootstrap-hub")


def _help() -> None:
    print("""
  game_commander.sh — Déploiement et gestion des instances Game Commander

  COMMANDES :
    deploy                   Nouvelle instance complète gérée par Game Commander
    attach                   Ajouter Commander à un serveur/service jeu existant
    deploy --attach          Alias CLI de la commande attach
    deploy --config FILE     Déploiement depuis un fichier de config
    deploy --generate-config Générer un modèle de fichier de config
    uninstall                Retirer une instance ou nettoyer des reliquats
    uninstall --dry-run      Simulation (aucune modification)
    status                   Voir l'état des instances déployées
    update                   Resynchroniser le runtime d'une instance existante
    update --instance ID     Mettre à jour une instance précise
    update --all             Met à jour toutes les instances
    rebalance                Recalculer l'affinité CPU des instances gérées
    rebalance --restart      Recalculer puis redémarrer les serveurs concernés
    bootstrap-hub            Installer uniquement le Hub Admin sur un serveur vierge

  MENU PRINCIPAL :
    [1] deploy     Nouvelle instance complète
    [2] attach     Commander sur serveur existant
    [3] uninstall  Retirer / nettoyer
    [4] status     Voir l'état
    [5] update     Propager les changements du dépôt
    [6] rebalance  Répartir les serveurs sur les cœurs CPU
    [7] bootstrap  Installer uniquement le Hub Admin
    [0] quit       Quitter

  EXEMPLES :
    sudo bash game_commander.sh
    sudo bash game_commander.sh deploy
    sudo bash game_commander.sh attach
    sudo bash game_commander.sh deploy --config env/deploy_config.env
    sudo bash game_commander.sh uninstall
    sudo bash game_commander.sh status
    sudo bash game_commander.sh update --instance testfabric
    sudo bash game_commander.sh rebalance --restart
    sudo bash game_commander.sh bootstrap-hub --domain gaming.example.com --admin-password '...'
""")


def _run(script_dir: Path, command: str, remaining: list[str], dry_run: bool) -> int:
    exe = sys.executable
    sd = str(script_dir)
    if command == "deploy":
        return subprocess.run(
            [exe, str(script_dir / "shared" / "cmd_deploy.py"),
             "--script-dir", sd, *remaining],
        ).returncode
    if command == "attach":
        return subprocess.run(
            [exe, str(script_dir / "shared" / "cmd_deploy.py"),
             "--script-dir", sd, "--attach", *remaining],
        ).returncode
    if command == "uninstall":
        cmd = [exe, str(script_dir / "shared" / "uninstall_interactive.py"),
               "--script-dir", sd]
        if dry_run:
            cmd.append("--dry-run")
        cmd.extend(remaining)
        return subprocess.run(cmd).returncode
    if command == "status":
        return subprocess.run(
            [exe, str(script_dir / "shared" / "cmd_status.py"),
             "--script-dir", sd],
        ).returncode
    if command == "update":
        return subprocess.run(
            [exe, str(script_dir / "shared" / "cmd_update.py"),
             "--script-dir", sd, *remaining],
        ).returncode
    if command == "rebalance":
        return subprocess.run(
            [exe, str(script_dir / "shared" / "cmd_rebalance.py"),
             "--script-dir", sd, *remaining],
        ).returncode
    if command == "bootstrap-hub":
        return subprocess.run(
            [exe, str(script_dir / "tools" / "host_cli.py"),
             "bootstrap-hub",
             "--main-script", str(script_dir / "game_commander.sh"),
             *remaining],
        ).returncode
    _help()
    return 1


def _interactive_menu(script_dir: Path) -> None:
    if os.geteuid() != 0:
        console.die("Lancez en root : sudo bash game_commander.sh")

    menu = [
        ("0", "quit",       "Quitter"),
        ("1", "deploy",     "Nouvelle instance complète gérée par Game Commander"),
        ("2", "attach",     "Ajouter Commander à un serveur/service déjà existant"),
        ("3", "uninstall",  "Retirer une instance ou nettoyer des reliquats"),
        ("4", "status",     "Voir l'état des instances déployées"),
        ("5", "update",     "Propager les changements du dépôt vers une instance"),
        ("6", "rebalance",  "Répartir les serveurs sur les cœurs CPU"),
        ("7", "bootstrap-hub", "Installer uniquement le Hub Admin"),
    ]

    while True:
        print()
        print(f"  {_BOLD}{_CYAN}╔══ GAME COMMANDER ══╗{_RESET}")
        print(f"  {_DIM}Déployer, attacher, mettre à jour ou retirer une interface Commander.{_RESET}")
        print()
        for key, name, desc in menu:
            label = f"{_BOLD}{name}{_RESET}"
            print(f"  {_CYAN}[{key}]{_RESET} {label:<30} — {desc}")
        print()

        try:
            choice = console.prompt("Votre choix", "").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if choice == "0" or choice == "":
            break

        dispatch = {str(i): cmd for i, (_, cmd, _) in enumerate(menu)}
        command = dispatch.get(choice)
        if command is None or command == "quit":
            console.warn("Choix invalide.")
            continue

        _run(script_dir, command, [], False)


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--script-dir", required=True)
    parser.add_argument("--help", "-h", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("command", nargs="?", default="")
    parser.add_argument("remaining", nargs=argparse.REMAINDER)
    args = parser.parse_args()

    if args.help:
        _help()
        return 0

    script_dir = Path(args.script_dir).resolve()

    # Remaining args: merge positional remainder + strip leading "--"
    remaining = [a for a in args.remaining if a != "--"]

    command = args.command
    # If the first "remaining" arg looks like a known flag, keep it
    # (e.g. game_commander.sh deploy --config FILE → command=deploy, remaining=[--config, FILE])

    if not command:
        _interactive_menu(script_dir)
        return 0

    if command not in COMMANDS:
        console.warn(f"Commande inconnue : {command}")
        _help()
        return 1

    return _run(script_dir, command, remaining, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
