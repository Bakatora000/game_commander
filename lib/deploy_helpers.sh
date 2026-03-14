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
    ADMIN_PASSWORD=""
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
    cat > "$outfile" << 'CFGTPL'
# ═══════════════════════════════════════════════════════════════════════════════
#  Game Commander — Fichier de configuration de déploiement
#  Usage : sudo bash game_commander.sh deploy --config env/deploy_config.env
# ═══════════════════════════════════════════════════════════════════════════════

# Jeu : valheim | enshrouded | minecraft | minecraft-fabric | terraria | soulmask
GAME_ID="valheim"

# Mode de déploiement : managed | attach
DEPLOY_MODE="managed"

# Utilisateur système
SYS_USER="gameserver"

# Chemins (laisser vide = valeur par défaut basée sur le home de SYS_USER)
INSTANCE_ID=""      # identifiant unique (ex. valheim2, mc-skyblock)
SERVER_DIR=""
DATA_DIR=""
BACKUP_DIR=""
APP_DIR=""
SRC_DIR=""          # racine du projet Game Commander ou dossier runtime
GAME_SERVICE=""     # vide = nom par défaut, utile en mode attach

# Configuration du serveur de jeu
SERVER_NAME="Mon Serveur Valheim"
SERVER_PASSWORD=""
SERVER_ADMIN_PASSWORD=""
SERVER_PORT=""          # vide = défaut du jeu
QUERY_PORT=""           # Soulmask uniquement
ECHO_PORT=""            # Soulmask uniquement
MAX_PLAYERS=""
SERVER_MODE="pve"       # Soulmask : pve | pvp
BACKUP_ENABLED=true     # Soulmask
SAVING_ENABLED=true     # Soulmask
BACKUP_INTERVAL="7200"  # Soulmask, en secondes
WORLD_NAME="Monde1"     # Valheim uniquement
CROSSPLAY=false
BEPINEX=true

# Interface web Game Commander
DOMAIN="monserveur.example.com"
URL_PREFIX=""           # vide = défaut du jeu
FLASK_PORT=""
SSL_MODE="existing"     # certbot | none | existing

# Compte administrateur
ADMIN_LOGIN="admin"
ADMIN_PASSWORD=""       # OBLIGATOIRE — renseigner ici ou laisser vide pour prompt

# Automatisation
AUTO_INSTALL_DEPS=true
AUTO_INSTALL_STEAMCMD=true
AUTO_INSTALL_BEPINEX=true
AUTO_UPDATE_SERVER=false
AUTO_CONFIRM=true
CFGTPL
    echo -e "${GREEN}  ✓  Modèle généré : $outfile${RESET}"
    echo -e "${CYAN}  →  Éditez puis lancez :${RESET}"
    echo -e "      sudo bash game_commander.sh deploy --config $outfile"
}

deploy_runtime_src_dir() {
    local src_dir="${1:-$SRC_DIR}"

    if [[ -f "$src_dir/runtime/app.py" ]]; then
        printf '%s\n' "$src_dir/runtime"
        return 0
    fi

    if [[ -f "$src_dir/app.py" ]]; then
        printf '%s\n' "$src_dir"
        return 0
    fi

    return 1
}

deploy_has_runtime_sources() {
    deploy_runtime_src_dir "${1:-$SRC_DIR}" >/dev/null 2>&1
}

set_game_defaults() {
    case "$GAME_ID" in
        valheim)
            SERVER_PORT="${SERVER_PORT:-2456}"
            MAX_PLAYERS="${MAX_PLAYERS:-10}"
            URL_PREFIX="${URL_PREFIX:-/valheim}"
            FLASK_PORT="${FLASK_PORT:-5002}"
            SERVER_NAME="${SERVER_NAME:-Mon Serveur Valheim}"
            ;;
        enshrouded)
            SERVER_PORT="${SERVER_PORT:-15636}"
            MAX_PLAYERS="${MAX_PLAYERS:-16}"
            URL_PREFIX="${URL_PREFIX:-/enshrouded}"
            FLASK_PORT="${FLASK_PORT:-5003}"
            SERVER_NAME="${SERVER_NAME:-Mon Serveur Enshrouded}"
            ;;
        minecraft)
            SERVER_PORT="${SERVER_PORT:-25565}"
            MAX_PLAYERS="${MAX_PLAYERS:-20}"
            URL_PREFIX="${URL_PREFIX:-/minecraft}"
            FLASK_PORT="${FLASK_PORT:-5004}"
            SERVER_NAME="${SERVER_NAME:-Mon Serveur Minecraft Java}"
            ;;
        minecraft-fabric)
            SERVER_PORT="${SERVER_PORT:-25565}"
            MAX_PLAYERS="${MAX_PLAYERS:-20}"
            URL_PREFIX="${URL_PREFIX:-/minecraft-fabric}"
            FLASK_PORT="${FLASK_PORT:-5005}"
            SERVER_NAME="${SERVER_NAME:-Mon Serveur Minecraft Fabric}"
            ;;
        terraria)
            SERVER_PORT="${SERVER_PORT:-7777}"
            MAX_PLAYERS="${MAX_PLAYERS:-8}"
            URL_PREFIX="${URL_PREFIX:-/terraria}"
            FLASK_PORT="${FLASK_PORT:-5006}"
            SERVER_NAME="${SERVER_NAME:-Mon Serveur Terraria}"
            ;;
        soulmask)
            SERVER_PORT="${SERVER_PORT:-8777}"
            QUERY_PORT="${QUERY_PORT:-27015}"
            ECHO_PORT="${ECHO_PORT:-18888}"
            MAX_PLAYERS="${MAX_PLAYERS:-50}"
            URL_PREFIX="${URL_PREFIX:-/soulmask}"
            FLASK_PORT="${FLASK_PORT:-5011}"
            SERVER_NAME="${SERVER_NAME:-Mon Serveur Soulmask}"
            SERVER_MODE="${SERVER_MODE:-pve}"
            BACKUP_INTERVAL="${BACKUP_INTERVAL:-7200}"
            ;;
    esac
}

deploy_load_config_file() {
    if $CONFIG_MODE; then
        [[ -f "$CONFIG_FILE_DEPLOY" ]] || die "Fichier de config introuvable : $CONFIG_FILE_DEPLOY"
        # shellcheck source=/dev/null
        source "$CONFIG_FILE_DEPLOY"
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
