# ── lib/uninstall_orphans.sh ────────────────────────────────────────────────
# Détection et arrêt optionnel de processus orphelins hors systemd/AMP

uninstall_orphans_is_systemd_managed() {
    local pid="$1"
    local proc_root="${PROC_ROOT:-/proc}"
    local cgroup_file="${proc_root}/${pid}/cgroup"

    [[ -r "$cgroup_file" ]] || return 1
    grep -qE '\.service($|[^[:alnum:]_])' "$cgroup_file" 2>/dev/null
}

uninstall_orphans_collect() {
    local safe_pids_file="$1" orphan_file="$2"
    local pid user cmd desc wdir app_name binary

    while IFS= read -r psline; do
        pid=$(echo "$psline" | awk '{print $1}')
        user=$(echo "$psline" | awk '{print $2}')
        cmd=$(echo "$psline" | awk '{for(i=3;i<=NF;i++) printf $i" "; print ""}' | xargs)
        [[ "$pid" =~ ^[0-9]+$ ]] || continue
        (( pid > 1 )) || continue
        [[ "$pid" != "$$" ]] || continue
        echo "$cmd" | grep -qE 'game_commander|uninstall_flask|grep' && continue
        grep -qxF "$pid" "$safe_pids_file" 2>/dev/null && continue
        uninstall_orphans_is_systemd_managed "$pid" && continue
        uninstall_orphans_is_amp_process "$pid" && continue

        desc=""
        if echo "$cmd" | grep -qiE 'python[0-9.]*.*(app|wsgi|main)\.py|gunicorn|uvicorn'; then
            wdir=$(readlink -f "/proc/${pid}/cwd" 2>/dev/null || echo "")
            app_name=""
            if [[ -n "$wdir" && -f "$wdir/game.json" ]]; then
                app_name=$(python3 -c \
                    "import json; d=json.load(open('$wdir/game.json')); print(d.get('name','?')+' — '+d.get('subtitle',''))" \
                    2>/dev/null || true)
            fi
            desc="Flask/Python"
            [[ -n "$app_name" ]] && desc="$desc ($app_name)"
            [[ -n "$wdir" ]] && desc="$desc  [${wdir}]"
        elif echo "$cmd" | grep -qiP 'valheim_server\.x86_64|enshrouded_server|bedrock_server|(?<!\w)java(?!\w).*nogui'; then
            binary=$(echo "$cmd" | grep -oP 'valheim_server\.x86_64|enshrouded_server|bedrock_server|java' | head -1)
            desc="Serveur de jeu ($binary)"
        else
            continue
        fi

        echo "${pid}|${user}|${desc}|$(echo "$cmd" | cut -c1-80)" >> "$orphan_file"
    done < <(ps -eo pid,user,cmd --no-headers 2>/dev/null | grep -v ' Z ')
}

uninstall_orphans_is_amp_process() {
    local pid="$1" cur="$1" depth=0 cmdline

    while [[ "$cur" =~ ^[0-9]+$ ]] && (( cur > 1 && depth < 8 )); do
        [[ -r "/proc/${cur}/cmdline" ]] || return 1
        cmdline=$(tr '\0' ' ' < "/proc/${cur}/cmdline" 2>/dev/null) || true
        echo "$cmdline" | grep -qiE 'ampdata|cubecoders|ampinstmgr' && return 0
        [[ -r "/proc/${cur}/stat" ]] || return 1
        cur=$(awk '{print $4}' "/proc/${cur}/stat" 2>/dev/null) || cur=1
        (( depth++ ))
    done
    return 1
}

uninstall_orphans_section() {
    local safe_pids_file orphan_file orphan_count kill_sel sig_choice kill_sig tok idx pid desc
    local -a o_pids=() o_users=() o_descs=() o_cmds=() kill_idx=()

    hdr "C — Processus orphelins en mémoire"

    safe_pids_file=$(mktemp)
    orphan_file=$(mktemp)

    systemctl show $(systemctl list-units --type=service --no-legend 2>/dev/null | awk '{print $1}') -p MainPID 2>/dev/null \
        | grep -v '=0$' | grep -oP '(?<=)\d+' > "$safe_pids_file" || true

    uninstall_orphans_collect "$safe_pids_file" "$orphan_file"
    rm -f "$safe_pids_file"

    orphan_count=$(wc -l < "$orphan_file" 2>/dev/null || echo 0)
    if (( orphan_count == 0 )); then
        ok "Aucun processus orphelin détecté."
        rm -f "$orphan_file"
        return
    fi

    echo ""
    warn "${orphan_count} processus orphelin(s) trouvé(s) :"
    echo ""

    while IFS='|' read -r pid user desc cmd; do
        o_pids+=("$pid")
        o_users+=("$user")
        o_descs+=("$desc")
        o_cmds+=("$cmd")
    done < "$orphan_file"
    rm -f "$orphan_file"

    for idx in "${!o_pids[@]}"; do
        echo -e "  ${BOLD}[C$((idx+1))]${RESET}  PID ${BOLD}${o_pids[$idx]}${RESET}  — ${o_descs[$idx]}"
        echo -e "         Utilisateur : ${o_users[$idx]}"
        echo -e "         Commande    : ${DIM}${o_cmds[$idx]}${RESET}"
        sep
    done

    echo -e "  Numéros à terminer (ex: ${BOLD}C1 C2${RESET}), ${BOLD}all${RESET} pour tout, ${BOLD}skip${RESET} pour passer :"
    echo -en "  ${YELLOW}?  Sélection : ${RESET}"
    read -r kill_sel

    if [[ "$kill_sel" == "skip" || -z "$kill_sel" ]]; then
        return
    fi

    if [[ "$kill_sel" == "all" ]]; then
        for idx in "${!o_pids[@]}"; do kill_idx+=("$idx"); done
    else
        for tok in $kill_sel; do
            tok="${tok^^}"
            tok="${tok#C}"
            if [[ "$tok" =~ ^[0-9]+$ ]] && (( tok >= 1 && tok <= ${#o_pids[@]} )); then
                kill_idx+=($((tok-1)))
            else
                warn "Numéro invalide : $tok — ignoré"
            fi
        done
    fi

    (( ${#kill_idx[@]} > 0 )) || return

    echo ""
    echo -e "  Signal :"
    echo -e "    ${BOLD}1${RESET}) SIGTERM  — arrêt propre (recommandé)"
    echo -e "    ${BOLD}2${RESET}) SIGKILL  — arrêt forcé"
    echo -en "  ${YELLOW}?  Choix : ${RESET}"
    read -r sig_choice
    kill_sig="-15"
    [[ "${sig_choice:-1}" == "2" ]] && kill_sig="-9"

    for idx in "${kill_idx[@]}"; do
        pid="${o_pids[$idx]}"
        desc="${o_descs[$idx]}"
        if ! kill -0 "$pid" 2>/dev/null; then
            warn "PID $pid déjà terminé"
            continue
        fi
        info "Envoi signal $kill_sig → PID $pid ($desc)..."
        run kill "$kill_sig" "$pid" || true
        if ! $DRY_RUN; then
            sleep 2
            if kill -0 "$pid" 2>/dev/null; then
                warn "PID $pid toujours actif — kill -9 $pid pour forcer"
            else
                ok "PID $pid terminé"
            fi
        fi
    done
}
