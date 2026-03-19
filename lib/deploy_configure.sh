# ── lib/deploy_configure.sh ──────────────────────────────────────────────────
# Étape 2 interactive / config du déploiement

deploy_warn_port_group_conflicts() {
    local line label proto port owner proto_label
    while IFS='|' read -r label proto port owner; do
        [[ -n "$label" ]] || continue
        proto_label="UDP"
        [[ "$proto" == "t" ]] && proto_label="TCP"
        warn "${label} ${port}/${proto_label} déjà utilisé par : ${owner}"
    done < <(
        python3 "$SCRIPT_DIR/shared/deployplan.py" describe-conflicts \
            --game-id "$GAME_ID" \
            --server-port "${SERVER_PORT:-0}" \
            --query-port "${QUERY_PORT:-0}" \
            --echo-port "${ECHO_PORT:-0}" \
            --game-service "$GAME_SERVICE"
    )
}

deploy_select_game() {
    echo ""
    if [[ -z "$GAME_ID" ]]; then
        if [[ "$DEPLOY_MODE" == "attach" ]]; then
            echo -e "  ${BOLD}Jeu du serveur existant :${RESET}"
        else
            echo -e "  ${BOLD}Jeu à déployer :${RESET}"
        fi
        while IFS='|' read -r key label; do
            echo -e "  ${CYAN}[${key}]${RESET} ${label}"
        done < <(python3 "$SCRIPT_DIR/shared/deployplan.py" game-menu)
        echo ""
        prompt "Votre choix" "1"
        source <(python3 "$SCRIPT_DIR/shared/deployplan.py" game-choice --choice "$REPLY" --default-game-id "valheim")
        [[ "$GAME_ACCEPTED" == "true" ]] || return 10
    else
        echo -e "  ${DIM}  (config) Jeu : ${BOLD}${GAME_ID}${RESET}"
    fi

    set_game_defaults

    source <(python3 "$SCRIPT_DIR/shared/deployplan.py" game-meta --game-id "$GAME_ID")
    ok "Jeu sélectionné : ${BOLD}${GAME_LABEL}${RESET}"
}

deploy_configure_mode() {
    echo ""
    info "Mode de déploiement"
    if $CONFIG_MODE; then
        echo -e "  ${DIM}  (config) Mode : ${BOLD}${DEPLOY_MODE}${RESET}"
    else
        echo -e "  ${DIM}  (menu) Mode : ${BOLD}${DEPLOY_MODE}${RESET}"
    fi
    ok "Mode sélectionné : ${BOLD}${DEPLOY_MODE}${RESET}"
}

deploy_configure_user() {
    echo ""
    info "Utilisateur système"
    prompt "Nom d'utilisateur" "${SYS_USER}"
    SYS_USER="$REPLY"

    if ! id "$SYS_USER" &>/dev/null; then
        warn "L'utilisateur '$SYS_USER' n'existe pas."
        if confirm "Créer $SYS_USER ?" "o"; then
            useradd -m -s /bin/bash "$SYS_USER"
            ok "Utilisateur $SYS_USER créé"
            if ! $CONFIG_MODE; then
                prompt_secret "Mot de passe système pour $SYS_USER"
                echo "$SYS_USER:$REPLY" | chpasswd && ok "Mot de passe défini"
            fi
        else
            die "Utilisateur requis."
        fi
    fi

    HOME_DIR=$(eval echo "~$SYS_USER")
    ok "Utilisateur : $SYS_USER ($HOME_DIR)"
}

deploy_prepare_instance_defaults() {
    source <(
        python3 "$SCRIPT_DIR/shared/deployplan.py" instance-defaults \
            --game-id "$GAME_ID" \
            --instance-id "$INSTANCE_ID" \
            --home-dir "$HOME_DIR" \
            --src-dir "$SCRIPT_DIR" \
            --server-dir "$SERVER_DIR" \
            --data-dir "$DATA_DIR" \
            --backup-dir "$BACKUP_DIR" \
            --app-dir "$APP_DIR" \
            --game-service "$GAME_SERVICE"
    )
}

