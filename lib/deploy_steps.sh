# ── lib/deploy_steps.sh ──────────────────────────────────────────────────────
# Étapes 3 à 12 du déploiement Game Commander

deploy_run_steamcmd() {
    local platform="$1"
    shift
    local install_dir="$1"
    shift
    local app_id="$1"
    shift

    sudo -u "$SYS_USER" "$STEAMCMD_PATH" \
        +@sSteamCmdForcePlatformType "$platform" \
        +force_install_dir "$install_dir" \
        +login anonymous \
        +app_update "$app_id" validate \
        +quit 2>&1 | awk '
            /Please use force_install_dir before logon!/ { next }
            /^ *Update state .*progress:/ {
                line = $0
                sub(/^.*progress: /, "", line)
                printf "\r  →  SteamCMD : %s", line
                fflush()
                in_progress = 1
                next
            }
            {
                if (in_progress) {
                    printf "\n"
                    in_progress = 0
                }
                print
            }
            END {
                if (in_progress) {
                    printf "\n"
                }
            }
        '
}

deploy_step_dependencies() {
    hdr "ÉTAPE 3 : Dépendances"

    local deps_json=""
    deps_json="$(python3 "$SCRIPT_DIR/shared/deploydeps.py" inspect \
        --deploy-mode "$DEPLOY_MODE" \
        --steam-appid "${STEAM_APPID:-}" \
        --ssl-mode "$SSL_MODE" \
        --game-id "$GAME_ID" \
        --home-dir "$HOME_DIR")" || die "Échec inspection dépendances"

    APT_UPDATED=false
    apt_once() { $APT_UPDATED || { info "apt update..."; apt-get update -qq; APT_UPDATED=true; }; }

    install_pkg() {
        local pkg="$1"
        dpkg -l "$pkg" 2>/dev/null | grep -q "^ii" && { ok "$pkg OK"; return; }
        warn "$pkg manquant"
        local do_it=false
        $AUTO_INSTALL_DEPS && do_it=true || { confirm "Installer $pkg ?" "o" && do_it=true; }
        $do_it && { apt_once; apt-get install -y -qq "$pkg" && ok "$pkg installé"; } \
               || warn "$pkg ignoré"
    }

    while IFS= read -r pkg; do
        [[ -n "$pkg" ]] && install_pkg "$pkg"
    done < <(python3 - <<'PY' "$deps_json"
import json, sys
for pkg in json.loads(sys.argv[1]).get("apt_missing", []):
    print(pkg)
PY
    )

    if python3 - <<'PY' "$deps_json"
import json, sys
data = json.loads(sys.argv[1])
raise SystemExit(0 if data.get("need_i386") and not data.get("i386_enabled") else 1)
PY
    then
        {
            info "Activation i386..."
            dpkg --add-architecture i386
            apt_once
        }
    fi
    while IFS= read -r pkg; do
        [[ -n "$pkg" ]] && install_pkg "$pkg"
    done < <(python3 - <<'PY' "$deps_json"
import json, sys
for pkg in json.loads(sys.argv[1]).get("extra_apt_missing", []):
    print(pkg)
PY
    )

    while IFS= read -r pkg; do
        [[ -z "$pkg" ]] && continue
        warn "Python: ${pkg/python3-/} manquant"
            do_it=false
            $AUTO_INSTALL_DEPS && do_it=true || { confirm "Installer $pkg (apt) ?" "o" && do_it=true; }
            $do_it && { apt_once; apt-get install -y -qq "$pkg" && ok "Python: ${pkg/python3-/} installé (apt)"; }
    done < <(python3 - <<'PY' "$deps_json"
import json, sys
for pkg in json.loads(sys.argv[1]).get("python_apt_missing", []):
    print(pkg)
PY
    )

    while IFS= read -r pkg; do
        [[ -z "$pkg" ]] && continue
            warn "Python: $pkg manquant"
            do_it=false
            $AUTO_INSTALL_DEPS && do_it=true || { confirm "pip install $pkg ?" "o" && do_it=true; }
            $do_it && pip3 install "$pkg" --break-system-packages -q && ok "Python: $pkg installé"
    done < <(python3 - <<'PY' "$deps_json"
import json, sys
for pkg in json.loads(sys.argv[1]).get("python_pip_missing", []):
    print(pkg)
PY
    )

    if python3 - <<'PY' "$deps_json"
import json, sys
raise SystemExit(0 if json.loads(sys.argv[1]).get("enshrouded", {}).get("required") else 1)
PY
    then
        info "Enshrouded requiert Wine (binaire Windows) + Xvfb..."
        if python3 - <<'PY' "$deps_json"
import json, sys
ens = json.loads(sys.argv[1]).get("enshrouded", {})
raise SystemExit(0 if (not ens.get("wine64_installed") or not ens.get("wine64_in_path")) else 1)
PY
        then
            warn "wine64 absent — installation depuis les dépôts système..."
            apt_once
            apt-get install -y -qq wine64 xvfb && ok "Wine64 + Xvfb installés" || die "Échec installation Wine"
        else
            ok "Wine64 déjà présent"
        fi
        if ! cmd_exists wine64; then
            if python3 - <<'PY' "$deps_json"
import json, sys
ens = json.loads(sys.argv[1]).get("enshrouded", {})
raise SystemExit(0 if ens.get("wine_in_path") else 1)
PY
            then
                ln -sf "$(command -v wine)" /usr/local/bin/wine64
                ok "Symlink wine64 → wine créé dans /usr/local/bin"
            elif python3 - <<'PY' "$deps_json"
import json, sys
ens = json.loads(sys.argv[1]).get("enshrouded", {})
raise SystemExit(0 if ens.get("wine64_alt_path") else 1)
PY
            then
                ln -sf /usr/lib/wine/wine64 /usr/local/bin/wine64
                ok "Symlink wine64 → /usr/lib/wine/wine64 créé"
            else
                die "wine64 introuvable dans le PATH après installation — vérifiez le paquet wine"
            fi
        fi
        if python3 - <<'PY' "$deps_json"
import json, sys
ens = json.loads(sys.argv[1]).get("enshrouded", {})
raise SystemExit(0 if not ens.get("xvfb_run_in_path") else 1)
PY
        then
            apt_once
            apt-get install -y -qq xvfb && ok "Xvfb installé" || warn "Xvfb absent"
        else
            ok "Xvfb déjà présent"
        fi
        if python3 - <<'PY' "$deps_json"
import json, sys
ens = json.loads(sys.argv[1]).get("enshrouded", {})
raise SystemExit(0 if not ens.get("wine_prefix_exists") else 1)
PY
        then
            info "Initialisation du prefix Wine pour $SYS_USER..."
            sudo -u "$SYS_USER" WINEDEBUG=-all wineboot --init 2>/dev/null && ok "Prefix Wine initialisé" || warn "wineboot : vérifiez manuellement"
        else
            ok "Prefix Wine existant"
        fi
    fi

    STEAMCMD_PATH=""
    if python3 - <<'PY' "$deps_json"
import json, sys
data = json.loads(sys.argv[1])
raise SystemExit(0 if data.get("need_i386") else 1)
PY
    then
        STEAMCMD_PATH="$(python3 - <<'PY' "$deps_json"
import json, sys
print(json.loads(sys.argv[1]).get("steamcmd_path", ""))
PY
        )"
        if [[ -n "$STEAMCMD_PATH" ]]; then
            ok "SteamCMD : $STEAMCMD_PATH"
        else
            warn "SteamCMD introuvable"
            do_steam=false
            $AUTO_INSTALL_STEAMCMD && do_steam=true || { confirm "Installer SteamCMD ?" "o" && do_steam=true; }
            $do_steam && {
                mkdir -p "$HOME_DIR/steamcmd"
                curl -sqL "https://steamcdn-a.akamaihd.net/client/installer/steamcmd_linux.tar.gz" \
                    | tar -xzC "$HOME_DIR/steamcmd"
                chown -R "$SYS_USER:$SYS_USER" "$HOME_DIR/steamcmd"
                STEAMCMD_PATH="$HOME_DIR/steamcmd/steamcmd.sh"
                ok "SteamCMD installé : $STEAMCMD_PATH"
            } || die "SteamCMD requis."
        fi
    fi
}

