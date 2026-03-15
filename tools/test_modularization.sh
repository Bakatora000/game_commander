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
    grep -q 'source "\$SCRIPT_DIR/lib/cmd_update.sh"' "$file" || return 1

    if grep -qE 'apt-get|steamcmd|systemctl reload nginx|certbot|journalctl -u' "$file"; then
        return 1
    fi
}

test_deploy_uses_nginx_module() {
    local file="$ROOT_DIR/lib/cmd_deploy.sh"

    grep -q 'deploy_step_dependencies' "$file" || return 1
    grep -q 'deploy_step_game_install' "$file" || return 1
    grep -q 'deploy_step_nginx' "$file" || return 1
    grep -q 'deploy_step_validation' "$file" || return 1
}

test_deploy_modules_present() {
    local helpers_file="$ROOT_DIR/lib/deploy_helpers.sh"
    local configure_file="$ROOT_DIR/lib/deploy_configure.sh"
    local steps_file="$ROOT_DIR/lib/deploy_steps.sh"

    grep -q 'deploy_set_defaults()' "$helpers_file" || return 1
    grep -q 'deploy_handle_special_args()' "$helpers_file" || return 1
    grep -q 'deploy_init_logging()' "$helpers_file" || return 1
    grep -q 'deploy_step_configuration()' "$configure_file" || return 1
    grep -q 'deploy_check_port_conflict()' "$configure_file" || return 1
    grep -q 'deploy_configure_server()' "$configure_file" || return 1
    grep -q 'deploy_step_dependencies()' "$steps_file" || return 1
    grep -q 'mkdir -p "\$APP_DIR"' "$steps_file" || return 1
    grep -q '\[\[ "\$GAME_ID" == "minecraft" || "\$GAME_ID" == "minecraft-fabric" \]\]' "$steps_file" || return 1
    grep -q 'server.properties ops.json whitelist.json banned-players.json banned-ips.json usercache.json' "$steps_file" || return 1
    grep -q 'exec ./WSServer.sh Level01_Main -server "\${ARGS\[@\]}" -log -UTF8Output -MULTIHOME=0.0.0.0 "-EchoPort=\${ECHO_PORT}" -forcepassthrough' "$steps_file" || return 1
    grep -q 'deploy_step_nginx()' "$steps_file" || return 1
    grep -q 'nginx_manifest_add "\$INSTANCE_ID" "\$URL_PREFIX" "\$FLASK_PORT" "\$GAME_LABEL"' "$steps_file" || return 1
    grep -q 'deploy_step_validation()' "$steps_file" || return 1
}

test_attach_mode_present() {
    local helpers_file="$ROOT_DIR/lib/deploy_helpers.sh"
    local configure_file="$ROOT_DIR/lib/deploy_configure.sh"
    local deploy_file="$ROOT_DIR/lib/cmd_deploy.sh"
    local steps_file="$ROOT_DIR/lib/deploy_steps.sh"
    local update_file="$ROOT_DIR/lib/cmd_update.sh"

    grep -q 'DEPLOY_MODE="managed"' "$helpers_file" || return 1
    grep -q 'GAME_SERVICE=""' "$helpers_file" || return 1
    grep -q 'DEPLOY_MODE="managed"' "$helpers_file" || return 1
    grep -q 'deploy_configure_mode()' "$configure_file" || return 1
    grep -q 'Mode sélectionné :' "$configure_file" || return 1
    grep -q 'prev_server_dir' "$configure_file" || return 1
    grep -q 'if \[\[ "\$DEPLOY_MODE" != "attach" \]\] && conflict=' "$configure_file" || return 1
    grep -q '\[\[ "\$DEPLOY_MODE" != "attach" \]\] && deploy_warn_port_group_conflicts' "$configure_file" || return 1
    grep -q -- '--attach\|--existing-server' "$deploy_file" || return 1
    grep -q '\[\[ "\$DEPLOY_MODE" == "attach" \]\]' "$steps_file" || return 1
    grep -q 'Mode attach — installation/mise à jour du serveur ignorée' "$steps_file" || return 1
    grep -q 'Mode attach — service de jeu existant conservé' "$steps_file" || return 1
    grep -q 'echo "DEPLOY_MODE=\\"${DEPLOY_MODE}\\""' "$steps_file" || return 1
    grep -q 'echo "GAME_SERVICE=\\"${GAME_SERVICE}\\""' "$steps_file" || return 1
    grep -q 'DEPLOY_MODE GAME_SERVICE' "$update_file" || return 1
    grep -q 'GAME_SERVICE="${GAME_SERVICE:-valheim-server-${INSTANCE_ID}}"' "$update_file" || return 1
}

test_uninstall_prefers_manifest() {
    local file="$ROOT_DIR/lib/cmd_uninstall.sh"

    grep -q 'uninstall_gc_section' "$file" || return 1
    grep -q 'uninstall_flask_section' "$file" || return 1
    grep -q 'uninstall_orphans_section' "$file" || return 1
}