deploy_configure_paths() {
    local prev_instance prev_server_dir prev_data_dir prev_app_dir prev_game_service

    echo ""
    info "Instance"
    prev_instance="$INSTANCE_ID"
    prev_server_dir="$SERVER_DIR"
    prev_data_dir="$DATA_DIR"
    prev_app_dir="$APP_DIR"
    prev_game_service="$GAME_SERVICE"
    prompt "Identifiant d'instance (unique par serveur)" "${INSTANCE_ID}"
    INSTANCE_ID="$REPLY"
    source <(
        python3 "$SCRIPT_DIR/shared/deployplan.py" update-instance-paths \
            --game-id "$GAME_ID" \
            --instance-id "$INSTANCE_ID" \
            --home-dir "$HOME_DIR" \
            --server-dir "$SERVER_DIR" \
            --data-dir "$DATA_DIR" \
            --app-dir "$APP_DIR" \
            --game-service "$GAME_SERVICE" \
            --prev-instance "$prev_instance" \
            --prev-server-dir "$prev_server_dir" \
            --prev-data-dir "$prev_data_dir" \
            --prev-app-dir "$prev_app_dir" \
            --prev-game-service "$prev_game_service"
    )

    info "Chemins"
    prompt "Répertoire serveur $GAME_LABEL" "${SERVER_DIR}"
    SERVER_DIR="$REPLY"
    [[ "$GAME_ID" != "enshrouded" ]] && {
        prompt "Répertoire données de jeu" "${DATA_DIR}"
        DATA_DIR="$REPLY"
    } || DATA_DIR="$SERVER_DIR"
    prompt "Répertoire sauvegardes" "${BACKUP_DIR}"
    BACKUP_DIR="$REPLY"
    prompt "Répertoire Game Commander" "${APP_DIR}"
    APP_DIR="$REPLY"
    prompt "Dossier source Game Commander (racine du projet)" "${SRC_DIR}"
    SRC_DIR="$REPLY"

    if ! deploy_has_runtime_sources "$SRC_DIR"; then
        warn "runtime/app.py introuvable dans $SRC_DIR — Game Commander ne sera pas déployé"
        DEPLOY_APP=false
    else
        DEPLOY_APP=true
        ok "Sources Game Commander trouvées"
    fi

    if [[ "$DEPLOY_MODE" == "attach" ]]; then
        prompt "Nom du service systemd existant" "${GAME_SERVICE}"
        GAME_SERVICE="$REPLY"
        systemctl list-unit-files "${GAME_SERVICE}.service" 2>/dev/null | grep -qv "not-found" \
            && ok "Service existant détecté : $GAME_SERVICE" \
            || warn "Service systemd non détecté : $GAME_SERVICE"
    fi
}

