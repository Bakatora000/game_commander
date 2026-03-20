#!/usr/bin/env bash
# game_commander.sh — thin entry point, delegates everything to Python
set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$SCRIPT_DIR/shared/cmd_main.py" --script-dir "$SCRIPT_DIR" "$@"
