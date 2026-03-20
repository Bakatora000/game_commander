#!/usr/bin/env python3
"""Découverte des dépendances pour le deploy Game Commander."""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import subprocess
import sys
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


_LIST_PKG_KEYS = {
    "apt": "apt_missing",
    "extra-apt": "extra_apt_missing",
    "python-apt": "python_apt_missing",
    "python-pip": "python_pip_missing",
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


def _cmd_list_pkgs(args: argparse.Namespace) -> int:
    data = json.loads(args.from_json)
    key = _LIST_PKG_KEYS.get(args.type, "")
    for pkg in data.get(key, []):
        sys.stdout.write(f"{pkg}\n")
    return 0


def _cmd_flags(args: argparse.Namespace) -> int:
    data = json.loads(args.from_json)
    ens = data.get("enshrouded") or {}
    pairs = {
        "NEEDS_I386": "true" if data.get("need_i386") else "false",
        "I386_ENABLED": "true" if data.get("i386_enabled") else "false",
        "NEEDS_ENSHROUDED": "true" if ens.get("required") else "false",
        "WINE64_OK": "true" if (ens.get("wine64_installed") and ens.get("wine64_in_path")) else "false",
        "WINE_IN_PATH": "true" if ens.get("wine_in_path") else "false",
        "WINE64_ALT_PATH": ens.get("wine64_alt_path") or "",
        "XVFB_IN_PATH": "true" if ens.get("xvfb_run_in_path") else "false",
        "WINE_PREFIX_EXISTS": "true" if ens.get("wine_prefix_exists") else "false",
        "STEAMCMD_PATH": data.get("steamcmd_path") or "",
        "STEAMCMD_HOME": data.get("steamcmd_home") or "",
    }
    for k, v in pairs.items():
        sys.stdout.write(f'{k}="{v}"\n')
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
    list_pkgs = sub.add_parser("list-pkgs")
    list_pkgs.add_argument("--from-json", required=True)
    list_pkgs.add_argument("--type", required=True, choices=list(_LIST_PKG_KEYS))
    list_pkgs.set_defaults(func=_cmd_list_pkgs)
    flags = sub.add_parser("flags")
    flags.add_argument("--from-json", required=True)
    flags.set_defaults(func=_cmd_flags)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
