# ── lib/cpu_affinity.sh ─────────────────────────────────────────────────────
# Répartition CPU par cœur physique pour les instances Game Commander.

cpu_affinity_scan_roots() {
    if [[ -n "${GC_DEPLOY_SCAN_ROOTS:-}" ]]; then
        tr ' ' '\n' <<< "${GC_DEPLOY_SCAN_ROOTS}" | sed '/^$/d'
    else
        printf '%s\n' /home /opt /root
    fi
}

cpu_affinity_sysfs_root() {
    printf '%s\n' "${GC_CPU_SYSFS_ROOT:-/sys/devices/system/cpu}"
}

cpu_affinity_expand_cpu_list() {
    local raw="${1:-}" part start end i
    raw="${raw//,/ }"
    for part in $raw; do
        if [[ "$part" == *-* ]]; then
            start="${part%-*}"
            end="${part#*-}"
            for ((i=start; i<=end; i++)); do
                printf '%s\n' "$i"
            done
        elif [[ -n "$part" ]]; then
            printf '%s\n' "$part"
        fi
    done
}

cpu_affinity_detect_core_groups() {
    local sysfs_root
    sysfs_root="$(cpu_affinity_sysfs_root)"
    [[ -d "$sysfs_root" ]] || return 1

    local path raw group
    declare -A seen=()
    for path in "$sysfs_root"/cpu[0-9]*/topology/thread_siblings_list; do
        [[ -f "$path" ]] || continue
        raw="$(<"$path")"
        group="$(
            cpu_affinity_expand_cpu_list "$raw" \
                | awk 'NF{print $1}' \
                | sort -n -u \
                | paste -sd' ' -
        )"
        [[ -n "$group" ]] || continue
        [[ -n "${seen[$group]:-}" ]] && continue
        seen["$group"]=1
        printf '%s\n' "$group"
    done
}

cpu_affinity_weight_for_game() {
    case "$1" in
        soulmask|enshrouded) echo 4 ;;
        satisfactory) echo 3 ;;
        valheim|minecraft|minecraft-fabric) echo 2 ;;
        terraria) echo 1 ;;
        *) echo 2 ;;
    esac
}

cpu_affinity_cpu_weight_for_game() {
    local weight
    weight="$(cpu_affinity_weight_for_game "$1")"
    echo $((weight * 100))
}

cpu_affinity_is_heavy_idle_game() {
    [[ "$1" == "soulmask" || "$1" == "enshrouded" ]]
}

cpu_affinity_collect_instances() {
    local cfg
    local -a roots=()
    mapfile -t roots < <(cpu_affinity_scan_roots)
    while IFS= read -r cfg; do
        [[ -f "$cfg" ]] || continue
        unset GAME_ID INSTANCE_ID GAME_SERVICE DEPLOY_MODE
        source <(grep -E '^[A-Z_]+=' "$cfg" 2>/dev/null)
        [[ -n "${GAME_ID:-}" && -n "${INSTANCE_ID:-}" ]] || continue
        [[ "${DEPLOY_MODE:-managed}" == "managed" ]] || continue
        GAME_SERVICE="${GAME_SERVICE:-${GAME_ID}-server-${INSTANCE_ID}}"
        printf '%s|%s|%s\n' "$INSTANCE_ID" "$GAME_ID" "$GAME_SERVICE"
    done < <(find "${roots[@]}" -maxdepth 5 -name "deploy_config.env" 2>/dev/null | sort -u)
}

