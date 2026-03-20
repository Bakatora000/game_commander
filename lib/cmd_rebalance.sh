# ── lib/cmd_rebalance.sh ────────────────────────────────────────────────────
# Commande : sudo bash game_commander.sh rebalance [--restart]

cmd_rebalance() {
    [[ $EUID -eq 0 ]] || die "Lancez en root : sudo bash $0 rebalance"

    local restart_running=false
    local arg
    for arg in "$@"; do
        [[ "$arg" == "--restart" ]] && restart_running=true
    done

    hdr "Répartition CPU"
    info "Calcul de l'affinité par cœur physique"
    $restart_running \
        && warn "Les services actifs seront redémarrés pour appliquer l'affinité" \
        || info "Les services actifs conserveront l'ancienne affinité jusqu'au prochain redémarrage"

    echo ""
    echo -e "  ${BOLD}Affectation actuelle :${RESET}"
    python3 "$SCRIPT_DIR/shared/cpuplan.py" show-current || true
    echo ""
    echo -e "  ${BOLD}Affectation planifiée :${RESET}"
    python3 "$SCRIPT_DIR/shared/cpuplan.py" show-plan || true
    echo ""

    while IFS= read -r _line; do
        [[ -n "$_line" ]] && ok "$_line"
    done < <(python3 "$SCRIPT_DIR/shared/cpuplan.py" apply \
        $($restart_running && echo "--restart" || true) 2>/dev/null || true)
}
