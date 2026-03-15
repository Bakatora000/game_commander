#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════════
#  game_commander.sh v2.2 — Déploiement et gestion des instances Game Commander
#
#  Usage :
#    sudo bash game_commander.sh                          # menu interactif
#    sudo bash game_commander.sh deploy                   # déploiement interactif
#    sudo bash game_commander.sh deploy --config FILE     # déploiement silencieux
#    sudo bash game_commander.sh deploy --generate-config # générer un modèle
#    sudo bash game_commander.sh uninstall                # désinstallation guidée
#    sudo bash game_commander.sh uninstall --dry-run      # simulation
#    sudo bash game_commander.sh status                   # état de toutes les instances
#    sudo bash game_commander.sh update                   # met à jour l'app d'une instance
# ═══════════════════════════════════════════════════════════════════════════════
set -uo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Chargement des modules ─────────────────────────────────────────────────────
source "$SCRIPT_DIR/lib/helpers.sh"
source "$SCRIPT_DIR/lib/nginx.sh"
source "$SCRIPT_DIR/lib/cmd_status.sh"
source "$SCRIPT_DIR/lib/deploy_helpers.sh"
source "$SCRIPT_DIR/lib/deploy_configure.sh"
source "$SCRIPT_DIR/lib/deploy_steps.sh"
source "$SCRIPT_DIR/lib/uninstall_gc.sh"
source "$SCRIPT_DIR/lib/uninstall_flask.sh"
source "$SCRIPT_DIR/lib/uninstall_orphans.sh"
source "$SCRIPT_DIR/lib/cmd_deploy.sh"
source "$SCRIPT_DIR/lib/cmd_uninstall.sh"
source "$SCRIPT_DIR/lib/cmd_update.sh"

# ═══════════════════════════════════════════════════════════════════════════════
# AIDE
# ═══════════════════════════════════════════════════════════════════════════════
show_help() {
    cat << 'EOF'

  game_commander.sh — Déploiement et gestion des instances Game Commander

  COMMANDES :
    deploy                   Déploiement interactif
    deploy --attach          Attacher Game Commander à un serveur existant
    deploy --config FILE     Déploiement silencieux depuis un fichier de config
    deploy --generate-config Générer un modèle de fichier de config
    uninstall                Désinstallation guidée
    uninstall --dry-run      Simulation (aucune modification)
    status                   Liste l'état de toutes les instances
    update                   Met à jour l'app d'une instance existante
    update --instance ID     Met à jour une instance précise
    update --all             Met à jour toutes les instances

  EXEMPLES :
    sudo bash game_commander.sh
    sudo bash game_commander.sh deploy
    sudo bash game_commander.sh deploy --attach
    sudo bash game_commander.sh deploy --config env/deploy_config.env
    sudo bash game_commander.sh uninstall
    sudo bash game_commander.sh status
    sudo bash game_commander.sh update --instance testfabric

EOF
}

run_command() {
    local cmd="$1"
    shift || true
    case "$cmd" in
        deploy)    cmd_deploy    "$@" ;;
        attach)    cmd_deploy    --attach "$@" ;;
        uninstall) cmd_uninstall ;;
        status)    cmd_status    ;;
        update)    cmd_update    "$@" ;;
        *)         show_help; return 1 ;;
    esac
}

# ═══════════════════════════════════════════════════════════════════════════════
# MAIN — Parsing des arguments et dispatch
# ═══════════════════════════════════════════════════════════════════════════════
COMMAND=""
REMAINING_ARGS=()

for arg in "$@"; do
    case "$arg" in
        deploy|attach|uninstall|status|update) COMMAND="$arg" ;;
        --dry-run) DRY_RUN=true ;;
        --help|-h) show_help; exit 0 ;;
        *) REMAINING_ARGS+=("$arg") ;;
    esac
done

# Menu interactif si aucune commande
if [[ -z "$COMMAND" ]]; then
    [[ $EUID -ne 0 ]] && die "Lancez en root : sudo bash $0"
    while true; do
        echo ""
        echo -e "  ${BOLD}${CYAN}╔══ GAME COMMANDER ══╗${RESET}"
        echo ""
        echo -e "  ${CYAN}[1]${RESET} ${BOLD}deploy${RESET}     — Installer une nouvelle instance complète"
        echo -e "  ${CYAN}[2]${RESET} ${BOLD}attach${RESET}     — Ajouter Game Commander à un serveur existant"
        echo -e "  ${CYAN}[3]${RESET} ${BOLD}uninstall${RESET}  — Retirer une instance ou nettoyer"
        echo -e "  ${CYAN}[4]${RESET} ${BOLD}status${RESET}     — État de toutes les instances"
        echo -e "  ${CYAN}[5]${RESET} ${BOLD}update${RESET}     — Mettre à jour une instance existante"
        echo -e "  ${CYAN}[6]${RESET} ${BOLD}quit${RESET}       — Quitter"
        echo ""
        echo -en "  ${YELLOW}?  Votre choix : ${RESET}"
        read -r _choice
        case "$_choice" in
            1) run_command deploy ;;
            2) run_command attach ;;
            3) run_command uninstall ;;
            4) run_command status ;;
            5) run_command update ;;
            6) exit 0 ;;
            *) warn "Choix invalide." ;;
        esac
    done
fi

run_command "$COMMAND" "${REMAINING_ARGS[@]:-}"
