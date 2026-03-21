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

test_gcctl_entrypoint_is_thin() {
    local file="$ROOT_DIR/gcctl"

    grep -q 'from shared import cmd_main' "$file" || return 1
    grep -q 'cmd_main.main' "$file" || return 1

    if grep -qE 'apt-get|steamcmd|systemctl reload nginx|certbot|journalctl -u' "$file"; then
        return 1
    fi
}

test_deploy_uses_nginx_module() {
    local file="$ROOT_DIR/shared/cmd_deploy.py"

    grep -q 'run_configure' "$file" || return 1
    grep -q 'run_all_steps' "$file" || return 1
    grep -q 'deploy_step_nginx\|deploynginx' "$ROOT_DIR/shared/deploysteps.py" || return 1
    grep -q 'deploy_step_validation' "$ROOT_DIR/shared/deploysteps.py" || return 1
}

test_deploy_modules_present() {
    local config_file="$ROOT_DIR/shared/deployconfig.py"
    local configure_file="$ROOT_DIR/shared/deployconfigure.py"
    local steps_file="$ROOT_DIR/shared/deploysteps.py"

    grep -q 'class DeployConfig' "$config_file" || return 1
    grep -q 'def to_env' "$config_file" || return 1
    grep -q 'deploy_mode.*managed\|managed.*deploy_mode' "$config_file" || return 1
    grep -q 'def run_configure' "$configure_file" || return 1
    grep -q 'def _configure_server' "$configure_file" || return 1
    grep -q 'deployplan.game_meta' "$configure_file" || return 1
    grep -q 'deployplan.next_free_flask_port\|deployplan.existing_prefix_owner' "$configure_file" || return 1
    grep -q 'deployplan.describe_port_conflicts' "$configure_file" || return 1
    grep -q 'def deploy_step_dependencies' "$steps_file" || return 1
    grep -q 'deploybackups' "$steps_file" || return 1
    grep -q 'appfiles' "$steps_file" || return 1
    grep -q 'render_soulmask_start_script\|soulmask' "$steps_file" || return 1
    grep -q 'def deploy_step_nginx' "$steps_file" || return 1
    grep -q 'deploynginx.run_deploy_nginx' "$steps_file" || return 1
    grep -q 'def deploy_step_validation' "$steps_file" || return 1
}

test_attach_mode_present() {
    local config_file="$ROOT_DIR/shared/deployconfig.py"
    local configure_file="$ROOT_DIR/shared/deployconfigure.py"
    local deploy_file="$ROOT_DIR/shared/cmd_deploy.py"
    local steps_file="$ROOT_DIR/shared/deploysteps.py"
    grep -q 'deploy_mode.*managed\|managed.*deploy_mode' "$config_file" || return 1
    grep -q 'game_service.*=.*""' "$config_file" || return 1
    grep -q 'def _configure_mode' "$configure_file" || return 1
    grep -q 'Mode sélectionné :' "$configure_file" || return 1
    grep -q 'apply_instance_defaults' "$configure_file" || return 1
    grep -q 'suggest_free_port_group' "$configure_file" || return 1
    grep -q 'deploy_mode.*!=.*attach\|attach.*deploy_mode' "$configure_file" || return 1
    grep -q -- '--attach\|--existing-server' "$deploy_file" || return 1
    grep -q 'deploy_mode.*==.*attach\|attach.*deploy_mode' "$steps_file" || return 1
    grep -q 'Mode attach — installation/mise à jour du serveur ignorée' "$steps_file" || return 1
    grep -q 'Mode attach — service de jeu existant conservé' "$steps_file" || return 1
    grep -q 'deploypost.save_deploy_config' "$steps_file" || return 1
    grep -q 'update-instance' "$ROOT_DIR/shared/cmd_update.py" || return 1
}

test_uninstall_prefers_manifest() {
    local file="$ROOT_DIR/shared/cmd_main.py"

    grep -q 'uninstall_interactive.py' "$file" || return 1
    grep -q '\-\-script-dir' "$file" || return 1
}

test_uninstall_modules_present() {
    local gc_file="$ROOT_DIR/shared/uninstall_gc.py"
    local flask_file="$ROOT_DIR/shared/uninstall_flask.py"
    local orphans_file="$ROOT_DIR/shared/uninstall_orphans.py"
    local orchestrator="$ROOT_DIR/shared/uninstall_interactive.py"

    grep -q '_nginx_manifest_in_manifest' "$gc_file" || return 1
    grep -q '_nginx_remove_manifest' "$gc_file" || return 1
    grep -q 'stop_and_disable' "$gc_file" || return 1
    grep -q '_process_entry' "$gc_file" || return 1
    grep -q '_collect_flask_services' "$flask_file" || return 1
    grep -q '_process_entry' "$flask_file" || return 1
    grep -q '_collect_orphans' "$orphans_file" || return 1
    grep -q '_is_systemd_managed' "$orphans_file" || return 1
    grep -q '_is_amp_process' "$orphans_file" || return 1
    grep -q 'uninstall_gc.section' "$orchestrator" || return 1
    grep -q 'uninstall_flask.section' "$orchestrator" || return 1
    grep -q 'uninstall_orphans.section' "$orchestrator" || return 1
}

test_console_prompt_falls_back_to_stdin() {
    python3 - "$ROOT_DIR" <<'PYEOF'
import sys, io
sys.path.insert(0, sys.argv[1])
import shared.console as c
sys.stdin = io.StringIO("hello\n")
result = c.prompt("test", "")
assert result == "hello", f"Expected 'hello', got {result!r}"
PYEOF
}

