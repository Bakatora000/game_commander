#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "[preflight] Vérification dépôt Game Commander"

fail() {
    echo "[preflight] ERREUR: $*" >&2
    exit 1
}

require_clean_ignore_rules() {
    local tracked_sensitive=()
    while IFS= read -r path; do
        [[ -z "$path" ]] && continue
        tracked_sensitive+=("$path")
    done < <(git ls-files -- \
        game.json \
        users.json \
        metrics.log \
        deploy_config.env \
        'deploy_*.env' \
        '*.bak' \
        '*.bak.*')

    if [[ ${#tracked_sensitive[@]} -gt 0 ]]; then
        printf '[preflight] Fichiers sensibles trackés:\n%s\n' "${tracked_sensitive[*]}" >&2
        fail "retirer ces fichiers du suivi Git avant push"
    fi
}

require_git_remote() {
    git remote get-url origin >/dev/null 2>&1 \
        || fail "remote origin absent"
}

run_tests() {
    "$ROOT_DIR/tools/test_modularization.sh" \
        || fail "tests de modularisation en échec"
}

main() {
    require_git_remote
    require_clean_ignore_rules
    run_tests
    echo "[preflight] OK"
}

main "$@"
