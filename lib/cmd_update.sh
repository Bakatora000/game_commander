# ── lib/cmd_update.sh ────────────────────────────────────────────────────────
# Commande : sudo bash game_commander.sh update [--instance ID] [--all]

update_collect_configs() {
    python3 "$SCRIPT_DIR/tools/host_cli.py" list-configs
}

update_game_meta() {
    case "$GAME_ID" in
        valheim)
            GAME_LABEL="Valheim"
            GAME_BINARY="valheim_server.x86_64"
            GAME_SERVICE="${GAME_SERVICE:-valheim-server-${INSTANCE_ID}}"
            ;;
        enshrouded)
            GAME_LABEL="Enshrouded"
            GAME_BINARY="enshrouded_server.exe"
            GAME_SERVICE="${GAME_SERVICE:-enshrouded-server-${INSTANCE_ID}}"
            ;;
        minecraft)
            GAME_LABEL="Minecraft Java"
            GAME_BINARY="java"
            GAME_SERVICE="${GAME_SERVICE:-minecraft-server-${INSTANCE_ID}}"
            ;;
        minecraft-fabric)
            GAME_LABEL="Minecraft Fabric"
            GAME_BINARY="java"
            GAME_SERVICE="${GAME_SERVICE:-minecraft-fabric-server-${INSTANCE_ID}}"
            ;;
        terraria)
            GAME_LABEL="Terraria"
            GAME_BINARY="TerrariaServer.bin.x86_64"
            GAME_SERVICE="${GAME_SERVICE:-terraria-server-${INSTANCE_ID}}"
            ;;
        satisfactory)
            GAME_LABEL="Satisfactory"
            GAME_BINARY="FactoryServer.sh"
            GAME_SERVICE="${GAME_SERVICE:-satisfactory-server-${INSTANCE_ID}}"
            ;;
        soulmask)
            GAME_LABEL="Soulmask"
            GAME_BINARY="StartServer.sh"
            GAME_SERVICE="${GAME_SERVICE:-soulmask-server-${INSTANCE_ID}}"
            ;;
        *)
            die "GAME_ID non supporté pour update : $GAME_ID"
            ;;
    esac
}

update_process_config() {
    local cfg="$1"
    local hooks_only="${2:-false}"
    unset GAME_ID INSTANCE_ID SYS_USER SERVER_DIR DATA_DIR BACKUP_DIR APP_DIR SRC_DIR \
          WORLD_NAME SERVER_NAME SERVER_PASSWORD SERVER_ADMIN_PASSWORD SERVER_PORT QUERY_PORT ECHO_PORT \
          MAX_PLAYERS SERVER_MODE BACKUP_ENABLED SAVING_ENABLED BACKUP_INTERVAL CROSSPLAY BEPINEX DOMAIN \
          URL_PREFIX FLASK_PORT SSL_MODE ADMIN_LOGIN STEAM_APPID STEAMCMD_PATH DEPLOY_MODE GAME_SERVICE

    source <(grep -E '^[A-Z_]+=' "$cfg" 2>/dev/null)

    GAME_ID="${GAME_ID:-}"
    INSTANCE_ID="${INSTANCE_ID:-}"
    SYS_USER="${SYS_USER:-gameserver}"
    HOME_DIR="$(eval echo "~$SYS_USER")"
    APP_DIR="${APP_DIR:-}"
    SERVER_DIR="${SERVER_DIR:-}"
    DATA_DIR="${DATA_DIR:-$SERVER_DIR}"
    SRC_DIR="${SRC_DIR:-$SCRIPT_DIR}"
    ADMIN_LOGIN="${ADMIN_LOGIN:-admin}"
    DEPLOY_MODE="${DEPLOY_MODE:-managed}"
    GAME_SERVICE="${GAME_SERVICE:-}"
    GC_SERVICE="game-commander-${INSTANCE_ID}"

    [[ -n "$GAME_ID" && -n "$INSTANCE_ID" && -n "$APP_DIR" ]] || {
        warn "Config incomplète ignorée : $cfg"
        return
    }
    [[ -d "$APP_DIR" ]] || {
        warn "APP_DIR introuvable, instance ignorée : $APP_DIR"
        return
    }

    update_game_meta

    info "Mise à jour de ${INSTANCE_ID} (${GAME_ID})"
    if [[ "$hooks_only" != "true" ]]; then
        local runtime_src
        runtime_src=$(deploy_runtime_src_dir "$SRC_DIR") || die "Sources runtime introuvables dans $SRC_DIR"

        rsync -a --delete --exclude='__pycache__' --exclude='*.pyc' \
                  --exclude='metrics.log' --exclude='users.json' --exclude='game.json' \
                  --exclude='deploy_config.env' \
                  "$runtime_src/" "$APP_DIR/"
        chown -R "$SYS_USER:$SYS_USER" "$APP_DIR"
        ok "Runtime synchronisé"

        local gc_bepinex_path=""
        if [[ "$GAME_ID" == "valheim" && "${BEPINEX:-false}" == "true" ]]; then
            gc_bepinex_path="${SERVER_DIR}/BepInEx"
        fi

        local -a game_json_extra_args=()
        [[ -n "${QUERY_PORT:-}" ]] && game_json_extra_args+=(--query-port "$QUERY_PORT")
        [[ -n "${ECHO_PORT:-}" ]] && game_json_extra_args+=(--echo-port "$ECHO_PORT")

        python3 "$SCRIPT_DIR/tools/config_gen.py" game-json \
            --out           "$APP_DIR/game.json" \
            --game-id       "$GAME_ID" \
            --game-label    "$GAME_LABEL" \
            --game-binary   "$GAME_BINARY" \
            --game-service  "$GAME_SERVICE" \
            --server-dir    "$SERVER_DIR" \
            --data-dir      "${DATA_DIR:-$SERVER_DIR}" \
            --world-name    "${WORLD_NAME:-}" \
            --max-players   "${MAX_PLAYERS:-20}" \
            --port          "$SERVER_PORT" \
            "${game_json_extra_args[@]}" \
            --url-prefix    "$URL_PREFIX" \
            --flask-port    "$FLASK_PORT" \
            --admin-user    "$ADMIN_LOGIN" \
            --bepinex-path  "${gc_bepinex_path:-}" \
            --steam-appid   "${STEAM_APPID:-}" \
            --steamcmd-path "${STEAMCMD_PATH:-}" \
        || die "Échec régénération game.json pour ${INSTANCE_ID}"
        chown "$SYS_USER:$SYS_USER" "$APP_DIR/game.json"
        ok "game.json régénéré"
    fi

    SKIP_BACKUP_TEST=true
    deploy_step_backups
    cpu_affinity_apply_all false
    cpu_monitor_install
    deploy_step_hub_service

    systemctl restart "$GC_SERVICE"
    if service_active "$GC_SERVICE"; then
        ok "Service $GC_SERVICE redémarré"
    else
        warn "$GC_SERVICE inactif après update — journalctl -u $GC_SERVICE -n 30"
    fi
}

