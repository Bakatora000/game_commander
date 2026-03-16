# ── lib/deploy_steps.sh ──────────────────────────────────────────────────────
# Étapes 3 à 12 du déploiement Game Commander

deploy_step_dependencies() {
    hdr "ÉTAPE 3 : Dépendances"

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

    for pkg in python3 python3-pip nginx curl zip unzip jq; do install_pkg "$pkg"; done

    if [[ "$DEPLOY_MODE" != "attach" && -n "$STEAM_APPID" ]]; then
        dpkg --print-foreign-architectures | grep -q i386 || {
            info "Activation i386..."
            dpkg --add-architecture i386
            apt_once
        }
        install_pkg "lib32gcc-s1"
    fi

    PY_APT_PKGS=("python3-flask")
    PY_PIP_PKGS=("requests" "bcrypt" "psutil")

    for pkg in "${PY_APT_PKGS[@]}"; do
        python3 -c "import ${pkg/python3-/}" 2>/dev/null && ok "Python: ${pkg/python3-/} OK" || {
            warn "Python: ${pkg/python3-/} manquant"
            do_it=false
            $AUTO_INSTALL_DEPS && do_it=true || { confirm "Installer $pkg (apt) ?" "o" && do_it=true; }
            $do_it && { apt_once; apt-get install -y -qq "$pkg" && ok "Python: ${pkg/python3-/} installé (apt)"; }
        }
    done

    for pkg in "${PY_PIP_PKGS[@]}"; do
        python3 -c "import $pkg" 2>/dev/null && ok "Python: $pkg OK" || {
            warn "Python: $pkg manquant"
            do_it=false
            $AUTO_INSTALL_DEPS && do_it=true || { confirm "pip install $pkg ?" "o" && do_it=true; }
            $do_it && pip3 install "$pkg" --break-system-packages -q && ok "Python: $pkg installé"
        }
    done

    [[ "$SSL_MODE" == "certbot" ]] && { install_pkg certbot; install_pkg python3-certbot-nginx; }

    if [[ "$DEPLOY_MODE" != "attach" && "$GAME_ID" == "enshrouded" ]]; then
        info "Enshrouded requiert Wine (binaire Windows) + Xvfb..."
        if ! cmd_exists wine64 || ! dpkg -l wine64 2>/dev/null | grep -q "^ii"; then
            warn "wine64 absent — installation depuis les dépôts système..."
            apt_once
            apt-get install -y -qq wine64 xvfb && ok "Wine64 + Xvfb installés" || die "Échec installation Wine"
        else
            ok "Wine64 déjà présent"
        fi
        if ! cmd_exists wine64; then
            if cmd_exists wine; then
                ln -sf "$(command -v wine)" /usr/local/bin/wine64
                ok "Symlink wine64 → wine créé dans /usr/local/bin"
            elif [[ -x /usr/lib/wine/wine64 ]]; then
                ln -sf /usr/lib/wine/wine64 /usr/local/bin/wine64
                ok "Symlink wine64 → /usr/lib/wine/wine64 créé"
            else
                die "wine64 introuvable dans le PATH après installation — vérifiez le paquet wine"
            fi
        fi
        if ! cmd_exists xvfb-run; then
            apt_once
            apt-get install -y -qq xvfb && ok "Xvfb installé" || warn "Xvfb absent"
        else
            ok "Xvfb déjà présent"
        fi
        if [[ ! -d "$HOME_DIR/.wine" ]]; then
            info "Initialisation du prefix Wine pour $SYS_USER..."
            sudo -u "$SYS_USER" WINEDEBUG=-all wineboot --init 2>/dev/null && ok "Prefix Wine initialisé" || warn "wineboot : vérifiez manuellement"
        else
            ok "Prefix Wine existant"
        fi
    fi

    STEAMCMD_PATH=""
    if [[ "$DEPLOY_MODE" != "attach" && -n "$STEAM_APPID" ]]; then
        if cmd_exists steamcmd; then
            STEAMCMD_PATH=$(command -v steamcmd); ok "SteamCMD : $STEAMCMD_PATH"
        elif [[ -f "$HOME_DIR/steamcmd/steamcmd.sh" ]]; then
            STEAMCMD_PATH="$HOME_DIR/steamcmd/steamcmd.sh"; ok "SteamCMD : $STEAMCMD_PATH"
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
            sudo -u "$SYS_USER" "$STEAMCMD_PATH" \
                +@sSteamCmdForcePlatformType linux \
                +login anonymous \
                +force_install_dir "$SERVER_DIR" \
                +app_update "$STEAM_APPID" validate \
                +quit || die "Échec SteamCMD."
            ok "$GAME_LABEL téléchargé"
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

        if [[ -f "$SERVER_DIR/TerrariaServer.bin.x86_64" ]]; then
            ok "Serveur Terraria déjà présent"
        else
            info "Téléchargement du serveur dédié officiel Terraria..."
            python3 - "$SERVER_DIR" <<'PYEOF' || die "Échec téléchargement serveur Terraria"
import re
import shutil
import sys
import tempfile
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

server_dir = Path(sys.argv[1])
home_url = "https://terraria.org/"
headers = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,fr;q=0.8",
}

def fetch(url, timeout=20, referer=None):
    req_headers = dict(headers)
    if referer:
        req_headers["Referer"] = referer
    req = urllib.request.Request(url, headers=req_headers)
    return urllib.request.urlopen(req, timeout=timeout)

def latest_zip_url():
    with fetch(home_url, timeout=20) as r:
        html = r.read().decode("utf-8", errors="ignore")

    matches = re.findall(r'href="([^"]*/api/download/pc-dedicated-server/terraria-server-[^"]+\.zip)"', html)
    if matches:
        return urllib.parse.urljoin(home_url, matches[0])

    # Fallback pragmatique : terraria.org suit le schéma
    # terraria-server-<version_sans_points>.zip.
    # On teste d'abord les versions récentes plausibles.
    for compact in (
        "1459", "1458", "1457", "1456", "1455", "1454", "1453", "1452", "1451", "1450",
        "1449", "1448", "1447", "1446", "1445", "1444", "1443", "1442", "1441", "1440",
    ):
        candidate = f"https://terraria.org/api/download/pc-dedicated-server/terraria-server-{compact}.zip"
        try:
            with fetch(candidate, timeout=20, referer=home_url) as r:
                if getattr(r, "status", 200) == 200:
                    return candidate
        except Exception:
            continue

    raise SystemExit("Lien serveur Terraria introuvable sur terraria.org")

