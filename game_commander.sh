#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════════
#  game_commander.sh v2.0 — Déploiement et gestion des instances Game Commander
#
#  Usage :
#    sudo bash game_commander.sh                          # menu interactif
#    sudo bash game_commander.sh deploy                   # déploiement interactif
#    sudo bash game_commander.sh deploy --config FILE     # déploiement silencieux
#    sudo bash game_commander.sh deploy --generate-config # générer un modèle
#    sudo bash game_commander.sh uninstall                # désinstallation guidée
#    sudo bash game_commander.sh uninstall --dry-run      # simulation
#    sudo bash game_commander.sh status                   # état de toutes les instances
# ═══════════════════════════════════════════════════════════════════════════════
set -uo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Couleurs ──────────────────────────────────────────────────────────────────
RED='\033[0;31m';  GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m';     DIM='\033[2m'; RESET='\033[0m'

ok()   { echo -e "${GREEN}  ✓  $*${RESET}"; }
warn() { echo -e "${YELLOW}  ⚠  $*${RESET}"; }
err()  { echo -e "${RED}  ✗  $*${RESET}"; }
info() { echo -e "${CYAN}  →  $*${RESET}"; }
hdr()  { echo -e "\n${BOLD}${CYAN}╔══ $* ══╗${RESET}"; }
sep()  { echo -e "${DIM}  ───────────────────────────────────────${RESET}"; }
ask()  { echo -en "${YELLOW}  ?  $* ${RESET}"; }
die()  { err "$*"; exit 1; }

# ── Helpers partagés ──────────────────────────────────────────────────────────

# Exécution avec support dry-run (utilisé par uninstall)
DRY_RUN=false
run() { $DRY_RUN && echo -e "${DIM}    [dry-run] $*${RESET}" || "$@"; }

ask_yn() {
    local prompt="$1"
    echo -en "  ${YELLOW}?  ${prompt} (o/n) : ${RESET}"
    read -r _ans
    [[ "$_ans" == "o" || "$_ans" == "O" || "$_ans" == "oui" ]]
}

service_state() { systemctl is-active "$1" 2>/dev/null || echo "inactive"; }

stop_and_disable() {
    local svc="$1"
    if systemctl list-unit-files "${svc}.service" &>/dev/null \
       && systemctl list-unit-files "${svc}.service" | grep -qv "not-found"; then
        if [[ "$(service_state "$svc")" != "inactive" ]]; then
            info "Arrêt de $svc..."
            run systemctl stop "$svc" || true
        fi
        if systemctl is-enabled --quiet "$svc" 2>/dev/null; then
            run systemctl disable "$svc" || true
        fi
        if [[ -f "/etc/systemd/system/${svc}.service" ]]; then
            run rm -f "/etc/systemd/system/${svc}.service"
            run systemctl daemon-reload
            ok "Service supprimé : $svc"
        fi
    else
        warn "Service introuvable : $svc"
    fi
}

remove_dir() {
    local dir="$1" label="$2"
    if [[ -d "$dir" ]]; then
        local size
        size=$(du -sh "$dir" 2>/dev/null | cut -f1)
        if ask_yn "Supprimer $label : ${BOLD}$dir${RESET}${YELLOW} (${size}) ?"; then
            run rm -rf "$dir"
            ok "Supprimé : $dir"
        else
            info "Conservé : $dir"
        fi
    fi
}

# Vérifie si un dossier est référencé par d'autres deploy_config.env
shared_by_others() {
    local check_dir="$1" current_cfg="$2"
    local others=()
    while IFS= read -r other_cfg; do
        [[ "$other_cfg" == "$current_cfg" ]] && continue
        grep -qF "$check_dir" "$other_cfg" 2>/dev/null || continue
        local iid
        iid=$(grep '^INSTANCE_ID=' "$other_cfg" 2>/dev/null \
              | cut -d= -f2- | tr -d '"')
        [[ -n "$iid" ]] && others+=("$iid")
    done < <(find /home /opt /root -maxdepth 5 -name "deploy_config.env" 2>/dev/null)
    echo "${others[*]:-}"
}

remove_dir_safe() {
    local dir="$1" label="$2" current_cfg="$3"
    [[ -z "$dir" || ! -d "$dir" ]] && return
    local others
    others=$(shared_by_others "$dir" "$current_cfg")
    if [[ -n "$others" ]]; then
        warn "Dossier partagé — NON supprimé : $dir"
        warn "  Référencé aussi par : $others"
    else
        remove_dir "$dir" "$label"
    fi
}

cmd_exists()     { command -v "$1" &>/dev/null; }
service_active() { systemctl is-active --quiet "$1" 2>/dev/null; }

# ═══════════════════════════════════════════════════════════════════════════════
# STATUS — Liste toutes les instances Game Commander
# ═══════════════════════════════════════════════════════════════════════════════
cmd_status() {
    hdr "Instances Game Commander"

    mapfile -t CONFIGS < <(
        find /home /opt /root -maxdepth 5 -name "deploy_config.env" 2>/dev/null \
        | xargs -I{} grep -l "GAME_ID=" {} 2>/dev/null \
        | sort -u
    )

    if [[ ${#CONFIGS[@]} -eq 0 ]]; then
        info "Aucune instance Game Commander trouvée."
        return
    fi

    echo ""
    for cfg in "${CONFIGS[@]}"; do
        unset GAME_ID INSTANCE_ID SYS_USER DOMAIN FLASK_PORT SERVER_NAME \
              GAME_SERVICE GC_SERVICE
        source <(grep -E '^[A-Z_]+=' "$cfg" 2>/dev/null)

        GAME_ID="${GAME_ID:-?}"
        INSTANCE_ID="${INSTANCE_ID:-$GAME_ID}"
        GC_SERVICE="game-commander-${INSTANCE_ID}"
        GAME_SERVICE="${GAME_ID}-server-${INSTANCE_ID}"
        GC_STATE=$(service_state "$GC_SERVICE")
        GAME_STATE=$(service_state "$GAME_SERVICE")

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

        echo -e "  ${BOLD}${INSTANCE_ID}${RESET}  (${GAME_ID^^})"
        echo -e "     Serveur jeu  : ${GAME_SERVICE}  →  $ss"
        echo -e "     Game Cmd web : ${GC_SERVICE}   →  $gs"
        [[ -n "${SERVER_NAME:-}" ]] && echo -e "     Nom          : $SERVER_NAME"
        [[ -n "${DOMAIN:-}"      ]] && echo -e "     URL          : https://${DOMAIN}${URL_PREFIX:-}  (port ${FLASK_PORT:-?})"
        echo -e "     Config       : $cfg"
        sep
    done
}

# ═══════════════════════════════════════════════════════════════════════════════
# DEPLOY
# ═══════════════════════════════════════════════════════════════════════════════
cmd_deploy() {

# ── Valeurs par défaut ────────────────────────────────────────────────────────
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
SERVER_PORT=""
MAX_PLAYERS=""
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
CONFIG_MODE=false
CONFIG_FILE_DEPLOY=""

# ── Arguments spécifiques deploy ─────────────────────────────────────────────
local _args=("$@")
local i=0
while [[ $i -lt ${#_args[@]} ]]; do
    case "${_args[$i]}" in
        --config)
            i=$((i+1))
            CONFIG_FILE_DEPLOY="${_args[$i]}"
            CONFIG_MODE=true
            ;;
        --generate-config)
            local OUTFILE="${_args[$((i+1))]:-deploy_game_commander.env}"
            # Si le prochain arg n'existe pas ou commence par --, utiliser le défaut
            [[ "${OUTFILE}" == --* ]] && OUTFILE="deploy_game_commander.env"
            cat > "$OUTFILE" << 'CFGTPL'
# ═══════════════════════════════════════════════════════════════════════════════
#  Game Commander — Fichier de configuration de déploiement
#  Usage : sudo bash game_commander.sh deploy --config deploy_game_commander.env
# ═══════════════════════════════════════════════════════════════════════════════

# Jeu : valheim | enshrouded | minecraft
GAME_ID="valheim"

# Utilisateur système
SYS_USER="gameserver"

# Chemins (laisser vide = valeur par défaut basée sur le home de SYS_USER)
INSTANCE_ID=""      # identifiant unique (ex. valheim2, mc-skyblock)
SERVER_DIR=""
DATA_DIR=""
BACKUP_DIR=""
APP_DIR=""
SRC_DIR=""          # dossier contenant le projet Game Commander (app.py etc.)

# Configuration du serveur de jeu
SERVER_NAME="Mon Serveur Valheim"
SERVER_PASSWORD=""
SERVER_PORT=""          # vide = défaut du jeu
MAX_PLAYERS=""
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
            echo -e "${GREEN}  ✓  Modèle généré : $OUTFILE${RESET}"
            echo -e "${CYAN}  →  Éditez puis lancez :${RESET}"
            echo -e "      sudo bash game_commander.sh deploy --config $OUTFILE"
            return 0
            ;;
    esac
    i=$((i+1))
done

# ── Valeurs par défaut par jeu ────────────────────────────────────────────────
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
            SERVER_NAME="${SERVER_NAME:-Mon Serveur Minecraft}"
            ;;
    esac
}

# ── Chargement config ─────────────────────────────────────────────────────────
if $CONFIG_MODE; then
    [[ ! -f "$CONFIG_FILE_DEPLOY" ]] && die "Fichier de config introuvable : $CONFIG_FILE_DEPLOY"
    # shellcheck source=/dev/null
    source "$CONFIG_FILE_DEPLOY"
    info "Config chargée depuis : $CONFIG_FILE_DEPLOY"
fi

# ── Helpers interactifs ───────────────────────────────────────────────────────
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
        local m="${REPLY:0:2}****"; [[ -z "$REPLY" ]] && m="(vide)"
        echo -e "  ${DIM}  (config) $question : ${BOLD}$m${RESET}"
    else
        ask "${question}: "; read -rs REPLY; echo ""; REPLY="${REPLY:-$default}"
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
        ask "${question} (o/n) [${default}]: "; read -r ans; ans="${ans:-$default}"
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
        sleep 2; elapsed=$((elapsed+2))
        [[ $elapsed -ge $timeout ]] && return 1
    done
}

# ── Logging ───────────────────────────────────────────────────────────────────
LOGFILE="/tmp/gamecommander_deploy_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee -a "$LOGFILE") 2>&1
info "Journal : $LOGFILE"

# ═══════════════════════════════════════════════════════════════════════════════
# ÉTAPE 0 — Root
# ═══════════════════════════════════════════════════════════════════════════════
clear
cat << 'BANNER'

  ╔════════════════════════════════════════════════════════╗
  ║      GAME COMMANDER — DÉPLOIEMENT v2.0                 ║
  ║   Serveur de jeu + Interface web (sans AMP)            ║
  ╚════════════════════════════════════════════════════════╝

BANNER

$CONFIG_MODE && info "Mode : FICHIER DE CONFIG ($CONFIG_FILE_DEPLOY)"
[[ $EUID -ne 0 ]] && die "Lancez en root : sudo bash $0 deploy"
ok "Droits root confirmés"

# ═══════════════════════════════════════════════════════════════════════════════
# ÉTAPE 1 — OS
# ═══════════════════════════════════════════════════════════════════════════════
hdr "ÉTAPE 1 : Environnement"

[[ -f /etc/os-release ]] && { . /etc/os-release; OS_ID="${ID:-unknown}"; OS_PRETTY="${PRETTY_NAME:-Linux}"; } \
                          || { OS_ID="unknown"; OS_PRETTY="Linux"; }
info "Système : $OS_PRETTY"
[[ "$OS_ID" != "ubuntu" ]] && { warn "Optimisé pour Ubuntu."; confirm "Continuer ?" "o" || die "Annulé."; }

# ═══════════════════════════════════════════════════════════════════════════════
# ÉTAPE 2 — Configuration
# ═══════════════════════════════════════════════════════════════════════════════
hdr "ÉTAPE 2 : Configuration"

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
        3) GAME_ID="minecraft"  ;;
        *) GAME_ID="valheim"    ;;
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

# ── Utilisateur système ───────────────────────────────────────────────────────
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

# ── INSTANCE_ID ───────────────────────────────────────────────────────────────
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

# ── Chemins ───────────────────────────────────────────────────────────────────
echo ""
info "Instance"
prompt "Identifiant d'instance (unique par serveur)" "${INSTANCE_ID}"
INSTANCE_ID="$REPLY"
[[ "$SERVER_DIR" == *"_server" ]] && SERVER_DIR="$HOME_DIR/${INSTANCE_ID}_server"
[[ "$DATA_DIR"   == *"_data"   ]] && DATA_DIR="$HOME_DIR/${INSTANCE_ID}_data"
[[ "$APP_DIR"    == *"game-commander-"* ]] && APP_DIR="$HOME_DIR/game-commander-${INSTANCE_ID}"
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
prompt "Dossier source Game Commander (contenant app.py)" "${SRC_DIR}"
SRC_DIR="$REPLY"

if [[ ! -f "$SRC_DIR/app.py" ]]; then
    warn "app.py introuvable dans $SRC_DIR — Game Commander ne sera pas déployé"
    DEPLOY_APP=false
else
    DEPLOY_APP=true
    ok "Sources Game Commander trouvées"
fi

# ── Config serveur ────────────────────────────────────────────────────────────
echo ""
info "Configuration du serveur $GAME_LABEL"
prompt "Nom du serveur" "${SERVER_NAME}"
SERVER_NAME="$REPLY"
prompt_secret "Mot de passe (vide = public)" "${SERVER_PASSWORD}"
SERVER_PASSWORD="$REPLY"
# ── Vérification conflits de ports ───────────────────────────────────────────
_check_port_conflict() {
    local port="$1" proto="${2:-u}"
    ss -${proto}lnH 2>/dev/null | grep -q ":${port} " && return 0
    ss -${proto}nH  2>/dev/null | grep -q ":${port} " && return 0
    return 1
}
_port_owner() {
    local port="$1"
    local pid
    pid=$(ss -ulnpH 2>/dev/null | grep ":${port} " | grep -oP 'pid=\K\d+' | head -1)
    [[ -z "$pid" ]] && pid=$(ss -tlnpH 2>/dev/null | grep ":${port} " | grep -oP 'pid=\K\d+' | head -1)
    if [[ -n "$pid" ]]; then
        local cmd; cmd=$(ps -p "$pid" -o comm= 2>/dev/null)
        echo "PID $pid ($cmd)"
    else
        echo "processus inconnu"
    fi
}

# Résoudre le port libre AVANT le prompt
if _check_port_conflict "$SERVER_PORT" u || _check_port_conflict "$((SERVER_PORT+1))" u; then
    _next_port="$SERVER_PORT"
    while _check_port_conflict "$_next_port" u || _check_port_conflict "$((_next_port+1))" u; do
        _next_port=$((_next_port + 2))
    done
    warn "Port ${SERVER_PORT}/UDP déjà utilisé — suggestion : ${_next_port}"
    SERVER_PORT="$_next_port"
fi

prompt "Port principal" "${SERVER_PORT}"
SERVER_PORT="$REPLY"

# Vérification finale (l'utilisateur a pu saisir un autre port)
_query_port=$((SERVER_PORT + 1))
if _check_port_conflict "$SERVER_PORT" u; then
    warn "Port ${SERVER_PORT}/UDP déjà utilisé par : $(_port_owner "$SERVER_PORT")"
fi
if _check_port_conflict "$_query_port" u; then
    warn "Port ${_query_port}/UDP déjà utilisé par : $(_port_owner "$_query_port")"
fi
prompt "Joueurs max" "${MAX_PLAYERS}"
MAX_PLAYERS="$REPLY"

GC_FORCE_PLAYFAB=false
if [[ "$GAME_ID" == "valheim" ]]; then
    prompt "Nom du monde" "${WORLD_NAME}"
    WORLD_NAME="$REPLY"
    if $CONFIG_MODE; then
        echo -e "  ${DIM}  (config) Crossplay : ${BOLD}$($CROSSPLAY && echo "Oui" || echo "Non")${RESET}"
        echo -e "  ${DIM}  (config) BepInEx   : ${BOLD}$($BEPINEX   && echo "Oui" || echo "Non")${RESET}"
    else
        confirm "Activer le crossplay ?" "n" && CROSSPLAY=true || CROSSPLAY=false
        confirm "Installer BepInEx (mods) ?" "o" && BEPINEX=true || BEPINEX=false
    fi
    if $CROSSPLAY; then
        _other_valheim=$(pgrep -a valheim_server 2>/dev/null | grep -v "^$$" | head -1 || true)
        if [[ -n "$_other_valheim" ]]; then
            warn "Une autre instance Valheim est déjà en cours d'exécution"
            warn "  $_other_valheim"
            warn "Le flag -crossplay sera remplacé par -playfab (multi-instance PlayFab)."
            GC_FORCE_PLAYFAB=true
        fi
    fi
fi

# ── Config interface web ──────────────────────────────────────────────────────
echo ""
info "Interface web Game Commander"
prompt "Domaine" "${DOMAIN}"
DOMAIN="$REPLY"
prompt "Préfixe URL" "${URL_PREFIX}"
URL_PREFIX="${REPLY%/}"

_nginx_conf_for_domain=""
for _nc in "/etc/nginx/conf.d/${DOMAIN}.conf" \
           "/etc/nginx/sites-enabled/${DOMAIN}.conf" \
           "/etc/nginx/sites-available/${DOMAIN}.conf"; do
    [[ -f "$_nc" ]] && { _nginx_conf_for_domain="$_nc"; break; }
done
if [[ -n "$_nginx_conf_for_domain" ]]; then
    _existing_owner=$(grep -A5 "location ${URL_PREFIX} {" "$_nginx_conf_for_domain" 2>/dev/null \
        | grep -oP '(?<=proxy_pass http://127\.0\.0\.1:)\d+' | head -1 || true)
    if [[ -n "$_existing_owner" ]]; then
        warn "Le préfixe '${URL_PREFIX}' est déjà utilisé sur ${DOMAIN}"
        warn "  → proxy_pass existant : http://127.0.0.1:${_existing_owner}"
        echo ""
        echo -e "  Suggestions : ${BOLD}/commander${RESET}  /gc  /gameadmin  /${GAME_ID}"
        echo ""
        prompt "Nouveau préfixe URL" "/${GAME_ID}"
        URL_PREFIX="${REPLY%/}"
    fi
fi

_next_free_port() {
    local p="$1"
    while ss -tlnH "sport = :$p" 2>/dev/null | grep -q ":$p"; do p=$((p+1)); done
    echo "$p"
}
FLASK_PORT="$(_next_free_port "${FLASK_PORT}")"
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
    case "$REPLY" in 1) SSL_MODE="certbot" ;; 2) SSL_MODE="none" ;; *) SSL_MODE="existing" ;; esac
