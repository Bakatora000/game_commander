# ── lib/cmd_status.sh ───────────────────────────────────────────────────────
# Commande : sudo bash game_commander.sh status

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