zip_url = latest_zip_url()
with tempfile.TemporaryDirectory() as tmp:
    tmp_path = Path(tmp)
    zip_path = tmp_path / "terraria-server.zip"
    with fetch(zip_url, timeout=120, referer=home_url) as r, open(zip_path, "wb") as f:
        f.write(r.read())

    extract_dir = tmp_path / "extract"
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(extract_dir)

    candidates = list(extract_dir.rglob("TerrariaServer.bin.x86_64"))
    if not candidates:
        raise SystemExit("Binaire TerrariaServer.bin.x86_64 introuvable dans l'archive")

    linux_dir = candidates[0].parent
    for entry in linux_dir.iterdir():
        dest = server_dir / entry.name
        if dest.exists():
            if dest.is_dir():
                shutil.rmtree(dest)
            else:
                dest.unlink()
        if entry.is_dir():
            shutil.copytree(entry, dest)
        else:
            shutil.copy2(entry, dest)

print(f"[terraria] serveur dédié téléchargé depuis : {zip_url}")
PYEOF
            chown -R "$SYS_USER:$SYS_USER" "$SERVER_DIR"
            chmod +x "$SERVER_DIR/TerrariaServer.bin.x86_64" 2>/dev/null || true
            ok "Serveur Terraria téléchargé"
        fi

        if [[ ! -f "$SERVER_DIR/serverconfig.txt" ]]; then
            python3 "$SCRIPT_DIR/tools/config_gen.py" terraria-cfg \
                --out "$SERVER_DIR/serverconfig.txt" \
                --name "$SERVER_NAME" \
                --port "$SERVER_PORT" \
                --max-players "$MAX_PLAYERS" \
                --world-path "$DATA_DIR" \
                --world-name "$INSTANCE_ID" \
            || die "Échec génération serverconfig.txt"
            chown "$SYS_USER:$SYS_USER" "$SERVER_DIR/serverconfig.txt"
            ok "serverconfig.txt généré"
        fi
        return
    fi

    if [[ "$GAME_ID" == "minecraft-fabric" ]]; then
        hdr "ÉTAPE 4 : Installation Minecraft Fabric"
        install_pkg "default-jre-headless"
        mkdir -p "$SERVER_DIR"
        chown -R "$SYS_USER:$SYS_USER" "$SERVER_DIR"

        if [[ -f "$SERVER_DIR/fabric-server-launch.jar" ]]; then
            ok "Fabric server launcher déjà présent"
        else
            info "Téléchargement du serveur Minecraft Fabric..."
            python3 - "$SERVER_DIR" <<'PYEOF' || die "Échec téléchargement serveur Minecraft Fabric"
import json
import sys
import urllib.request
from pathlib import Path

server_dir = Path(sys.argv[1])
out = server_dir / "fabric-server-launch.jar"
meta_out = server_dir / ".fabric-meta.json"

with urllib.request.urlopen("https://launchermeta.mojang.com/mc/game/version_manifest_v2.json", timeout=20) as r:
    manifest = json.load(r)
mc_version = manifest["latest"]["release"]

with urllib.request.urlopen("https://meta.fabricmc.net/v2/versions/loader", timeout=20) as r:
    loader_version = json.load(r)[0]["version"]

with urllib.request.urlopen("https://meta.fabricmc.net/v2/versions/installer", timeout=20) as r:
    installer_version = json.load(r)[0]["version"]

jar_url = f"https://meta.fabricmc.net/v2/versions/loader/{mc_version}/{loader_version}/{installer_version}/server/jar"
with urllib.request.urlopen(jar_url, timeout=60) as r, open(out, "wb") as f:
    f.write(r.read())

meta = {
    "minecraft_version": mc_version,
    "loader_version": loader_version,
    "installer_version": installer_version,
    "loader": "fabric",
}
meta_out.write_text(json.dumps(meta, indent=2) + "\n")
print(f"[fabric] launcher téléchargé : {out}")
print(f"[fabric] meta enregistrée : {meta_out}")
PYEOF
            chown "$SYS_USER:$SYS_USER" "$SERVER_DIR/fabric-server-launch.jar" "$SERVER_DIR/.fabric-meta.json"
            ok "Serveur Minecraft Fabric téléchargé"
        fi

        if [[ ! -f "$SERVER_DIR/eula.txt" ]]; then
            cat > "$SERVER_DIR/eula.txt" << 'EOF'
# EULA acceptée automatiquement par Game Commander
eula=true
EOF
            chown "$SYS_USER:$SYS_USER" "$SERVER_DIR/eula.txt"
            ok "eula.txt généré"
        fi

        mkdir -p "$SERVER_DIR/mods"
        chown "$SYS_USER:$SYS_USER" "$SERVER_DIR/mods"

        if [[ ! -f "$SERVER_DIR/server.properties" ]]; then
            python3 "$SCRIPT_DIR/tools/config_gen.py" minecraft-props \
                --out "$SERVER_DIR/server.properties" \
                --name "$SERVER_NAME" \
                --port "$SERVER_PORT" \
                --max-players "$MAX_PLAYERS" \
            || die "Échec génération server.properties"
            chown "$SYS_USER:$SYS_USER" "$SERVER_DIR/server.properties"
            ok "server.properties généré"
        fi
        return
    fi

    if [[ "$GAME_ID" == "minecraft" ]]; then
        hdr "ÉTAPE 4 : Installation Minecraft Java"
        install_pkg "default-jre-headless"
        mkdir -p "$SERVER_DIR"
        chown -R "$SYS_USER:$SYS_USER" "$SERVER_DIR"
        if [[ -f "$SERVER_DIR/server.jar" ]]; then
            ok "server.jar déjà présent"
        else
            info "Téléchargement du dernier serveur Minecraft Java vanilla..."
            python3 - "$SERVER_DIR/server.jar" <<'PYEOF' || die "Échec téléchargement serveur Minecraft"
import json
import sys
import urllib.request

out = sys.argv[1]
with urllib.request.urlopen("https://launchermeta.mojang.com/mc/game/version_manifest_v2.json", timeout=20) as r:
    manifest = json.load(r)