fi

# ── Compte admin ──────────────────────────────────────────────────────────────
echo ""
info "Compte administrateur Game Commander"
prompt "Identifiant admin" "${ADMIN_LOGIN}"
ADMIN_LOGIN="$REPLY"
if [[ -z "$ADMIN_PASSWORD" ]]; then
    prompt_secret "Mot de passe pour $ADMIN_LOGIN"
    ADMIN_PASSWORD="$REPLY"
fi
[[ -z "$ADMIN_PASSWORD" ]] && die "Mot de passe admin obligatoire."

# ── Récapitulatif ─────────────────────────────────────────────────────────────
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

$AUTO_CONFIRM \
    && ok "Confirmation automatique (AUTO_CONFIRM=true)" \
    || { confirm "Lancer l'installation ?" "o" || die "Annulé."; }

# ═══════════════════════════════════════════════════════════════════════════════
# ÉTAPE 3 — Dépendances
# ═══════════════════════════════════════════════════════════════════════════════
hdr "ÉTAPE 3 : Dépendances"

APT_UPDATED=false
apt_once() { $APT_UPDATED || { info "apt update..."; apt-get update -qq; APT_UPDATED=true; }; }

install_pkg() {
    local pkg="$1"
    dpkg -l "$pkg" 2>/dev/null | grep -q "^ii" && { ok "$pkg OK"; return; }
    warn "$pkg manquant"
    local do_it=false
    $AUTO_INSTALL_DEPS && do_it=true || { confirm "Installer $pkg ?" "o" && do_it=true; }
    $do_it && { apt_once; apt-get install -y -qq "$pkg" && ok "$pkg installé"; } \
           || warn "$pkg ignoré"
}

for pkg in python3 python3-pip nginx curl unzip jq; do install_pkg "$pkg"; done

if [[ -n "$STEAM_APPID" ]]; then
    dpkg --print-foreign-architectures | grep -q i386 || {
        info "Activation i386..."; dpkg --add-architecture i386; apt_once
    }
    install_pkg "lib32gcc-s1"
fi

PY_APT_PKGS=("python3-flask")
PY_PIP_PKGS=("requests" "bcrypt" "psutil")

for pkg in "${PY_APT_PKGS[@]}"; do
    python3 -c "import ${pkg/python3-/}" 2>/dev/null && ok "Python: ${pkg/python3-/} OK" || {
        warn "Python: ${pkg/python3-/} manquant"
        do_it=false
        $AUTO_INSTALL_DEPS && do_it=true || { confirm "Installer $pkg (apt) ?" "o" && do_it=true; }
        $do_it && { apt_once; apt-get install -y -qq "$pkg" && ok "Python: ${pkg/python3-/} installé (apt)"; }
    }
done

for pkg in "${PY_PIP_PKGS[@]}"; do
    python3 -c "import $pkg" 2>/dev/null && ok "Python: $pkg OK" || {
        warn "Python: $pkg manquant"
        do_it=false
        $AUTO_INSTALL_DEPS && do_it=true || { confirm "pip install $pkg ?" "o" && do_it=true; }
        $do_it && pip3 install "$pkg" --break-system-packages -q && ok "Python: $pkg installé"
    }
done

[[ "$SSL_MODE" == "certbot" ]] && { install_pkg certbot; install_pkg python3-certbot-nginx; }