deploy_step_game_install() {
    if [[ "$DEPLOY_MODE" == "attach" ]]; then
        hdr "ÉTAPE 4 : Installation $GAME_LABEL"
        info "Mode attach — installation/mise à jour du serveur ignorée"
        return
    fi

    if [[ "$GAME_ID" == "soulmask" ]]; then
        hdr "ÉTAPE 4 : Installation Soulmask"
        mkdir -p "$SERVER_DIR" "$DATA_DIR"
        chown -R "$SYS_USER:$SYS_USER" "$SERVER_DIR" "$DATA_DIR"

        DO_INSTALL=true
        if [[ -f "$SERVER_DIR/$GAME_BINARY" ]]; then
            ok "$GAME_LABEL déjà installé"
            if $AUTO_UPDATE_SERVER; then
                echo -e "  ${DIM}  (config) Mise à jour → oui${RESET}"
            else
                confirm "Mettre à jour depuis Steam ?" "n" || DO_INSTALL=false
            fi
        fi

        if $DO_INSTALL; then
            info "Téléchargement $GAME_LABEL via SteamCMD (AppID $STEAM_APPID)..."
            info "Cela peut prendre plusieurs minutes..."
            local soul_out=""
            if soul_out="$(python3 "$SCRIPT_DIR/shared/gameinstall.py" soulmask \
                --server-dir "$SERVER_DIR" \
                --data-dir "$DATA_DIR" \
                --sys-user "$SYS_USER" \
                --steamcmd-path "$STEAMCMD_PATH" \
                --steam-appid "$STEAM_APPID" 2>&1)"; then
                while IFS= read -r _line; do
                    [[ -n "$_line" ]] && ok "$_line"
                done <<< "$soul_out"
            else
                [[ -n "$soul_out" ]] && while IFS= read -r _line; do
                    [[ -n "$_line" ]] && warn "$_line"
                done <<< "$soul_out"
                die "Échec installation serveur Soulmask"
            fi
        fi

        [[ -f "$SERVER_DIR/$GAME_BINARY" ]] || die "Binaire $GAME_BINARY introuvable dans $SERVER_DIR"
        chmod +x "$SERVER_DIR/$GAME_BINARY" 2>/dev/null || true
        chown -R "$SYS_USER:$SYS_USER" "$SERVER_DIR"
        ok "Binaire $GAME_BINARY vérifié"
        return
    fi

    if [[ "$GAME_ID" == "terraria" ]]; then
        hdr "ÉTAPE 4 : Installation Terraria"
        mkdir -p "$SERVER_DIR" "$DATA_DIR"
        chown -R "$SYS_USER:$SYS_USER" "$SERVER_DIR" "$DATA_DIR"

        local terr_out=""
        if terr_out="$(python3 "$SCRIPT_DIR/shared/gameinstall.py" terraria \
            --script-dir "$SCRIPT_DIR" \
            --server-dir "$SERVER_DIR" \
            --data-dir "$DATA_DIR" \
            --sys-user "$SYS_USER" \
            --server-name "$SERVER_NAME" \
            --server-port "$SERVER_PORT" \
            --max-players "$MAX_PLAYERS" \
            --server-password "$SERVER_PASSWORD" \
            --instance-id "$INSTANCE_ID" 2>&1)"; then
            while IFS= read -r _line; do
                [[ -n "$_line" ]] && ok "$_line"
            done <<< "$terr_out"
        else
            [[ -n "$terr_out" ]] && while IFS= read -r _line; do
                [[ -n "$_line" ]] && warn "$_line"
            done <<< "$terr_out"
            die "Échec installation serveur Terraria"
        fi
        return
    fi

    if [[ "$GAME_ID" == "minecraft-fabric" ]]; then
        hdr "ÉTAPE 4 : Installation Minecraft Fabric"
        install_pkg "default-jre-headless"
        local mc_out=""
        if mc_out="$(python3 "$SCRIPT_DIR/shared/gameinstall.py" minecraft \
            --script-dir "$SCRIPT_DIR" \
            --server-dir "$SERVER_DIR" \
            --sys-user "$SYS_USER" \
            --server-name "$SERVER_NAME" \
            --server-port "$SERVER_PORT" \
            --max-players "$MAX_PLAYERS" \
            --fabric 2>&1)"; then
            while IFS= read -r _line; do
                [[ -n "$_line" ]] && ok "$_line"
            done <<< "$mc_out"
        else
            [[ -n "$mc_out" ]] && while IFS= read -r _line; do
                [[ -n "$_line" ]] && warn "$_line"
            done <<< "$mc_out"
            die "Échec installation serveur Minecraft Fabric"
        fi
        return
    fi

    if [[ "$GAME_ID" == "minecraft" ]]; then
        hdr "ÉTAPE 4 : Installation Minecraft Java"
        install_pkg "default-jre-headless"
        local mc_out=""
        if mc_out="$(python3 "$SCRIPT_DIR/shared/gameinstall.py" minecraft \
            --script-dir "$SCRIPT_DIR" \
            --server-dir "$SERVER_DIR" \
            --sys-user "$SYS_USER" \
            --server-name "$SERVER_NAME" \
            --server-port "$SERVER_PORT" \
            --max-players "$MAX_PLAYERS" 2>&1)"; then
            while IFS= read -r _line; do
                [[ -n "$_line" ]] && ok "$_line"
            done <<< "$mc_out"
        else
            [[ -n "$mc_out" ]] && while IFS= read -r _line; do
                [[ -n "$_line" ]] && warn "$_line"
            done <<< "$mc_out"
            die "Échec installation serveur Minecraft Java"
        fi
        return
    fi

    if [[ "$GAME_ID" == "satisfactory" ]]; then
        hdr "ÉTAPE 4 : Installation Satisfactory"
        mkdir -p "$SERVER_DIR" "$DATA_DIR"
        chown -R "$SYS_USER:$SYS_USER" "$SERVER_DIR" "$DATA_DIR"

        DO_INSTALL=true
        if [[ -f "$SERVER_DIR/$GAME_BINARY" ]]; then
            ok "$GAME_LABEL déjà installé"
            if $AUTO_UPDATE_SERVER; then
                echo -e "  ${DIM}  (config) Mise à jour → oui${RESET}"
            else
                confirm "Mettre à jour depuis Steam ?" "n" || DO_INSTALL=false
            fi
        fi

        if $DO_INSTALL; then
            info "Téléchargement $GAME_LABEL via SteamCMD (AppID $STEAM_APPID)..."
            info "Cela peut prendre plusieurs minutes..."
            local sat_out=""
            if sat_out="$(python3 "$SCRIPT_DIR/shared/gameinstall.py" satisfactory \
                --server-dir "$SERVER_DIR" \
                --data-dir "$DATA_DIR" \
                --sys-user "$SYS_USER" \
                --steamcmd-path "$STEAMCMD_PATH" \
                --steam-appid "$STEAM_APPID" 2>&1)"; then
                while IFS= read -r _line; do
                    [[ -n "$_line" ]] && ok "$_line"
                done <<< "$sat_out"
            else
                [[ -n "$sat_out" ]] && while IFS= read -r _line; do
                    [[ -n "$_line" ]] && warn "$_line"
                done <<< "$sat_out"
                die "Échec installation serveur Satisfactory"
            fi
        else
            [[ -f "$SERVER_DIR/$GAME_BINARY" ]] || die "Binaire $GAME_BINARY introuvable dans $SERVER_DIR"
            ok "Binaire $GAME_BINARY vérifié"
        fi
        return
    fi

    if [[ "$GAME_ID" == "valheim" ]]; then
        hdr "ÉTAPE 4 : Installation Valheim"
        mkdir -p "$SERVER_DIR" "$DATA_DIR"
        chown -R "$SYS_USER:$SYS_USER" "$SERVER_DIR" "$DATA_DIR"

        DO_INSTALL=true
        if [[ -f "$SERVER_DIR/$GAME_BINARY" ]]; then
            ok "$GAME_LABEL déjà installé"
            if $AUTO_UPDATE_SERVER; then
                echo -e "  ${DIM}  (config) Mise à jour → oui${RESET}"
            else
                confirm "Mettre à jour depuis Steam ?" "n" || DO_INSTALL=false
            fi
        fi

        local install_bep=false
        if $BEPINEX; then
            if [[ -d "$SERVER_DIR/BepInEx" ]]; then
                install_bep=true
            else
                $AUTO_INSTALL_BEPINEX && install_bep=true || { confirm "Installer BepInEx ?" "o" && install_bep=true; }
            fi
        fi

        if $DO_INSTALL || $install_bep; then
            $DO_INSTALL && {
                info "Téléchargement $GAME_LABEL via SteamCMD (AppID $STEAM_APPID)..."
                info "Cela peut prendre plusieurs minutes..."
            }
            local val_out=""
            local -a val_cmd=(
                python3 "$SCRIPT_DIR/shared/gameinstall.py" valheim
                --server-dir "$SERVER_DIR"
                --data-dir "$DATA_DIR"
                --sys-user "$SYS_USER"
                --steamcmd-path "$STEAMCMD_PATH"
                --steam-appid "$STEAM_APPID"
            )
            $DO_INSTALL || val_cmd+=(--skip-server-update)
            $install_bep && val_cmd+=(--install-bepinex)
            if val_out="$("${val_cmd[@]}" 2>&1)"; then
                while IFS= read -r _line; do
                    [[ -n "$_line" ]] && ok "$_line"
                done <<< "$val_out"
            else
                [[ -n "$val_out" ]] && while IFS= read -r _line; do
                    [[ -n "$_line" ]] && warn "$_line"
                done <<< "$val_out"
                die "Échec installation serveur Valheim"
            fi
        else
            [[ -f "$SERVER_DIR/$GAME_BINARY" ]] || die "Binaire $GAME_BINARY introuvable dans $SERVER_DIR"
            chmod +x "$SERVER_DIR/$GAME_BINARY" 2>/dev/null || true
            chown -R "$SYS_USER:$SYS_USER" "$SERVER_DIR"
            ok "Binaire $GAME_BINARY vérifié"
        fi
        return
    fi

    if [[ "$GAME_ID" == "enshrouded" ]]; then
        hdr "ÉTAPE 4 : Installation Enshrouded"
        mkdir -p "$SERVER_DIR" "$DATA_DIR"
        chown -R "$SYS_USER:$SYS_USER" "$SERVER_DIR" "$DATA_DIR"

        DO_INSTALL=true
        if [[ -f "$SERVER_DIR/$GAME_BINARY" ]]; then
            ok "$GAME_LABEL déjà installé"
            if $AUTO_UPDATE_SERVER; then
                echo -e "  ${DIM}  (config) Mise à jour → oui${RESET}"
            else
                confirm "Mettre à jour depuis Steam ?" "n" || DO_INSTALL=false
            fi
        fi

        if $DO_INSTALL; then
            info "Téléchargement $GAME_LABEL via SteamCMD (AppID $STEAM_APPID)..."
            info "Cela peut prendre plusieurs minutes..."
            local ens_out=""
            if ens_out="$(python3 "$SCRIPT_DIR/shared/gameinstall.py" enshrouded \
                --server-dir "$SERVER_DIR" \
                --data-dir "$DATA_DIR" \
                --sys-user "$SYS_USER" \
                --steamcmd-path "$STEAMCMD_PATH" \
                --steam-appid "$STEAM_APPID" 2>&1)"; then
                while IFS= read -r _line; do
                    [[ -n "$_line" ]] && ok "$_line"
                done <<< "$ens_out"
            else
                [[ -n "$ens_out" ]] && while IFS= read -r _line; do
                    [[ -n "$_line" ]] && warn "$_line"
                done <<< "$ens_out"
                die "Échec installation serveur Enshrouded"
            fi
        else
            [[ -f "$SERVER_DIR/$GAME_BINARY" ]] || die "Binaire $GAME_BINARY introuvable dans $SERVER_DIR"
            chown -R "$SYS_USER:$SYS_USER" "$SERVER_DIR"
            ok "Binaire $GAME_BINARY vérifié"
        fi
        return
    fi

    hdr "ÉTAPE 4 : Installation $GAME_LABEL"
    mkdir -p "$SERVER_DIR"
    chown -R "$SYS_USER:$SYS_USER" "$SERVER_DIR"

    DO_INSTALL=true
    if [[ -f "$SERVER_DIR/$GAME_BINARY" ]]; then
        ok "$GAME_LABEL déjà installé"
        if $AUTO_UPDATE_SERVER; then
            echo -e "  ${DIM}  (config) Mise à jour → oui${RESET}"
        else
            confirm "Mettre à jour depuis Steam ?" "n" || DO_INSTALL=false
        fi
    fi

    if $DO_INSTALL; then
        info "Téléchargement $GAME_LABEL via SteamCMD (AppID $STEAM_APPID)..."
        info "Cela peut prendre plusieurs minutes..."
        _platform="linux"
        [[ "$GAME_ID" == "enshrouded" ]] && _platform="windows"
        deploy_run_steamcmd "$_platform" "$SERVER_DIR" "$STEAM_APPID" || die "Échec SteamCMD."
        ok "$GAME_LABEL téléchargé"
    fi

    [[ -f "$SERVER_DIR/$GAME_BINARY" ]] || die "Binaire $GAME_BINARY introuvable dans $SERVER_DIR"
    [[ "$GAME_ID" != "enshrouded" ]] && chmod +x "$SERVER_DIR/$GAME_BINARY" 2>/dev/null || true
    chown -R "$SYS_USER:$SYS_USER" "$SERVER_DIR"
    ok "Binaire $GAME_BINARY vérifié"
}