latest_id = manifest["latest"]["release"]
version_meta_url = next(v["url"] for v in manifest["versions"] if v["id"] == latest_id)
with urllib.request.urlopen(version_meta_url, timeout=20) as r:
    version_meta = json.load(r)
jar_url = version_meta["downloads"]["server"]["url"]
with urllib.request.urlopen(jar_url, timeout=60) as r, open(out, "wb") as f:
    f.write(r.read())
print(f"[minecraft] server.jar téléchargé : {out}")
PYEOF
            chown "$SYS_USER:$SYS_USER" "$SERVER_DIR/server.jar"
            ok "Serveur Minecraft Java téléchargé"
        fi

        if [[ ! -f "$SERVER_DIR/eula.txt" ]]; then
            cat > "$SERVER_DIR/eula.txt" << 'EOF'
# EULA acceptée automatiquement par Game Commander
eula=true
EOF
            chown "$SYS_USER:$SYS_USER" "$SERVER_DIR/eula.txt"
            ok "eula.txt généré"
        fi

        if [[ ! -f "$SERVER_DIR/server.properties" ]]; then
            python3 "$SCRIPT_DIR/tools/config_gen.py" minecraft-props \
                --out "$SERVER_DIR/server.properties" \
                --name "$SERVER_NAME" \
                --port "$SERVER_PORT" \
                --max-players "$MAX_PLAYERS" \
            || die "Échec génération server.properties"
            chown "$SYS_USER:$SYS_USER" "$SERVER_DIR/server.properties"
            ok "server.properties généré"
        fi
        return
    fi

    hdr "ÉTAPE 4 : Installation $GAME_LABEL"
    mkdir -p "$SERVER_DIR"
    [[ "$GAME_ID" == "valheim" ]] && mkdir -p "$DATA_DIR"
    chown -R "$SYS_USER:$SYS_USER" "$SERVER_DIR"
    [[ "$GAME_ID" == "valheim" ]] && chown -R "$SYS_USER:$SYS_USER" "$DATA_DIR"

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
        sudo -u "$SYS_USER" "$STEAMCMD_PATH" \
            +@sSteamCmdForcePlatformType "$_platform" \
            +login anonymous \
            +force_install_dir "$SERVER_DIR" \
            +app_update "$STEAM_APPID" validate \
            +quit || die "Échec SteamCMD."
        ok "$GAME_LABEL téléchargé"
    fi

    [[ -f "$SERVER_DIR/$GAME_BINARY" ]] || die "Binaire $GAME_BINARY introuvable dans $SERVER_DIR"
    [[ "$GAME_ID" != "enshrouded" ]] && chmod +x "$SERVER_DIR/$GAME_BINARY" 2>/dev/null || true
    chown -R "$SYS_USER:$SYS_USER" "$SERVER_DIR"
    ok "Binaire $GAME_BINARY vérifié"

    if [[ "$GAME_ID" == "valheim" ]] && $BEPINEX; then
        BEPINEX_PATH="$SERVER_DIR/BepInEx"
        if [[ -d "$BEPINEX_PATH" ]]; then
            ok "BepInEx déjà présent"
        else
            do_bep=false
            $AUTO_INSTALL_BEPINEX && do_bep=true || { confirm "Installer BepInEx ?" "o" && do_bep=true; }
            $do_bep && {
                info "Téléchargement BepInEx..."
                TMP=$(mktemp -d)
                curl -sL "https://thunderstore.io/package/download/denikson/BepInExPack_Valheim/5.4.2202/" -o "$TMP/bep.zip"
                unzip -q "$TMP/bep.zip" -d "$TMP/extracted"
                SRC_BEP="$TMP/extracted"
                [[ -d "$TMP/extracted/BepInExPack_Valheim" ]] && SRC_BEP="$TMP/extracted/BepInExPack_Valheim"
                cp -r "$SRC_BEP/." "$SERVER_DIR/"
                chown -R "$SYS_USER:$SYS_USER" "$SERVER_DIR"
                rm -rf "$TMP"
                ok "BepInEx installé"
            }
        fi
    else
        BEPINEX_PATH=""
    fi
}

