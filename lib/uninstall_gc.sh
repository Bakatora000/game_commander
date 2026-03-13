# ── lib/uninstall_gc.sh ──────────────────────────────────────────────────────
# Désinstallation / arrêt des instances Game Commander décrites par deploy_config.env

uninstall_gc_remove_nginx() {
    local instance_id="$1" domain="$2" flask_port="$3" url_prefix="$4"
    local nginx_conf="" loc_count has_our_block

    if [[ -f "$GC_NGINX_MANIFEST" ]] && nginx_manifest_check "$instance_id"; then
        if ask_yn "Retirer ${BOLD}${url_prefix:-$instance_id}${RESET} du vhost Nginx (manifest) ?"; then
            nginx_manifest_remove "$instance_id" \
            && nginx_regenerate_locations \
            && nginx_apply \
            || warn "Vérifiez nginx manuellement : nginx -t"
        fi
        return
    fi

    for nf in "/etc/nginx/conf.d/${domain:-___}.conf" \
              "/etc/nginx/sites-enabled/${domain:-___}.conf" \
              "/etc/nginx/sites-available/${domain:-___}.conf"; do
        [[ -f "$nf" ]] && { nginx_conf="$nf"; break; }
    done

    if [[ -z "$nginx_conf" && -n "$flask_port" ]]; then
        nginx_conf=$(grep -rl "127.0.0.1:${flask_port}" \
            /etc/nginx/conf.d/ /etc/nginx/sites-enabled/ 2>/dev/null | head -1 || true)
    fi

    [[ -n "$nginx_conf" && -f "$nginx_conf" ]] || return

    loc_count=$(grep -c '^\s*location ' "$nginx_conf" 2>/dev/null || echo 0)
    has_our_block=$(grep -c "location ${url_prefix:-___}" "$nginx_conf" 2>/dev/null || echo 0)

    if (( loc_count <= 2 && has_our_block > 0 )); then
        if ask_yn "Supprimer vhost Nginx : ${BOLD}$nginx_conf${RESET} (seule instance) ?"; then
            run rm -f "$nginx_conf"
            ok "Vhost Nginx supprimé"
            run nginx -t 2>/dev/null && run systemctl reload nginx || true
        fi
    elif (( has_our_block > 0 )); then
        if ask_yn "Retirer le bloc ${BOLD}${url_prefix}${RESET} du vhost ${BOLD}$nginx_conf${RESET} (partagé) ?"; then
            python3 "$SCRIPT_DIR/tools/nginx_manager.py" remove \
                --conf        "$nginx_conf" \
                --instance-id "$instance_id" \
                --prefix      "$url_prefix" \
            && ok "Bloc ${url_prefix} retiré du vhost" \
            || warn "Échec suppression bloc nginx — vérifiez manuellement"
            run nginx -t 2>/dev/null && run systemctl reload nginx || true
        fi
    else
        warn "Bloc ${url_prefix:-$instance_id} non trouvé dans $nginx_conf — vérifiez manuellement"
    fi
}

uninstall_gc_remove_sudoers() {
    local game_id="$1" instance_id="$2" gc_service="$3"
    local sf

    for sf in "/etc/sudoers.d/game-commander-${game_id}" \
              "/etc/sudoers.d/game-commander-${instance_id}" \
              "/etc/sudoers.d/${gc_service}"; do
        if [[ -f "$sf" ]] && ask_yn "Supprimer sudoers : ${BOLD}$sf${RESET} ?"; then
            run rm -f "$sf"
            ok "Sudoers supprimé"
        fi
    done
}

uninstall_gc_remove_cron() {
    local sys_user="$1" app_dir="$2"
    local cron_count

    [[ -n "$sys_user" && -n "$app_dir" ]] || return

    cron_count=$(crontab -u "$sys_user" -l 2>/dev/null | grep -c "$app_dir" || true)
    if (( cron_count > 0 )) && ask_yn "Supprimer entrée cron backup de $sys_user ?"; then
        run bash -c \
            "crontab -u '$sys_user' -l 2>/dev/null \
             | grep -v '$app_dir' \
             | crontab -u '$sys_user' -"
        ok "Entrée cron supprimée"
    fi
}