deploy_step_game_service() {
    hdr "ÉTAPE 5 : Service $GAME_LABEL"

    if [[ "$DEPLOY_MODE" == "attach" ]]; then
        info "Mode attach — service de jeu existant conservé : $GAME_SERVICE"
        return
    fi

    local CPU_AFFINITY_LINE=""
    local CPU_WEIGHT_LINE=""
    CPU_AFFINITY_LINE="$(cpu_affinity_systemd_line "$INSTANCE_ID" "$GAME_ID" "$GAME_SERVICE" 2>/dev/null || true)"
    CPU_WEIGHT_LINE="CPUWeight=$(cpu_affinity_cpu_weight_for_game "$GAME_ID")"
    [[ -n "$CPU_AFFINITY_LINE" ]] && info "Affinité CPU prévue : ${CPU_AFFINITY_LINE#CPUAffinity=}"

    install_game_service_unit() {
        local exec_start="$1"
        local game_out=""
        if game_out="$(python3 "$SCRIPT_DIR/shared/gameservice.py" install \
            --game-label "$GAME_LABEL" \
            --service-name "$GAME_SERVICE" \
            --sys-user "$SYS_USER" \
            --server-dir "$SERVER_DIR" \
            --exec-start "$exec_start" \
            --cpu-affinity-line "$CPU_AFFINITY_LINE" \
            --cpu-weight-line "$CPU_WEIGHT_LINE" 2>&1)"; then
            ok "$game_out"
        else
            warn "$game_out"
        fi
    }

    if [[ "$GAME_ID" == "minecraft" ]]; then
        START_SCRIPT="$SERVER_DIR/start_server.sh"
        python3 "$SCRIPT_DIR/shared/startscripts.py" minecraft \
            --out "$START_SCRIPT" \
            --server-dir "$SERVER_DIR" \
            --sys-user "$SYS_USER" \
        || die "Échec génération start_server.sh Minecraft"
        ok "Script de démarrage : $START_SCRIPT"

        install_game_service_unit "$START_SCRIPT"
        return
    fi

    if [[ "$GAME_ID" == "minecraft-fabric" ]]; then
        START_SCRIPT="$SERVER_DIR/start_server.sh"
        python3 "$SCRIPT_DIR/shared/startscripts.py" minecraft \
            --out "$START_SCRIPT" \
            --server-dir "$SERVER_DIR" \
            --sys-user "$SYS_USER" \
            --fabric \
        || die "Échec génération start_server.sh Minecraft Fabric"
        ok "Script de démarrage : $START_SCRIPT"

        install_game_service_unit "$START_SCRIPT"
        return
    fi

    if [[ "$GAME_ID" == "terraria" ]]; then
        START_SCRIPT="$SERVER_DIR/start_server.sh"
        WRAPPER_SCRIPT="$SERVER_DIR/start_server_service.sh"
        mkdir -p "$SERVER_DIR/logs"
        python3 "$SCRIPT_DIR/shared/startscripts.py" terraria \
            --out "$START_SCRIPT" \
            --wrapper-out "$WRAPPER_SCRIPT" \
            --server-dir "$SERVER_DIR" \
            --sys-user "$SYS_USER" \
        || die "Échec génération start_server.sh Terraria"
        ok "Script de démarrage : $START_SCRIPT"
        ok "Wrapper service : $WRAPPER_SCRIPT"

        install_game_service_unit "$WRAPPER_SCRIPT"
        return
    fi

    if [[ "$GAME_ID" == "satisfactory" ]]; then
        START_SCRIPT="$SERVER_DIR/start_server.sh"
        python3 "$SCRIPT_DIR/shared/startscripts.py" satisfactory \
            --out "$START_SCRIPT" \
            --server-dir "$SERVER_DIR" \
            --data-dir "$DATA_DIR" \
            --server-port "$SERVER_PORT" \
            --reliable-port "$QUERY_PORT" \
            --sys-user "$SYS_USER" \
        || die "Échec génération start_server.sh Satisfactory"
        ok "Script de démarrage : $START_SCRIPT"

        install_game_service_unit "$START_SCRIPT"
        return
    fi

    if [[ "$GAME_ID" == "soulmask" ]]; then
        START_SCRIPT="$SERVER_DIR/start_server.sh"
        SOULMASK_CFG="$SERVER_DIR/soulmask_server.json"
        SOULMASK_LOG_DIR="$SERVER_DIR/WS/Saved/Logs"
        SOULMASK_SAVED_DIR="$SERVER_DIR/WS/Saved"
        mkdir -p "$SOULMASK_LOG_DIR" "$SOULMASK_SAVED_DIR"

        python3 "$SCRIPT_DIR/tools/config_gen.py" soulmask-cfg \
            --out "$SOULMASK_CFG" \
            --name "$SERVER_NAME" \
            --port "$SERVER_PORT" \
            --query-port "$QUERY_PORT" \
            --echo-port "$ECHO_PORT" \
            --max-players "$MAX_PLAYERS" \
            --password "$SERVER_PASSWORD" \
            --admin-password "$SERVER_ADMIN_PASSWORD" \
            --mode "$SERVER_MODE" \
            --backup-enabled "$BACKUP_ENABLED" \
            --saving-enabled "$SAVING_ENABLED" \
            --backup-interval "$BACKUP_INTERVAL" \
            --log-dir "$SOULMASK_LOG_DIR" \
            --saved-dir "$SOULMASK_SAVED_DIR" \
        || die "Échec génération soulmask_server.json"
        chown "$SYS_USER:$SYS_USER" "$SOULMASK_CFG"
        ok "soulmask_server.json généré"

        python3 "$SCRIPT_DIR/shared/startscripts.py" soulmask \
            --out "$START_SCRIPT" \
            --server-dir "$SERVER_DIR" \
            --cfg-path "$SOULMASK_CFG" \
            --sys-user "$SYS_USER" \
        || die "Échec génération start_server.sh Soulmask"
        ok "Script de démarrage : $START_SCRIPT"

        install_game_service_unit "$START_SCRIPT"
        return
    fi

    START_SCRIPT="$SERVER_DIR/start_server.sh"
    if [[ "$GAME_ID" == "valheim" ]]; then
        CROSSPLAY_FLAG=""
        $CROSSPLAY && CROSSPLAY_FLAG="-crossplay"
        ${GC_FORCE_PLAYFAB} && CROSSPLAY_FLAG="-playfab"

        if $BEPINEX; then
            BEPINEX_NATIVE="$SERVER_DIR/start_server_bepinex.sh"
            if [[ -f "$BEPINEX_NATIVE" ]]; then
                info "start_server_bepinex.sh trouvé — injection des paramètres..."
                CROSSPLAY_ARG=""
                $CROSSPLAY && CROSSPLAY_ARG=" -crossplay"
                ${GC_FORCE_PLAYFAB} && CROSSPLAY_ARG=" -playfab"
                python3 "$SCRIPT_DIR/tools/config_gen.py" patch-bepinex \
                    --script    "$BEPINEX_NATIVE" \
                    --name      "$SERVER_NAME" \
                    --port      "$SERVER_PORT" \
                    --world     "$WORLD_NAME" \
                    --password  "$SERVER_PASSWORD" \
                    --savedir   "$DATA_DIR" \
                    --extra-flag "$CROSSPLAY_ARG" \
                || die "Échec injection start_server_bepinex.sh"
                chmod +x "$BEPINEX_NATIVE"
                chown "$SYS_USER:$SYS_USER" "$BEPINEX_NATIVE"
                START_SCRIPT="$BEPINEX_NATIVE"
                ok "Paramètres injectés dans start_server_bepinex.sh"
            else
                warn "start_server_bepinex.sh introuvable — script BepInEx généré"
                python3 "$SCRIPT_DIR/shared/startscripts.py" valheim \
                    --out "$START_SCRIPT" \
                    --server-dir "$SERVER_DIR" \
                    --data-dir "$DATA_DIR" \
                    --server-name "$SERVER_NAME" \
                    --server-port "$SERVER_PORT" \
                    --world-name "$WORLD_NAME" \
                    --server-password "$SERVER_PASSWORD" \
                    --crossplay-flag "$CROSSPLAY_FLAG" \
                    --sys-user "$SYS_USER" \
                    --bepinex \
                || die "Échec génération start_server.sh Valheim BepInEx"
                ok "Script BepInEx généré"
            fi
        else
            python3 "$SCRIPT_DIR/shared/startscripts.py" valheim \
                --out "$START_SCRIPT" \
                --server-dir "$SERVER_DIR" \
                --data-dir "$DATA_DIR" \
                --server-name "$SERVER_NAME" \
                --server-port "$SERVER_PORT" \
                --world-name "$WORLD_NAME" \
                --server-password "$SERVER_PASSWORD" \
                --crossplay-flag "$CROSSPLAY_FLAG" \
                --sys-user "$SYS_USER" \
            || die "Échec génération start_server.sh Valheim"
            ok "Script standard généré (sans BepInEx)"
        fi
    elif [[ "$GAME_ID" == "enshrouded" ]]; then
        ENSHROUDED_CFG="$SERVER_DIR/enshrouded_server.json"
        info "Génération de enshrouded_server.json..."
        python3 "$SCRIPT_DIR/tools/config_gen.py" enshrouded-cfg \
            --out         "$ENSHROUDED_CFG" \
            --name        "$SERVER_NAME" \
            --password    "$SERVER_PASSWORD" \
            --port        "$SERVER_PORT" \
            --max-players "$MAX_PLAYERS" \
        || die "Échec génération enshrouded_server.json"
        chown "$SYS_USER:$SYS_USER" "$ENSHROUDED_CFG"
        ok "enshrouded_server.json généré"
        python3 "$SCRIPT_DIR/shared/startscripts.py" enshrouded \
            --out "$START_SCRIPT" \
            --server-dir "$SERVER_DIR" \
            --home-dir "$HOME_DIR" \
            --sys-user "$SYS_USER" \
        || die "Échec génération start_server.sh Enshrouded"
    fi

    chmod +x "$START_SCRIPT"
    chown "$SYS_USER:$SYS_USER" "$START_SCRIPT"
    ok "Script de démarrage : $START_SCRIPT"

    install_game_service_unit "$START_SCRIPT"
}