deploy_configure_server() {
    local other_valheim nginx_conf_for_domain existing_owner conflict spec proto label port

    echo ""
    info "Configuration du serveur $GAME_LABEL"
    prompt "Nom du serveur" "${SERVER_NAME}"
    SERVER_NAME="$REPLY"
    prompt_secret "Mot de passe (vide = public)" "${SERVER_PASSWORD}"
    SERVER_PASSWORD="$REPLY"

    if [[ "$DEPLOY_MODE" != "attach" ]]; then
        source <(
            python3 "$SCRIPT_DIR/shared/deployplan.py" suggest-ports \
                --game-id "$GAME_ID" \
                --server-port "${SERVER_PORT:-0}" \
                --query-port "${QUERY_PORT:-0}" \
                --echo-port "${ECHO_PORT:-0}" \
                --game-service "$GAME_SERVICE"
        )
        if [[ -n "${CONFLICT_LABEL:-}" ]]; then
            warn "${CONFLICT_LABEL} ${CONFLICT_PORT}/$([[ "$CONFLICT_PROTO" == "t" ]] && echo TCP || echo UDP) déjà utilisé — groupe de ports suggéré mis à jour"
        fi
    fi

    prompt "Port principal" "${SERVER_PORT}"
    SERVER_PORT="$REPLY"
    if [[ "$GAME_ID" == "soulmask" || "$GAME_ID" == "satisfactory" ]]; then
        prompt "$([[ "$GAME_ID" == "satisfactory" ]] && echo 'Port fiable / join' || echo 'Port Query')" "${QUERY_PORT}"
        QUERY_PORT="$REPLY"
        if [[ "$GAME_ID" == "soulmask" ]]; then
            prompt "Port Echo" "${ECHO_PORT}"
            ECHO_PORT="$REPLY"
        fi
    fi
    [[ "$DEPLOY_MODE" != "attach" ]] && deploy_warn_port_group_conflicts
    prompt "Joueurs max" "${MAX_PLAYERS}"
    MAX_PLAYERS="$REPLY"

    GC_FORCE_PLAYFAB=false
    if [[ "$GAME_ID" == "valheim" ]]; then
        prompt "Nom du monde" "${WORLD_NAME}"
        WORLD_NAME="$REPLY"
        if $CONFIG_MODE; then
            echo -e "  ${DIM}  (config) Crossplay : ${BOLD}$($CROSSPLAY && echo "Oui" || echo "Non")${RESET}"
            echo -e "  ${DIM}  (config) BepInEx   : ${BOLD}$($BEPINEX && echo "Oui" || echo "Non")${RESET}"
        else
            confirm "Activer le crossplay ?" "n" && CROSSPLAY=true || CROSSPLAY=false
            confirm "Installer BepInEx (mods) ?" "o" && BEPINEX=true || BEPINEX=false
        fi
        if $CROSSPLAY; then
            source <(python3 "$SCRIPT_DIR/shared/deployplan.py" valheim-playfab --crossplay true)
            other_valheim="${OTHER_VALHEIM:-}"
            if [[ -n "${GC_FORCE_PLAYFAB:-}" && "$GC_FORCE_PLAYFAB" == "true" ]]; then
                warn "Une autre instance Valheim est déjà en cours d'exécution"
                warn "  $other_valheim"
                warn "Le flag -crossplay sera remplacé par -playfab (multi-instance PlayFab)."
            fi
        fi
    elif [[ "$GAME_ID" == "soulmask" ]]; then
        if $CONFIG_MODE; then
            echo -e "  ${DIM}  (config) Mode serveur : ${BOLD}${SERVER_MODE}${RESET}"
            echo -e "  ${DIM}  (config) Backups auto : ${BOLD}${BACKUP_ENABLED}${RESET}"
            echo -e "  ${DIM}  (config) Sauvegardes  : ${BOLD}${SAVING_ENABLED}${RESET}"
            echo -e "  ${DIM}  (config) Backup intervalle : ${BOLD}${BACKUP_INTERVAL}${RESET}"
        else
            SERVER_MODE="pve"
            confirm "Activer les backups Soulmask ?" "o" && BACKUP_ENABLED=true || BACKUP_ENABLED=false
            confirm "Activer les sauvegardes périodiques ?" "o" && SAVING_ENABLED=true || SAVING_ENABLED=false
        fi
        prompt "Intervalle backup (secondes)" "${BACKUP_INTERVAL}"
        BACKUP_INTERVAL="$REPLY"
    fi

    echo ""
    info "Interface web Game Commander"
    prompt "Domaine" "${DOMAIN}"
    DOMAIN="$REPLY"
    prompt "Préfixe URL" "${URL_PREFIX}"
    URL_PREFIX="${REPLY%/}"

    source <(
        python3 "$SCRIPT_DIR/shared/deployplan.py" web-defaults \
            --domain "$DOMAIN" \
            --url-prefix "$URL_PREFIX" \
            --flask-port "${FLASK_PORT:-0}"
    )
    if [[ -n "$EXISTING_OWNER" ]]; then
        warn "Le préfixe '${URL_PREFIX}' est déjà utilisé sur ${DOMAIN}"
        warn "  → proxy_pass existant : http://127.0.0.1:${EXISTING_OWNER}"
        echo ""
        echo -e "  Suggestions : ${BOLD}/commander${RESET}  /gc  /gameadmin  /${GAME_ID}"
        echo ""
        prompt "Nouveau préfixe URL" "/${GAME_ID}"
        URL_PREFIX="${REPLY%/}"
    fi

    prompt "Port Flask interne" "${FLASK_PORT}"
    FLASK_PORT="$REPLY"

    if $CONFIG_MODE; then
        echo -e "  ${DIM}  (config) SSL : ${BOLD}${SSL_MODE}${RESET}"
    else
        echo -e "  ${BOLD}SSL :${RESET}"
        echo -e "  ${CYAN}[0]${RESET} Quit"
        echo -e "  ${CYAN}[1]${RESET} Certbot (Let's Encrypt)"
        echo -e "  ${CYAN}[2]${RESET} HTTP uniquement"
        echo -e "  ${CYAN}[3]${RESET} SSL déjà configuré"
        prompt "Configuration SSL" "3"
        source <(python3 "$SCRIPT_DIR/shared/deployplan.py" ssl-mode --choice "$REPLY")
        [[ "$SSL_ACCEPTED" == "true" ]] || return 10
    fi
}

