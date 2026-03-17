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

    cpu_affinity_apply_all "$restart_running"
}