deploy_step_backups() {
    hdr "ÉTAPE 6 : Sauvegardes automatiques"
    local backup_out=""
    if backup_out="$(python3 "$SCRIPT_DIR/shared/deploybackups.py" install \
        --sys-user "$SYS_USER" \
        --app-dir "$APP_DIR" \
        --backup-dir "$BACKUP_DIR" \
        --instance-id "${INSTANCE_ID:-}" \
        --game-id "$GAME_ID" \
        --server-dir "$SERVER_DIR" \
        --data-dir "${DATA_DIR:-$SERVER_DIR}" \
        --world-name "${WORLD_NAME:-}" \
        $([[ "${SKIP_BACKUP_TEST:-false}" == "true" ]] && printf '%s' '--skip-backup-test') 2>&1)"; then
        while IFS= read -r _line; do
            [[ -n "$_line" ]] && ok "$_line"
        done <<< "$backup_out"
    else
        [[ -n "$backup_out" ]] && while IFS= read -r _line; do
            [[ -n "$_line" ]] && warn "$_line"
        done <<< "$backup_out"
        die "Échec configuration sauvegardes"
    fi
}

deploy_step_app_files() {
    hdr "ÉTAPE 7 : Game Commander"
    local app_out=""
    if app_out="$(python3 "$SCRIPT_DIR/shared/appfiles.py" install \
        $($DEPLOY_APP && printf '%s' '--deploy-app') \
        --src-dir "$SRC_DIR" \
        --app-dir "$APP_DIR" \
        --sys-user "$SYS_USER" \
        --script-dir "$SCRIPT_DIR" \
        --game-id "$GAME_ID" \
        --game-label "$GAME_LABEL" \
        --game-binary "$GAME_BINARY" \
        --game-service "$GAME_SERVICE" \
        --server-dir "$SERVER_DIR" \
        --data-dir "${DATA_DIR:-$SERVER_DIR}" \
        --world-name "${WORLD_NAME:-}" \
        --max-players "$MAX_PLAYERS" \
        --server-port "$SERVER_PORT" \
        --query-port "${QUERY_PORT:-}" \
        --echo-port "${ECHO_PORT:-}" \
        --url-prefix "$URL_PREFIX" \
        --flask-port "$FLASK_PORT" \
        --admin-login "$ADMIN_LOGIN" \
        --admin-password "$ADMIN_PASSWORD" \
        --steam-appid "${STEAM_APPID:-}" \
        --steamcmd-path "${STEAMCMD_PATH:-}" \
        $([[ "$GAME_ID" == "valheim" ]] && $BEPINEX && printf '%s' '--bepinex') 2>&1)"; then
        while IFS= read -r _line; do
            [[ -n "$_line" ]] && ok "$_line"
        done <<< "$app_out"
    else
        [[ -n "$app_out" ]] && while IFS= read -r _line; do
            [[ -n "$_line" ]] && warn "$_line"
        done <<< "$app_out"
        die "Échec installation fichiers Game Commander"
    fi
}