deploy_configure_admin() {
    echo ""
    info "Compte administrateur Game Commander"
    prompt "Identifiant admin" "${ADMIN_LOGIN}"
    ADMIN_LOGIN="$REPLY"
    if [[ -z "$ADMIN_PASSWORD" ]]; then
        prompt_secret "Mot de passe pour $ADMIN_LOGIN"
        ADMIN_PASSWORD="$REPLY"
    fi
    source <(python3 "$SCRIPT_DIR/shared/deployplan.py" validate-admin --password "$ADMIN_PASSWORD")
    [[ "$ADMIN_PASSWORD_OK" == "true" ]] || die "Mot de passe admin obligatoire."
}

deploy_print_summary() {
    hdr "RÉCAPITULATIF"
    echo ""
    while IFS= read -r line; do
        [[ -n "$line" ]] || continue
        local label="${line%%:*}"
        local value="${line#*: }"
        echo -e "  ${BOLD}${label}:${RESET} ${value}"
    done < <(
        python3 "$SCRIPT_DIR/shared/deployplan.py" summary \
            --game-id "$GAME_ID" \
            --game-label "$GAME_LABEL" \
            --deploy-mode "$DEPLOY_MODE" \
            --sys-user "$SYS_USER" \
            --home-dir "$HOME_DIR" \
            --server-dir "$SERVER_DIR" \
            --data-dir "$DATA_DIR" \
            --server-name "$SERVER_NAME" \
            --server-port "$SERVER_PORT" \
            --query-port "${QUERY_PORT:-}" \
            --echo-port "${ECHO_PORT:-}" \
            --server-mode "${SERVER_MODE:-}" \
            --max-players "$MAX_PLAYERS" \
            --world-name "${WORLD_NAME:-}" \
            --crossplay "$([[ "${CROSSPLAY:-false}" == "true" ]] && echo true || echo false)" \
            --bepinex "$([[ "${BEPINEX:-false}" == "true" ]] && echo true || echo false)" \
            --backup-dir "$BACKUP_DIR" \
            --game-service "$GAME_SERVICE" \
            --app-dir "$APP_DIR" \
            --domain "$DOMAIN" \
            --url-prefix "$URL_PREFIX" \
            --flask-port "$FLASK_PORT" \
            --ssl-mode "$SSL_MODE" \
            --admin-login "$ADMIN_LOGIN"
    )
    echo ""
    sep
}

deploy_step_configuration() {
    hdr "ÉTAPE 2 : Configuration"
    deploy_select_game || return $?
    deploy_configure_mode || return $?
    deploy_configure_user || return $?
    deploy_prepare_instance_defaults || return $?
    deploy_configure_paths || return $?
    deploy_configure_server || return $?
    deploy_configure_admin || return $?
    deploy_print_summary

    $AUTO_CONFIRM \
        && ok "Confirmation automatique (AUTO_CONFIRM=true)" \
        || { confirm "Lancer l'installation ?" "o" || die "Annulé."; }
}
