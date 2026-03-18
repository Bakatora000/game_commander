# ── lib/deploy_configure.sh ──────────────────────────────────────────────────
# Étape 2 interactive / config du déploiement

deploy_check_port_conflict() {
    local port="$1" proto="${2:-u}"
    local line pid ignored_pid
    ignored_pid="$(deploy_current_service_pid)"
    while IFS= read -r line; do
        [[ "$line" == *":${port} "* ]] || continue
        if [[ -n "$ignored_pid" ]]; then
            pid="$(printf '%s\n' "$line" | grep -oP 'pid=\K\d+' | head -1)"
            [[ -n "$pid" && "$pid" == "$ignored_pid" ]] && continue
        fi
        return 0
    done < <(ss -${proto}lnpH 2>/dev/null)
    while IFS= read -r line; do
        [[ "$line" == *":${port} "* ]] || continue
        return 0
    done < <(ss -${proto}lnH 2>/dev/null)
    return 1
}

deploy_current_service_pid() {
    [[ -z "${GAME_SERVICE:-}" ]] && return 0
    systemctl show "$GAME_SERVICE" --property MainPID --value 2>/dev/null | head -1
}

deploy_game_port_proto() {
    case "${GAME_ID:-}" in
        minecraft|minecraft-fabric|terraria|satisfactory) printf 't\n' ;;
        *) printf 'u\n' ;;
    esac
}

deploy_port_owner() {
    local port="$1" pid cmd
    pid=$(ss -ulnpH 2>/dev/null | grep ":${port} " | grep -oP 'pid=\K\d+' | head -1)
    [[ -z "$pid" ]] && pid=$(ss -tlnpH 2>/dev/null | grep ":${port} " | grep -oP 'pid=\K\d+' | head -1)
    if [[ -n "$pid" ]]; then
        cmd=$(ps -p "$pid" -o comm= 2>/dev/null)
        echo "PID $pid ($cmd)"
    else
        echo "processus inconnu"
    fi
}

deploy_next_free_flask_port() {
    local port="$1"
    while ss -tlnH "sport = :$port" 2>/dev/null | grep -q ":$port"; do
        port=$((port + 1))
    done
    echo "$port"
}

deploy_port_group_step() {
    case "${GAME_ID:-}" in
        valheim|enshrouded) printf '2\n' ;;
        *) printf '1\n' ;;
    esac
}

deploy_port_group_specs() {
    case "${GAME_ID:-}" in
        minecraft|minecraft-fabric)
            printf 'SERVER_PORT|t|Port principal\n'
            ;;
        terraria)
            printf 'SERVER_PORT|t|Port principal\n'
            ;;
        satisfactory)
            printf 'SERVER_PORT|t|Port de jeu (TCP)\n'
            printf 'SERVER_PORT|u|Port de jeu (UDP)\n'
            printf 'QUERY_PORT|t|Port fiable / join\n'
            ;;
        soulmask)
            printf 'SERVER_PORT|u|Port de jeu\n'
            printf 'QUERY_PORT|u|Port requête\n'
            printf 'ECHO_PORT|t|Port Echo\n'
            ;;
        valheim)
            printf 'SERVER_PORT|u|Port principal\n'
            printf 'SERVER_PORT_PLUS1|u|Port query\n'
            ;;
        enshrouded)
            printf 'SERVER_PORT|u|Port principal\n'
            printf 'SERVER_PORT_PLUS1|u|Port requête\n'
            ;;
    esac
}

deploy_port_value() {
    local spec="$1"
    case "$spec" in
        SERVER_PORT) printf '%s\n' "${SERVER_PORT:-}" ;;
        QUERY_PORT) printf '%s\n' "${QUERY_PORT:-}" ;;
        ECHO_PORT) printf '%s\n' "${ECHO_PORT:-}" ;;
        SERVER_PORT_PLUS1) printf '%s\n' "$((SERVER_PORT + 1))" ;;
        *) printf '0\n' ;;
    esac
}

deploy_shift_port_group() {
    local step="$1"
    SERVER_PORT=$((SERVER_PORT + step))
    [[ -n "${QUERY_PORT:-}" ]] && QUERY_PORT=$((QUERY_PORT + step))
    [[ -n "${ECHO_PORT:-}" ]] && ECHO_PORT=$((ECHO_PORT + step))
}

deploy_first_port_group_conflict() {
    local line spec proto label port
    while IFS='|' read -r spec proto label; do
        [[ -n "$spec" ]] || continue
        port="$(deploy_port_value "$spec")"
        if deploy_check_port_conflict "$port" "$proto"; then
            printf '%s|%s|%s|%s\n' "$spec" "$proto" "$label" "$port"
            return 0
        fi
    done < <(deploy_port_group_specs)
    return 1
}

deploy_suggest_port_group() {
    local step
    step="$(deploy_port_group_step)"
    while deploy_first_port_group_conflict >/dev/null; do
        deploy_shift_port_group "$step"
    done
}