test_uninstall_modules_present() {
    local gc_file="$ROOT_DIR/lib/uninstall_gc.sh"
    local flask_file="$ROOT_DIR/lib/uninstall_flask.sh"
    local orphans_file="$ROOT_DIR/lib/uninstall_orphans.sh"
    local helpers_file="$ROOT_DIR/lib/helpers.sh"

    grep -q 'gc_read()' "$helpers_file" || return 1
    grep -q 'gc_read _ans' "$helpers_file" || return 1
    grep -q 'gc_read gc_sel' "$gc_file" || return 1
    grep -q 'gc_read gc_action' "$gc_file" || return 1
    grep -q 'gc_read fl_sel' "$flask_file" || return 1
    grep -q 'gc_read fl_action' "$flask_file" || return 1
    grep -q 'gc_read kill_sel' "$orphans_file" || return 1
    grep -q 'gc_read sig_choice' "$orphans_file" || return 1
    grep -q '\[\[ -f "\$GC_NGINX_MANIFEST" \]\] && nginx_manifest_check "\$instance_id"' "$gc_file" || return 1
    grep -q 'nginx_manifest_remove "\$instance_id"' "$gc_file" || return 1
    grep -q 'nginx_regenerate_locations' "$gc_file" || return 1
    grep -q 'nginx_apply' "$gc_file" || return 1
    grep -q 'uninstall_flask_process_entry' "$flask_file" || return 1
    grep -q 'uninstall_orphans_section' "$orphans_file" || return 1
}

test_gc_read_falls_back_to_stdin() {
    local sandbox="$TMPDIR/helpers_read"
    mkdir -p "$sandbox"

    GC_READ_OUT="$sandbox/out" \
    ROOT_DIR="$ROOT_DIR" \
    bash <<'EOF'
set -euo pipefail
source "$ROOT_DIR/lib/helpers.sh"
printf 'hello\n' | {
    gc_read val
    printf '%s\n' "$val" > "$GC_READ_OUT"
}
EOF

    grep -q '^hello$' "$sandbox/out" || return 1
}

test_update_module_present() {
    local file="$ROOT_DIR/lib/cmd_update.sh"

    grep -q 'cmd_update()' "$file" || return 1
    grep -q 'update_collect_configs()' "$file" || return 1
    grep -q 'rsync -a --delete' "$file" || return 1
    grep -q 'tools/config_gen.py" game-json' "$file" || return 1
    grep -q 'systemctl restart "\$GC_SERVICE"' "$file" || return 1
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

    grep -q 'tools/nginx_manager.py init --domain gaming.example.com --manifest /etc/nginx/game-commander-manifest.json --loc-file /etc/nginx/game-commander-locations.conf --hub-file /etc/nginx/game-commander-hub.html --backup-dir /etc/nginx/backups' "$sandbox/calls.log" || return 1
    grep -q 'tools/nginx_manager.py manifest-add --manifest /etc/nginx/game-commander-manifest.json --instance-id valheim8 --prefix /valheim8 --port 5002 --game Valheim' "$sandbox/calls.log" || return 1
    grep -q 'tools/nginx_manager.py manifest-check --manifest /etc/nginx/game-commander-manifest.json --instance-id valheim8' "$sandbox/calls.log" || return 1
    grep -q 'tools/nginx_manager.py manifest-remove --manifest /etc/nginx/game-commander-manifest.json --instance-id valheim8' "$sandbox/calls.log" || return 1
    grep -q 'tools/nginx_manager.py regenerate --manifest /etc/nginx/game-commander-manifest.json --out /etc/nginx/game-commander-locations.conf --hub-file /etc/nginx/game-commander-hub.html' "$sandbox/calls.log" || return 1
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

test_orphans_skip_systemd_managed_processes() {
    local sandbox="$TMPDIR/orphans"
    mkdir -p "$sandbox/proc/4242"

    cat > "$sandbox/proc/4242/cgroup" <<'EOF'
0::/system.slice/enshrouded-server-testensh.service
EOF

    PROC_ROOT="$sandbox/proc" \
    ROOT_DIR="$ROOT_DIR" \
    bash <<'EOF'
set -euo pipefail
source "$ROOT_DIR/lib/uninstall_orphans.sh"
uninstall_orphans_is_systemd_managed 4242
EOF
}

main() {
    run_test "Python tool tests" test_python_tools
    run_test "Thin game_commander.sh entrypoint" test_entrypoint_is_thin
    run_test "Deploy delegates to modular steps" test_deploy_uses_nginx_module
    run_test "Deploy helper and step modules present" test_deploy_modules_present
    run_test "Attach mode is wired through deploy and update" test_attach_mode_present
    run_test "Uninstall delegates to dedicated modules" test_uninstall_prefers_manifest
    run_test "Uninstall modules keep manifest and process logic" test_uninstall_modules_present
    run_test "Interactive prompt helper falls back to stdin" test_gc_read_falls_back_to_stdin
    run_test "Update command refreshes installed app runtime" test_update_module_present
    run_test "Nginx shell wrappers call python manager" test_nginx_wrappers_call_python_manager
    run_test "Helpers support dry-run and shared-dir detection" test_helpers_dry_run_and_shared_detection
    run_test "Orphan scan skips systemd-managed child processes" test_orphans_skip_systemd_managed_processes

    printf '\nSummary: %d passed, %d failed\n' "$PASS_COUNT" "$FAIL_COUNT"
    [[ "$FAIL_COUNT" -eq 0 ]]
}

main "$@"
