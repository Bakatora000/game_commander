# ── lib/cpu_monitor.sh ────────────────────────────────────────────────────────
# Monitor passif de déséquilibre CPU pour Game Commander.

cpu_monitor_state_file() {
    printf '%s\n' "${GC_CPU_MONITOR_STATE:-/var/lib/game-commander/cpu-monitor.json}"
}

cpu_monitor_install() {
    local state_file state_dir script_path
    state_file="$(cpu_monitor_state_file)"
    state_dir="$(dirname "$state_file")"
    script_path="$SCRIPT_DIR/tools/cpu_monitor.py"

    [[ -f "$script_path" ]] || {
        warn "Monitor CPU introuvable : $script_path"
        return 0
    }

    mkdir -p "$state_dir"

    cat > /etc/systemd/system/game-commander-cpu-monitor.service <<EOF
[Unit]
Description=Game Commander — CPU imbalance monitor
After=network.target

[Service]
Type=oneshot
ExecStart=/usr/bin/python3 ${script_path} --state-file ${state_file}
EOF

    cat > /etc/systemd/system/game-commander-cpu-monitor.timer <<'EOF'
[Unit]
Description=Game Commander — CPU imbalance monitor (timer)

[Timer]
OnBootSec=2min
OnUnitActiveSec=1min
RandomizedDelaySec=10s
Persistent=true

[Install]
WantedBy=timers.target
EOF

    systemctl daemon-reload
    systemctl enable --now game-commander-cpu-monitor.timer >/dev/null 2>&1 \
        || warn "Impossible d'activer game-commander-cpu-monitor.timer"
    systemctl start game-commander-cpu-monitor.service >/dev/null 2>&1 \
        || warn "Monitor CPU non initialisé immédiatement"
}