deploy_warn_port_group_conflicts() {
    local line spec proto label port
    while IFS='|' read -r spec proto label; do
        [[ -n "$spec" ]] || continue
        port="$(deploy_port_value "$spec")"
        if deploy_check_port_conflict "$port" "$proto"; then
            local proto_label="UDP"
            [[ "$proto" == "t" ]] && proto_label="TCP"
            warn "${label} ${port}/${proto_label} déjà utilisé par : $(deploy_port_owner "$port")"
        fi
    done < <(deploy_port_group_specs)
}

deploy_select_game() {
    echo ""
    if [[ -z "$GAME_ID" ]]; then
        if [[ "$DEPLOY_MODE" == "attach" ]]; then
            echo -e "  ${BOLD}Jeu du serveur existant :${RESET}"
        else
            echo -e "  ${BOLD}Jeu à déployer :${RESET}"
        fi
        echo -e "  ${CYAN}[0]${RESET} Quit"
        echo -e "  ${CYAN}[1]${RESET} Valheim"
        echo -e "  ${CYAN}[2]${RESET} Enshrouded"
        echo -e "  ${CYAN}[3]${RESET} Minecraft Java"
        echo -e "  ${CYAN}[4]${RESET} Minecraft Fabric"
        echo -e "  ${CYAN}[5]${RESET} Terraria"
        echo -e "  ${CYAN}[6]${RESET} Soulmask"
        echo -e "  ${CYAN}[7]${RESET} Satisfactory"
        echo ""
        prompt "Votre choix" "1"
        case "$REPLY" in
            0) return 10 ;;
            2) GAME_ID="enshrouded" ;;
            3) GAME_ID="minecraft" ;;
            4) GAME_ID="minecraft-fabric" ;;
            5) GAME_ID="terraria" ;;
            6) GAME_ID="soulmask" ;;
            7) GAME_ID="satisfactory" ;;
            *) GAME_ID="valheim" ;;
        esac
    else
        echo -e "  ${DIM}  (config) Jeu : ${BOLD}${GAME_ID}${RESET}"
    fi

    set_game_defaults

    case "$GAME_ID" in
        valheim)    GAME_LABEL="Valheim";    STEAM_APPID="896660";  GAME_BINARY="valheim_server.x86_64" ;;
        enshrouded) GAME_LABEL="Enshrouded"; STEAM_APPID="2278520"; GAME_BINARY="enshrouded_server.exe" ;;
        minecraft)  GAME_LABEL="Minecraft Java";  STEAM_APPID="";        GAME_BINARY="java" ;;
        minecraft-fabric) GAME_LABEL="Minecraft Fabric"; STEAM_APPID=""; GAME_BINARY="java" ;;
        terraria) GAME_LABEL="Terraria"; STEAM_APPID=""; GAME_BINARY="TerrariaServer.bin.x86_64" ;;
        soulmask) GAME_LABEL="Soulmask"; STEAM_APPID="3017300"; GAME_BINARY="StartServer.sh" ;;
        satisfactory) GAME_LABEL="Satisfactory"; STEAM_APPID="1690800"; GAME_BINARY="FactoryServer.sh" ;;
    esac
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
    if [[ -z "$INSTANCE_ID" ]]; then
        _base="${GAME_ID}"
        _candidate="${_base}"
        _n=2
        while [[ -d "$HOME_DIR/game-commander-${_candidate}" ]] \
           || systemctl list-units --full --all 2>/dev/null | grep -q "game-commander-${_candidate}\.service"; do
            _candidate="${_base}${_n}"
            (( _n++ ))
        done
        INSTANCE_ID="$_candidate"
    fi

    [[ -z "$SERVER_DIR" ]] && SERVER_DIR="$HOME_DIR/${INSTANCE_ID}_server"
    [[ -z "$DATA_DIR"   ]] && DATA_DIR="$HOME_DIR/${INSTANCE_ID}_data"
    [[ -z "$BACKUP_DIR" ]] && BACKUP_DIR="$HOME_DIR/gamebackups"
    [[ -z "$APP_DIR"    ]] && APP_DIR="$HOME_DIR/game-commander-${INSTANCE_ID}"
    [[ -z "$SRC_DIR"    ]] && SRC_DIR="$SCRIPT_DIR"

    [[ -z "$GAME_SERVICE" ]] && GAME_SERVICE="${GAME_ID}-server-${INSTANCE_ID}"
    GC_SERVICE="game-commander-${INSTANCE_ID}"
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

    if [[ -z "$prev_server_dir" || "$prev_server_dir" == "$HOME_DIR/${prev_instance}_server" ]]; then
        SERVER_DIR="$HOME_DIR/${INSTANCE_ID}_server"
    fi
    if [[ -z "$prev_data_dir" || "$prev_data_dir" == "$HOME_DIR/${prev_instance}_data" ]]; then
        DATA_DIR="$HOME_DIR/${INSTANCE_ID}_data"
    fi
    if [[ -z "$prev_app_dir" || "$prev_app_dir" == "$HOME_DIR/game-commander-${prev_instance}" ]]; then
        APP_DIR="$HOME_DIR/game-commander-${INSTANCE_ID}"
    fi
    if [[ -z "$prev_game_service" || "$prev_game_service" == "${GAME_ID}-server-${prev_instance}" ]]; then
        GAME_SERVICE="${GAME_ID}-server-${INSTANCE_ID}"
    fi
    GC_SERVICE="game-commander-${INSTANCE_ID}"

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

    if [[ "$DEPLOY_MODE" != "attach" ]] && conflict="$(deploy_first_port_group_conflict)"; then
        IFS='|' read -r spec proto label port <<< "$conflict"
        deploy_suggest_port_group
        warn "${label} ${port}/$([[ "$proto" == "t" ]] && echo TCP || echo UDP) déjà utilisé — groupe de ports suggéré mis à jour"
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
            other_valheim=$(pgrep -a valheim_server 2>/dev/null | grep -v "^$$" | head -1 || true)
            if [[ -n "$other_valheim" ]]; then
                warn "Une autre instance Valheim est déjà en cours d'exécution"
                warn "  $other_valheim"
                warn "Le flag -crossplay sera remplacé par -playfab (multi-instance PlayFab)."
                GC_FORCE_PLAYFAB=true
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

    nginx_conf_for_domain=""
    for _nc in "/etc/nginx/conf.d/${DOMAIN}.conf" \
               "/etc/nginx/sites-enabled/${DOMAIN}.conf" \
               "/etc/nginx/sites-available/${DOMAIN}.conf"; do
        [[ -f "$_nc" ]] && { nginx_conf_for_domain="$_nc"; break; }
    done
    if [[ -n "$nginx_conf_for_domain" ]]; then
        existing_owner=$(grep -A5 "location ${URL_PREFIX} {" "$nginx_conf_for_domain" 2>/dev/null \
            | grep -oP '(?<=proxy_pass http://127\.0\.0\.1:)\d+' | head -1 || true)
        if [[ -n "$existing_owner" ]]; then
            warn "Le préfixe '${URL_PREFIX}' est déjà utilisé sur ${DOMAIN}"
            warn "  → proxy_pass existant : http://127.0.0.1:${existing_owner}"
            echo ""
            echo -e "  Suggestions : ${BOLD}/commander${RESET}  /gc  /gameadmin  /${GAME_ID}"
            echo ""
            prompt "Nouveau préfixe URL" "/${GAME_ID}"
            URL_PREFIX="${REPLY%/}"
        fi
    fi

    FLASK_PORT="$(deploy_next_free_flask_port "${FLASK_PORT}")"
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
        case "$REPLY" in
            0) return 10 ;;
            1) SSL_MODE="certbot" ;;
            2) SSL_MODE="none" ;;
            *) SSL_MODE="existing" ;;
        esac
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
    [[ -n "$ADMIN_PASSWORD" ]] || die "Mot de passe admin obligatoire."
}

