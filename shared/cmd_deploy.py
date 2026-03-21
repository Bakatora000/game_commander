#!/usr/bin/env python3
"""CLI deploy — replaces lib/cmd_deploy.sh + lib/cmd_configure.sh + lib/deploy_helpers.sh."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

_here = Path(__file__).resolve().parent.parent
if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))

from shared import console, deployenv
from shared.deployconfig import DeployConfig
from shared.deployconfigure import run_configure
from shared.deploysteps import run_all_steps


def _init_logging(cfg: DeployConfig) -> None:
    ts = time.strftime("%Y%m%d_%H%M%S")
    cfg.logfile = f"/tmp/gamecommander_deploy_{ts}.log"
    # Tee to logfile via script is complex in Python; just record the path
    console.info(f"Journal : {cfg.logfile}")


def _print_banner(cfg: DeployConfig) -> None:
    os.system("clear")
    print("""
  ╔════════════════════════════════════════════════════════╗
  ║      GAME COMMANDER — DÉPLOIEMENT v2.0                 ║
  ║   Serveur de jeu + Interface web (sans AMP)            ║
  ╚════════════════════════════════════════════════════════╝
""")
    if cfg.config_mode:
        console.info(f"Mode : FICHIER DE CONFIG ({cfg.config_file_deploy})")
    if os.geteuid() != 0:
        console.die("Lancez en root : sudo ./gcctl deploy")
    console.ok("Droits root confirmés")


def main() -> None:
    parser = argparse.ArgumentParser(description="Déploiement Game Commander")
    parser.add_argument("--script-dir", required=True)
    parser.add_argument("--config", default="", help="Fichier de config .env")
    parser.add_argument(
        "--attach", "--existing-server", dest="attach", action="store_true",
        help="Commander sur un serveur existant"
    )
    parser.add_argument(
        "--generate-config", metavar="FILE", nargs="?",
        const="env/deploy_config.env",
        help="Générer un modèle de fichier de config"
    )
    args = parser.parse_args()

    script_dir = Path(args.script_dir).resolve()

    # ── Generate config template ──────────────────────────────────────────────
    if args.generate_config is not None:
        outfile = args.generate_config or "env/deploy_config.env"
        ok_t, err_t = _generate_template(outfile, script_dir)
        if not ok_t:
            console.die(err_t)
        print(f"\033[0;32m  ✓  Modèle généré : {outfile}\033[0m")
        print(f"\033[0;36m  →  Éditez puis lancez :\033[0m")
        print(f"      sudo ./gcctl deploy --config {outfile}")
        return

    # ── Build initial config ──────────────────────────────────────────────────
    cfg = DeployConfig()

    if args.attach:
        cfg.deploy_mode = "attach"

    if args.config:
        cfg.config_file_deploy = args.config
        cfg.config_mode = True
        ok_v, err_v = deployenv.validate_config_file(args.config)
        if not ok_v:
            console.die(f"Config invalide : {args.config} — {err_v}")
        env = deployenv.normalize_deploy_env(args.config)
        cfg = DeployConfig.from_env(env)
        cfg.config_mode = True
        cfg.config_file_deploy = args.config
        if args.attach:
            cfg.deploy_mode = "attach"
        console.info(f"Config chargée depuis : {args.config}")

    # ── OS check ─────────────────────────────────────────────────────────────
    _init_logging(cfg)
    _print_banner(cfg)

    console.hdr("ÉTAPE 1 : Environnement")
    os_id, os_pretty = _detect_os()
    console.info(f"Système : {os_pretty}")
    if os_id != "ubuntu":
        console.warn("Optimisé pour Ubuntu.")
        if not console.confirm("Continuer ?"):
            console.die("Annulé.")

    # ── Configuration ─────────────────────────────────────────────────────────
    if not run_configure(cfg, script_dir):
        console.info("Déploiement annulé.")
        print()
        return

    # ── Deploy steps ──────────────────────────────────────────────────────────
    run_all_steps(cfg, script_dir)


def _generate_template(outfile: str, script_dir: Path) -> tuple[bool, str]:
    try:
        r = subprocess.run(
            ["python3", str(script_dir / "shared" / "deployenv.py"),
             "template", "--out", outfile],
            check=False, capture_output=True,
        )
        return r.returncode == 0, r.stderr.decode().strip()
    except Exception as exc:
        return False, str(exc)


def _detect_os() -> tuple[str, str]:
    os_id = "unknown"
    os_pretty = "Linux"
    try:
        lines = Path("/etc/os-release").read_text().splitlines()
        for line in lines:
            if line.startswith("ID="):
                os_id = line.split("=", 1)[1].strip().strip('"')
            elif line.startswith("PRETTY_NAME="):
                os_pretty = line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return os_id, os_pretty


if __name__ == "__main__":
    main()