# ── Wine + Xvfb (Enshrouded uniquement — binaire Windows) ────────────────────
if [[ "$GAME_ID" == "enshrouded" ]]; then
    info "Enshrouded requiert Wine (binaire Windows) + Xvfb..."
    # Ajouter le dépôt WineHQ si wine64 absent ou trop ancien
    if ! cmd_exists wine64 || ! dpkg -l wine64 2>/dev/null | grep -q "^ii"; then
        warn "wine64 absent — installation depuis les dépôts système..."
        apt_once
        apt-get install -y -qq wine64 xvfb && ok "Wine64 + Xvfb installés" || die "Échec installation Wine"
    else
        ok "Wine64 déjà présent"
    fi
    # Ubuntu 24.04 : le paquet wine64 n'installe que les libs (/usr/lib/wine/wine64)
    # sans binaire dans le PATH — créer un symlink si nécessaire
    if ! cmd_exists wine64; then
        if cmd_exists wine; then
            ln -sf "$(command -v wine)" /usr/local/bin/wine64
            ok "Symlink wine64 → wine créé dans /usr/local/bin"
        elif [[ -x /usr/lib/wine/wine64 ]]; then
            ln -sf /usr/lib/wine/wine64 /usr/local/bin/wine64
            ok "Symlink wine64 → /usr/lib/wine/wine64 créé"
        else
            die "wine64 introuvable dans le PATH après installation — vérifiez le paquet wine"
        fi
    fi
    if ! cmd_exists xvfb-run; then
        apt_once; apt-get install -y -qq xvfb && ok "Xvfb installé" || warn "Xvfb absent"
    else
        ok "Xvfb déjà présent"
    fi
    # Initialiser le prefix Wine si nécessaire
    if [[ ! -d "$HOME_DIR/.wine" ]]; then
        info "Initialisation du prefix Wine pour $SYS_USER..."
        sudo -u "$SYS_USER" WINEDEBUG=-all wineboot --init 2>/dev/null && ok "Prefix Wine initialisé" || warn "wineboot : vérifiez manuellement"
    else
        ok "Prefix Wine existant"
    fi
fi

# ── SteamCMD ──────────────────────────────────────────────────────────────────
STEAMCMD_PATH=""
if [[ -n "$STEAM_APPID" ]]; then
    if cmd_exists steamcmd; then
        STEAMCMD_PATH=$(command -v steamcmd); ok "SteamCMD : $STEAMCMD_PATH"
    elif [[ -f "$HOME_DIR/steamcmd/steamcmd.sh" ]]; then
        STEAMCMD_PATH="$HOME_DIR/steamcmd/steamcmd.sh"; ok "SteamCMD : $STEAMCMD_PATH"
    else
        warn "SteamCMD introuvable"
        do_steam=false
        $AUTO_INSTALL_STEAMCMD && do_steam=true || { confirm "Installer SteamCMD ?" "o" && do_steam=true; }
        $do_steam && {
            mkdir -p "$HOME_DIR/steamcmd"
            curl -sqL "https://steamcdn-a.akamaihd.net/client/installer/steamcmd_linux.tar.gz" \
                | tar -xzC "$HOME_DIR/steamcmd"
            chown -R "$SYS_USER:$SYS_USER" "$HOME_DIR/steamcmd"
            STEAMCMD_PATH="$HOME_DIR/steamcmd/steamcmd.sh"
            ok "SteamCMD installé : $STEAMCMD_PATH"
        } || die "SteamCMD requis."
    fi
fi

# ═══════════════════════════════════════════════════════════════════════════════
# ÉTAPE 4 — Installation du serveur de jeu
# ═══════════════════════════════════════════════════════════════════════════════
if [[ "$GAME_ID" == "minecraft" ]]; then
    hdr "ÉTAPE 4 : Serveur Minecraft (placeholder)"
    warn "L'installation automatique de Minecraft n'est pas encore implémentée."
    warn "Installez manuellement le serveur dans $SERVER_DIR puis relancez."
    install_pkg "default-jre"
    mkdir -p "$SERVER_DIR"
    chown -R "$SYS_USER:$SYS_USER" "$SERVER_DIR"
    ok "Java installé — serveur à configurer manuellement"
else
    hdr "ÉTAPE 4 : Installation $GAME_LABEL"

    mkdir -p "$SERVER_DIR"
    [[ "$GAME_ID" == "valheim" ]] && mkdir -p "$DATA_DIR"
    chown -R "$SYS_USER:$SYS_USER" "$SERVER_DIR"
    [[ "$GAME_ID" == "valheim" ]] && chown -R "$SYS_USER:$SYS_USER" "$DATA_DIR"

    DO_INSTALL=true
    if [[ -f "$SERVER_DIR/$GAME_BINARY" ]]; then
        ok "$GAME_LABEL déjà installé"
        if $AUTO_UPDATE_SERVER; then
            echo -e "  ${DIM}  (config) Mise à jour → oui${RESET}"
        else
            confirm "Mettre à jour depuis Steam ?" "n" || DO_INSTALL=false
        fi
    fi

    if $DO_INSTALL; then
        info "Téléchargement $GAME_LABEL via SteamCMD (AppID $STEAM_APPID)..."
        info "Cela peut prendre plusieurs minutes..."
        # Enshrouded n'a pas de binaire Linux natif — forcer la plateforme Windows
        _platform="linux"
        [[ "$GAME_ID" == "enshrouded" ]] && _platform="windows"
        sudo -u "$SYS_USER" "$STEAMCMD_PATH" \
            +@sSteamCmdForcePlatformType "$_platform" \
            +login anonymous \
            +force_install_dir "$SERVER_DIR" \
            +app_update "$STEAM_APPID" validate \
            +quit || die "Échec SteamCMD."
        ok "$GAME_LABEL téléchargé"
    fi

    [[ ! -f "$SERVER_DIR/$GAME_BINARY" ]] && die "Binaire $GAME_BINARY introuvable dans $SERVER_DIR"
    [[ "$GAME_ID" != "enshrouded" ]] && chmod +x "$SERVER_DIR/$GAME_BINARY" 2>/dev/null || true
    chown -R "$SYS_USER:$SYS_USER" "$SERVER_DIR"
    ok "Binaire $GAME_BINARY vérifié"

    # BepInEx (Valheim uniquement)
    if [[ "$GAME_ID" == "valheim" ]] && $BEPINEX; then
        BEPINEX_PATH="$SERVER_DIR/BepInEx"
        if [[ -d "$BEPINEX_PATH" ]]; then
            ok "BepInEx déjà présent"
        else
            do_bep=false
            $AUTO_INSTALL_BEPINEX && do_bep=true || { confirm "Installer BepInEx ?" "o" && do_bep=true; }
            $do_bep && {
                info "Téléchargement BepInEx..."
                TMP=$(mktemp -d)
                curl -sL "https://thunderstore.io/package/download/denikson/BepInExPack_Valheim/5.4.2202/" \
                    -o "$TMP/bep.zip"
                unzip -q "$TMP/bep.zip" -d "$TMP/extracted"
                SRC_BEP="$TMP/extracted"
                [[ -d "$TMP/extracted/BepInExPack_Valheim" ]] && SRC_BEP="$TMP/extracted/BepInExPack_Valheim"
                cp -r "$SRC_BEP/." "$SERVER_DIR/"
                chown -R "$SYS_USER:$SYS_USER" "$SERVER_DIR"
                rm -rf "$TMP"
                ok "BepInEx installé"
            }
        fi
    else
        BEPINEX_PATH=""
    fi
fi

# ═══════════════════════════════════════════════════════════════════════════════
# ÉTAPE 5 — Service systemd du serveur de jeu
# ═══════════════════════════════════════════════════════════════════════════════
hdr "ÉTAPE 5 : Service $GAME_LABEL"

if [[ "$GAME_ID" == "minecraft" ]]; then
    warn "Service Minecraft à créer manuellement"
else
    START_SCRIPT="$SERVER_DIR/start_server.sh"

    if [[ "$GAME_ID" == "valheim" ]]; then
        CROSSPLAY_FLAG=""; $CROSSPLAY && CROSSPLAY_FLAG="-crossplay"
        ${GC_FORCE_PLAYFAB} && CROSSPLAY_FLAG="-playfab"

        if $BEPINEX; then
            BEPINEX_NATIVE="$SERVER_DIR/start_server_bepinex.sh"
            if [[ -f "$BEPINEX_NATIVE" ]]; then
                info "start_server_bepinex.sh trouvé — injection des paramètres..."
                CROSSPLAY_ARG=""; $CROSSPLAY && CROSSPLAY_ARG=" -crossplay"
                ${GC_FORCE_PLAYFAB} && CROSSPLAY_ARG=" -playfab"
                python3 - << PYEOF
import re
path   = "${BEPINEX_NATIVE}"
name   = "${SERVER_NAME}"
port   = "${SERVER_PORT}"
world  = "${WORLD_NAME}"
pw     = "${SERVER_PASSWORD}"
save   = "${DATA_DIR}"
extra  = "${CROSSPLAY_ARG}"
new_exec = (
    f'exec ./valheim_server.x86_64'
    f' -name "{name}"'
    f' -port {port}'
    f' -world "{world}"'
    f' -password "{pw}"'
    f' -savedir "{save}"'
    f' -public 1{extra}'
)
with open(path) as f:
    content = f.read()
if re.search(r'^exec \./valheim_server', content, re.MULTILINE):
    content = re.sub(r'^exec \./valheim_server.*$', new_exec, content, flags=re.MULTILINE)
else:
    content = content.rstrip('\n') + '\n' + new_exec + '\n'
with open(path, 'w') as f:
    f.write(content)
print(f"  exec injecté : {new_exec[:80]}...")
PYEOF
                chmod +x "$BEPINEX_NATIVE"
                chown "$SYS_USER:$SYS_USER" "$BEPINEX_NATIVE"
                START_SCRIPT="$BEPINEX_NATIVE"
                ok "Paramètres injectés dans start_server_bepinex.sh"
            else
                warn "start_server_bepinex.sh introuvable — script BepInEx généré"
                cat > "$START_SCRIPT" << STARTEOF
#!/usr/bin/env bash
export DOORSTOP_ENABLE=TRUE
export DOORSTOP_INVOKE_DLL_PATH=./BepInEx/core/BepInEx.Preloader.dll
export DOORSTOP_CORLIB_OVERRIDE_PATH=./unstripped_corlib
export LD_LIBRARY_PATH="./doorstop_libs:\$LD_LIBRARY_PATH"
export LD_PRELOAD="libdoorstop_x64.so:\$LD_PRELOAD"
export LD_LIBRARY_PATH="./linux64:\$LD_LIBRARY_PATH"
export SteamAppId=892970
cd "${SERVER_DIR}"
exec ./valheim_server.x86_64 \\
    -name "${SERVER_NAME}" \\
    -port ${SERVER_PORT} \\
    -world "${WORLD_NAME}" \\
    -password "${SERVER_PASSWORD}" \\
    -savedir "${DATA_DIR}" \\
    -public 1 \\
    ${CROSSPLAY_FLAG}
STARTEOF
                ok "Script BepInEx généré"
            fi
        else
            cat > "$START_SCRIPT" << STARTEOF
#!/usr/bin/env bash
export SteamAppId=892970
export LD_LIBRARY_PATH="${SERVER_DIR}/linux64:\$LD_LIBRARY_PATH"
cd "${SERVER_DIR}"
exec ./valheim_server.x86_64 \\
    -name "${SERVER_NAME}" \\
    -port ${SERVER_PORT} \\
    -world "${WORLD_NAME}" \\
    -password "${SERVER_PASSWORD}" \\
    -savedir "${DATA_DIR}" \\
    -public 1 \\
    ${CROSSPLAY_FLAG}
