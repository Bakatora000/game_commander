# ── lib/cmd_uninstall.sh ────────────────────────────────────────────────────
# Commande : sudo bash game_commander.sh uninstall [--dry-run]

# ═══════════════════════════════════════════════════════════════════════════════
# UNINSTALL
# ═══════════════════════════════════════════════════════════════════════════════
cmd_uninstall() {
    local _args=("$@")
    local i=0
    local target_instance="" target_config="" gc_action="2"
    while [[ $i -lt ${#_args[@]} ]]; do
        case "${_args[$i]}" in
            --dry-run)
                DRY_RUN=true
                ;;
            --yes)
                ASSUME_YES=true
                ;;
            --instance)
                i=$((i+1))
                target_instance="${_args[$i]:-}"
                ;;
            --config)
                i=$((i+1))
                target_config="${_args[$i]:-}"
                ;;
            --stop-only)
                gc_action="1"
                ;;
            --full)
                gc_action="2"
                ;;
        esac
        i=$((i+1))
    done

    [[ $EUID -ne 0 ]] && { err "Ce script doit être exécuté en root (sudo)"; exit 1; }
    $DRY_RUN && warn "MODE DRY-RUN — aucune modification ne sera effectuée"

    if [[ -n "$target_instance" || -n "$target_config" ]]; then
        local cfg=""
        if [[ -n "$target_config" ]]; then
            cfg="$target_config"
        else
            cfg="$(python3 "$SCRIPT_DIR/tools/host_cli.py" resolve-config --instance "$target_instance" 2>/dev/null || true)"
        fi
        [[ -n "$cfg" && -f "$cfg" ]] || die "Configuration d'instance introuvable"
        uninstall_gc_process_entry "$cfg" "$gc_action"
        echo ""
        hdr "Terminé"
        $DRY_RUN && warn "DRY-RUN — aucune modification n'a été effectuée"
        echo ""
        return
    fi

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