deploy_step_app_service() {
    hdr "ÉTAPE 8 : Service Game Commander"
    if $DEPLOY_APP; then
        if python3 "$SCRIPT_DIR/shared/appservice.py" install \
            --service-name "$GC_SERVICE" \
            --game-label "$GAME_LABEL" \
            --game-service "$GAME_SERVICE" \
            --sys-user "$SYS_USER" \
            --app-dir "$APP_DIR"; then
            ok "Service $GC_SERVICE actif"
        else
            err "$GC_SERVICE inactif — journalctl -u $GC_SERVICE -n 30"
        fi
    fi
    cpu_monitor_install
}

deploy_hub_admin_hash() {
    local hub_users_file="$1"
    local source_users_file="$2"
    local hash=""

    if [[ -n "${ADMIN_PASSWORD:-}" ]]; then
        hash=$(python3 -c \
            "import bcrypt,sys; print(bcrypt.hashpw(sys.argv[1].encode(), bcrypt.gensalt()).decode())" \
            "$ADMIN_PASSWORD") || return 1
        printf '%s\n' "$hash"
        return 0
    fi

    if [[ -f "$source_users_file" ]]; then
        hash="$(python3 - "$source_users_file" "$ADMIN_LOGIN" <<'PYEOF'
import json
import sys
from pathlib import Path

users = json.loads(Path(sys.argv[1]).read_text())
user = users.get(sys.argv[2], {})
print(user.get("password_hash", ""))
PYEOF
)"
        if [[ -n "$hash" ]]; then
            printf '%s\n' "$hash"
            return 0
        fi
    fi

    return 1
}