deploy_step_game_service() {
    hdr "ÉTAPE 5 : Service $GAME_LABEL"

    if [[ "$DEPLOY_MODE" == "attach" ]]; then
        info "Mode attach — service de jeu existant conservé : $GAME_SERVICE"
        return
    fi

    if [[ "$GAME_ID" == "minecraft" ]]; then
        START_SCRIPT="$SERVER_DIR/start_server.sh"
        cat > "$START_SCRIPT" << STARTEOF
#!/usr/bin/env bash
cd "${SERVER_DIR}"
exec /usr/bin/java -Xms1G -Xmx2G -jar server.jar nogui
STARTEOF
        chmod +x "$START_SCRIPT"
        chown "$SYS_USER:$SYS_USER" "$START_SCRIPT"
        ok "Script de démarrage : $START_SCRIPT"

        cat > "/etc/systemd/system/${GAME_SERVICE}.service" << SVCEOF
[Unit]
Description=${GAME_LABEL} Dedicated Server
After=network.target

[Service]
Type=simple
User=${SYS_USER}
WorkingDirectory=${SERVER_DIR}
ExecStart=${START_SCRIPT}
Restart=on-failure
RestartSec=10
SuccessExitStatus=0 130 143
StandardOutput=journal
StandardError=journal
SyslogIdentifier=${GAME_SERVICE}
KillSignal=SIGINT
KillMode=mixed
TimeoutStopSec=60

[Install]
WantedBy=multi-user.target
SVCEOF

        systemctl daemon-reload
        systemctl enable "$GAME_SERVICE"
        info "Démarrage de $GAME_SERVICE..."
        systemctl start "$GAME_SERVICE"
        sleep 5
        service_active "$GAME_SERVICE" \
            && ok "Service $GAME_SERVICE actif" \
            || warn "$GAME_SERVICE pas encore actif — journalctl -u $GAME_SERVICE -f"
        return
    fi

    if [[ "$GAME_ID" == "minecraft-fabric" ]]; then
        START_SCRIPT="$SERVER_DIR/start_server.sh"
        cat > "$START_SCRIPT" << STARTEOF
#!/usr/bin/env bash
cd "${SERVER_DIR}"
exec /usr/bin/java -Xms1G -Xmx2G -jar fabric-server-launch.jar nogui
STARTEOF
        chmod +x "$START_SCRIPT"
        chown "$SYS_USER:$SYS_USER" "$START_SCRIPT"
        ok "Script de démarrage : $START_SCRIPT"

        cat > "/etc/systemd/system/${GAME_SERVICE}.service" << SVCEOF
[Unit]
Description=${GAME_LABEL} Dedicated Server
After=network.target

[Service]
Type=simple
User=${SYS_USER}
WorkingDirectory=${SERVER_DIR}
ExecStart=${START_SCRIPT}
Restart=on-failure
RestartSec=10
SuccessExitStatus=0 130 143
StandardOutput=journal
StandardError=journal
SyslogIdentifier=${GAME_SERVICE}
KillSignal=SIGINT
KillMode=mixed
TimeoutStopSec=60

[Install]
WantedBy=multi-user.target
SVCEOF

        systemctl daemon-reload
        systemctl enable "$GAME_SERVICE"
        info "Démarrage de $GAME_SERVICE..."
        systemctl start "$GAME_SERVICE"
        sleep 5
        service_active "$GAME_SERVICE" \
            && ok "Service $GAME_SERVICE actif" \
            || warn "$GAME_SERVICE pas encore actif — journalctl -u $GAME_SERVICE -f"
        return
    fi

    if [[ "$GAME_ID" == "terraria" ]]; then
        START_SCRIPT="$SERVER_DIR/start_server.sh"
        WRAPPER_SCRIPT="$SERVER_DIR/start_server_service.sh"
        mkdir -p "$SERVER_DIR/logs"
        cat > "$START_SCRIPT" << 'STARTEOF'
#!/usr/bin/env bash
cd "__SERVER_DIR__"
CFG="__SERVER_DIR__/serverconfig.txt"
cfg_get() {
    local key="$1"
    sed -n "s/^${key}=//p" "$CFG" | head -1
}
WORLD="\$(cfg_get world)"
WORLDPATH="\$(cfg_get worldpath)"
WORLDNAME="\$(cfg_get worldname)"
AUTOCREATE="\$(cfg_get autocreate)"
DIFFICULTY="\$(cfg_get difficulty)"
PORT="\$(cfg_get port)"
MAXPLAYERS="\$(cfg_get maxplayers)"
PASSWORD="\$(cfg_get password)"
MOTD="\$(cfg_get motd)"
[[ -z "\$WORLD" && -n "\$WORLDPATH" && -n "\$WORLDNAME" ]] && WORLD="\$WORLDPATH/\$WORLDNAME.wld"
mkdir -p "\$WORLDPATH" "${SERVER_DIR}/logs"
ARGS=(
    -world "\$WORLD"
    -autocreate "\${AUTOCREATE:-2}"
    -worldname "\$WORLDNAME"
    -difficulty "\${DIFFICULTY:-0}"
    -port "\${PORT:-7777}"
    -maxplayers "\${MAXPLAYERS:-8}"
    -motd "\$MOTD"
    -logpath "${SERVER_DIR}/logs"
)
[[ -n "\$PASSWORD" ]] && ARGS+=(-password "\$PASSWORD")
exec ./TerrariaServer.bin.x86_64 "\${ARGS[@]}"
STARTEOF
        sed -i "s|__SERVER_DIR__|${SERVER_DIR}|g" "$START_SCRIPT"
        chmod +x "$START_SCRIPT"
        chown "$SYS_USER:$SYS_USER" "$START_SCRIPT"
        ok "Script de démarrage : $START_SCRIPT"

        cat > "$WRAPPER_SCRIPT" << WRAPEOF
#!/usr/bin/env bash
exec /usr/bin/script -qefc "${START_SCRIPT}" /dev/null
WRAPEOF
        chmod +x "$WRAPPER_SCRIPT"
        chown "$SYS_USER:$SYS_USER" "$WRAPPER_SCRIPT"
        ok "Wrapper service : $WRAPPER_SCRIPT"

        cat > "/etc/systemd/system/${GAME_SERVICE}.service" << SVCEOF
[Unit]
Description=${GAME_LABEL} Dedicated Server
After=network.target

[Service]
Type=simple
User=${SYS_USER}
WorkingDirectory=${SERVER_DIR}
ExecStart=${WRAPPER_SCRIPT}
Restart=on-failure
RestartSec=10
SuccessExitStatus=0 130 143
StandardOutput=journal
StandardError=journal
SyslogIdentifier=${GAME_SERVICE}
KillSignal=SIGINT
KillMode=mixed
TimeoutStopSec=60

[Install]
WantedBy=multi-user.target
SVCEOF

        systemctl daemon-reload
        systemctl enable "$GAME_SERVICE"
        info "Démarrage de $GAME_SERVICE..."
        systemctl start "$GAME_SERVICE"
        sleep 5
        service_active "$GAME_SERVICE" \
            && ok "Service $GAME_SERVICE actif" \
            || warn "$GAME_SERVICE pas encore actif — journalctl -u $GAME_SERVICE -f"
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

        cat > "$START_SCRIPT" << 'STARTEOF'
#!/usr/bin/env bash
set -euo pipefail
cd "__SERVER_DIR__"
CFG="__CFG_PATH__"

json_get() {
    jq -r "$1" "$CFG"
}

SERVER_NAME="$(json_get '.server_name')"
MAX_PLAYERS="$(json_get '.max_players')"
PASSWORD="$(json_get '.password')"
ADMIN_PASSWORD="$(json_get '.admin_password')"
MODE="$(json_get '.mode')"
PORT="$(json_get '.port')"
QUERY_PORT="$(json_get '.query_port')"
ECHO_PORT="$(json_get '.echo_port')"
BACKUP_ENABLED="$(json_get '.backup_enabled')"
SAVING_ENABLED="$(json_get '.saving_enabled')"
BACKUP_INTERVAL="$(json_get '.backup_interval')"

ARGS=(
  "-SteamServerName=${SERVER_NAME}"
  "-MaxPlayers=${MAX_PLAYERS}"
  "-Port=${PORT}"
  "-QueryPort=${QUERY_PORT}"
)

[[ -n "$PASSWORD" && "$PASSWORD" != "null" ]] && ARGS+=("-PSW=${PASSWORD}")
[[ -n "$ADMIN_PASSWORD" && "$ADMIN_PASSWORD" != "null" ]] && ARGS+=("-adminpsw=${ADMIN_PASSWORD}")
[[ "$MODE" == "pvp" ]] && ARGS+=(-pvp) || ARGS+=(-pve)
[[ "$BACKUP_ENABLED" == "true" ]] && ARGS+=(-backup)
[[ "$SAVING_ENABLED" == "true" ]] && ARGS+=(-saving)
[[ -n "$BACKUP_INTERVAL" && "$BACKUP_INTERVAL" != "null" ]] && ARGS+=("-backupinterval=${BACKUP_INTERVAL}")

exec ./WSServer.sh Level01_Main -server "${ARGS[@]}" -log -UTF8Output -MULTIHOME=0.0.0.0 "-EchoPort=${ECHO_PORT}" -forcepassthrough
STARTEOF
        sed -i "s|__SERVER_DIR__|${SERVER_DIR}|g; s|__CFG_PATH__|${SOULMASK_CFG}|g" "$START_SCRIPT"
        chmod +x "$START_SCRIPT"
        chown "$SYS_USER:$SYS_USER" "$START_SCRIPT"
        ok "Script de démarrage : $START_SCRIPT"

        cat > "/etc/systemd/system/${GAME_SERVICE}.service" << SVCEOF
[Unit]
Description=${GAME_LABEL} Dedicated Server
After=network.target

[Service]
Type=simple
User=${SYS_USER}
WorkingDirectory=${SERVER_DIR}
ExecStart=${START_SCRIPT}
Restart=on-failure
RestartSec=10
SuccessExitStatus=0 130 143
StandardOutput=journal
StandardError=journal
SyslogIdentifier=${GAME_SERVICE}
KillSignal=SIGINT
KillMode=mixed
TimeoutStopSec=60

[Install]
WantedBy=multi-user.target
SVCEOF

        systemctl daemon-reload
        systemctl enable "$GAME_SERVICE"
        info "Démarrage de $GAME_SERVICE..."
        systemctl start "$GAME_SERVICE"
        sleep 5
        service_active "$GAME_SERVICE" \
            && ok "Service $GAME_SERVICE actif" \
            || warn "$GAME_SERVICE pas encore actif — journalctl -u $GAME_SERVICE -f"
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
                cat > "$START_SCRIPT" << STARTEOF
#!/usr/bin/env bash
export DOORSTOP_ENABLE=TRUE
export DOORSTOP_INVOKE_DLL_PATH=./BepInEx/core/BepInEx.Preloader.dll
export DOORSTOP_CORLIB_OVERRIDE_PATH=./unstripped_corlib
export LD_LIBRARY_PATH="./doorstop_libs:\$LD_LIBRARY_PATH"
export LD_PRELOAD="libdoorstop_x64.so:\$LD_PRELOAD"
export LD_LIBRARY_PATH="./linux64:\$LD_LIBRARY_PATH"
export SteamAppId=892970
cd "${SERVER_DIR}"
exec ./valheim_server.x86_64 \\
    -name "${SERVER_NAME}" \\
    -port ${SERVER_PORT} \\
    -world "${WORLD_NAME}" \\
    -password "${SERVER_PASSWORD}" \\
    -savedir "${DATA_DIR}" \\
    -public 1 \\
    ${CROSSPLAY_FLAG}
STARTEOF
                ok "Script BepInEx généré"
            fi
        else
            cat > "$START_SCRIPT" << STARTEOF
#!/usr/bin/env bash
export SteamAppId=892970
export LD_LIBRARY_PATH="${SERVER_DIR}/linux64:\$LD_LIBRARY_PATH"
cd "${SERVER_DIR}"
exec ./valheim_server.x86_64 \\
    -name "${SERVER_NAME}" \\
    -port ${SERVER_PORT} \\
    -world "${WORLD_NAME}" \\
    -password "${SERVER_PASSWORD}" \\
    -savedir "${DATA_DIR}" \\
    -public 1 \\
    ${CROSSPLAY_FLAG}
STARTEOF
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
        cat > "$START_SCRIPT" << STARTEOF
#!/usr/bin/env bash
export WINEDEBUG=-all
export WINEPREFIX="${HOME_DIR}/.wine"
cd "${SERVER_DIR}"
exec xvfb-run --auto-servernum wine64 ./enshrouded_server.exe
STARTEOF
    fi

    chmod +x "$START_SCRIPT"
    chown "$SYS_USER:$SYS_USER" "$START_SCRIPT"
    ok "Script de démarrage : $START_SCRIPT"

    cat > "/etc/systemd/system/${GAME_SERVICE}.service" << SVCEOF
[Unit]
Description=${GAME_LABEL} Dedicated Server
After=network.target

[Service]
Type=simple
User=${SYS_USER}
WorkingDirectory=${SERVER_DIR}
ExecStart=${START_SCRIPT}
Restart=on-failure
RestartSec=10
SuccessExitStatus=0 130 143
StandardOutput=journal
StandardError=journal
SyslogIdentifier=${GAME_SERVICE}
KillSignal=SIGINT
KillMode=mixed
TimeoutStopSec=60

[Install]
WantedBy=multi-user.target
SVCEOF

    systemctl daemon-reload
    systemctl enable "$GAME_SERVICE"
    info "Démarrage de $GAME_SERVICE..."
    systemctl start "$GAME_SERVICE"
    sleep 5
    service_active "$GAME_SERVICE" \
        && ok "Service $GAME_SERVICE actif" \
        || warn "$GAME_SERVICE pas encore actif — journalctl -u $GAME_SERVICE -f"
}

