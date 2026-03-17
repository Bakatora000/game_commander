#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════════
#  game_commander.sh v2.3 — Déploiement et gestion des instances Game Commander
#
#  Usage :
#    sudo bash game_commander.sh                          # menu interactif
#    sudo bash game_commander.sh deploy                   # nouvelle instance complète
#    sudo bash game_commander.sh attach                   # commander sur serveur existant
#    sudo bash game_commander.sh deploy --config FILE     # déploiement depuis un fichier
#    sudo bash game_commander.sh deploy --generate-config # générer un modèle
#    sudo bash game_commander.sh uninstall                # désinstallation guidée
#    sudo bash game_commander.sh uninstall --dry-run      # simulation
#    sudo bash game_commander.sh status                   # état de toutes les instances
#    sudo bash game_commander.sh update                   # resynchronise une instance
#    sudo bash game_commander.sh rebalance                # recalcule l'affinité CPU
# ═══════════════════════════════════════════════════════════════════════════════
set -uo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Chargement des modules ─────────────────────────────────────────────────────
source "$SCRIPT_DIR/lib/helpers.sh"
source "$SCRIPT_DIR/lib/cpu_affinity.sh"
source "$SCRIPT_DIR/lib/cpu_monitor.sh"
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
source "$SCRIPT_DIR/lib/cmd_rebalance.sh"

# ═══════════════════════════════════════════════════════════════════════════════
# AIDE
# ═══════════════════════════════════════════════════════════════════════════════
show_help() {
    cat << 'EOF'

  game_commander.sh — Déploiement et gestion des instances Game Commander

  COMMANDES :
    deploy                   Nouvelle instance complète gérée par Game Commander
    attach                   Ajouter Commander à un serveur/service jeu existant
    deploy --attach          Alias CLI de la commande attach
    deploy --config FILE     Déploiement depuis un fichier de config
    deploy --generate-config Générer un modèle de fichier de config
    uninstall                Retirer une instance ou nettoyer des reliquats
    uninstall --dry-run      Simulation (aucune modification)
    status                   Voir l'état des instances déployées
    update                   Resynchroniser le runtime d'une instance existante
    update --instance ID     Mettre à jour une instance précise
    update --all             Met à jour toutes les instances
    rebalance                Recalculer l'affinité CPU des instances gérées
    rebalance --restart      Recalculer puis redémarrer les serveurs concernés

  MENU PRINCIPAL :
    [1] deploy     Nouvelle instance complète
    [2] attach     Commander sur serveur existant
    [3] uninstall  Retirer / nettoyer
    [4] status     Voir l'état
    [5] update     Propager les changements du dépôt
    [6] rebalance  Répartir les serveurs sur les cœurs CPU
    [0] quit       Quitter

  EXEMPLES :
    sudo bash game_commander.sh
    sudo bash game_commander.sh deploy
    sudo bash game_commander.sh attach
    sudo bash game_commander.sh deploy --config env/deploy_config.env
    sudo bash game_commander.sh uninstall
    sudo bash game_commander.sh status
    sudo bash game_commander.sh update --instance testfabric
    sudo bash game_commander.sh rebalance --restart

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
        rebalance) cmd_rebalance "$@" ;;
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
        deploy|attach|uninstall|status|update|rebalance) COMMAND="$arg" ;;
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
        echo -e "  ${DIM}Déployer, attacher, mettre à jour ou retirer une interface Commander.${RESET}"
        echo ""
        echo -e "  ${CYAN}[0]${RESET} ${BOLD}quit${RESET}       — Quitter"
        echo -e "  ${CYAN}[1]${RESET} ${BOLD}deploy${RESET}     — Nouvelle instance complète gérée par Game Commander"
        echo -e "  ${CYAN}[2]${RESET} ${BOLD}attach${RESET}     — Ajouter Commander à un serveur/service déjà existant"
        echo -e "  ${CYAN}[3]${RESET} ${BOLD}uninstall${RESET}  — Retirer une instance ou nettoyer des reliquats"
        echo -e "  ${CYAN}[4]${RESET} ${BOLD}status${RESET}     — Voir l'état des instances déployées"
        echo -e "  ${CYAN}[5]${RESET} ${BOLD}update${RESET}     — Propager les changements du dépôt vers une instance"
        echo -e "  ${CYAN}[6]${RESET} ${BOLD}rebalance${RESET}  — Répartir les serveurs sur les cœurs CPU"
        echo ""
        echo -en "  ${YELLOW}?  Votre choix : ${RESET}"
        read -r _choice
        case "$_choice" in
            0) exit 0 ;;
            1) run_command deploy ;;
            2) run_command attach ;;
            3) run_command uninstall ;;
            4) run_command status ;;
            5) run_command update ;;
            6) run_command rebalance ;;
            *) warn "Choix invalide." ;;
        esac
    done
fi

run_command "$COMMAND" "${REMAINING_ARGS[@]:-}"
