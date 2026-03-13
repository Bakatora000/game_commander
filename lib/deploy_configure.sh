# ── lib/deploy_configure.sh ──────────────────────────────────────────────────
# Étape 2 interactive / config du déploiement

deploy_check_port_conflict() {
    local port="$1" proto="${2:-u}"
    ss -${proto}lnH 2>/dev/null | grep -q ":${port} " && return 0
    ss -${proto}nH 2>/dev/null | grep -q ":${port} " && return 0
    return 1
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

deploy_select_game() {
    echo ""
    if [[ -z "$GAME_ID" ]]; then
        echo -e "  ${BOLD}Jeu à déployer :${RESET}"
        echo -e "  ${CYAN}[1]${RESET} Valheim"
        echo -e "  ${CYAN}[2]${RESET} Enshrouded"
        echo -e "  ${CYAN}[3]${RESET} Minecraft ${DIM}(placeholder — serveur non installé)${RESET}"
        echo ""
        prompt "Votre choix" "1"
        case "$REPLY" in
            2) GAME_ID="enshrouded" ;;
            3) GAME_ID="minecraft" ;;
            *) GAME_ID="valheim" ;;
        esac
    else
        echo -e "  ${DIM}  (config) Jeu : ${BOLD}${GAME_ID}${RESET}"
    fi

    set_game_defaults

    case "$GAME_ID" in
        valheim)    GAME_LABEL="Valheim";    STEAM_APPID="896660";  GAME_BINARY="valheim_server.x86_64" ;;
        enshrouded) GAME_LABEL="Enshrouded"; STEAM_APPID="2278520"; GAME_BINARY="enshrouded_server.exe" ;;
        minecraft)  GAME_LABEL="Minecraft";  STEAM_APPID="";        GAME_BINARY="java" ;;
    esac
    ok "Jeu sélectionné : ${BOLD}${GAME_LABEL}${RESET}"
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

    GAME_SERVICE="${GAME_ID}-server-${INSTANCE_ID}"
    GC_SERVICE="game-commander-${INSTANCE_ID}"
}

deploy_configure_paths() {
    echo ""
    info "Instance"
    prompt "Identifiant d'instance (unique par serveur)" "${INSTANCE_ID}"
    INSTANCE_ID="$REPLY"
    [[ "$SERVER_DIR" == *"_server" ]] && SERVER_DIR="$HOME_DIR/${INSTANCE_ID}_server"
    [[ "$DATA_DIR" == *"_data" ]] && DATA_DIR="$HOME_DIR/${INSTANCE_ID}_data"
    [[ "$APP_DIR" == *"game-commander-"* ]] && APP_DIR="$HOME_DIR/game-commander-${INSTANCE_ID}"
    GAME_SERVICE="${GAME_ID}-server-${INSTANCE_ID}"
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
}

deploy_configure_server() {
    local query_port next_port other_valheim nginx_conf_for_domain existing_owner

    echo ""
    info "Configuration du serveur $GAME_LABEL"
    prompt "Nom du serveur" "${SERVER_NAME}"
    SERVER_NAME="$REPLY"
    prompt_secret "Mot de passe (vide = public)" "${SERVER_PASSWORD}"
    SERVER_PASSWORD="$REPLY"

    if deploy_check_port_conflict "$SERVER_PORT" u || deploy_check_port_conflict "$((SERVER_PORT+1))" u; then
        next_port="$SERVER_PORT"
        while deploy_check_port_conflict "$next_port" u || deploy_check_port_conflict "$((next_port+1))" u; do
            next_port=$((next_port + 2))
        done
        warn "Port ${SERVER_PORT}/UDP déjà utilisé — suggestion : ${next_port}"
        SERVER_PORT="$next_port"
    fi

    prompt "Port principal" "${SERVER_PORT}"
    SERVER_PORT="$REPLY"
    query_port=$((SERVER_PORT + 1))
    if deploy_check_port_conflict "$SERVER_PORT" u; then
        warn "Port ${SERVER_PORT}/UDP déjà utilisé par : $(deploy_port_owner "$SERVER_PORT")"
    fi
    if deploy_check_port_conflict "$query_port" u; then
        warn "Port ${query_port}/UDP déjà utilisé par : $(deploy_port_owner "$query_port")"
    fi
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
        echo -e "  ${CYAN}[1]${RESET} Certbot (Let's Encrypt)"
        echo -e "  ${CYAN}[2]${RESET} HTTP uniquement"
        echo -e "  ${CYAN}[3]${RESET} SSL déjà configuré"
        prompt "Configuration SSL" "3"
        case "$REPLY" in
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
    echo -e "  ${BOLD}Utilisateur       :${RESET} $SYS_USER ($HOME_DIR)"
    echo -e "  ${BOLD}Serveur           :${RESET} $SERVER_DIR"
    [[ "$GAME_ID" != "enshrouded" ]] && echo -e "  ${BOLD}Données           :${RESET} $DATA_DIR"
    echo -e "  ${BOLD}Nom serveur       :${RESET} $SERVER_NAME"
    echo -e "  ${BOLD}Port              :${RESET} $SERVER_PORT"
    echo -e "  ${BOLD}Joueurs max       :${RESET} $MAX_PLAYERS"
    [[ "$GAME_ID" == "valheim" ]] && {
        echo -e "  ${BOLD}Monde             :${RESET} $WORLD_NAME"
        echo -e "  ${BOLD}Crossplay         :${RESET} $($CROSSPLAY && echo "Oui" || echo "Non")"
        echo -e "  ${BOLD}BepInEx           :${RESET} $($BEPINEX && echo "Oui" || echo "Non")"
    }
    echo -e "  ${BOLD}Sauvegardes       :${RESET} $BACKUP_DIR (7j)"
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
    deploy_select_game
    deploy_configure_user
    deploy_prepare_instance_defaults
    deploy_configure_paths
    deploy_configure_server
    deploy_configure_admin
    deploy_print_summary

    $AUTO_CONFIRM \
        && ok "Confirmation automatique (AUTO_CONFIRM=true)" \
        || { confirm "Lancer l'installation ?" "o" || die "Annulé."; }
}