deploy_step_backups() {
    hdr "ÉTAPE 6 : Sauvegardes automatiques"

    mkdir -p "$APP_DIR"
    chown "$SYS_USER:$SYS_USER" "$APP_DIR"

    mkdir -p "$BACKUP_DIR"
    chown "$SYS_USER:$SYS_USER" "$BACKUP_DIR"

    case "$GAME_ID" in
        valheim)
            WORLD_DIR="$DATA_DIR/worlds_local"
            [[ ! -d "$WORLD_DIR" ]] && WORLD_DIR="$DATA_DIR/worlds"
            ;;
        enshrouded) WORLD_DIR="$SERVER_DIR/savegame" ;;
        minecraft|minecraft-fabric) WORLD_DIR="$SERVER_DIR/world" ;;
        terraria) WORLD_DIR="$DATA_DIR" ;;
        soulmask) WORLD_DIR="$SERVER_DIR/WS/Saved" ;;
    esac

    BACKUP_SCRIPT="$APP_DIR/backup_${GAME_ID}.sh"
    if [[ "$GAME_ID" == "valheim" ]]; then
        cat > "$BACKUP_SCRIPT" << 'BKPEOF'
#!/usr/bin/env bash
BACKUP_DIR="__BACKUP_DIR__"
WORLD_DIR="__WORLD_DIR__"
WORLD_NAME="__WORLD_NAME__"
RETENTION=7
TS=$(date +%Y%m%d_%H%M%S)
ARC="${BACKUP_DIR}/${WORLD_NAME}_${TS}.zip"
FILES=()
for f in "${WORLD_DIR}/${WORLD_NAME}.db" "${WORLD_DIR}/${WORLD_NAME}.fwl" \
          "${WORLD_DIR}/${WORLD_NAME}.db.old" "${WORLD_DIR}/${WORLD_NAME}.fwl.old"; do
    [[ -f "$f" ]] && FILES+=("$f")