STARTEOF
            ok "Script standard généré (sans BepInEx)"
        fi

    elif [[ "$GAME_ID" == "enshrouded" ]]; then
        ENSHROUDED_CFG="$SERVER_DIR/enshrouded_server.json"
        info "Génération de enshrouded_server.json..."
        python3 - << PYEOF
import json, os
cfg = {
    "name":          "${SERVER_NAME}",
    "password":      "${SERVER_PASSWORD}",
    "saveDirectory": "./savegame",
    "logDirectory":  "./logs",
    "ip":            "0.0.0.0",
    "queryPort":     int("${SERVER_PORT}") + 1,
    "gamePort":      int("${SERVER_PORT}"),
    "slotCount":     int("${MAX_PLAYERS}"),
}
os.makedirs("${SERVER_DIR}", exist_ok=True)
with open("${ENSHROUDED_CFG}", "w") as f:
    json.dump(cfg, f, indent=2)
print(f"  OK : ${ENSHROUDED_CFG}")
PYEOF
        chown "$SYS_USER:$SYS_USER" "$ENSHROUDED_CFG"
        ok "enshrouded_server.json généré"
        cat > "$START_SCRIPT" << STARTEOF
#!/usr/bin/env bash
export WINEDEBUG=-all
export WINEPREFIX="${HOME_DIR}/.wine"
cd "${SERVER_DIR}"
exec xvfb-run --auto-servernum wine64 ./enshrouded_server.exe
STARTEOF
    fi

    chmod +x "$START_SCRIPT"
    chown "$SYS_USER:$SYS_USER" "$START_SCRIPT"
    ok "Script de démarrage : $START_SCRIPT"

    cat > "/etc/systemd/system/${GAME_SERVICE}.service" << SVCEOF
[Unit]
Description=${GAME_LABEL} Dedicated Server
After=network.target

[Service]
Type=simple
User=${SYS_USER}
WorkingDirectory=${SERVER_DIR}
ExecStart=${START_SCRIPT}
Restart=on-failure
RestartSec=10
SuccessExitStatus=0 130 143
StandardOutput=journal
StandardError=journal
SyslogIdentifier=${GAME_SERVICE}
KillSignal=SIGINT
KillMode=mixed
TimeoutStopSec=60

[Install]
WantedBy=multi-user.target
SVCEOF

    systemctl daemon-reload
    systemctl enable "$GAME_SERVICE"
    info "Démarrage de $GAME_SERVICE..."
    systemctl start "$GAME_SERVICE"
    sleep 5

    service_active "$GAME_SERVICE" \
        && ok "Service $GAME_SERVICE actif" \
        || warn "$GAME_SERVICE pas encore actif — journalctl -u $GAME_SERVICE -f"
fi

# ═══════════════════════════════════════════════════════════════════════════════
# ÉTAPE 6 — Sauvegardes
# ═══════════════════════════════════════════════════════════════════════════════
hdr "ÉTAPE 6 : Sauvegardes automatiques"

mkdir -p "$BACKUP_DIR"
chown "$SYS_USER:$SYS_USER" "$BACKUP_DIR"

case "$GAME_ID" in
    valheim)
        WORLD_DIR="$DATA_DIR/worlds_local"
        [[ ! -d "$WORLD_DIR" ]] && WORLD_DIR="$DATA_DIR/worlds"
        ;;
    enshrouded)
        WORLD_DIR="$SERVER_DIR/savegame"
        ;;
    minecraft)
        WORLD_DIR="$SERVER_DIR/world"
        ;;
esac

BACKUP_SCRIPT="$APP_DIR/backup_${GAME_ID}.sh"

if [[ "$GAME_ID" == "valheim" ]]; then
    cat > "$BACKUP_SCRIPT" << 'BKPEOF'
#!/usr/bin/env bash
BACKUP_DIR="__BACKUP_DIR__"
WORLD_DIR="__WORLD_DIR__"
WORLD_NAME="__WORLD_NAME__"
RETENTION=7
TS=$(date +%Y%m%d_%H%M%S)
ARC="${BACKUP_DIR}/${WORLD_NAME}_${TS}.zip"
FILES=()
for f in "${WORLD_DIR}/${WORLD_NAME}.db" "${WORLD_DIR}/${WORLD_NAME}.fwl" \
          "${WORLD_DIR}/${WORLD_NAME}.db.old" "${WORLD_DIR}/${WORLD_NAME}.fwl.old"; do
    [[ -f "$f" ]] && FILES+=("$f")
