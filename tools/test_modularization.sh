#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMPDIR="$(mktemp -d)"
trap 'rm -rf "$TMPDIR"' EXIT

PASS_COUNT=0
FAIL_COUNT=0

pass() {
    printf 'PASS: %s\n' "$1"
    PASS_COUNT=$((PASS_COUNT + 1))
}

fail() {
    printf 'FAIL: %s\n' "$1" >&2
    FAIL_COUNT=$((FAIL_COUNT + 1))
}

run_test() {
    local name="$1"
    shift
    if "$@"; then
        pass "$name"
    else
        fail "$name"
    fi
}

test_python_tools() {
    (
        cd "$ROOT_DIR"
        python3 tools/test_tools.py >/tmp/game_commander_test_tools.log 2>&1
    )
}

test_entrypoint_is_thin() {
    local file="$ROOT_DIR/game_commander.sh"

    grep -q 'source "\$SCRIPT_DIR/lib/helpers.sh"' "$file" || return 1
    grep -q 'source "\$SCRIPT_DIR/lib/nginx.sh"' "$file" || return 1
    grep -q 'source "\$SCRIPT_DIR/lib/cmd_status.sh"' "$file" || return 1
    grep -q 'source "\$SCRIPT_DIR/lib/cmd_deploy.sh"' "$file" || return 1
    grep -q 'source "\$SCRIPT_DIR/lib/cmd_uninstall.sh"' "$file" || return 1

    if grep -qE 'apt-get|steamcmd|systemctl reload nginx|certbot|journalctl -u' "$file"; then
        return 1
    fi
}

test_deploy_uses_nginx_module() {
    local file="$ROOT_DIR/lib/cmd_deploy.sh"

    grep -q 'nginx_ensure_init "\$DOMAIN"' "$file" || return 1
    grep -q 'nginx_manifest_add "\$INSTANCE_ID" "\$URL_PREFIX" "\$FLASK_PORT" "\$GAME_LABEL"' "$file" || return 1
    grep -q 'nginx_regenerate_locations' "$file" || return 1
    grep -q 'nginx_apply' "$file" || return 1
}

test_uninstall_prefers_manifest() {
    local file="$ROOT_DIR/lib/cmd_uninstall.sh"

    grep -q '\[\[ -f "\$GC_NGINX_MANIFEST" \]\] && nginx_manifest_check "\$INSTANCE_ID"' "$file" || return 1
    grep -q 'nginx_manifest_remove "\$INSTANCE_ID"' "$file" || return 1
    grep -q 'nginx_regenerate_locations' "$file" || return 1
    grep -q 'nginx_apply' "$file" || return 1
}

test_nginx_wrappers_call_python_manager() {
    local sandbox="$TMPDIR/nginx_wrappers"
    mkdir -p "$sandbox/bin" "$sandbox/repo/tools"

    cat > "$sandbox/bin/python3" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$GC_TEST_LOG"
case "${2:-}" in
  manifest-check)
    exit 0
    ;;
  *)
    exit 0
    ;;
esac
EOF
    chmod +x "$sandbox/bin/python3"

    cat > "$sandbox/bin/nginx" <<'EOF'
#!/usr/bin/env bash
printf 'nginx %s\n' "$*" >> "$GC_TEST_LOG"
exit 0
EOF
    chmod +x "$sandbox/bin/nginx"

    cat > "$sandbox/bin/systemctl" <<'EOF'
#!/usr/bin/env bash
printf 'systemctl %s\n' "$*" >> "$GC_TEST_LOG"
exit 0
EOF
    chmod +x "$sandbox/bin/systemctl"

    : > "$sandbox/calls.log"

    GC_TEST_LOG="$sandbox/calls.log" \
    PATH="$sandbox/bin:$PATH" \
    ROOT_DIR="$ROOT_DIR" \
    bash <<'EOF'
set -euo pipefail
SCRIPT_DIR="$ROOT_DIR"
source "$ROOT_DIR/lib/helpers.sh"
source "$ROOT_DIR/lib/nginx.sh"
nginx_ensure_init "gaming.example.com"
nginx_manifest_add "valheim8" "/valheim8" "5002" "Valheim"
nginx_manifest_check "valheim8"
nginx_manifest_remove "valheim8"
nginx_regenerate_locations
nginx_apply
EOF

    grep -q 'tools/nginx_manager.py init --domain gaming.example.com --manifest /etc/nginx/game-commander-manifest.json --loc-file /etc/nginx/game-commander-locations.conf --backup-dir /etc/nginx/backups' "$sandbox/calls.log" || return 1
    grep -q 'tools/nginx_manager.py manifest-add --manifest /etc/nginx/game-commander-manifest.json --instance-id valheim8 --prefix /valheim8 --port 5002 --game Valheim' "$sandbox/calls.log" || return 1
    grep -q 'tools/nginx_manager.py manifest-check --manifest /etc/nginx/game-commander-manifest.json --instance-id valheim8' "$sandbox/calls.log" || return 1
    grep -q 'tools/nginx_manager.py manifest-remove --manifest /etc/nginx/game-commander-manifest.json --instance-id valheim8' "$sandbox/calls.log" || return 1
    grep -q 'tools/nginx_manager.py regenerate --manifest /etc/nginx/game-commander-manifest.json --out /etc/nginx/game-commander-locations.conf' "$sandbox/calls.log" || return 1
    grep -q '^nginx -t$' "$sandbox/calls.log" || return 1
    grep -q '^systemctl reload nginx$' "$sandbox/calls.log" || return 1
}

test_helpers_dry_run_and_shared_detection() {
    local sandbox="$TMPDIR/helpers"
    mkdir -p "$sandbox/home/a" "$sandbox/home/b" "$sandbox/bin"

    cat > "$sandbox/home/a/deploy_config.env" <<'EOF'
INSTANCE_ID="valheim8"
APP_DIR="/srv/shared-app"
EOF

    cat > "$sandbox/home/b/deploy_config.env" <<'EOF'
INSTANCE_ID="ens1"
APP_DIR="/srv/shared-app"
EOF

    cat > "$sandbox/bin/find" <<EOF
#!/usr/bin/env bash
printf '%s\n' "$sandbox/home/a/deploy_config.env" "$sandbox/home/b/deploy_config.env"
EOF
    chmod +x "$sandbox/bin/find"

    HELPERS_OUT="$sandbox/helpers.out" \
    PATH="$sandbox/bin:$PATH" \
    ROOT_DIR="$ROOT_DIR" \
    bash <<'EOF'
set -euo pipefail
source "$ROOT_DIR/lib/helpers.sh"
DRY_RUN=true
run touch /tmp/should_not_exist_gc
shared_by_others "/srv/shared-app" "__missing__" > "$HELPERS_OUT"
EOF

    [[ ! -e /tmp/should_not_exist_gc ]] || return 1
    grep -q 'valheim8 ens1\|ens1 valheim8' "$sandbox/helpers.out" || return 1
}

main() {
    run_test "Python tool tests" test_python_tools
    run_test "Thin game_commander.sh entrypoint" test_entrypoint_is_thin
    run_test "Deploy uses nginx module" test_deploy_uses_nginx_module
    run_test "Uninstall prefers nginx manifest flow" test_uninstall_prefers_manifest
    run_test "Nginx shell wrappers call python manager" test_nginx_wrappers_call_python_manager
    run_test "Helpers support dry-run and shared-dir detection" test_helpers_dry_run_and_shared_detection

    printf '\nSummary: %d passed, %d failed\n' "$PASS_COUNT" "$FAIL_COUNT"
    [[ "$FAIL_COUNT" -eq 0 ]]
}

main "$@"