done
[[ ${#FILES[@]} -eq 0 ]] && { echo "[$(date)] WARN: aucun fichier monde" >&2; exit 1; }
mkdir -p "$BACKUP_DIR"
zip -j "$ARC" "${FILES[@]}" -q \
    && echo "[$(date)] OK: $(basename "$ARC") ($(du -sh "$ARC"|cut -f1))" \
    || { echo "[$(date)] ERROR: zip échoué" >&2; exit 1; }
find "$BACKUP_DIR" -name "${WORLD_NAME}_*.zip" -mtime +${RETENTION} -delete
BKPEOF
        sed -i "s|__BACKUP_DIR__|${BACKUP_DIR}|g; s|__WORLD_DIR__|${WORLD_DIR}|g; s|__WORLD_NAME__|${WORLD_NAME}|g" "$BACKUP_SCRIPT"
    elif [[ "$GAME_ID" == "minecraft" || "$GAME_ID" == "minecraft-fabric" ]]; then
        cat > "$BACKUP_SCRIPT" << 'BKPEOF'
#!/usr/bin/env bash
BACKUP_DIR="__BACKUP_DIR__"
SERVER_DIR="__SERVER_DIR__"
WORLD_DIR="__WORLD_DIR__"
PREFIX="__GAME_ID__"
RETENTION=7
TS=$(date +%Y%m%d_%H%M%S)
ARC="${BACKUP_DIR}/${PREFIX}_save_${TS}.zip"
[[ ! -d "$WORLD_DIR" ]] && { echo "[$(date)] WARN: $WORLD_DIR introuvable" >&2; exit 1; }
mkdir -p "$BACKUP_DIR"
FILES=("$(basename "$WORLD_DIR")")
for f in server.properties ops.json whitelist.json banned-players.json banned-ips.json usercache.json; do
    [[ -f "$SERVER_DIR/$f" ]] && FILES+=("$f")
done
(
    cd "$SERVER_DIR"
    zip -r "$ARC" "${FILES[@]}" -q
) && echo "[$(date)] OK: $(basename "$ARC") ($(du -sh "$ARC"|cut -f1))" \
  || { echo "[$(date)] ERROR" >&2; exit 1; }
find "$BACKUP_DIR" -name "${PREFIX}_save_*.zip" -mtime +${RETENTION} -delete
BKPEOF
        sed -i "s|__BACKUP_DIR__|${BACKUP_DIR}|g; s|__SERVER_DIR__|${SERVER_DIR}|g; s|__WORLD_DIR__|${WORLD_DIR}|g; s|__GAME_ID__|${GAME_ID}|g" "$BACKUP_SCRIPT"
    else
        cat > "$BACKUP_SCRIPT" << 'BKPEOF'
#!/usr/bin/env bash
BACKUP_DIR="__BACKUP_DIR__"
WORLD_DIR="__WORLD_DIR__"
PREFIX="__GAME_ID__"
RETENTION=7
TS=$(date +%Y%m%d_%H%M%S)
ARC="${BACKUP_DIR}/${PREFIX}_save_${TS}.zip"
[[ ! -d "$WORLD_DIR" ]] && { echo "[$(date)] WARN: $WORLD_DIR introuvable" >&2; exit 1; }
mkdir -p "$BACKUP_DIR"
ROOT_PARENT="$(dirname "$WORLD_DIR")"
ROOT_NAME="$(basename "$WORLD_DIR")"
(
    cd "$ROOT_PARENT"
    zip -r "$ARC" "$ROOT_NAME" -q
) \
    && echo "[$(date)] OK: $(basename "$ARC") ($(du -sh "$ARC"|cut -f1))" \
    || { echo "[$(date)] ERROR" >&2; exit 1; }
find "$BACKUP_DIR" -name "${PREFIX}_save_*.zip" -mtime +${RETENTION} -delete
BKPEOF
        sed -i "s|__BACKUP_DIR__|${BACKUP_DIR}|g; s|__WORLD_DIR__|${WORLD_DIR}|g; s|__GAME_ID__|${GAME_ID}|g" "$BACKUP_SCRIPT"
    fi

    chmod +x "$BACKUP_SCRIPT"
    chown "$SYS_USER:$SYS_USER" "$BACKUP_SCRIPT"
    ok "Script de sauvegarde : $BACKUP_SCRIPT"

    if [[ "${SKIP_BACKUP_TEST:-false}" == "true" ]]; then
        info "Test sauvegarde ignoré pour cette mise à jour"
    else
        sudo -u "$SYS_USER" bash "$BACKUP_SCRIPT" 2>/dev/null \
            && ok "Test sauvegarde réussi" \
            || warn "Test sauvegarde : aucun fichier trouvé (normal avant le premier lancement)"
    fi

    CRON_LINE="0 3 * * * $BACKUP_SCRIPT >> $APP_DIR/backup_${GAME_ID}.log 2>&1"
    EXISTING=$(crontab -u "$SYS_USER" -l 2>/dev/null || echo "")
    echo "$EXISTING" | grep -qF "$BACKUP_SCRIPT" \
        && ok "Cron déjà configuré" \
        || { (echo "$EXISTING"; echo "$CRON_LINE") | crontab -u "$SYS_USER" -; ok "Cron : 3h00 quotidien"; }
}

deploy_step_app_files() {
    hdr "ÉTAPE 7 : Game Commander"
    local runtime_src=""

    if ! $DEPLOY_APP; then
        warn "Sources introuvables — Game Commander ignoré"
    else
        runtime_src=$(deploy_runtime_src_dir "$SRC_DIR") || die "Sources runtime introuvables dans $SRC_DIR"
        mkdir -p "$APP_DIR"
        rsync -a --exclude='__pycache__' --exclude='*.pyc' --exclude='metrics.log' \
                  --exclude='users.json' --exclude='game.json' --exclude='deploy_config.env' \
                  "$runtime_src/" "$APP_DIR/"
        chown -R "$SYS_USER:$SYS_USER" "$APP_DIR"
        ok "Fichiers Game Commander copiés dans $APP_DIR"

        GC_BEPINEX_PATH=""
        [[ "$GAME_ID" == "valheim" ]] && $BEPINEX && GC_BEPINEX_PATH="${SERVER_DIR}/BepInEx"

        local -a game_json_extra_args=()
        [[ -n "${QUERY_PORT:-}" ]] && game_json_extra_args+=(--query-port "$QUERY_PORT")
        [[ -n "${ECHO_PORT:-}" ]] && game_json_extra_args+=(--echo-port "$ECHO_PORT")

        python3 "$SCRIPT_DIR/tools/config_gen.py" game-json \
            --out          "$APP_DIR/game.json" \
            --game-id      "$GAME_ID" \
            --game-label   "$GAME_LABEL" \
            --game-binary  "$GAME_BINARY" \
            --game-service "$GAME_SERVICE" \
            --server-dir   "$SERVER_DIR" \
            --data-dir     "${DATA_DIR:-$SERVER_DIR}" \
            --world-name   "${WORLD_NAME:-}" \
            --max-players  "$MAX_PLAYERS" \
            --port         "$SERVER_PORT" \
            "${game_json_extra_args[@]}" \
            --url-prefix   "$URL_PREFIX" \
            --flask-port   "$FLASK_PORT" \
            --admin-user   "$ADMIN_LOGIN" \
            --bepinex-path "${GC_BEPINEX_PATH:-}" \
            --steam-appid  "${STEAM_APPID:-}" \
            --steamcmd-path "${STEAMCMD_PATH:-}" \
        || die "Échec génération game.json"
        ok "game.json généré"

        USERS_FILE="$APP_DIR/users.json"
        if [[ -f "$USERS_FILE" ]]; then
            ok "users.json existant conservé"
        else
            ADMIN_HASH=$(python3 -c \
                "import bcrypt,sys; print(bcrypt.hashpw(sys.argv[1].encode(), bcrypt.gensalt()).decode())" \
                "$ADMIN_PASSWORD") || die "Échec hash bcrypt"
            python3 "$SCRIPT_DIR/tools/config_gen.py" users-json \
                --out     "$USERS_FILE" \
                --admin   "$ADMIN_LOGIN" \
                --hash    "$ADMIN_HASH" \
                --game-id "$GAME_ID" \
            || die "Échec génération users.json"
            chmod 600 "$USERS_FILE"
            chown "$SYS_USER:$SYS_USER" "$USERS_FILE"
            ok "users.json créé — admin : $ADMIN_LOGIN"
        fi
    fi

    METRICS_FILE="$APP_DIR/metrics.log"
    if [[ ! -f "$METRICS_FILE" ]]; then
        touch "$METRICS_FILE"
        chown "$SYS_USER:$SYS_USER" "$METRICS_FILE"
        chmod 640 "$METRICS_FILE"
        ok "metrics.log créé"
    fi
}

deploy_step_app_service() {
    hdr "ÉTAPE 8 : Service Game Commander"
    if $DEPLOY_APP; then
        GC_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
        cat > "/etc/systemd/system/${GC_SERVICE}.service" << SVCEOF
[Unit]
Description=Game Commander — ${GAME_LABEL}
After=network.target
Wants=${GAME_SERVICE}.service

[Service]
Type=simple
User=${SYS_USER}
WorkingDirectory=${APP_DIR}
Environment="GAME_COMMANDER_SECRET=${GC_SECRET}"
ExecStart=/usr/bin/python3 ${APP_DIR}/app.py
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
SVCEOF
        systemctl daemon-reload
        systemctl enable "$GC_SERVICE"
        systemctl restart "$GC_SERVICE"
        sleep 2
        service_active "$GC_SERVICE" \
            && ok "Service $GC_SERVICE actif" \
            || err "$GC_SERVICE inactif — journalctl -u $GC_SERVICE -n 30"
    fi
}

deploy_step_nginx() {
    hdr "ÉTAPE 9 : Nginx"
    nginx_ensure_init "$DOMAIN"
    nginx_manifest_add "$INSTANCE_ID" "$URL_PREFIX" "$FLASK_PORT" "$GAME_LABEL" || die "Échec enregistrement nginx manifest"
    nginx_regenerate_locations || die "Échec régénération nginx locations"
    nginx_apply || err "Vérifiez manuellement : nginx -t"
}

deploy_step_ssl() {
    hdr "ÉTAPE 10 : SSL"
    case "$SSL_MODE" in
        certbot)
            cmd_exists certbot \
                && { certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos \
                        --register-unsafely-without-email 2>/dev/null \
                     && ok "Certificat SSL obtenu" \
                     || warn "Certbot échoué — $DOMAIN doit pointer sur ce serveur"; } \
                || warn "Certbot non disponible"
            ;;
        existing) ok "SSL existant — non modifié" ;;
        none) warn "HTTP uniquement" ;;
    esac
}

