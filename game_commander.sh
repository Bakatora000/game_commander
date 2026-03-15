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
    sudo bash game_commander.sh deploy --config env/deploy_config.env
    sudo bash game_commander.sh uninstall
    sudo bash game_commander.sh status
    sudo bash game_commander.sh update --instance testfabric

EOF
}

# ═══════════════════════════════════════════════════════════════════════════════
# MAIN — Parsing des arguments et dispatch
# ═══════════════════════════════════════════════════════════════════════════════
COMMAND=""
REMAINING_ARGS=()

for arg in "$@"; do
    case "$arg" in
        deploy|uninstall|status|update) COMMAND="$arg" ;;
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
    echo -e "  ${CYAN}[4]${RESET} ${BOLD}update${RESET}     — Mettre à jour une instance existante"
    echo ""
    echo -en "  ${YELLOW}?  Votre choix : ${RESET}"
    read -r _choice
    case "$_choice" in
        1) COMMAND="deploy" ;;
        2) COMMAND="uninstall" ;;
        3) COMMAND="status" ;;
        4) COMMAND="update" ;;
        *) die "Choix invalide." ;;
    esac
fi

case "$COMMAND" in
    deploy)    cmd_deploy    "${REMAINING_ARGS[@]:-}" ;;
    uninstall) cmd_uninstall ;;
    status)    cmd_status    ;;
    update)    cmd_update    "${REMAINING_ARGS[@]:-}" ;;
    *)         show_help; exit 1 ;;
esac
