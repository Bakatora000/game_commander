# ── lib/deploy_helpers.sh ────────────────────────────────────────────────────
# Helpers partagés pour cmd_deploy

deploy_set_defaults() {
    GAME_ID=""
    INSTANCE_ID=""
    SYS_USER="gameserver"
    SERVER_DIR=""
    DATA_DIR=""
    BACKUP_DIR=""
    APP_DIR=""
    SRC_DIR=""
    WORLD_NAME="Monde1"
    SERVER_NAME="Mon Serveur"
    SERVER_PASSWORD=""
    SERVER_ADMIN_PASSWORD=""
    SERVER_PORT=""
    QUERY_PORT=""
    ECHO_PORT=""
    MAX_PLAYERS=""
    SERVER_MODE="pve"
    BACKUP_ENABLED=true
    SAVING_ENABLED=true
    BACKUP_INTERVAL="7200"
    CROSSPLAY=false
    BEPINEX=true
    DOMAIN="monserveur.example.com"
    URL_PREFIX=""
    FLASK_PORT=""
    SSL_MODE="existing"
    ADMIN_LOGIN="admin"
    ADMIN_PASSWORD="${ADMIN_PASSWORD:-}"
    AUTO_INSTALL_DEPS=true
    AUTO_INSTALL_STEAMCMD=true
    AUTO_INSTALL_BEPINEX=true
    AUTO_UPDATE_SERVER=false
    AUTO_CONFIRM=false
    DEPLOY_MODE="managed"
    CONFIG_MODE=false
    CONFIG_FILE_DEPLOY=""
    GAME_SERVICE=""
}

deploy_handle_special_args() {
    local outfile="${1:-env/deploy_config.env}"

    [[ "$outfile" == --* ]] && outfile="env/deploy_config.env"
    python3 "$SCRIPT_DIR/shared/deployenv.py" template --out "$outfile" >/dev/null \
        || die "Échec génération du modèle de configuration"
    echo -e "${GREEN}  ✓  Modèle généré : $outfile${RESET}"
    echo -e "${CYAN}  →  Éditez puis lancez :${RESET}"
    echo -e "      sudo bash game_commander.sh deploy --config $outfile"
}

deploy_runtime_src_dir() {
    local src_dir="${1:-$SRC_DIR}"
    python3 "$SCRIPT_DIR/shared/deployenv.py" runtime-src --src-dir "$src_dir"
}

deploy_has_runtime_sources() {
    deploy_runtime_src_dir "${1:-$SRC_DIR}" >/dev/null 2>&1
}

set_game_defaults() {
    source <(
        GAME_ID="$GAME_ID" \
        DEPLOY_MODE="${DEPLOY_MODE}" \
        SYS_USER="${SYS_USER}" \
        INSTANCE_ID="${INSTANCE_ID}" \
        SERVER_DIR="${SERVER_DIR}" \
        DATA_DIR="${DATA_DIR}" \
        BACKUP_DIR="${BACKUP_DIR}" \
        APP_DIR="${APP_DIR}" \
        SRC_DIR="${SRC_DIR}" \
        GAME_SERVICE="${GAME_SERVICE}" \
        SERVER_NAME="${SERVER_NAME}" \
        SERVER_PASSWORD="${SERVER_PASSWORD}" \
        SERVER_ADMIN_PASSWORD="${SERVER_ADMIN_PASSWORD}" \
        SERVER_PORT="${SERVER_PORT}" \
        QUERY_PORT="${QUERY_PORT}" \
        ECHO_PORT="${ECHO_PORT}" \
        MAX_PLAYERS="${MAX_PLAYERS}" \
        SERVER_MODE="${SERVER_MODE}" \
        BACKUP_ENABLED="${BACKUP_ENABLED}" \
        SAVING_ENABLED="${SAVING_ENABLED}" \
        BACKUP_INTERVAL="${BACKUP_INTERVAL}" \
        WORLD_NAME="${WORLD_NAME}" \
        CROSSPLAY="${CROSSPLAY}" \
        BEPINEX="${BEPINEX}" \
        DOMAIN="${DOMAIN}" \
        URL_PREFIX="${URL_PREFIX}" \
        FLASK_PORT="${FLASK_PORT}" \
        SSL_MODE="${SSL_MODE}" \
        ADMIN_LOGIN="${ADMIN_LOGIN}" \
        ADMIN_PASSWORD="${ADMIN_PASSWORD}" \
        AUTO_CONFIRM="${AUTO_CONFIRM}" \
        python3 "$SCRIPT_DIR/shared/deployenv.py" fill-defaults
    )
}