cpu_affinity_plan_all() {
    local extra_instance="${1:-}" extra_game="${2:-}" extra_service="${3:-}"
    local -a core_groups=()
    mapfile -t core_groups < <(cpu_affinity_detect_core_groups)
    [[ ${#core_groups[@]} -gt 0 ]] || return 1

    local tmp instance_id game_id service_name weight
    tmp="$(mktemp)"
    while IFS='|' read -r instance_id game_id service_name; do
        weight="$(cpu_affinity_weight_for_game "$game_id")"
        printf '%s|%s|%s|%s\n' "$weight" "$instance_id" "$game_id" "$service_name" >> "$tmp"
    done < <(cpu_affinity_collect_instances)

    if [[ -n "$extra_instance" && -n "$extra_game" && -n "$extra_service" ]]; then
        if ! grep -qE "^[0-9]+\|${extra_instance}\|" "$tmp" 2>/dev/null; then
            weight="$(cpu_affinity_weight_for_game "$extra_game")"
            printf '%s|%s|%s|%s\n' "$weight" "$extra_instance" "$extra_game" "$extra_service" >> "$tmp"
        fi
    fi

    local -a loads=() heavy=()
    local idx best_idx best_score score
    for ((idx=0; idx<${#core_groups[@]}; idx++)); do
        loads[idx]=0
        heavy[idx]=0
    done

    while IFS='|' read -r weight instance_id game_id service_name; do
        [[ -n "$instance_id" ]] || continue
        best_idx=-1
        best_score=999999
        for ((idx=0; idx<${#core_groups[@]}; idx++)); do
            score=${loads[idx]}
            if cpu_affinity_is_heavy_idle_game "$game_id" && [[ "${heavy[idx]}" -gt 0 ]]; then
                score=$((score + 1000))
            fi
            if (( score < best_score )); then
                best_score=$score
                best_idx=$idx
            fi
        done
        [[ $best_idx -ge 0 ]] || continue
        loads[$best_idx]=$((loads[$best_idx] + weight))
        if cpu_affinity_is_heavy_idle_game "$game_id"; then
            heavy[$best_idx]=1
        fi
        printf '%s|%s|%s|%s|%s\n' \
            "$instance_id" "$game_id" "$service_name" "${core_groups[$best_idx]}" "$weight"
    done < <(sort -t'|' -k1,1nr -k2,2 "$tmp")

    rm -f "$tmp"
}

cpu_affinity_systemd_line() {
    local instance_id="$1" game_id="$2" service_name="$3"
    local iid gid svc cpus weight
    while IFS='|' read -r iid gid svc cpus weight; do
        if [[ "$iid" == "$instance_id" && "$svc" == "$service_name" ]]; then
            echo "CPUAffinity=${cpus}"
            return 0
        fi
    done < <(cpu_affinity_plan_all "$instance_id" "$game_id" "$service_name")
    return 1
}

cpu_affinity_apply_all() {
    local restart_running="${1:-false}"
    local changed=false
    local instance_id game_id service_name cpus weight dropin_dir dropin_file cpu_weight
    local plan_output

    plan_output="$(cpu_affinity_plan_all || true)"
    if [[ -z "$plan_output" ]]; then
        if ! cpu_affinity_detect_core_groups >/dev/null 2>&1; then
            warn "Topologie CPU introuvable — aucune affinité appliquée"
        else
            warn "Aucune instance gérée trouvée pour la répartition CPU"
        fi
        return 0
    fi

    while IFS='|' read -r instance_id game_id service_name cpus weight; do
        [[ -n "$service_name" && -n "$cpus" ]] || continue
        dropin_dir="/etc/systemd/system/${service_name}.service.d"
        dropin_file="${dropin_dir}/10-cpu-affinity.conf"
        cpu_weight="$(cpu_affinity_cpu_weight_for_game "$game_id")"
        mkdir -p "$dropin_dir"
        cat > "$dropin_file" <<EOF
[Service]
CPUAffinity=${cpus}
CPUWeight=${cpu_weight}
EOF
        changed=true
        info "CPU ${instance_id} (${game_id}) → ${cpus} [poids ${cpu_weight}]"
        if [[ "$restart_running" == "true" ]] && service_active "$service_name"; then
            systemctl restart "$service_name" || warn "Redémarrage impossible : $service_name"
        fi
    done <<< "$plan_output"

    if [[ "$changed" == "true" ]]; then
        systemctl daemon-reload
        ok "Répartition CPU recalculée"
    fi
}
