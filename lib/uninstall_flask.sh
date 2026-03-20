# ── lib/uninstall_flask.sh ───────────────────────────────────────────────────
# Désinstallation / arrêt des applications Flask génériques hors Game Commander

uninstall_flask_remove_nginx_block() {
    local nginx="$1" port="$2"
    local loc_count has_port

    [[ -n "$nginx" && -f "$nginx" ]] || return

    loc_count=$(grep -c '^\s*location ' "$nginx" 2>/dev/null || echo 0)
    has_port=$(grep -c "127.0.0.1:${port}" "$nginx" 2>/dev/null || echo 0)

    if (( loc_count <= 2 && has_port > 0 )); then
        ask_yn "Supprimer vhost Nginx : ${BOLD}$nginx${RESET} (seule instance) ?" && {
            run rm -f "$nginx"
            ok "Vhost supprimé"
            run nginx -t 2>/dev/null && run systemctl reload nginx || true
        }
    elif (( has_port > 0 )); then
        ask_yn "Retirer le bloc port ${port} du vhost ${BOLD}$nginx${RESET} (partagé) ?" && {
            cp "$nginx" "${nginx}.bak.$(date +%Y%m%d%H%M%S)"
            python3 "$SCRIPT_DIR/shared/deploynginx.py" remove-legacy-block \
                --nginx-file "$nginx" --port "$port"
            ok "Bloc port ${port} retiré"
            run nginx -t 2>/dev/null && run systemctl reload nginx || true
        }
    fi
}