deploy_print_summary() {
    hdr "RÉCAPITULATIF"
    echo ""
    echo -e "  ${BOLD}Jeu               :${RESET} $GAME_LABEL"
    echo -e "  ${BOLD}Mode              :${RESET} $DEPLOY_MODE"
    echo -e "  ${BOLD}Utilisateur       :${RESET} $SYS_USER ($HOME_DIR)"
    echo -e "  ${BOLD}Serveur           :${RESET} $SERVER_DIR"
    [[ "$GAME_ID" != "enshrouded" ]] && echo -e "  ${BOLD}Données           :${RESET} $DATA_DIR"
    echo -e "  ${BOLD}Nom serveur       :${RESET} $SERVER_NAME"
    echo -e "  ${BOLD}Port              :${RESET} $SERVER_PORT"
    [[ "$GAME_ID" == "soulmask" ]] && {
        echo -e "  ${BOLD}Query Port        :${RESET} $QUERY_PORT"
        echo -e "  ${BOLD}Echo Port         :${RESET} $ECHO_PORT"
        echo -e "  ${BOLD}Mode              :${RESET} $SERVER_MODE"
    }
    echo -e "  ${BOLD}Joueurs max       :${RESET} $MAX_PLAYERS"
    [[ "$GAME_ID" == "valheim" ]] && {
        echo -e "  ${BOLD}Monde             :${RESET} $WORLD_NAME"
        echo -e "  ${BOLD}Crossplay         :${RESET} $($CROSSPLAY && echo "Oui" || echo "Non")"
        echo -e "  ${BOLD}BepInEx           :${RESET} $($BEPINEX && echo "Oui" || echo "Non")"
    }
    echo -e "  ${BOLD}Sauvegardes       :${RESET} $BACKUP_DIR (7j)"
    echo -e "  ${BOLD}Service jeu       :${RESET} $GAME_SERVICE"
    echo -e "  ${BOLD}Game Commander    :${RESET} $APP_DIR"
    echo -e "  ${BOLD}URL               :${RESET} $DOMAIN${URL_PREFIX}"
    echo -e "  ${BOLD}Port Flask        :${RESET} $FLASK_PORT"
    echo -e "  ${BOLD}SSL               :${RESET} $SSL_MODE"
    echo -e "  ${BOLD}Admin             :${RESET} $ADMIN_LOGIN"
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