deploy_load_config_file() {
    if $CONFIG_MODE; then
        python3 "$SCRIPT_DIR/shared/deployenv.py" validate-config --config "$CONFIG_FILE_DEPLOY" \
            || die "Config invalide : $CONFIG_FILE_DEPLOY"
        source <(python3 "$SCRIPT_DIR/shared/deployenv.py" exports --config "$CONFIG_FILE_DEPLOY")
        info "Config chargée depuis : $CONFIG_FILE_DEPLOY"
    fi
}

prompt() {
    local question="$1" default="${2:-}"
    if $CONFIG_MODE; then
        REPLY="$default"
        echo -e "  ${DIM}  (config) $question : ${BOLD}$REPLY${RESET}"
    else
        [[ -n "$default" ]] && ask "${question} [${DIM}${default}${RESET}${YELLOW}]: " \
                             || ask "${question}: "
        read -r REPLY
        REPLY=$(printf '%s' "${REPLY:-$default}" | tr -cd '[:print:]')
        REPLY="${REPLY:-$default}"
    fi
}

prompt_secret() {
    local question="$1" default="${2:-}"
    if $CONFIG_MODE; then
        REPLY="$default"
        local masked="${REPLY:0:2}****"
        [[ -z "$REPLY" ]] && masked="(vide)"
        echo -e "  ${DIM}  (config) $question : ${BOLD}$masked${RESET}"
    else
        ask "${question}: "
        read -rs REPLY
        echo ""
        REPLY="${REPLY:-$default}"
    fi
}

confirm() {
    local question="$1" default="${2:-o}"
    if $CONFIG_MODE; then
        [[ "$default" =~ ^[oOyY] ]] \
            && echo -e "  ${DIM}  (auto) $question → oui${RESET}" \
            || echo -e "  ${DIM}  (auto) $question → non${RESET}"
        [[ "$default" =~ ^[oOyY] ]]
    else
        ask "${question} (o/n) [${default}]: "
        read -r ans
        ans="${ans:-$default}"
        [[ "$ans" =~ ^[oOyY] ]]
    fi
}

confirm_bool() {
    local val="$1" question="$2"
    if $CONFIG_MODE; then
        $val && echo -e "  ${DIM}  (config) $question → oui${RESET}" \
             || echo -e "  ${DIM}  (config) $question → non${RESET}"
        $val
    else
        confirm "$question"
    fi
}

wait_for_process() {
    local pattern="$1" timeout="${2:-30}" elapsed=0
    while ! pgrep -f "$pattern" &>/dev/null; do
        sleep 2
        elapsed=$((elapsed + 2))
        [[ $elapsed -lt $timeout ]] || return 1
    done
}

deploy_init_logging() {
    LOGFILE="/tmp/gamecommander_deploy_$(date +%Y%m%d_%H%M%S).log"
    exec > >(tee -a "$LOGFILE") 2>&1
    info "Journal : $LOGFILE"
}

deploy_print_banner() {
    clear
    cat << 'BANNER'

  ╔════════════════════════════════════════════════════════╗
  ║      GAME COMMANDER — DÉPLOIEMENT v2.0                 ║
  ║   Serveur de jeu + Interface web (sans AMP)            ║
  ╚════════════════════════════════════════════════════════╝

BANNER

    $CONFIG_MODE && info "Mode : FICHIER DE CONFIG ($CONFIG_FILE_DEPLOY)"
    [[ $EUID -eq 0 ]] || die "Lancez en root : sudo bash $0 deploy"
    ok "Droits root confirmés"
}