uninstall_flask_remove_sudoers() {
    local work="$1" svc="$2" sf

    for sf in /etc/sudoers.d/*; do
        [[ -f "$sf" ]] || continue
        grep -q "$work\|$svc" "$sf" 2>/dev/null || continue
        ask_yn "Supprimer sudoers : ${BOLD}$sf${RESET} ?" && {
            run rm -f "$sf"
            ok "Sudoers supprimé"
        }
    done
}

uninstall_flask_process_entry() {
    local svc="$1" work="$2" nginx="$3" port="$4" fl_action="$5"

    echo ""
    hdr "Traitement : $svc"
    stop_and_disable "$svc"

    if [[ "$fl_action" == "2" ]]; then
        uninstall_flask_remove_nginx_block "$nginx" "$port"
        uninstall_flask_remove_sudoers "$work" "$svc"
        remove_dir "$work" "répertoire application"
    fi

    ok "Terminé : $svc"
}

uninstall_flask_section() {
    local cfg svc unit_file exec_line work_dir already is_flask state svc_user port nginx_file
    local fl_sel fl_action tok idx
    local -a already_handled=() fl_names=() fl_states=() fl_work_dirs=() fl_users=() fl_ports=() fl_nginx=() fl_selected=()

    hdr "B — Recherche applications Flask génériques (systemd)"

    for cfg in "${DEPLOY_CONFIGS[@]:-}"; do
        [[ -z "$cfg" ]] && continue
        work_dir=$(grep '^APP_DIR=' "$cfg" 2>/dev/null | cut -d= -f2- | tr -d '"')
        [[ -n "$work_dir" ]] && already_handled+=("$work_dir")
    done

    while IFS= read -r svc; do
        unit_file="/etc/systemd/system/${svc}"
        [[ ! -f "$unit_file" ]] && unit_file="/lib/systemd/system/${svc}"
        [[ -f "$unit_file" ]] || continue

        exec_line=$(grep -i '^ExecStart=' "$unit_file" 2>/dev/null | head -1)
        echo "$exec_line" | grep -qiE 'python|gunicorn|uvicorn|flask' || continue

        work_dir=$(grep '^WorkingDirectory=' "$unit_file" 2>/dev/null | head -1 | cut -d= -f2-)
        [[ -n "$work_dir" ]] || continue

        already=false
        for handled in "${already_handled[@]:-}"; do
            [[ "$handled" == "$work_dir" ]] && already=true && break
        done
        $already && continue

        is_flask=false
        [[ -f "$work_dir/app.py" ]] && is_flask=true
        [[ -f "$work_dir/wsgi.py" ]] && is_flask=true
        grep -qiE 'flask|gunicorn' "$work_dir/requirements.txt" 2>/dev/null && is_flask=true
        $is_flask || continue

        state=$(systemctl is-active "${svc%.service}" 2>/dev/null || echo "inactive")
        svc_user=$(grep '^User=' "$unit_file" 2>/dev/null | head -1 | cut -d= -f2-)
        [[ -n "$svc_user" ]] || svc_user="root"

        port=""
        [[ -f "$work_dir/game.json" ]] && \
            port=$(python3 "$SCRIPT_DIR/shared/appfiles.py" read-game-json \
                --path "$work_dir/game.json" --field flask-port 2>/dev/null || true)
        [[ -n "$port" ]] || port=$(grep -oP '(?<=port=)\d+' "$work_dir/app.py" 2>/dev/null | tail -1 || true)
        [[ -n "$port" ]] || port="?"

        nginx_file=""
        [[ "$port" != "?" ]] && \
            nginx_file=$(grep -rl "127.0.0.1:${port}" \
                /etc/nginx/conf.d/ /etc/nginx/sites-enabled/ 2>/dev/null | head -1 || true)

        fl_names+=("${svc%.service}")
        fl_states+=("$state")
        fl_work_dirs+=("$work_dir")
        fl_users+=("$svc_user")
        fl_ports+=("$port")
        fl_nginx+=("$nginx_file")
    done < <(systemctl list-unit-files --type=service --no-legend 2>/dev/null | awk '{print $1}' | grep -v '@')

    if [[ ${#fl_names[@]} -eq 0 ]]; then
        info "Aucune application Flask générique trouvée."
        return
    fi

    echo ""
    for idx in "${!fl_names[@]}"; do
        case "${fl_states[$idx]}" in
            active) st="${GREEN}● actif${RESET}"   ;;
            failed) st="${RED}✗ échoué${RESET}"    ;;
            *)      st="${DIM}○ inactif${RESET}"   ;;
        esac
        echo -e "  ${BOLD}[B$((idx+1))]${RESET}  ${fl_names[$idx]}"
        echo -e "         État       : $st"
        echo -e "         Répertoire : ${fl_work_dirs[$idx]}  $(du -sh "${fl_work_dirs[$idx]}" 2>/dev/null | cut -f1)"
        echo -e "         Utilisateur: ${fl_users[$idx]}"
        echo -e "         Port       : ${fl_ports[$idx]}"
        [[ -n "${fl_nginx[$idx]}" ]] && echo -e "         Nginx      : ${fl_nginx[$idx]}"
        sep
    done

    echo -e "  Entrez les numéros à traiter (ex: ${BOLD}B1 B2${RESET}), ${BOLD}all${RESET} pour tout, ${BOLD}skip${RESET} pour passer :"
    echo -en "  ${YELLOW}?  Sélection : ${RESET}"
    gc_read fl_sel

    if [[ "$fl_sel" == "skip" || -z "$fl_sel" ]]; then
        return
    fi

    if [[ "$fl_sel" == "all" ]]; then
        for idx in "${!fl_names[@]}"; do fl_selected+=("$idx"); done
    else
        for tok in $fl_sel; do
            tok="${tok^^}"
            tok="${tok#B}"
            if [[ "$tok" =~ ^[0-9]+$ ]] && (( tok >= 1 && tok <= ${#fl_names[@]} )); then
                fl_selected+=($((tok-1)))
            else
                warn "Numéro invalide : $tok — ignoré"
            fi
        done
    fi

    [[ ${#fl_selected[@]} -gt 0 ]] || return

    echo ""
    echo -e "  Que souhaitez-vous faire ?"
    echo -e "    ${BOLD}1${RESET}) Stopper uniquement"
    echo -e "    ${BOLD}2${RESET}) Désinstaller complètement"
    echo -en "  ${YELLOW}?  Choix : ${RESET}"
    gc_read fl_action

    for idx in "${fl_selected[@]}"; do
        uninstall_flask_process_entry \
            "${fl_names[$idx]}" \
            "${fl_work_dirs[$idx]}" \
            "${fl_nginx[$idx]}" \
            "${fl_ports[$idx]}" \
            "$fl_action"
    done
}