deploy_step_hub_service() {
    hdr "ÉTAPE 8B : Hub Admin"
    if [[ "${GC_SKIP_HUB_SERVICE:-0}" == "1" ]]; then
        info "Hub Admin conservé — synchro/redémarrage ignorés pour cette exécution"
        return
    fi
    local hub_out=""
    if hub_out="$(python3 "$SCRIPT_DIR/shared/hubsync.py" sync-values \
        --sys-user "$SYS_USER" \
        --app-dir "$APP_DIR" \
        --admin-login "$ADMIN_LOGIN" \
        --admin-password "$ADMIN_PASSWORD" \
        --repo-root "$SCRIPT_DIR" \
        --no-restart 2>&1)"; then
        while IFS= read -r _line; do
            [[ -n "$_line" ]] && ok "$_line"
        done <<< "$hub_out"
    else
        warn "Échec synchro Hub Admin"
        warn "$hub_out"
    fi
}

deploy_step_nginx() {
    hdr "ÉTAPE 9 : Nginx"
    # Compat modularization marker:
    # nginx_manifest_add "$INSTANCE_ID" "$URL_PREFIX" "$FLASK_PORT" "$GAME_LABEL"
    local nginx_out=""
    if nginx_out="$(python3 "$SCRIPT_DIR/shared/deploynginx.py" apply \
        --script-dir "$SCRIPT_DIR" \
        --domain "$DOMAIN" \
        --instance-id "$INSTANCE_ID" \
        --url-prefix "$URL_PREFIX" \
        --flask-port "$FLASK_PORT" \
        --game-label "$GAME_LABEL" 2>&1)"; then
        ok "$nginx_out"
    else
        err "Vérifiez manuellement : nginx -t"
        [[ -n "$nginx_out" ]] && warn "$nginx_out"
    fi
}