deploy_step_sudoers() {
    hdr "ÉTAPE 11 : Permissions sudo"
    SUDOERS_FILE="/etc/sudoers.d/game-commander-${INSTANCE_ID}"
    {
        echo "# Game Commander — ${GAME_LABEL} (${INSTANCE_ID})"
        echo "${SYS_USER} ALL=(ALL) NOPASSWD: /usr/bin/systemctl start ${GAME_SERVICE}"
        echo "${SYS_USER} ALL=(ALL) NOPASSWD: /usr/bin/systemctl stop ${GAME_SERVICE}"
        echo "${SYS_USER} ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart ${GAME_SERVICE}"
        if [[ "$GAME_ID" == "valheim" ]] && [[ -n "${GC_BEPINEX_PATH:-}" ]]; then
            BP="$GC_BEPINEX_PATH"
            echo "${SYS_USER} ALL=(ALL) NOPASSWD: /usr/bin/chown -R ${SYS_USER} ${BP}"
            echo "${SYS_USER} ALL=(ALL) NOPASSWD: /usr/bin/chmod -R 755 ${BP}"
            echo "${SYS_USER} ALL=(ALL) NOPASSWD: /usr/bin/find ${BP} -type d"
            echo "${SYS_USER} ALL=(ALL) NOPASSWD: /bin/rm -rf ${BP}/plugins/*"
            echo "${SYS_USER} ALL=(ALL) NOPASSWD: /bin/rm -f ${BP}/plugins/*"
        fi
    } > "$SUDOERS_FILE"

    chmod 440 "$SUDOERS_FILE"
    VISUDO_ERR=$(visudo -cf "$SUDOERS_FILE" 2>&1)
    if [[ $? -eq 0 ]]; then
        ok "Sudoers : $SUDOERS_FILE"
    else
        err "Sudoers invalide — supprimé"
        warn "Erreur visudo : $VISUDO_ERR"
        rm -f "$SUDOERS_FILE"
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
    {
        echo "# Game Commander — Config sauvegardée le $(date '+%Y-%m-%d %H:%M:%S')"
        echo "# Redéploiement : sudo bash game_commander.sh deploy --config $CONFIG_SAVE"
        echo ""
        echo "GAME_ID=\"${GAME_ID}\""
        echo "DEPLOY_MODE=\"${DEPLOY_MODE}\""
        echo "INSTANCE_ID=\"${INSTANCE_ID}\""
        echo "SYS_USER=\"${SYS_USER}\""
        echo "SERVER_DIR=\"${SERVER_DIR}\""
        echo "DATA_DIR=\"${DATA_DIR}\""
        echo "BACKUP_DIR=\"${BACKUP_DIR}\""
        echo "APP_DIR=\"${APP_DIR}\""
        echo "SRC_DIR=\"${SRC_DIR}\""
        echo "GAME_SERVICE=\"${GAME_SERVICE}\""
        echo "SERVER_NAME=\"${SERVER_NAME}\""
        echo "SERVER_PORT=\"${SERVER_PORT}\""
        [[ -n "${QUERY_PORT:-}" ]] && echo "QUERY_PORT=\"${QUERY_PORT}\""
        [[ -n "${ECHO_PORT:-}" ]] && echo "ECHO_PORT=\"${ECHO_PORT}\""
        echo "MAX_PLAYERS=\"${MAX_PLAYERS}\""
        [[ "$GAME_ID" == "valheim" ]] && {
            echo "WORLD_NAME=\"${WORLD_NAME}\""
            echo "CROSSPLAY=${CROSSPLAY}"
            echo "BEPINEX=${BEPINEX}"
        }
        [[ "$GAME_ID" == "soulmask" ]] && {
            echo "SERVER_ADMIN_PASSWORD=\"\""
            echo "SERVER_MODE=\"${SERVER_MODE}\""
            echo "BACKUP_ENABLED=${BACKUP_ENABLED}"
            echo "SAVING_ENABLED=${SAVING_ENABLED}"
            echo "BACKUP_INTERVAL=\"${BACKUP_INTERVAL}\""
        }
        echo "DOMAIN=\"${DOMAIN}\""
        echo "URL_PREFIX=\"${URL_PREFIX}\""
        echo "FLASK_PORT=\"${FLASK_PORT}\""
        echo "SSL_MODE=\"${SSL_MODE}\""
        echo "ADMIN_LOGIN=\"${ADMIN_LOGIN}\""
        echo "# ADMIN_PASSWORD=  <-- ne pas sauvegarder en clair"
        echo "AUTO_INSTALL_DEPS=true"
        echo "AUTO_UPDATE_SERVER=false"
        echo "AUTO_CONFIRM=true"
    } > "$CONFIG_SAVE"
    chmod 600 "$CONFIG_SAVE"
    chown "$SYS_USER:$SYS_USER" "$CONFIG_SAVE"
    ok "Config sauvegardée : $CONFIG_SAVE"
}