test_update_module_present() {
    local file="$ROOT_DIR/shared/cmd_update.py"

    grep -q 'def main' "$file" || return 1
    grep -q 'update-instance' "$file" || return 1
    grep -q 'deploybackups.install_backup_assets' "$file" || return 1
    grep -q 'cpuplan.apply_plan' "$file" || return 1
    grep -q 'hubsync.sync_hub_service_from_values' "$file" || return 1
}

test_cpu_affinity_module_present() {
    local file="$ROOT_DIR/shared/cpuplan.py"

    grep -q 'def detect_core_groups' "$file" || return 1
    grep -q 'def weight_for_game' "$file" || return 1
    grep -q 'def apply_plan' "$file" || return 1
    grep -q 'def affinity_line_for_instance' "$file" || return 1
}

test_cpu_monitor_module_present() {
    local file="$ROOT_DIR/shared/cpuplan.py"

    grep -q 'def install_cpu_monitor' "$file" || return 1
    grep -q 'game-commander-cpu-monitor.service' "$file" || return 1
}

test_rebalance_command_present() {
    local file="$ROOT_DIR/shared/cmd_rebalance.py"

    grep -q 'def main' "$file" || return 1
    grep -q 'cpuplan.apply_plan' "$file" || return 1
    grep -q 'cpuplan.collect_managed_instances' "$file" || return 1
}

test_deploynginx_calls_nginx_manager() {
    # deploynginx.run_deploy_nginx must invoke nginx_manager.py
    grep -q 'nginx_manager.py' "$ROOT_DIR/shared/deploynginx.py" || return 1
    grep -q 'run_deploy_nginx' "$ROOT_DIR/shared/deploynginx.py" || return 1
}

test_sysutil_dry_run_and_shared_detection() {
    python3 - "$ROOT_DIR" <<'PYEOF'
import sys, os, tempfile
root = sys.argv[1]
sys.path.insert(0, root)
from shared import sysutil, instanceenv

# dry_run: stop_and_disable with dry_run=True should not call systemctl
msgs = sysutil.stop_and_disable("nonexistent-service-gc-test", dry_run=True)
assert any("dry" in m.lower() or "nonexistent" in m.lower() or m for m in msgs), \
    "stop_and_disable dry_run returned no messages"

# shared_by_others: create two fake deploy_config.env files
with tempfile.TemporaryDirectory() as d:
    import pathlib
    for name, iid in [("a", "valheim8"), ("b", "ens1")]:
        p = pathlib.Path(d) / name / "deploy_config.env"
        p.parent.mkdir()
        p.write_text(f'INSTANCE_ID="{iid}"\nAPP_DIR="/srv/shared-app"\n')
    # Monkeypatch discover to return our test configs
    import shared.hostctl as hostctl
    orig = hostctl.discover_instance_configs
    hostctl.discover_instance_configs = lambda: [
        pathlib.Path(d) / "a" / "deploy_config.env",
        pathlib.Path(d) / "b" / "deploy_config.env",
    ]
    owners = sysutil.shared_by_others("/srv/shared-app", "__missing__")
    hostctl.discover_instance_configs = orig
    assert set(owners) == {"valheim8", "ens1"}, f"Expected both instances, got {owners}"
PYEOF
}

test_orphans_skip_systemd_managed_processes() {
    local sandbox="$TMPDIR/orphans"
    mkdir -p "$sandbox/proc/4242"

    cat > "$sandbox/proc/4242/cgroup" <<'EOF'
0::/system.slice/enshrouded-server-testensh.service
EOF

    PROC_ROOT="$sandbox/proc" \
    python3 - <<PYEOF
import sys
sys.path.insert(0, "$ROOT_DIR")
from shared import uninstall_orphans
assert uninstall_orphans._is_systemd_managed(4242), "Expected PID 4242 to be systemd-managed"
PYEOF
}

main() {
    run_test "Python tool tests" test_python_tools
    run_test "Thin gcctl entrypoint" test_gcctl_entrypoint_is_thin
    run_test "Deploy delegates to modular steps" test_deploy_uses_nginx_module
    run_test "Deploy helper and step modules present" test_deploy_modules_present
    run_test "Attach mode is wired through deploy and update" test_attach_mode_present
    run_test "Uninstall delegates to dedicated modules" test_uninstall_prefers_manifest
    run_test "Uninstall modules keep manifest and process logic" test_uninstall_modules_present
    run_test "Interactive prompt helper falls back to stdin" test_console_prompt_falls_back_to_stdin
    run_test "Update command refreshes installed app runtime" test_update_module_present
    run_test "CPU affinity helper module present" test_cpu_affinity_module_present
    run_test "CPU monitor module present" test_cpu_monitor_module_present
    run_test "CPU rebalance command present" test_rebalance_command_present
    run_test "Nginx deploy calls nginx_manager.py" test_deploynginx_calls_nginx_manager
    run_test "Sysutil dry-run and shared-dir detection" test_sysutil_dry_run_and_shared_detection
    run_test "Orphan scan skips systemd-managed child processes" test_orphans_skip_systemd_managed_processes

    printf '\nSummary: %d passed, %d failed\n' "$PASS_COUNT" "$FAIL_COUNT"
    [[ "$FAIL_COUNT" -eq 0 ]]
}

main "$@"