done
[[ ${#FILES[@]} -eq 0 ]] && { echo "[$(date)] WARN: aucun fichier monde" >&2; exit 1; }
mkdir -p "$BACKUP_DIR"
zip -j "$ARC" "${FILES[@]}" -q \
    && echo "[$(date)] OK: $(basename "$ARC") ($(du -sh "$ARC"|cut -f1))" \
    || { echo "[$(date)] ERROR: zip échoué" >&2; exit 1; }
find "$BACKUP_DIR" -name "${WORLD_NAME}_*.zip" -mtime +${RETENTION} -delete
BKPEOF
    sed -i "s|__BACKUP_DIR__|${BACKUP_DIR}|g; s|__WORLD_DIR__|${WORLD_DIR}|g; s|__WORLD_NAME__|${WORLD_NAME}|g" "$BACKUP_SCRIPT"
else
    cat > "$BACKUP_SCRIPT" << 'BKPEOF'
#!/usr/bin/env bash
BACKUP_DIR="__BACKUP_DIR__"
WORLD_DIR="__WORLD_DIR__"
PREFIX="__GAME_ID__"
RETENTION=7
TS=$(date +%Y%m%d_%H%M%S)
ARC="${BACKUP_DIR}/${PREFIX}_save_${TS}.zip"
[[ ! -d "$WORLD_DIR" ]] && { echo "[$(date)] WARN: $WORLD_DIR introuvable" >&2; exit 1; }
mkdir -p "$BACKUP_DIR"
zip -r "$ARC" "$WORLD_DIR" -q \
    && echo "[$(date)] OK: $(basename "$ARC") ($(du -sh "$ARC"|cut -f1))" \
    || { echo "[$(date)] ERROR" >&2; exit 1; }
find "$BACKUP_DIR" -name "${PREFIX}_save_*.zip" -mtime +${RETENTION} -delete
BKPEOF
    sed -i "s|__BACKUP_DIR__|${BACKUP_DIR}|g; s|__WORLD_DIR__|${WORLD_DIR}|g; s|__GAME_ID__|${GAME_ID}|g" "$BACKUP_SCRIPT"
fi

chmod +x "$BACKUP_SCRIPT"
chown "$SYS_USER:$SYS_USER" "$BACKUP_SCRIPT"
ok "Script de sauvegarde : $BACKUP_SCRIPT"

sudo -u "$SYS_USER" bash "$BACKUP_SCRIPT" 2>/dev/null \
    && ok "Test sauvegarde réussi" \
    || warn "Test sauvegarde : aucun fichier trouvé (normal avant le premier lancement)"

CRON_LINE="0 3 * * * $BACKUP_SCRIPT >> $APP_DIR/backup_${GAME_ID}.log 2>&1"
EXISTING=$(crontab -u "$SYS_USER" -l 2>/dev/null || echo "")
echo "$EXISTING" | grep -qF "$BACKUP_SCRIPT" \
    && ok "Cron déjà configuré" \
    || { (echo "$EXISTING"; echo "$CRON_LINE") | crontab -u "$SYS_USER" -; ok "Cron : 3h00 quotidien"; }

# ═══════════════════════════════════════════════════════════════════════════════
# ÉTAPE 7 — Déploiement Game Commander
# ═══════════════════════════════════════════════════════════════════════════════
hdr "ÉTAPE 7 : Game Commander"

if ! $DEPLOY_APP; then
    warn "Sources introuvables — Game Commander ignoré"
else
    mkdir -p "$APP_DIR"
    rsync -a --exclude='__pycache__' --exclude='*.pyc' --exclude='metrics.log' \
              --exclude='users.json' --exclude='game.json' --exclude='deploy_config.env' \
              "$SRC_DIR/" "$APP_DIR/"
    chown -R "$SYS_USER:$SYS_USER" "$APP_DIR"
    ok "Fichiers Game Commander copiés dans $APP_DIR"

    GC_BEPINEX_PATH=""
    [[ "$GAME_ID" == "valheim" ]] && $BEPINEX && GC_BEPINEX_PATH="${SERVER_DIR}/BepInEx"

    python3 - << PYEOF
import json, os
game = {
    "id":       "${GAME_ID}",
    "name":     "${GAME_LABEL}",
    "subtitle": "${SERVER_NAME}",
    "logo":     {"valheim":"⚔","enshrouded":"🌿","minecraft":"⛏"}.get("${GAME_ID}","🎮"),
    "server": {
        "binary":      "${GAME_BINARY}",
        "service":     "${GAME_SERVICE}",
        "install_dir": "${SERVER_DIR}",
        "data_dir":    "${DATA_DIR:-${SERVER_DIR}}",
        "world_name":  "${WORLD_NAME}" if "${GAME_ID}" == "valheim" else None,
        "max_players": int("${MAX_PLAYERS}"),
        "port":        int("${SERVER_PORT}"),
    },
    "web": {
        "url_prefix": "${URL_PREFIX}",
        "flask_port": int("${FLASK_PORT}"),
        "admin_user": "${ADMIN_LOGIN}",
    },
    "features": {
        "mods":    "${GAME_ID}" == "valheim" and bool("${GC_BEPINEX_PATH}"),
        "config":  "${GAME_ID}" in ("valheim", "enshrouded"),
        "console": True,
        "players": False,
    },
    "permissions": (
        ["start_server","stop_server","restart_server",
         "install_mod","remove_mod","manage_config","console","manage_users"]
        if "${GAME_ID}" == "valheim"
        else ["start_server","stop_server","restart_server","manage_config","console","manage_users"]
        if "${GAME_ID}" == "enshrouded"
        else ["start_server","stop_server","restart_server","console","manage_users"]
    ),
    "theme": {"name": "${GAME_ID}" if "${GAME_ID}" in ("valheim","enshrouded") else "valheim"},
}
if "${GAME_ID}" == "valheim" and "${GC_BEPINEX_PATH}":
    game["mods"] = {
        "platform":     "thunderstore",
        "community":    "valheim",
        "bepinex_path": "${GC_BEPINEX_PATH}",
    }
if "${STEAM_APPID}":
    game["steamcmd"] = {
        "app_id": "${STEAM_APPID}",
        "path":   "${STEAMCMD_PATH:-}",
    }
out = os.path.join("${APP_DIR}", "game.json")
with open(out, "w") as f:
    json.dump(game, f, indent=2, ensure_ascii=False)
print(f"  game.json généré : {out}")
PYEOF
    ok "game.json généré"

    USERS_FILE="$APP_DIR/users.json"
    if [[ -f "$USERS_FILE" ]]; then
        ok "users.json existant conservé"
    else
        ADMIN_HASH=$(python3 -c "
import bcrypt, sys
print(bcrypt.hashpw(sys.argv[1].encode(), bcrypt.gensalt()).decode())
" "$ADMIN_PASSWORD")

        python3 - << PYEOF
import json
perms = ["start_server","stop_server","restart_server","install_mod","remove_mod",
         "manage_config","console","manage_users"] if "${GAME_ID}"=="valheim" else \
        ["start_server","stop_server","restart_server","manage_config","console","manage_users"]
data = {"${ADMIN_LOGIN}": {"password_hash": "${ADMIN_HASH}", "permissions": perms}}
with open("${USERS_FILE}", "w") as f:
    json.dump(data, f, indent=2)
PYEOF
        chmod 600 "$USERS_FILE"
        chown "$SYS_USER:$SYS_USER" "$USERS_FILE"
        ok "users.json créé — admin : $ADMIN_LOGIN"
    fi
fi

METRICS_FILE="$APP_DIR/metrics.log"
if [[ ! -f "$METRICS_FILE" ]]; then
    touch "$METRICS_FILE"
    chown "$SYS_USER:$SYS_USER" "$METRICS_FILE"
    chmod 640 "$METRICS_FILE"
    ok "metrics.log créé"
fi

# ═══════════════════════════════════════════════════════════════════════════════
# ÉTAPE 8 — Service Flask
# ═══════════════════════════════════════════════════════════════════════════════
hdr "ÉTAPE 8 : Service Game Commander"

if $DEPLOY_APP; then
    GC_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
    cat > "/etc/systemd/system/${GC_SERVICE}.service" << SVCEOF
[Unit]
Description=Game Commander — ${GAME_LABEL}
After=network.target
Wants=${GAME_SERVICE}.service

[Service]
Type=simple
User=${SYS_USER}
WorkingDirectory=${APP_DIR}
Environment="GAME_COMMANDER_SECRET=${GC_SECRET}"
ExecStart=/usr/bin/python3 ${APP_DIR}/app.py
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
SVCEOF
    systemctl daemon-reload
    systemctl enable "$GC_SERVICE"
    systemctl restart "$GC_SERVICE"
    sleep 2
    service_active "$GC_SERVICE" \
        && ok "Service $GC_SERVICE actif" \
        || err "$GC_SERVICE inactif — journalctl -u $GC_SERVICE -n 30"
fi

# ═══════════════════════════════════════════════════════════════════════════════
# ÉTAPE 9 — Nginx
# ═══════════════════════════════════════════════════════════════════════════════
hdr "ÉTAPE 9 : Nginx"

NGINX_CONF=""
for c in "/etc/nginx/conf.d/${DOMAIN}.conf" \
         "/etc/nginx/sites-enabled/${DOMAIN}.conf" \
         "/etc/nginx/sites-available/${DOMAIN}.conf" \
         "/etc/nginx/sites-available/${DOMAIN}"; do
    [[ -f "$c" ]] && { NGINX_CONF="$c"; break; }
done
if [[ -z "$NGINX_CONF" ]]; then
    while IFS= read -r _f; do
        grep -q "server_name.*${DOMAIN}" "$_f" 2>/dev/null && { NGINX_CONF="$_f"; break; }
    done < <(find /etc/nginx -name "*.conf" 2>/dev/null)
fi

LOC_BLOCK="    # ── Game Commander — ${GAME_LABEL} (${INSTANCE_ID}) ──────────────────────
    location ${URL_PREFIX} {
        proxy_pass         http://127.0.0.1:${FLASK_PORT};
        proxy_http_version 1.1;
        proxy_set_header   Host              \$host;
        proxy_set_header   X-Real-IP         \$remote_addr;
        proxy_set_header   X-Forwarded-For   \$proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto \$scheme;
        proxy_read_timeout 120s;
        proxy_send_timeout 120s;
    }
    location ${URL_PREFIX}/static {
        proxy_pass http://127.0.0.1:${FLASK_PORT};
        expires 1h;
        add_header Cache-Control \"public\";
    }
    # ─────────────────────────────────────────────────────────────────────────"

if [[ -n "$NGINX_CONF" ]]; then
    ok "Vhost existant : $NGINX_CONF"
    if grep -q "location ${URL_PREFIX}" "$NGINX_CONF" 2>/dev/null; then
        warn "Bloc ${URL_PREFIX} déjà présent — ignoré"
    else
        cp "$NGINX_CONF" "${NGINX_CONF}.bak.$(date +%Y%m%d%H%M%S)"
        python3 - << PYEOF
import re
content = open('${NGINX_CONF}').read()
block = """${LOC_BLOCK}
"""
# Cibler le bloc server SSL (listen 443) pour y injecter le location
ssl_match = re.search(r'listen\s+443\s+ssl', content)
if ssl_match:
    # Remonter au debut du bloc server contenant "listen 443"
    start = content.rfind('server {', 0, ssl_match.start())
    # Trouver la } fermante de ce bloc en comptant les accolades
    depth = 0
    insert_pos = -1
    for idx in range(start, len(content)):
        if content[idx] == '{':
            depth += 1
        elif content[idx] == '}':
            depth -= 1
            if depth == 0:
                insert_pos = idx
                break
    if insert_pos > 0:
        content = content[:insert_pos] + block + "\n}" + content[insert_pos+1:]
    else:
        i = content.rfind('}')
        content = content[:i] + block + "\n}" + content[i+1:]
elif '    location / {' in content:
    content = content.replace('    location / {', block + '\n    location / {', 1)
else:
    i = content.rfind('}')
    content = content[:i] + block + "\n}" + content[i+1:]
with open('${NGINX_CONF}', 'w') as f:
    f.write(content)
print('OK')
PYEOF
        ok "Bloc location injecté"
    fi
else
    _amp_managed=false
    [[ -d "${HOME_DIR}/.ampdata" ]] || [[ -f /opt/cubecoders/amp/AMP ]] && _amp_managed=true
    NGINX_CONF="/etc/nginx/conf.d/${DOMAIN}.conf"
    if $_amp_managed; then
        warn "Aucun vhost Nginx trouvé pour ${DOMAIN}"
        warn "AMP semble gérer ce serveur — ajoutez manuellement le bloc location dans le vhost SSL d'AMP."
    fi
    cat > "$NGINX_CONF" << NGEOF
server {
    listen 80;
    server_name ${DOMAIN};
${LOC_BLOCK}
}
NGEOF
    ok "Nouveau vhost port 80 : $NGINX_CONF"
fi

nginx -t 2>/dev/null && { systemctl reload nginx; ok "Nginx reloadé"; } \
                     || err "Erreur Nginx — vérifiez avec nginx -t"

# ═══════════════════════════════════════════════════════════════════════════════
# ÉTAPE 10 — SSL
# ═══════════════════════════════════════════════════════════════════════════════
hdr "ÉTAPE 10 : SSL"
case "$SSL_MODE" in
    certbot)
        cmd_exists certbot \
            && { certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos \
                    --register-unsafely-without-email 2>/dev/null \
                 && ok "Certificat SSL obtenu" \
                 || warn "Certbot échoué — $DOMAIN doit pointer sur ce serveur"; } \
            || warn "Certbot non disponible" ;;
    existing) ok "SSL existant — non modifié" ;;
    none)     warn "HTTP uniquement" ;;
esac

# ═══════════════════════════════════════════════════════════════════════════════
# ÉTAPE 11 — Sudoers
# ═══════════════════════════════════════════════════════════════════════════════
hdr "ÉTAPE 11 : Permissions sudo"

SUDOERS_FILE="/etc/sudoers.d/game-commander-${INSTANCE_ID}"
{
    echo "# Game Commander — ${GAME_LABEL} (${INSTANCE_ID})"
    echo "${SYS_USER} ALL=(ALL) NOPASSWD: /usr/bin/systemctl start ${GAME_SERVICE}"
    echo "${SYS_USER} ALL=(ALL) NOPASSWD: /usr/bin/systemctl stop ${GAME_SERVICE}"
    echo "${SYS_USER} ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart ${GAME_SERVICE}"
    if [[ "$GAME_ID" == "valheim" ]] && [[ -n "${GC_BEPINEX_PATH:-}" ]]; then
        BP="$GC_BEPINEX_PATH"
        echo "${SYS_USER} ALL=(ALL) NOPASSWD: /usr/bin/chown -R ${SYS_USER} ${BP}"
        echo "${SYS_USER} ALL=(ALL) NOPASSWD: /usr/bin/chmod -R 755 ${BP}"
        echo "${SYS_USER} ALL=(ALL) NOPASSWD: /usr/bin/find ${BP} -type d"
        echo "${SYS_USER} ALL=(ALL) NOPASSWD: /bin/rm -rf ${BP}/plugins/*"
        echo "${SYS_USER} ALL=(ALL) NOPASSWD: /bin/rm -f ${BP}/plugins/*"
    fi
} > "$SUDOERS_FILE"

chmod 440 "$SUDOERS_FILE"
VISUDO_ERR=$(visudo -cf "$SUDOERS_FILE" 2>&1)
if [[ $? -eq 0 ]]; then
    ok "Sudoers : $SUDOERS_FILE"
else
    err "Sudoers invalide — supprimé"
    warn "Erreur visudo : $VISUDO_ERR"
    rm -f "$SUDOERS_FILE"
    warn "À créer manuellement :"
    echo "    sudo tee /etc/sudoers.d/game-commander-${INSTANCE_ID} > /dev/null << 'EOF'"
    echo "    ${SYS_USER} ALL=(ALL) NOPASSWD: /usr/bin/systemctl start ${GAME_SERVICE}"
    echo "    ${SYS_USER} ALL=(ALL) NOPASSWD: /usr/bin/systemctl stop ${GAME_SERVICE}"
    echo "    ${SYS_USER} ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart ${GAME_SERVICE}"
    echo "    EOF"
fi

# ═══════════════════════════════════════════════════════════════════════════════
# ÉTAPE 12 — Sauvegarde de la configuration
# ═══════════════════════════════════════════════════════════════════════════════
CONFIG_SAVE="$APP_DIR/deploy_config.env"
{
    echo "# Game Commander — Config sauvegardée le $(date '+%Y-%m-%d %H:%M:%S')"
    echo "# Redéploiement : sudo bash game_commander.sh deploy --config $CONFIG_SAVE"
    echo ""
    echo "GAME_ID=\"${GAME_ID}\""
    echo "INSTANCE_ID=\"${INSTANCE_ID}\""
    echo "SYS_USER=\"${SYS_USER}\""
    echo "SERVER_DIR=\"${SERVER_DIR}\""
    echo "DATA_DIR=\"${DATA_DIR}\""
    echo "BACKUP_DIR=\"${BACKUP_DIR}\""
    echo "APP_DIR=\"${APP_DIR}\""
    echo "SRC_DIR=\"${SRC_DIR}\""
    echo "SERVER_NAME=\"${SERVER_NAME}\""
    echo "SERVER_PORT=\"${SERVER_PORT}\""
    echo "MAX_PLAYERS=\"${MAX_PLAYERS}\""
    [[ "$GAME_ID" == "valheim" ]] && {
        echo "WORLD_NAME=\"${WORLD_NAME}\""
        echo "CROSSPLAY=${CROSSPLAY}"
        echo "BEPINEX=${BEPINEX}"
    }
    echo "DOMAIN=\"${DOMAIN}\""
    echo "URL_PREFIX=\"${URL_PREFIX}\""
    echo "FLASK_PORT=\"${FLASK_PORT}\""
    echo "SSL_MODE=\"${SSL_MODE}\""
    echo "ADMIN_LOGIN=\"${ADMIN_LOGIN}\""
    echo "# ADMIN_PASSWORD=  <-- ne pas sauvegarder en clair"
    echo "AUTO_INSTALL_DEPS=true"
    echo "AUTO_UPDATE_SERVER=false"
    echo "AUTO_CONFIRM=true"
} > "$CONFIG_SAVE"
chmod 600 "$CONFIG_SAVE"
chown "$SYS_USER:$SYS_USER" "$CONFIG_SAVE"
ok "Config sauvegardée : $CONFIG_SAVE"

# ═══════════════════════════════════════════════════════════════════════════════
# VALIDATION FINALE
# ═══════════════════════════════════════════════════════════════════════════════
hdr "VALIDATION FINALE"
echo ""
ERRORS=0

if [[ "$GAME_ID" != "minecraft" ]]; then
    service_active "$GAME_SERVICE" \
        && ok "Service $GAME_SERVICE : actif" \
        || { warn "Service $GAME_SERVICE : inactif"; ERRORS=$((ERRORS+1)); }
fi

if $DEPLOY_APP; then
    sleep 1
    curl -sf "http://127.0.0.1:${FLASK_PORT}${URL_PREFIX}" -o /dev/null 2>/dev/null \
        && ok "Game Commander répond sur :${FLASK_PORT}${URL_PREFIX}" \
        || { warn "Game Commander ne répond pas encore"; ERRORS=$((ERRORS+1)); }
fi

service_active nginx && ok "Nginx : actif" || { warn "Nginx : inactif"; ERRORS=$((ERRORS+1)); }

echo ""
sep
echo ""
echo -e "  ${BOLD}Accès à l'interface :${RESET}"
[[ "$SSL_MODE" != "none" ]] \
    && echo -e "  ${CYAN}  https://${DOMAIN}${URL_PREFIX}${RESET}" \
    || echo -e "  ${CYAN}  http://${DOMAIN}${URL_PREFIX}${RESET}"
echo ""
echo -e "  ${BOLD}Commandes utiles :${RESET}"
echo "    sudo systemctl status ${GAME_SERVICE}"
$DEPLOY_APP && echo "    sudo systemctl status ${GC_SERVICE}"
echo "    sudo journalctl -u ${GAME_SERVICE} -f"
$DEPLOY_APP && echo "    sudo journalctl -u ${GC_SERVICE} -f"
echo ""
echo -e "  ${BOLD}Redéploiement rapide :${RESET}"
echo "    sudo bash game_commander.sh deploy --config $CONFIG_SAVE"
echo ""

# ── Rappels UFW et Hetzner firewall ──────────────────────────────────────────
# Ports jeu selon le jeu
_GAME_PORTS=("${SERVER_PORT}/udp" "$((SERVER_PORT+1))/udp")
echo -e "  ${BOLD}Ports à ouvrir (firewall) :${RESET}"
echo -e "    Jeu  : ${SERVER_PORT}/UDP  $((SERVER_PORT+1))/UDP"
echo -e "    Web  : 80/TCP  443/TCP"
if command -v ufw &>/dev/null && ufw status 2>/dev/null | grep -q "Status: active"; then
    info "UFW actif — ouverture des ports..."
    for _p in "${_GAME_PORTS[@]}"; do
        ufw allow "$_p" && ok "UFW : $_p ouvert"
    done
    ufw allow "80/tcp"  && ok "UFW : 80/tcp ouvert"
    ufw allow "443/tcp" && ok "UFW : 443/tcp ouvert"
else
    warn "UFW inactif ou absent — pensez à ouvrir les ports dans le firewall Hetzner :"
    echo "    ${SERVER_PORT}/UDP, $((SERVER_PORT+1))/UDP, 80/TCP, 443/TCP"
fi
echo ""
[[ $ERRORS -eq 0 ]] \
    && echo -e "  ${GREEN}${BOLD}✓ Déploiement terminé avec succès !${RESET}" \
    || echo -e "  ${YELLOW}${BOLD}⚠ Déploiement terminé avec $ERRORS avertissement(s)${RESET}"
echo ""
info "Journal complet : $LOGFILE"

} # fin cmd_deploy

