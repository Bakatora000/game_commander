# ── lib/cmd_deploy.sh ───────────────────────────────────────────────────────
# Commande : sudo bash game_commander.sh deploy [--config FILE]

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
                python3 "$SCRIPT_DIR/tools/config_gen.py" patch-bepinex \
                    --script    "$BEPINEX_NATIVE" \
                    --name      "$SERVER_NAME" \
                    --port      "$SERVER_PORT" \
                    --world     "$WORLD_NAME" \
                    --password  "$SERVER_PASSWORD" \
                    --savedir   "$DATA_DIR" \
                    --extra-flag "$CROSSPLAY_ARG" \
                || die "Échec injection start_server_bepinex.sh"
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
        python3 "$SCRIPT_DIR/tools/config_gen.py" enshrouded-cfg \
            --out         "$ENSHROUDED_CFG" \
            --name        "$SERVER_NAME" \
            --password    "$SERVER_PASSWORD" \
            --port        "$SERVER_PORT" \
            --max-players "$MAX_PLAYERS" \
        || die "Échec génération enshrouded_server.json"
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

    python3 "$SCRIPT_DIR/tools/config_gen.py" game-json \
        --out          "$APP_DIR/game.json" \
        --game-id      "$GAME_ID" \
        --game-label   "$GAME_LABEL" \
        --game-binary  "$GAME_BINARY" \
        --game-service "$GAME_SERVICE" \
        --server-dir   "$SERVER_DIR" \
        --data-dir     "${DATA_DIR:-$SERVER_DIR}" \
        --world-name   "${WORLD_NAME:-}" \
        --max-players  "$MAX_PLAYERS" \
        --port         "$SERVER_PORT" \
        --url-prefix   "$URL_PREFIX" \
        --flask-port   "$FLASK_PORT" \
        --admin-user   "$ADMIN_LOGIN" \
        --bepinex-path "${GC_BEPINEX_PATH:-}" \
        --steam-appid  "${STEAM_APPID:-}" \
        --steamcmd-path "${STEAMCMD_PATH:-}" \
    || die "Échec génération game.json"
    ok "game.json généré"

    USERS_FILE="$APP_DIR/users.json"
    if [[ -f "$USERS_FILE" ]]; then
        ok "users.json existant conservé"
    else
        ADMIN_HASH=$(python3 -c \
            "import bcrypt,sys; print(bcrypt.hashpw(sys.argv[1].encode(), bcrypt.gensalt()).decode())" \
            "$ADMIN_PASSWORD") || die "Échec hash bcrypt"

        python3 "$SCRIPT_DIR/tools/config_gen.py" users-json \
            --out     "$USERS_FILE" \
            --admin   "$ADMIN_LOGIN" \
            --hash    "$ADMIN_HASH" \
            --game-id "$GAME_ID" \
        || die "Échec génération users.json"
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

# ── Initialisation manifest (one-shot, idempotent) ────────────────────────────
nginx_ensure_init "$DOMAIN"

# ── Enregistrement de l'instance dans le manifest ────────────────────────────
nginx_manifest_add "$INSTANCE_ID" "$URL_PREFIX" "$FLASK_PORT" "$GAME_LABEL" \
|| die "Échec enregistrement nginx manifest"

# ── Régénération du fichier locations ────────────────────────────────────────
nginx_regenerate_locations \
|| die "Échec régénération nginx locations"

# ── Application ───────────────────────────────────────────────────────────────
nginx_apply || err "Vérifiez manuellement : nginx -t"

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