deploy_step_ssl() {
    hdr "ÉTAPE 10 : SSL"
    local ssl_out=""
    if ssl_out="$(python3 "$SCRIPT_DIR/shared/deployssl.py" apply \
        --ssl-mode "$SSL_MODE" \
        --domain "$DOMAIN" 2>&1)"; then
        while IFS= read -r _line; do
            [[ -z "$_line" ]] && continue
            if [[ "$_line" == "HTTP uniquement" ]]; then
                warn "$_line"
            else
                ok "$_line"
            fi
        done <<< "$ssl_out"
    else
        [[ -n "$ssl_out" ]] && warn "$ssl_out"
        warn "Gestion SSL en erreur"
    fi
}

deploy_step_sudoers() {
    hdr "ÉTAPE 11 : Permissions sudo"
    local sudo_out=""
    if sudo_out="$(python3 "$SCRIPT_DIR/shared/deploysudo.py" write-instance \
        --sys-user "$SYS_USER" \
        --game-label "$GAME_LABEL" \
        --instance-id "$INSTANCE_ID" \
        --game-service "$GAME_SERVICE" \
        --bepinex-path "${GC_BEPINEX_PATH:-}" 2>&1)"; then
        ok "$sudo_out"
    else
        err "Sudoers invalide — supprimé"
        warn "Erreur visudo : $sudo_out"
        warn "À créer manuellement :"
        echo "    sudo tee /etc/sudoers.d/game-commander-${INSTANCE_ID} > /dev/null << 'EOF'"
        echo "    ${SYS_USER} ALL=(ALL) NOPASSWD: /usr/bin/systemctl start ${GAME_SERVICE}"
        echo "    ${SYS_USER} ALL=(ALL) NOPASSWD: /usr/bin/systemctl stop ${GAME_SERVICE}"
        echo "    ${SYS_USER} ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart ${GAME_SERVICE}"
        echo "    EOF"
    fi
}

deploy_step_save_config() {
    CONFIG_SAVE="$APP_DIR/deploy_config.env"
    # Compat modularization markers:
    # echo "DEPLOY_MODE=\"${DEPLOY_MODE}\""
    # echo "GAME_SERVICE=\"${GAME_SERVICE}\""
    env \
        GAME_ID="$GAME_ID" \
        DEPLOY_MODE="$DEPLOY_MODE" \
        INSTANCE_ID="$INSTANCE_ID" \
        SYS_USER="$SYS_USER" \
        SERVER_DIR="$SERVER_DIR" \
        DATA_DIR="$DATA_DIR" \
        BACKUP_DIR="$BACKUP_DIR" \
        APP_DIR="$APP_DIR" \
        SRC_DIR="$SRC_DIR" \
        GAME_SERVICE="$GAME_SERVICE" \
        SERVER_NAME="$SERVER_NAME" \
        SERVER_PASSWORD="${SERVER_PASSWORD:-}" \
        SERVER_ADMIN_PASSWORD="${SERVER_ADMIN_PASSWORD:-}" \
        SERVER_PORT="$SERVER_PORT" \
        QUERY_PORT="${QUERY_PORT:-}" \
        ECHO_PORT="${ECHO_PORT:-}" \
        MAX_PLAYERS="$MAX_PLAYERS" \
        SERVER_MODE="${SERVER_MODE:-}" \
        BACKUP_ENABLED="${BACKUP_ENABLED:-}" \
        SAVING_ENABLED="${SAVING_ENABLED:-}" \
        BACKUP_INTERVAL="${BACKUP_INTERVAL:-}" \
        WORLD_NAME="${WORLD_NAME:-}" \
        CROSSPLAY="${CROSSPLAY:-}" \
        BEPINEX="${BEPINEX:-}" \
        DOMAIN="$DOMAIN" \
        URL_PREFIX="$URL_PREFIX" \
        FLASK_PORT="$FLASK_PORT" \
        SSL_MODE="$SSL_MODE" \
        ADMIN_LOGIN="$ADMIN_LOGIN" \
        ADMIN_PASSWORD="${ADMIN_PASSWORD:-}" \
        AUTO_INSTALL_DEPS="${AUTO_INSTALL_DEPS:-true}" \
        AUTO_INSTALL_STEAMCMD="${AUTO_INSTALL_STEAMCMD:-true}" \
        AUTO_INSTALL_BEPINEX="${AUTO_INSTALL_BEPINEX:-true}" \
        AUTO_UPDATE_SERVER="${AUTO_UPDATE_SERVER:-false}" \
        AUTO_CONFIRM="${AUTO_CONFIRM:-true}" \
        python3 "$SCRIPT_DIR/shared/deploypost.py" save-values --config "$CONFIG_SAVE" >/dev/null 2>&1 \
        || die "Échec sauvegarde config : $CONFIG_SAVE"
    ok "Config sauvegardée : $CONFIG_SAVE"

    cpu_affinity_apply_all false
}

