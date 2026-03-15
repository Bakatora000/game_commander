# ── lib/cmd_uninstall.sh ────────────────────────────────────────────────────
# Commande : sudo bash game_commander.sh uninstall [--dry-run]

# ═══════════════════════════════════════════════════════════════════════════════
# UNINSTALL
# ═══════════════════════════════════════════════════════════════════════════════
cmd_uninstall() {
    [[ $EUID -ne 0 ]] && { err "Ce script doit être exécuté en root (sudo)"; exit 1; }
    $DRY_RUN && warn "MODE DRY-RUN — aucune modification ne sera effectuée"

    DEPLOY_CONFIGS=()
    uninstall_gc_section
    if [[ $? -eq 10 ]]; then
        info "Désinstallation annulée."
        echo ""
        return
    fi
    uninstall_flask_section
    uninstall_orphans_section

    echo ""
    hdr "Terminé"
    $DRY_RUN && warn "DRY-RUN — aucune modification n'a été effectuée"
    echo ""
} # fin cmd_uninstall