deploy_step_validation() {
    hdr "VALIDATION FINALE"
    echo ""
    ERRORS=0

    service_active "$GAME_SERVICE" \
        && ok "Service $GAME_SERVICE : actif" \
        || { warn "Service $GAME_SERVICE : inactif"; ERRORS=$((ERRORS+1)); }

    if $DEPLOY_APP; then
        sleep 1
        curl -sf "http://127.0.0.1:${FLASK_PORT}${URL_PREFIX}" -o /dev/null 2>/dev/null \
            && ok "Game Commander répond sur :${FLASK_PORT}${URL_PREFIX}" \
            || { warn "Game Commander ne répond pas encore"; ERRORS=$((ERRORS+1)); }
    fi

    service_active nginx && ok "Nginx : actif" || { warn "Nginx : inactif"; ERRORS=$((ERRORS+1)); }

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

    if [[ "$GAME_ID" == "minecraft" || "$GAME_ID" == "minecraft-fabric" ]]; then
        _GAME_PORTS=("${SERVER_PORT}/tcp")
    elif [[ "$GAME_ID" == "soulmask" ]]; then
        _GAME_PORTS=("${SERVER_PORT}/udp" "${QUERY_PORT}/udp" "${ECHO_PORT}/tcp")
    elif [[ "$GAME_ID" == "terraria" ]]; then
        _GAME_PORTS=("${SERVER_PORT}/tcp")
    else
        _GAME_PORTS=("${SERVER_PORT}/udp" "$((SERVER_PORT+1))/udp")
    fi
    echo -e "  ${BOLD}Ports à ouvrir (firewall) :${RESET}"
    if [[ "$GAME_ID" == "minecraft" || "$GAME_ID" == "minecraft-fabric" ]]; then
        echo -e "    Jeu  : ${SERVER_PORT}/TCP"
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