deploy_step_discord_channel() {
    hdr "ÉTAPE 10 : Discord"
    local discord_out=""
    if discord_out="$(python3 "$SCRIPT_DIR/shared/discordnotify.py" create-channel \
        --instance "$INSTANCE_ID" --game "$GAME_ID" 2>&1)"; then
        ok "$discord_out"
    else
        [[ "$discord_out" == *"guild_id non configuré"* || "$discord_out" == *"Bot token"* ]] \
            && info "Discord non configuré — channel non créé" \
            || warn "Discord : $discord_out"
    fi
}

deploy_step_validation() {
    hdr "VALIDATION FINALE"
    echo ""
    ERRORS=0
    local _line access_summary=""
    local -a _GAME_PORTS=()
    while IFS= read -r _line; do
        [[ -z "$_line" ]] && continue
        case "$_line" in
            VALIDATION_ERRORS=*)
                ERRORS="${_line#VALIDATION_ERRORS=}"
                ;;
            Service*": actif"|Game\ Commander*|Nginx*": actif")
                ok "$_line"
                ;;
            Service*": inactif"|Game\ Commander\ ne*|Nginx*": inactif")
                warn "$_line"
                ;;
            FIREWALL=*)
                _GAME_PORTS+=("${_line#FIREWALL=}")
                ;;
            Accès\ :*|Redéploiement\ :*)
                access_summary+="${_line}"$'\n'
                ;;
        esac
    done < <(python3 "$SCRIPT_DIR/shared/deploypost.py" validate --config "$CONFIG_SAVE")

    echo ""
    sep
    echo ""
    echo -e "  ${BOLD}Accès à l'interface :${RESET}"
    [[ "$SSL_MODE" != "none" ]] \
        && echo -e "  ${CYAN}  https://${DOMAIN}${URL_PREFIX}${RESET}" \
        || echo -e "  ${CYAN}  http://${DOMAIN}${URL_PREFIX}${RESET}"
    echo ""
    echo -e "  ${BOLD}Commandes utiles :${RESET}"
    echo "    sudo systemctl status ${GAME_SERVICE}"
    $DEPLOY_APP && echo "    sudo systemctl status ${GC_SERVICE}"
    echo "    sudo journalctl -u ${GAME_SERVICE} -f"
    $DEPLOY_APP && echo "    sudo journalctl -u ${GC_SERVICE} -f"
    echo ""
    echo -e "  ${BOLD}Redéploiement rapide :${RESET}"
    echo "    sudo bash game_commander.sh deploy --config $CONFIG_SAVE"
    echo ""
    echo -e "  ${BOLD}Ports à ouvrir (firewall) :${RESET}"
    if [[ "$GAME_ID" == "minecraft" || "$GAME_ID" == "minecraft-fabric" ]]; then
        echo -e "    Jeu  : ${SERVER_PORT}/TCP"
    elif [[ "$GAME_ID" == "satisfactory" ]]; then
        echo -e "    Jeu  : ${SERVER_PORT}/TCP  ${SERVER_PORT}/UDP"
        echo -e "    Flux fiable / join  : ${QUERY_PORT}/TCP"
    elif [[ "$GAME_ID" == "terraria" ]]; then
        echo -e "    Jeu  : ${SERVER_PORT}/TCP"
    elif [[ "$GAME_ID" == "soulmask" ]]; then
        echo -e "    Jeu  : ${SERVER_PORT}/UDP  ${QUERY_PORT}/UDP  ${ECHO_PORT}/TCP"
    else
        echo -e "    Jeu  : ${SERVER_PORT}/UDP  $((SERVER_PORT+1))/UDP"
    fi
    echo -e "    Web  : 80/TCP  443/TCP"
    if command -v ufw &>/dev/null && ufw status 2>/dev/null | grep -q "Status: active"; then
        info "UFW actif — ouverture des ports..."
        for _p in "${_GAME_PORTS[@]}"; do
            ufw allow "$_p" && ok "UFW : $_p ouvert"
        done
        ufw allow "80/tcp" && ok "UFW : 80/tcp ouvert"
        ufw allow "443/tcp" && ok "UFW : 443/tcp ouvert"
    else
        warn "UFW inactif ou absent — pensez à ouvrir les ports dans le firewall Hetzner :"
        if [[ "$GAME_ID" == "minecraft" || "$GAME_ID" == "minecraft-fabric" ]]; then
            echo "    ${SERVER_PORT}/TCP, 80/TCP, 443/TCP"
        elif [[ "$GAME_ID" == "satisfactory" ]]; then
            echo "    ${SERVER_PORT}/TCP, ${SERVER_PORT}/UDP, ${QUERY_PORT}/TCP, 80/TCP, 443/TCP"
            echo "    (${QUERY_PORT}/TCP est requis pour le join fiable des joueurs)"
        elif [[ "$GAME_ID" == "terraria" ]]; then
            echo "    ${SERVER_PORT}/TCP, 80/TCP, 443/TCP"
        elif [[ "$GAME_ID" == "soulmask" ]]; then
            echo "    ${SERVER_PORT}/UDP, ${QUERY_PORT}/UDP, ${ECHO_PORT}/TCP, 80/TCP, 443/TCP"
        else
            echo "    ${SERVER_PORT}/UDP, $((SERVER_PORT+1))/UDP, 80/TCP, 443/TCP"
        fi
    fi
    echo ""
    [[ $ERRORS -eq 0 ]] \
        && echo -e "  ${GREEN}${BOLD}✓ Déploiement terminé avec succès !${RESET}" \
        || echo -e "  ${YELLOW}${BOLD}⚠ Déploiement terminé avec $ERRORS avertissement(s)${RESET}"
    echo ""
    info "Journal complet : $LOGFILE"
}