uninstall_gc_remove_dirs() {
    local cfg="$1" sys_user="$2" app_dir="$3" server_dir="$4" data_dir="$5" backup_dir="$6"
    local home_dir steamcmd_dir others

    home_dir=$(eval echo "~${sys_user:-root}")

    remove_dir_safe "${app_dir:-}" "répertoire Game Commander" "$cfg"
    remove_dir_safe "${server_dir:-}" "répertoire serveur jeu" "$cfg"
    if [[ -n "${data_dir:-}" && "$data_dir" != "$server_dir" ]]; then
        remove_dir_safe "${data_dir:-}" "répertoire données jeu" "$cfg"
    fi

    steamcmd_dir="$home_dir/steamcmd"
    if [[ -d "$steamcmd_dir" ]]; then
        others=$(shared_by_others "$steamcmd_dir" "$cfg")
        if [[ -n "$others" ]]; then
            info "SteamCMD conservé — utilisé aussi par : $others"
        else
            remove_dir "$steamcmd_dir" "SteamCMD"
        fi
    fi

    if [[ -n "${backup_dir:-}" && -d "${backup_dir:-}" ]]; then
        others=$(shared_by_others "${backup_dir:-}" "$cfg")
        if [[ -n "$others" ]]; then
            info "Sauvegardes conservées — utilisées aussi par : $others"
        else
            remove_dir "$backup_dir" "répertoire sauvegardes"
        fi
    fi
}

uninstall_gc_maybe_remove_wine() {
    local game_id="$1" gc_action="$2"
    local remaining amp_enshrouded

    [[ "$game_id" == "enshrouded" && "$gc_action" == "2" ]] || return

    remaining=$(find /home /opt /root -maxdepth 5 -name "deploy_config.env" 2>/dev/null \
        | xargs grep -l 'GAME_ID="enshrouded"' 2>/dev/null | wc -l)
    amp_enshrouded=$(find /home /root /opt -maxdepth 6 \
        -name "instances.json" -path "*/.ampdata/*" 2>/dev/null \
        | xargs grep -l '"Enshrouded"' 2>/dev/null | wc -l)

    if (( remaining == 0 && amp_enshrouded == 0 )); then
        if ask_yn "Plus aucune instance Enshrouded — désinstaller Wine64/Xvfb ?"; then
            run apt-get remove -y wine64 xvfb 2>/dev/null \
                && ok "Wine64/Xvfb désinstallés" \
                || warn "Désinstallation Wine incomplète"
            run apt-get autoremove -y 2>/dev/null || true
        fi
    else
        (( remaining > 0 )) && \
            info "Wine conservé — $remaining autre(s) instance(s) Enshrouded (Game Commander)"
        (( amp_enshrouded > 0 )) && \
            info "Wine conservé — $amp_enshrouded instance(s) Enshrouded détectée(s) dans AMP"
    fi
}

uninstall_gc_process_entry() {
    local cfg="$1" gc_action="$2"

    unset GAME_ID INSTANCE_ID SYS_USER SERVER_DIR DATA_DIR BACKUP_DIR \
          APP_DIR DOMAIN FLASK_PORT SERVER_NAME URL_PREFIX
    source <(grep -E '^[A-Z_]+=' "$cfg" 2>/dev/null)

    GAME_ID="${GAME_ID:-?}"
    INSTANCE_ID="${INSTANCE_ID:-$GAME_ID}"
    SYS_USER="${SYS_USER:-}"
    GC_SERVICE="game-commander-${INSTANCE_ID}"
    GAME_SERVICE="${GAME_ID}-server-${INSTANCE_ID}"

    echo ""
    hdr "Traitement : $INSTANCE_ID"

    stop_and_disable "$GAME_SERVICE"
    stop_and_disable "$GC_SERVICE"

    if [[ "$gc_action" == "2" ]]; then
        uninstall_gc_remove_nginx "$INSTANCE_ID" "${DOMAIN:-}" "${FLASK_PORT:-}" "${URL_PREFIX:-}"
        uninstall_gc_remove_sudoers "$GAME_ID" "$INSTANCE_ID" "$GC_SERVICE"
        uninstall_gc_remove_cron "${SYS_USER:-}" "${APP_DIR:-}"
        uninstall_gc_remove_dirs "$cfg" "${SYS_USER:-}" "${APP_DIR:-}" "${SERVER_DIR:-}" "${DATA_DIR:-}" "${BACKUP_DIR:-}"
    fi

    ok "Terminé : $INSTANCE_ID"
    uninstall_gc_maybe_remove_wine "$GAME_ID" "$gc_action"
}

