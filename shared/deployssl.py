#!/usr/bin/env python3
"""Gestion Python de l'étape SSL du deploy."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys


def apply_ssl(ssl_mode: str, domain: str) -> tuple[bool, list[str]]:
    messages: list[str] = []
    if ssl_mode == "existing":
        return True, ["SSL existant — non modifié"]
    if ssl_mode == "none":
        return True, ["HTTP uniquement"]
    if ssl_mode != "certbot":
        return False, [f"Mode SSL inconnu : {ssl_mode}"]
    if not shutil.which("certbot"):
        return True, ["Certbot non disponible"]
    result = subprocess.run(
        [
            "certbot",
            "--nginx",
            "-d",
            domain,
            "--non-interactive",
            "--agree-tos",
            "--register-unsafely-without-email",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        return True, ["Certificat SSL obtenu"]
    return True, [f"Certbot échoué — {domain} doit pointer sur ce serveur"]


def _cmd_apply(args: argparse.Namespace) -> int:
    ok, messages = apply_ssl(args.ssl_mode, args.domain)
    stream = sys.stdout if ok else sys.stderr
    for line in messages:
        print(line, file=stream)
    return 0 if ok else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Game Commander deploy SSL helper")
    sub = parser.add_subparsers(dest="command", required=True)
    apply_cmd = sub.add_parser("apply")
    apply_cmd.add_argument("--ssl-mode", required=True)
    apply_cmd.add_argument("--domain", required=True)
    apply_cmd.set_defaults(func=_cmd_apply)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