# ═══════════════════════════════════════════════════════════════════════════════
# UNINSTALL
# ═══════════════════════════════════════════════════════════════════════════════
cmd_uninstall() {

[[ $EUID -ne 0 ]] && { err "Ce script doit être exécuté en root (sudo)"; exit 1; }
$DRY_RUN && warn "MODE DRY-RUN — aucune modification ne sera effectuée"

# ═══════════════════════════════════════════════════════════════════════════════
#  PARTIE A — Installations Game Commander (deploy_config.env)
# ═══════════════════════════════════════════════════════════════════════════════
hdr "A — Recherche installations Game Commander"

mapfile -t DEPLOY_CONFIGS < <(
    find /home /opt /root -maxdepth 5 -name "deploy_config.env" 2>/dev/null \
    | xargs -I{} grep -l "GAME_ID=" {} 2>/dev/null \
    | sort -u
)

declare -a GC_ENTRIES=()

if [[ ${#DEPLOY_CONFIGS[@]} -eq 0 ]]; then
    info "Aucune installation Game Commander trouvée."
else
    echo ""
    for cfg in "${DEPLOY_CONFIGS[@]}"; do
        unset GAME_ID INSTANCE_ID SYS_USER SERVER_DIR DATA_DIR BACKUP_DIR \
              APP_DIR DOMAIN FLASK_PORT SERVER_NAME GC_SERVICE GAME_SERVICE
        source <(grep -E '^[A-Z_]+=' "$cfg" 2>/dev/null)

        GAME_ID="${GAME_ID:-?}"
        INSTANCE_ID="${INSTANCE_ID:-$GAME_ID}"
        SYS_USER="${SYS_USER:-?}"
        SERVER_DIR="${SERVER_DIR:-}"
        DATA_DIR="${DATA_DIR:-}"
        APP_DIR="${APP_DIR:-}"
        DOMAIN="${DOMAIN:-}"
        FLASK_PORT="${FLASK_PORT:-?}"
        SERVER_NAME="${SERVER_NAME:-}"
        GC_SERVICE="game-commander-${INSTANCE_ID}"
        GAME_SERVICE="${GAME_ID}-server-${INSTANCE_ID}"
        GC_STATE=$(service_state "$GC_SERVICE")
        GAME_STATE=$(service_state "$GAME_SERVICE")

        idx=${#GC_ENTRIES[@]}
        GC_ENTRIES+=("$cfg")

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
        [[ -n "$SERVER_NAME"  ]] && echo -e "         Nom          : $SERVER_NAME"
        [[ -n "$DOMAIN"       ]] && echo -e "         Domaine      : $DOMAIN  (port $FLASK_PORT)"
        [[ -n "$SYS_USER"     ]] && echo -e "         Utilisateur  : $SYS_USER"
        [[ -n "$SERVER_DIR" && -d "$SERVER_DIR" ]] && \
            echo -e "         Dossier jeu  : $SERVER_DIR  $(du -sh "$SERVER_DIR" 2>/dev/null | cut -f1)"
        [[ -n "$DATA_DIR"   && -d "$DATA_DIR"   && "$DATA_DIR" != "$SERVER_DIR" ]] && \
            echo -e "         Dossier data : $DATA_DIR  $(du -sh "$DATA_DIR" 2>/dev/null | cut -f1)"
        [[ -n "$APP_DIR"    && -d "$APP_DIR"    ]] && \
            echo -e "         Dossier app  : $APP_DIR  $(du -sh "$APP_DIR" 2>/dev/null | cut -f1)"
        sep
    done

    echo -e "  Entrez les numéros à traiter (ex: ${BOLD}A1 A2${RESET}), ${BOLD}all${RESET} pour tout, ${BOLD}skip${RESET} pour passer :"
    echo -en "  ${YELLOW}?  Sélection : ${RESET}"
    read -r gc_sel

    if [[ "$gc_sel" != "skip" && -n "$gc_sel" ]]; then
        declare -a GC_SELECTED=()
        if [[ "$gc_sel" == "all" ]]; then
            for i in "${!GC_ENTRIES[@]}"; do GC_SELECTED+=($i); done
        else
            for tok in $gc_sel; do
                tok="${tok^^}"; tok="${tok#A}"
                if [[ "$tok" =~ ^[0-9]+$ ]] && (( tok >= 1 && tok <= ${#GC_ENTRIES[@]} )); then
                    GC_SELECTED+=($((tok-1)))
                else
                    warn "Numéro invalide : $tok — ignoré"
                fi
            done
        fi

        if [[ ${#GC_SELECTED[@]} -gt 0 ]]; then
            echo ""
            echo -e "  Que souhaitez-vous faire ?"
            echo -e "    ${BOLD}1${RESET}) Stopper les services (fichiers conservés)"
            echo -e "    ${BOLD}2${RESET}) Désinstaller complètement (services + fichiers)"
            echo -en "  ${YELLOW}?  Choix : ${RESET}"
            read -r gc_action

            for idx in "${GC_SELECTED[@]}"; do
                cfg="${GC_ENTRIES[$idx]}"
                unset GAME_ID INSTANCE_ID SYS_USER SERVER_DIR DATA_DIR BACKUP_DIR \
                      APP_DIR DOMAIN FLASK_PORT SERVER_NAME
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
                    # Nginx
                    NGINX_CONF=""
                    for nf in "/etc/nginx/conf.d/${DOMAIN:-___}.conf" \
                              "/etc/nginx/sites-enabled/${DOMAIN:-___}.conf" \
                              "/etc/nginx/sites-available/${DOMAIN:-___}.conf"; do
                        [[ -f "$nf" ]] && { NGINX_CONF="$nf"; break; }
                    done
                    [[ -z "$NGINX_CONF" && -n "${FLASK_PORT:-}" ]] && \
                        NGINX_CONF=$(grep -rl "127.0.0.1:${FLASK_PORT}" \
                            /etc/nginx/conf.d/ /etc/nginx/sites-enabled/ 2>/dev/null | head -1 || true)

                    if [[ -n "$NGINX_CONF" && -f "$NGINX_CONF" ]]; then
                        # Compter les blocs location dans le fichier
                        _loc_count=$(grep -c '^\s*location ' "$NGINX_CONF" 2>/dev/null || echo 0)
                        _has_our_block=$(grep -c "location ${URL_PREFIX:-___}" "$NGINX_CONF" 2>/dev/null || echo 0)

                        if (( _loc_count <= 2 && _has_our_block > 0 )); then
                            # Seule notre instance dans ce fichier — proposer suppression totale
                            if ask_yn "Supprimer vhost Nginx : ${BOLD}$NGINX_CONF${RESET} (seule instance) ?"; then
                                run rm -f "$NGINX_CONF"
                                ok "Vhost Nginx supprimé"
                                run nginx -t 2>/dev/null && run systemctl reload nginx || true
                            fi
                        elif (( _has_our_block > 0 )); then
                            # Fichier partagé — retirer uniquement le bloc location de cette instance
                            if ask_yn "Retirer le bloc ${BOLD}${URL_PREFIX}${RESET} du vhost ${BOLD}$NGINX_CONF${RESET} (partagé) ?"; then
                                cp "$NGINX_CONF" "${NGINX_CONF}.bak.$(date +%Y%m%d%H%M%S)"
                                python3 - << PYEOF
import re, sys
with open('${NGINX_CONF}', 'r') as f:
    content = f.read()
# Supprimer le commentaire + les blocs location de cette instance
pattern = r'\n?[ \t]*# ── Game Commander[^\n]*\(${INSTANCE_ID}\)[^\n]*\n.*?location ${URL_PREFIX}/static \{[^}]*\}[ \t]*\n?[ \t]*# ─+\n?'
result = re.sub(pattern, '\n', content, flags=re.DOTALL)
# Fallback : supprimer juste les blocs location si pas de commentaire
if result == content:
    pattern2 = r'\n?[ \t]*location ${URL_PREFIX} \{[^}]*\}\n?[ \t]*location ${URL_PREFIX}/static \{[^}]*\}\n?'
    result = re.sub(pattern2, '\n', content, flags=re.DOTALL)
with open('${NGINX_CONF}', 'w') as f:
    f.write(result)
print('OK')
PYEOF
                                ok "Bloc ${URL_PREFIX} retiré du vhost"
                                run nginx -t 2>/dev/null && run systemctl reload nginx || true
                            fi
                        else
                            warn "Bloc ${URL_PREFIX} non trouvé dans $NGINX_CONF — vérifiez manuellement"
                        fi
                    fi

                    # Sudoers
                    for sf in "/etc/sudoers.d/game-commander-${GAME_ID}" \
                              "/etc/sudoers.d/game-commander-${INSTANCE_ID}" \
                              "/etc/sudoers.d/${GC_SERVICE}"; do
                        if [[ -f "$sf" ]]; then
                            if ask_yn "Supprimer sudoers : ${BOLD}$sf${RESET} ?"; then
                                run rm -f "$sf"
                                ok "Sudoers supprimé"
                            fi
                        fi
                    done

                    # Cron backup
                    if [[ -n "$SYS_USER" && -n "${APP_DIR:-}" ]]; then
                        cron_count=$(crontab -u "$SYS_USER" -l 2>/dev/null \
                            | grep -c "$APP_DIR" || true)
                        if (( cron_count > 0 )); then
                            if ask_yn "Supprimer entrée cron backup de $SYS_USER ?"; then
                                run bash -c \
                                    "crontab -u '$SYS_USER' -l 2>/dev/null \
                                     | grep -v '$APP_DIR' \
                                     | crontab -u '$SYS_USER' -"
                                ok "Entrée cron supprimée"
                            fi
                        fi
                    fi

                    # Dossiers
                    HOME_DIR=$(eval echo "~${SYS_USER:-root}")
                    remove_dir_safe "${APP_DIR:-}"    "répertoire Game Commander" "$cfg"
                    remove_dir_safe "${SERVER_DIR:-}" "répertoire serveur jeu"    "$cfg"
                    if [[ -n "${DATA_DIR:-}" && "${DATA_DIR:-}" != "${SERVER_DIR:-}" ]]; then
                        remove_dir_safe "${DATA_DIR:-}" "répertoire données jeu"  "$cfg"
                    fi

                    STEAMCMD_DIR="$HOME_DIR/steamcmd"
                    if [[ -d "$STEAMCMD_DIR" ]]; then
                        others=$(shared_by_others "$STEAMCMD_DIR" "$cfg")
                        if [[ -n "$others" ]]; then
                            info "SteamCMD conservé — utilisé aussi par : $others"
                        else
                            remove_dir "$STEAMCMD_DIR" "SteamCMD"
                        fi
                    fi

                    if [[ -n "${BACKUP_DIR:-}" && -d "${BACKUP_DIR:-}" ]]; then
                        others=$(shared_by_others "${BACKUP_DIR:-}" "$cfg")
                        if [[ -n "$others" ]]; then
                            info "Sauvegardes conservées — utilisées aussi par : $others"
                        else
                            remove_dir "$BACKUP_DIR" "répertoire sauvegardes"
                        fi
                    fi
                fi
                ok "Terminé : $INSTANCE_ID"

                    # ── Désinstallation Wine si plus aucune instance Enshrouded ──
                    if [[ "${GAME_ID:-}" == "enshrouded" && "$gc_action" == "2" ]]; then
                        _remaining=$(find /home /opt /root -maxdepth 5 -name "deploy_config.env" 2>/dev/null \
                            | xargs grep -l 'GAME_ID="enshrouded"' 2>/dev/null | wc -l)
                        _amp_enshrouded=$(find /home /root /opt -maxdepth 6 \
                            -name "instances.json" -path "*/.ampdata/*" 2>/dev/null \
                            | xargs grep -l '"Enshrouded"' 2>/dev/null | wc -l)
                        if (( _remaining == 0 && _amp_enshrouded == 0 )); then
                            if ask_yn "Plus aucune instance Enshrouded — désinstaller Wine64/Xvfb ?"; then
                                run apt-get remove -y wine64 xvfb 2>/dev/null \
                                    && ok "Wine64/Xvfb désinstallés" \
                                    || warn "Désinstallation Wine incomplète"
                                run apt-get autoremove -y 2>/dev/null || true
                            fi
                        else
                            (( _remaining > 0 )) && \
                                info "Wine conservé — $_remaining autre(s) instance(s) Enshrouded (Game Commander)"
                            (( _amp_enshrouded > 0 )) && \
                                info "Wine conservé — $_amp_enshrouded instance(s) Enshrouded détectée(s) dans AMP"
                        fi
                    fi
            done
        fi
    fi
fi

# ═══════════════════════════════════════════════════════════════════════════════
#  PARTIE B — Applications Flask génériques (systemd)
# ═══════════════════════════════════════════════════════════════════════════════
hdr "B — Recherche applications Flask génériques (systemd)"

declare -a ALREADY_HANDLED=()
for cfg in "${DEPLOY_CONFIGS[@]:-}"; do
    [[ -z "$cfg" ]] && continue
    _dir=$(grep '^APP_DIR=' "$cfg" 2>/dev/null | cut -d= -f2- | tr -d '"')
    [[ -n "$_dir" ]] && ALREADY_HANDLED+=("$_dir")
done

declare -a FL_NAMES=() FL_STATES=() FL_WORK_DIRS=() FL_USERS=() FL_PORTS=() FL_NGINX=()

while IFS= read -r svc; do
    unit_file="/etc/systemd/system/${svc}"
    [[ ! -f "$unit_file" ]] && unit_file="/lib/systemd/system/${svc}"
    [[ ! -f "$unit_file" ]] && continue
    exec_line=$(grep -i '^ExecStart=' "$unit_file" 2>/dev/null | head -1)
    echo "$exec_line" | grep -qiE 'python|gunicorn|uvicorn|flask' || continue
    work_dir=$(grep '^WorkingDirectory=' "$unit_file" 2>/dev/null | head -1 | cut -d= -f2-)
    [[ -z "$work_dir" ]] && continue
    already=false
    for handled in "${ALREADY_HANDLED[@]:-}"; do
        [[ "$handled" == "$work_dir" ]] && already=true && break
    done
    $already && continue
    is_flask=false
    [[ -f "$work_dir/app.py"  ]] && is_flask=true
    [[ -f "$work_dir/wsgi.py" ]] && is_flask=true
    grep -qiE 'flask|gunicorn' "$work_dir/requirements.txt" 2>/dev/null && is_flask=true
    $is_flask || continue
    state=$(systemctl is-active "${svc%.service}" 2>/dev/null || echo "inactive")
    svc_user=$(grep '^User=' "$unit_file" 2>/dev/null | head -1 | cut -d= -f2-)
    [[ -z "$svc_user" ]] && svc_user="root"
    port=""
    [[ -f "$work_dir/game.json" ]] && \
        port=$(python3 -c \
            "import json,sys; d=json.load(open('$work_dir/game.json')); \
             print(d.get('web',{}).get('flask_port',''))" 2>/dev/null || true)
    [[ -z "$port" ]] && port=$(grep -oP '(?<=port=)\d+' "$work_dir/app.py" 2>/dev/null | tail -1 || true)
    [[ -z "$port" ]] && port="?"
    nginx_file=""
    [[ "$port" != "?" ]] && \
        nginx_file=$(grep -rl "127.0.0.1:${port}" \
            /etc/nginx/conf.d/ /etc/nginx/sites-enabled/ 2>/dev/null | head -1 || true)
    FL_NAMES+=("${svc%.service}")
    FL_STATES+=("$state")
    FL_WORK_DIRS+=("$work_dir")
    FL_USERS+=("$svc_user")
    FL_PORTS+=("$port")
    FL_NGINX+=("$nginx_file")
done < <(systemctl list-unit-files --type=service --no-legend 2>/dev/null \
         | awk '{print $1}' | grep -v '@')

if [[ ${#FL_NAMES[@]} -eq 0 ]]; then
    info "Aucune application Flask générique trouvée."
else
    echo ""
    for i in "${!FL_NAMES[@]}"; do
        case "${FL_STATES[$i]}" in
            active) st="${GREEN}● actif${RESET}"   ;;
            failed) st="${RED}✗ échoué${RESET}"    ;;
            *)      st="${DIM}○ inactif${RESET}"   ;;
        esac
        echo -e "  ${BOLD}[B$((i+1))]${RESET}  ${FL_NAMES[$i]}"
        echo -e "         État       : $st"
        echo -e "         Répertoire : ${FL_WORK_DIRS[$i]}  $(du -sh "${FL_WORK_DIRS[$i]}" 2>/dev/null | cut -f1)"
        echo -e "         Utilisateur: ${FL_USERS[$i]}"
        echo -e "         Port       : ${FL_PORTS[$i]}"
        [[ -n "${FL_NGINX[$i]}" ]] && echo -e "         Nginx      : ${FL_NGINX[$i]}"
        sep
    done

    echo -e "  Entrez les numéros à traiter (ex: ${BOLD}B1 B2${RESET}), ${BOLD}all${RESET} pour tout, ${BOLD}skip${RESET} pour passer :"
    echo -en "  ${YELLOW}?  Sélection : ${RESET}"
    read -r fl_sel

    if [[ "$fl_sel" != "skip" && -n "$fl_sel" ]]; then
        declare -a FL_SELECTED=()
        if [[ "$fl_sel" == "all" ]]; then
            for i in "${!FL_NAMES[@]}"; do FL_SELECTED+=($i); done
        else
            for tok in $fl_sel; do
                tok="${tok^^}"; tok="${tok#B}"
                if [[ "$tok" =~ ^[0-9]+$ ]] && (( tok >= 1 && tok <= ${#FL_NAMES[@]} )); then
                    FL_SELECTED+=($((tok-1)))
                else
                    warn "Numéro invalide : $tok — ignoré"
                fi
            done
        fi

        if [[ ${#FL_SELECTED[@]} -gt 0 ]]; then
            echo ""
            echo -e "  Que souhaitez-vous faire ?"
            echo -e "    ${BOLD}1${RESET}) Stopper uniquement"
            echo -e "    ${BOLD}2${RESET}) Désinstaller complètement"
            echo -en "  ${YELLOW}?  Choix : ${RESET}"
            read -r fl_action

            for idx in "${FL_SELECTED[@]}"; do
                svc="${FL_NAMES[$idx]}"
                work="${FL_WORK_DIRS[$idx]}"
                nginx="${FL_NGINX[$idx]}"
                echo ""
                hdr "Traitement : $svc"
                stop_and_disable "$svc"
                if [[ "$fl_action" == "2" ]]; then
                    if [[ -n "$nginx" && -f "$nginx" ]]; then
                        _port="${FL_PORTS[$idx]}"
                        _loc_count=$(grep -c '^\s*location ' "$nginx" 2>/dev/null || echo 0)
                        _has_port=$(grep -c "127.0.0.1:${_port}" "$nginx" 2>/dev/null || echo 0)
                        if (( _loc_count <= 2 && _has_port > 0 )); then
                            ask_yn "Supprimer vhost Nginx : ${BOLD}$nginx${RESET} (seule instance) ?" && \
                                { run rm -f "$nginx"; ok "Vhost supprimé"
                                  run nginx -t 2>/dev/null && run systemctl reload nginx || true; }
                        elif (( _has_port > 0 )); then
                            ask_yn "Retirer le bloc port ${_port} du vhost ${BOLD}$nginx${RESET} (partagé) ?" && \
                                { cp "$nginx" "${nginx}.bak.$(date +%Y%m%d%H%M%S)"
                                  python3 -c "
import re
with open('$nginx') as f: c = f.read()
c = re.sub(r'\n?[ \t]*# ── Game Commander[^\n]*\n.*?location [^\{]+\{[^}]*proxy_pass[^}]*${_port}[^}]*\}[^\n]*\n?[ \t]*location [^\{]+/static[^}]*\}[ \t]*\n?[ \t]*# ─+\n?', '\n', c, flags=re.DOTALL)
with open('$nginx','w') as f: f.write(c)
"
                                  ok "Bloc port ${_port} retiré"
                                  run nginx -t 2>/dev/null && run systemctl reload nginx || true; }
                        fi
                    fi
                    for sf in /etc/sudoers.d/*; do
                        [[ -f "$sf" ]] || continue
                        grep -q "$work\|$svc" "$sf" 2>/dev/null || continue
                        ask_yn "Supprimer sudoers : ${BOLD}$sf${RESET} ?" && \
                            { run rm -f "$sf"; ok "Sudoers supprimé"; }
                    done
                    remove_dir "$work" "répertoire application"
                fi
                ok "Terminé : $svc"
            done
        fi
    fi
fi

# ═══════════════════════════════════════════════════════════════════════════════
#  PARTIE C — Processus orphelins
# ═══════════════════════════════════════════════════════════════════════════════
hdr "C — Processus orphelins en mémoire"

SAFE_PIDS_FILE=$(mktemp)
systemctl show $(systemctl list-units --type=service --no-legend 2>/dev/null \
    | awk '{print $1}') -p MainPID 2>/dev/null \
    | grep -v '=0$' | grep -oP '(?<=)\d+' > "$SAFE_PIDS_FILE" || true

is_safe_pid() { grep -qxF "$1" "$SAFE_PIDS_FILE" 2>/dev/null; }

is_amp_process() {
    local pid="$1" cur="$1" depth=0
    while [[ "$cur" =~ ^[0-9]+$ ]] && (( cur > 1 && depth < 8 )); do
        [[ ! -r "/proc/${cur}/cmdline" ]] && return 1
        local cmdline
        cmdline=$(tr '\0' ' ' < "/proc/${cur}/cmdline" 2>/dev/null) || true
        echo "$cmdline" | grep -qiE 'ampdata|cubecoders|ampinstmgr' && return 0
        [[ ! -r "/proc/${cur}/stat" ]] && return 1
        cur=$(awk '{print $4}' "/proc/${cur}/stat" 2>/dev/null) || cur=1
        (( depth++ ))
    done
    return 1
}

ORPHAN_FILE=$(mktemp)

while IFS= read -r psline; do
    pid=$(echo  "$psline" | awk '{print $1}')
    user=$(echo "$psline" | awk '{print $2}')
    cmd=$(echo  "$psline" | awk '{for(i=3;i<=NF;i++) printf $i" "; print ""}' | xargs)
    [[ ! "$pid" =~ ^[0-9]+$ ]] && continue
    (( pid <= 1 ))              && continue
    [[ "$pid" == "$$" ]]        && continue
    echo "$cmd" | grep -qE 'game_commander|uninstall_flask|grep' && continue
    is_safe_pid "$pid" && continue
    is_amp_process "$pid" && continue
    desc=""
    if echo "$cmd" | grep -qiE 'python[0-9.]*.*(app|wsgi|main)\.py|gunicorn|uvicorn'; then
        wdir=$(readlink -f "/proc/${pid}/cwd" 2>/dev/null || echo "")
        app_name=""
        if [[ -n "$wdir" && -f "$wdir/game.json" ]]; then
            app_name=$(python3 -c \
                "import json; d=json.load(open('$wdir/game.json')); \
                 print(d.get('name','?')+' — '+d.get('subtitle',''))" 2>/dev/null || true)
        fi
        desc="Flask/Python"
        [[ -n "$app_name" ]] && desc="$desc ($app_name)"
        [[ -n "$wdir"     ]] && desc="$desc  [${wdir}]"
    elif echo "$cmd" | grep -qiP \
        'valheim_server\.x86_64|enshrouded_server|bedrock_server|(?<!\w)java(?!\w).*nogui'; then
        binary=$(echo "$cmd" | grep -oP \
            'valheim_server\.x86_64|enshrouded_server|bedrock_server|java' | head -1)
        desc="Serveur de jeu ($binary)"
    else
        continue
    fi
    echo "${pid}|${user}|${desc}|$(echo "$cmd" | cut -c1-80)" >> "$ORPHAN_FILE"
done < <(ps -eo pid,user,cmd --no-headers 2>/dev/null | grep -v ' Z ')

rm -f "$SAFE_PIDS_FILE"

orphan_count=$(wc -l < "$ORPHAN_FILE" 2>/dev/null || echo 0)

if (( orphan_count == 0 )); then
    ok "Aucun processus orphelin détecté."
    rm -f "$ORPHAN_FILE"
else
    echo ""
    warn "${orphan_count} processus orphelin(s) trouvé(s) :"
    echo ""
    declare -a O_PIDS=() O_USERS=() O_DESCS=() O_CMDS=()
    while IFS='|' read -r o_pid o_user o_desc o_cmd; do
        O_PIDS+=("$o_pid"); O_USERS+=("$o_user")
        O_DESCS+=("$o_desc"); O_CMDS+=("$o_cmd")
    done < "$ORPHAN_FILE"
    rm -f "$ORPHAN_FILE"

    for i in "${!O_PIDS[@]}"; do
        echo -e "  ${BOLD}[C$((i+1))]${RESET}  PID ${BOLD}${O_PIDS[$i]}${RESET}  — ${O_DESCS[$i]}"
        echo -e "         Utilisateur : ${O_USERS[$i]}"
        echo -e "         Commande    : ${DIM}${O_CMDS[$i]}${RESET}"
        sep
    done

    echo -e "  Numéros à terminer (ex: ${BOLD}C1 C2${RESET}), ${BOLD}all${RESET} pour tout, ${BOLD}skip${RESET} pour passer :"
    echo -en "  ${YELLOW}?  Sélection : ${RESET}"
    read -r kill_sel

    if [[ "$kill_sel" != "skip" && -n "$kill_sel" ]]; then
        declare -a KILL_IDX=()
        if [[ "$kill_sel" == "all" ]]; then
            for i in "${!O_PIDS[@]}"; do KILL_IDX+=($i); done
        else
            for tok in $kill_sel; do
                tok="${tok^^}"; tok="${tok#C}"
                if [[ "$tok" =~ ^[0-9]+$ ]] && (( tok >= 1 && tok <= ${#O_PIDS[@]} )); then
                    KILL_IDX+=($((tok-1)))
                else
                    warn "Numéro invalide : $tok — ignoré"
                fi
            done
        fi

        if (( ${#KILL_IDX[@]} > 0 )); then
            echo ""
            echo -e "  Signal :"
            echo -e "    ${BOLD}1${RESET}) SIGTERM  — arrêt propre (recommandé)"
            echo -e "    ${BOLD}2${RESET}) SIGKILL  — arrêt forcé"
            echo -en "  ${YELLOW}?  Choix : ${RESET}"
            read -r sig_choice
            KILL_SIG="-15"
            [[ "${sig_choice:-1}" == "2" ]] && KILL_SIG="-9"

            for idx in "${KILL_IDX[@]}"; do
                pid="${O_PIDS[$idx]}"
                desc="${O_DESCS[$idx]}"
                if ! kill -0 "$pid" 2>/dev/null; then
                    warn "PID $pid déjà terminé"
                    continue
                fi
                info "Envoi signal $KILL_SIG → PID $pid ($desc)..."
                run kill "$KILL_SIG" "$pid" || true
                if ! $DRY_RUN; then
                    sleep 2
                    if kill -0 "$pid" 2>/dev/null; then
                        warn "PID $pid toujours actif — kill -9 $pid pour forcer"
                    else
                        ok "PID $pid terminé"
                    fi
                fi
            done
        fi
    fi
fi

echo ""
hdr "Terminé"
$DRY_RUN && warn "DRY-RUN — aucune modification n'a été effectuée"
echo ""

} # fin cmd_uninstall

# ═══════════════════════════════════════════════════════════════════════════════
# MAIN — Parsing des arguments et dispatch
# ═══════════════════════════════════════════════════════════════════════════════
show_help() {
    cat << 'EOF'

  game_commander.sh — Déploiement et gestion des instances Game Commander

  COMMANDES :
    deploy                   Déploiement interactif
    deploy --config FILE     Déploiement silencieux depuis un fichier de config
    deploy --generate-config Générer un modèle de fichier de config
    uninstall                Désinstallation guidée
    uninstall --dry-run      Simulation (aucune modification)
    status                   Liste l'état de toutes les instances

  EXEMPLES :
    sudo bash game_commander.sh
    sudo bash game_commander.sh deploy
    sudo bash game_commander.sh deploy --config deploy_game_commander.env
    sudo bash game_commander.sh uninstall
    sudo bash game_commander.sh status

EOF
}

COMMAND=""
REMAINING_ARGS=()

for arg in "$@"; do
    case "$arg" in
        deploy|uninstall|status) COMMAND="$arg" ;;
        --dry-run) DRY_RUN=true ;;
        --help|-h) show_help; exit 0 ;;
        *) REMAINING_ARGS+=("$arg") ;;
    esac
done

# Menu interactif si aucune commande
if [[ -z "$COMMAND" ]]; then
    [[ $EUID -ne 0 ]] && die "Lancez en root : sudo bash $0"
    echo ""
    echo -e "  ${BOLD}${CYAN}╔══ GAME COMMANDER ══╗${RESET}"
    echo ""
    echo -e "  ${CYAN}[1]${RESET} ${BOLD}deploy${RESET}     — Installer une nouvelle instance"
    echo -e "  ${CYAN}[2]${RESET} ${BOLD}uninstall${RESET}  — Désinstaller une instance"
    echo -e "  ${CYAN}[3]${RESET} ${BOLD}status${RESET}     — État de toutes les instances"
    echo ""
    echo -en "  ${YELLOW}?  Votre choix : ${RESET}"
    read -r _choice
    case "$_choice" in
        1) COMMAND="deploy" ;;
        2) COMMAND="uninstall" ;;
        3) COMMAND="status" ;;
        *) die "Choix invalide." ;;
    esac
fi

case "$COMMAND" in
    deploy)    cmd_deploy    "${REMAINING_ARGS[@]:-}" ;;
    uninstall) cmd_uninstall ;;
    status)    cmd_status    ;;
    *)         show_help; exit 1 ;;
esac