uninstall_gc_section() {
    local cfg idx gc_sel gc_action tok
    local -a deploy_configs=() gc_entries=() gc_selected=()

    hdr "A — Recherche installations Game Commander"

    mapfile -t deploy_configs < <(
        find /home /opt /root -maxdepth 5 -name "deploy_config.env" 2>/dev/null \
        | xargs -I{} grep -l "GAME_ID=" {} 2>/dev/null \
        | sort -u
    )

    DEPLOY_CONFIGS=("${deploy_configs[@]}")

    if [[ ${#deploy_configs[@]} -eq 0 ]]; then
        info "Aucune installation Game Commander trouvée."
        return
    fi

    echo ""
    for cfg in "${deploy_configs[@]}"; do
        unset GAME_ID INSTANCE_ID SYS_USER SERVER_DIR DATA_DIR BACKUP_DIR \
              APP_DIR DOMAIN FLASK_PORT SERVER_NAME GC_SERVICE GAME_SERVICE URL_PREFIX
        source <(grep -E '^[A-Z_]+=' "$cfg" 2>/dev/null)

        GAME_ID="${GAME_ID:-?}"
        INSTANCE_ID="${INSTANCE_ID:-$GAME_ID}"
        SYS_USER="${SYS_USER:-?}"
        GC_SERVICE="game-commander-${INSTANCE_ID}"
        GAME_SERVICE="${GAME_ID}-server-${INSTANCE_ID}"
        GC_STATE=$(service_state "$GC_SERVICE")
        GAME_STATE=$(service_state "$GAME_SERVICE")

        idx=${#gc_entries[@]}
        gc_entries+=("$cfg")

        case "$GC_STATE" in
            active) gs="${GREEN}● actif${RESET}"   ;;
            failed) gs="${RED}✗ échoué${RESET}"    ;;
            *)      gs="${DIM}○ inactif${RESET}"   ;;
        esac
        case "$GAME_STATE" in
            active) ss="${GREEN}● actif${RESET}"   ;;
            failed) ss="${RED}✗ échoué${RESET}"    ;;
            *)      ss="${DIM}○ inactif${RESET}"   ;;
        esac

        echo -e "  ${BOLD}[A$((idx+1))]${RESET}  ${BOLD}${INSTANCE_ID}${RESET}  (${GAME_ID^^})"
        echo -e "         Config       : $cfg"
        echo -e "         Serveur jeu  : ${GAME_SERVICE}  →  $ss"
        echo -e "         Game Cmd web : ${GC_SERVICE}    →  $gs"
        [[ -n "${SERVER_NAME:-}" ]] && echo -e "         Nom          : $SERVER_NAME"
        [[ -n "${DOMAIN:-}" ]] && echo -e "         Domaine      : $DOMAIN  (port ${FLASK_PORT:-?})"
        [[ -n "${SYS_USER:-}" ]] && echo -e "         Utilisateur  : $SYS_USER"
        [[ -n "${SERVER_DIR:-}" && -d "${SERVER_DIR:-}" ]] && \
            echo -e "         Dossier jeu  : $SERVER_DIR  $(du -sh "$SERVER_DIR" 2>/dev/null | cut -f1)"
        [[ -n "${DATA_DIR:-}" && -d "${DATA_DIR:-}" && "${DATA_DIR:-}" != "${SERVER_DIR:-}" ]] && \
            echo -e "         Dossier data : $DATA_DIR  $(du -sh "$DATA_DIR" 2>/dev/null | cut -f1)"
        [[ -n "${APP_DIR:-}" && -d "${APP_DIR:-}" ]] && \
            echo -e "         Dossier app  : $APP_DIR  $(du -sh "$APP_DIR" 2>/dev/null | cut -f1)"
        sep
    done

    echo -e "  Entrez les numéros à traiter (ex: ${BOLD}A1 A2${RESET}), ${BOLD}all${RESET} pour tout, ${BOLD}skip${RESET} pour passer :"
    echo -en "  ${YELLOW}?  Sélection : ${RESET}"
    read -r gc_sel

    if [[ "$gc_sel" == "skip" || -z "$gc_sel" ]]; then
        return
    fi

    if [[ "$gc_sel" == "all" ]]; then
        for idx in "${!gc_entries[@]}"; do gc_selected+=("$idx"); done
    else
        for tok in $gc_sel; do
            tok="${tok^^}"
            tok="${tok#A}"
            if [[ "$tok" =~ ^[0-9]+$ ]] && (( tok >= 1 && tok <= ${#gc_entries[@]} )); then
                gc_selected+=($((tok-1)))
            else
                warn "Numéro invalide : $tok — ignoré"
            fi
        done
    fi

    [[ ${#gc_selected[@]} -gt 0 ]] || return

    echo ""
    echo -e "  Que souhaitez-vous faire ?"
    echo -e "    ${BOLD}1${RESET}) Stopper les services (fichiers conservés)"
    echo -e "    ${BOLD}2${RESET}) Désinstaller complètement (services + fichiers)"
    echo -en "  ${YELLOW}?  Choix : ${RESET}"
    read -r gc_action

    for idx in "${gc_selected[@]}"; do
        uninstall_gc_process_entry "${gc_entries[$idx]}" "$gc_action"
    done
}
