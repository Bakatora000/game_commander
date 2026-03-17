# ── lib/helpers.sh ───────────────────────────────────────────────────────────
# Couleurs, fonctions de sortie et helpers partagés entre toutes les commandes.
# Sourcé par game_commander.sh au démarrage.

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
ASSUME_YES=false
run() { $DRY_RUN && echo -e "${DIM}    [dry-run] $*${RESET}" || "$@"; }

gc_read() {
    local __var_name="$1"
    if [[ -r /dev/tty ]] && { read -r "$__var_name" </dev/tty; } 2>/dev/null; then
        :
    else
        read -r "$__var_name"
    fi
}

ask_yn() {
    local prompt="$1"
    $ASSUME_YES && return 0
    echo -en "  ${YELLOW}?  ${prompt} (o/n) : ${RESET}"
    gc_read _ans
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
