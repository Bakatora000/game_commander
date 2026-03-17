#!/usr/bin/env python3
"""Découverte des dépendances pour le deploy Game Commander."""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import subprocess
from pathlib import Path


BASE_APT_PACKAGES = ["python3", "python3-pip", "nginx", "curl", "zip", "unzip", "jq"]
PY_APT_PACKAGES = ["python3-flask"]
PY_PIP_PACKAGES = ["requests", "bcrypt", "psutil"]


def _is_dpkg_installed(pkg: str) -> bool:
    result = subprocess.run(["dpkg", "-l", pkg], capture_output=True, text=True, check=False)
    return result.returncode == 0 and any(line.startswith("ii") for line in result.stdout.splitlines())


def _python_module_available(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


def _cmd_exists(name: str) -> bool:
    return shutil.which(name) is not None


def inspect_dependencies(
    *,
    deploy_mode: str,
    steam_appid: str,
    ssl_mode: str,
    game_id: str,
    home_dir: str,
) -> dict:
    apt_missing = [pkg for pkg in BASE_APT_PACKAGES if not _is_dpkg_installed(pkg)]
    python_apt_missing = [pkg for pkg in PY_APT_PACKAGES if not _python_module_available(pkg.replace("python3-", ""))]
    python_pip_missing = [pkg for pkg in PY_PIP_PACKAGES if not _python_module_available(pkg)]

    need_i386 = False
    i386_enabled = True
    extra_apt_missing: list[str] = []
    if deploy_mode != "attach" and steam_appid:
        need_i386 = True
        archs = subprocess.run(["dpkg", "--print-foreign-architectures"], capture_output=True, text=True, check=False).stdout.split()
        i386_enabled = "i386" in archs
        if not _is_dpkg_installed("lib32gcc-s1"):
            extra_apt_missing.append("lib32gcc-s1")

    if ssl_mode == "certbot":
        for pkg in ("certbot", "python3-certbot-nginx"):
            if not _is_dpkg_installed(pkg):
                extra_apt_missing.append(pkg)

    enshrouded = {
        "required": deploy_mode != "attach" and game_id == "enshrouded",
        "wine64_installed": _is_dpkg_installed("wine64"),
        "wine64_in_path": _cmd_exists("wine64"),
        "wine_in_path": _cmd_exists("wine"),
        "wine64_alt_path": str(Path("/usr/lib/wine/wine64")) if Path("/usr/lib/wine/wine64").exists() else "",
        "xvfb_installed": _is_dpkg_installed("xvfb"),
        "xvfb_run_in_path": _cmd_exists("xvfb-run"),
        "wine_prefix_exists": Path(home_dir, ".wine").is_dir(),
    }

    steamcmd_system = shutil.which("steamcmd") or ""
    steamcmd_home = str(Path(home_dir) / "steamcmd" / "steamcmd.sh")
    steamcmd_path = steamcmd_system or (steamcmd_home if Path(steamcmd_home).is_file() else "")

    return {
        "apt_missing": apt_missing,
        "python_apt_missing": python_apt_missing,
        "python_pip_missing": python_pip_missing,
        "extra_apt_missing": extra_apt_missing,
        "need_i386": need_i386,
        "i386_enabled": i386_enabled,
        "enshrouded": enshrouded,
        "steamcmd_path": steamcmd_path,
        "steamcmd_home": steamcmd_home,
        "steamcmd_installed": bool(steamcmd_path),
    }


def _cmd_inspect(args: argparse.Namespace) -> int:
    payload = inspect_dependencies(
        deploy_mode=args.deploy_mode,
        steam_appid=args.steam_appid,
        ssl_mode=args.ssl_mode,
        game_id=args.game_id,
        home_dir=args.home_dir,
    )
    print(json.dumps(payload))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Game Commander deploy dependencies helper")
    sub = parser.add_subparsers(dest="command", required=True)
    inspect = sub.add_parser("inspect")
    inspect.add_argument("--deploy-mode", required=True)
    inspect.add_argument("--steam-appid", default="")
    inspect.add_argument("--ssl-mode", required=True)
    inspect.add_argument("--game-id", required=True)
    inspect.add_argument("--home-dir", required=True)
    inspect.set_defaults(func=_cmd_inspect)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
