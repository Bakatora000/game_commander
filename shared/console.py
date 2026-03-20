#!/usr/bin/env python3
"""Terminal output helpers for Game Commander — Python equivalent of lib/helpers.sh."""
from __future__ import annotations

import sys

_RED    = "\033[0;31m"
_GREEN  = "\033[0;32m"
_YELLOW = "\033[1;33m"
_CYAN   = "\033[0;36m"
_BOLD   = "\033[1m"
_DIM    = "\033[2m"
_RESET  = "\033[0m"


def ok(msg: str)   -> None: print(f"{_GREEN}  ✓  {msg}{_RESET}")
def warn(msg: str) -> None: print(f"{_YELLOW}  ⚠  {msg}{_RESET}")
def err(msg: str)  -> None: print(f"{_RED}  ✗  {msg}{_RESET}", file=sys.stderr)
def info(msg: str) -> None: print(f"{_CYAN}  →  {msg}{_RESET}")
def hdr(msg: str)  -> None: print(f"\n{_BOLD}{_CYAN}╔══ {msg} ══╗{_RESET}")
def sep()          -> None: print(f"{_DIM}  ───────────────────────────────────────{_RESET}")
def die(msg: str)  -> None: err(msg); sys.exit(1)


def prompt(question: str, default: str = "") -> str:
    """Print a prompt and return the user's input (falls back to default)."""
    if default:
        sys.stdout.write(f"  {_YELLOW}?  {question} [{_DIM}{default}{_RESET}{_YELLOW}]: {_RESET}")
    else:
        sys.stdout.write(f"  {_YELLOW}?  {question}: {_RESET}")
    sys.stdout.flush()
    try:
        reply = input().strip()
    except EOFError:
        reply = ""
    return reply or default


def prompt_secret(question: str, default: str = "") -> str:
    """Prompt for a password (no echo). Falls back to default on empty input."""
    import getpass
    try:
        reply = getpass.getpass(f"  {_YELLOW}?  {question}: {_RESET}")
    except (EOFError, KeyboardInterrupt):
        reply = ""
    return reply or default


def confirm(question: str, default: str = "o") -> bool:
    """Ask a yes/no question. Returns True for yes."""
    sys.stdout.write(f"  {_YELLOW}?  {question} (o/n) [{default}]: {_RESET}")
    sys.stdout.flush()
    try:
        ans = input().strip() or default
    except EOFError:
        ans = default
    return ans.lower() in ("o", "oui", "y", "yes")


def ask_yn(question: str, assume_yes: bool = False) -> bool:
    """Yes/no prompt. Returns True immediately if assume_yes is set."""
    if assume_yes:
        return True
    return confirm(question)


def confirm_bool(val: bool, question: str, config_mode: bool = False) -> bool:
    """Confirm a boolean value. In config mode, displays and returns val without prompting."""
    if config_mode:
        label = "oui" if val else "non"
        print(f"  {_DIM}  (config) {question} → {label}{_RESET}")
        return val
    return confirm(question)


def banner() -> None:
    """Print the Game Commander deploy banner."""
    print("""
  ╔════════════════════════════════════════════════════════╗
  ║      GAME COMMANDER — DÉPLOIEMENT v2.0                 ║
  ║   Serveur de jeu + Interface web (sans AMP)            ║
  ╚════════════════════════════════════════════════════════╝
""")