cmd_update() {
    [[ $EUID -eq 0 ]] || die "Lancez en root : sudo bash $0 update"

    local target_instance="" update_all=false
    local hooks_only=false
    local -a args=("$@")
    local i
    for ((i=0; i<${#args[@]}; i++)); do
        case "${args[$i]}" in
            --instance)
                target_instance="${args[$((i+1))]:-}"
                ((i++))
                ;;
            --all)
                update_all=true
                ;;
            --hooks-only)
                hooks_only=true
                ;;
        esac
    done

    hdr "Mise à jour des instances Game Commander"

    mapfile -t UPDATE_CONFIGS < <(update_collect_configs)
    [[ ${#UPDATE_CONFIGS[@]} -gt 0 ]] || die "Aucune instance Game Commander trouvée."

    local -a selected=()
    if $update_all; then
        selected=("${UPDATE_CONFIGS[@]}")
    elif [[ -n "$target_instance" ]]; then
        local cfg
        for cfg in "${UPDATE_CONFIGS[@]}"; do
            if grep -q "^INSTANCE_ID=\"${target_instance}\"" "$cfg" 2>/dev/null; then
                selected+=("$cfg")
                break
            fi
        done
        [[ ${#selected[@]} -gt 0 ]] || die "Instance introuvable : ${target_instance}"
    elif ! $hooks_only; then
        echo ""
        local idx=1 cfg iid gid
        echo -e "  ${CYAN}[0]${RESET} Quit"
        for cfg in "${UPDATE_CONFIGS[@]}"; do
            iid=$(grep '^INSTANCE_ID=' "$cfg" 2>/dev/null | cut -d= -f2- | tr -d '"')
            gid=$(grep '^GAME_ID=' "$cfg" 2>/dev/null | cut -d= -f2- | tr -d '"')
            echo -e "  ${CYAN}[$idx]${RESET} ${BOLD}${iid:-?}${RESET} (${gid:-?})"
            idx=$((idx + 1))
        done
        echo ""
        ask "Numéro à mettre à jour, ou all :"
        read -r choice
        if [[ "$choice" == "0" ]]; then
            info "Mise à jour annulée."
            echo ""
            return 0
        elif [[ "$choice" == "all" ]]; then
            selected=("${UPDATE_CONFIGS[@]}")
        elif [[ "$choice" =~ ^[0-9]+$ ]] && (( choice >= 1 && choice <= ${#UPDATE_CONFIGS[@]} )); then
            selected+=("${UPDATE_CONFIGS[$((choice-1))]}")
        else
            die "Choix invalide."
        fi
    else
        die "--hooks-only exige --instance"
    fi

    local cfg
    for cfg in "${selected[@]}"; do
        sep
        update_process_config "$cfg" "$hooks_only"
    done
}
