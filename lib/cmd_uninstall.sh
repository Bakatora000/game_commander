# ── lib/cmd_uninstall.sh ────────────────────────────────────────────────────
# Commande : sudo bash game_commander.sh uninstall [--dry-run]

# ═══════════════════════════════════════════════════════════════════════════════
# UNINSTALL
# ═══════════════════════════════════════════════════════════════════════════════
cmd_uninstall() {

[[ $EUID -ne 0 ]] && { err "Ce script doit être exécuté en root (sudo)"; exit 1; }
$DRY_RUN && warn "MODE DRY-RUN — aucune modification ne sera effectuée"

# ═══════════════════════════════════════════════════════════════════════════════
#  PARTIE A — Installations Game Commander (deploy_config.env)
# ═══════════════════════════════════════════════════════════════════════════════
hdr "A — Recherche installations Game Commander"

mapfile -t DEPLOY_CONFIGS < <(
    find /home /opt /root -maxdepth 5 -name "deploy_config.env" 2>/dev/null \
    | xargs -I{} grep -l "GAME_ID=" {} 2>/dev/null \
    | sort -u
)

declare -a GC_ENTRIES=()

if [[ ${#DEPLOY_CONFIGS[@]} -eq 0 ]]; then
    info "Aucune installation Game Commander trouvée."
else
    echo ""
    for cfg in "${DEPLOY_CONFIGS[@]}"; do
        unset GAME_ID INSTANCE_ID SYS_USER SERVER_DIR DATA_DIR BACKUP_DIR \
              APP_DIR DOMAIN FLASK_PORT SERVER_NAME GC_SERVICE GAME_SERVICE
        source <(grep -E '^[A-Z_]+=' "$cfg" 2>/dev/null)

        GAME_ID="${GAME_ID:-?}"
        INSTANCE_ID="${INSTANCE_ID:-$GAME_ID}"
        SYS_USER="${SYS_USER:-?}"
        SERVER_DIR="${SERVER_DIR:-}"
        DATA_DIR="${DATA_DIR:-}"
        APP_DIR="${APP_DIR:-}"
        DOMAIN="${DOMAIN:-}"
        FLASK_PORT="${FLASK_PORT:-?}"
        SERVER_NAME="${SERVER_NAME:-}"
        GC_SERVICE="game-commander-${INSTANCE_ID}"
        GAME_SERVICE="${GAME_ID}-server-${INSTANCE_ID}"
        GC_STATE=$(service_state "$GC_SERVICE")
        GAME_STATE=$(service_state "$GAME_SERVICE")

        idx=${#GC_ENTRIES[@]}
        GC_ENTRIES+=("$cfg")

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

        echo -e "  ${BOLD}[A$((idx+1))]${RESET}  ${BOLD}${INSTANCE_ID}${RESET}  (${GAME_ID^^})"
        echo -e "         Config       : $cfg"
        echo -e "         Serveur jeu  : ${GAME_SERVICE}  →  $ss"
        echo -e "         Game Cmd web : ${GC_SERVICE}    →  $gs"
        [[ -n "$SERVER_NAME"  ]] && echo -e "         Nom          : $SERVER_NAME"
        [[ -n "$DOMAIN"       ]] && echo -e "         Domaine      : $DOMAIN  (port $FLASK_PORT)"
        [[ -n "$SYS_USER"     ]] && echo -e "         Utilisateur  : $SYS_USER"
        [[ -n "$SERVER_DIR" && -d "$SERVER_DIR" ]] && \
            echo -e "         Dossier jeu  : $SERVER_DIR  $(du -sh "$SERVER_DIR" 2>/dev/null | cut -f1)"
        [[ -n "$DATA_DIR"   && -d "$DATA_DIR"   && "$DATA_DIR" != "$SERVER_DIR" ]] && \
            echo -e "         Dossier data : $DATA_DIR  $(du -sh "$DATA_DIR" 2>/dev/null | cut -f1)"
        [[ -n "$APP_DIR"    && -d "$APP_DIR"    ]] && \
            echo -e "         Dossier app  : $APP_DIR  $(du -sh "$APP_DIR" 2>/dev/null | cut -f1)"
        sep
    done

    echo -e "  Entrez les numéros à traiter (ex: ${BOLD}A1 A2${RESET}), ${BOLD}all${RESET} pour tout, ${BOLD}skip${RESET} pour passer :"
    echo -en "  ${YELLOW}?  Sélection : ${RESET}"
    read -r gc_sel

    if [[ "$gc_sel" != "skip" && -n "$gc_sel" ]]; then
        declare -a GC_SELECTED=()
        if [[ "$gc_sel" == "all" ]]; then
            for i in "${!GC_ENTRIES[@]}"; do GC_SELECTED+=($i); done
        else
            for tok in $gc_sel; do
                tok="${tok^^}"; tok="${tok#A}"
                if [[ "$tok" =~ ^[0-9]+$ ]] && (( tok >= 1 && tok <= ${#GC_ENTRIES[@]} )); then
                    GC_SELECTED+=($((tok-1)))
                else
                    warn "Numéro invalide : $tok — ignoré"
                fi
            done
        fi

        if [[ ${#GC_SELECTED[@]} -gt 0 ]]; then
            echo ""
            echo -e "  Que souhaitez-vous faire ?"
            echo -e "    ${BOLD}1${RESET}) Stopper les services (fichiers conservés)"
            echo -e "    ${BOLD}2${RESET}) Désinstaller complètement (services + fichiers)"
            echo -en "  ${YELLOW}?  Choix : ${RESET}"
            read -r gc_action

            for idx in "${GC_SELECTED[@]}"; do
                cfg="${GC_ENTRIES[$idx]}"
                unset GAME_ID INSTANCE_ID SYS_USER SERVER_DIR DATA_DIR BACKUP_DIR \
                      APP_DIR DOMAIN FLASK_PORT SERVER_NAME
                source <(grep -E '^[A-Z_]+=' "$cfg" 2>/dev/null)

                GAME_ID="${GAME_ID:-?}"
                INSTANCE_ID="${INSTANCE_ID:-$GAME_ID}"
                SYS_USER="${SYS_USER:-}"
                GC_SERVICE="game-commander-${INSTANCE_ID}"
                GAME_SERVICE="${GAME_ID}-server-${INSTANCE_ID}"

                echo ""
                hdr "Traitement : $INSTANCE_ID"

                stop_and_disable "$GAME_SERVICE"
                stop_and_disable "$GC_SERVICE"

                if [[ "$gc_action" == "2" ]]; then
                    # Nginx — système manifest (prioritaire) ou fallback inline
                    if [[ -f "$GC_NGINX_MANIFEST" ]] && nginx_manifest_check "$INSTANCE_ID"; then
                        if ask_yn "Retirer ${BOLD}${URL_PREFIX:-$INSTANCE_ID}${RESET} du vhost Nginx (manifest) ?"; then
                            nginx_manifest_remove "$INSTANCE_ID" \
                            && nginx_regenerate_locations \
                            && nginx_apply \
                            || warn "Vérifiez nginx manuellement : nginx -t"
                        fi
                    else
                        # Fallback : ancienne approche inline
                        NGINX_CONF=""
                        for nf in "/etc/nginx/conf.d/${DOMAIN:-___}.conf" \
                                  "/etc/nginx/sites-enabled/${DOMAIN:-___}.conf" \
                                  "/etc/nginx/sites-available/${DOMAIN:-___}.conf"; do
                            [[ -f "$nf" ]] && { NGINX_CONF="$nf"; break; }
                        done
                        [[ -z "$NGINX_CONF" && -n "${FLASK_PORT:-}" ]] && \
                            NGINX_CONF=$(grep -rl "127.0.0.1:${FLASK_PORT}" \
                                /etc/nginx/conf.d/ /etc/nginx/sites-enabled/ 2>/dev/null | head -1 || true)

                        if [[ -n "$NGINX_CONF" && -f "$NGINX_CONF" ]]; then
                            _loc_count=$(grep -c '^\s*location ' "$NGINX_CONF" 2>/dev/null || echo 0)
                            _has_our_block=$(grep -c "location ${URL_PREFIX:-___}" "$NGINX_CONF" 2>/dev/null || echo 0)

                            if (( _loc_count <= 2 && _has_our_block > 0 )); then
                                if ask_yn "Supprimer vhost Nginx : ${BOLD}$NGINX_CONF${RESET} (seule instance) ?"; then
                                    run rm -f "$NGINX_CONF"
                                    ok "Vhost Nginx supprimé"
                                    run nginx -t 2>/dev/null && run systemctl reload nginx || true
                                fi
                            elif (( _has_our_block > 0 )); then
                                if ask_yn "Retirer le bloc ${BOLD}${URL_PREFIX}${RESET} du vhost ${BOLD}$NGINX_CONF${RESET} (partagé) ?"; then
                                    python3 "$SCRIPT_DIR/tools/nginx_manager.py" remove \
                                        --conf        "$NGINX_CONF" \
                                        --instance-id "$INSTANCE_ID" \
                                        --prefix      "$URL_PREFIX" \
                                    && ok "Bloc ${URL_PREFIX} retiré du vhost" \
                                    || warn "Échec suppression bloc nginx — vérifiez manuellement"
                                    run nginx -t 2>/dev/null && run systemctl reload nginx || true
                                fi
                            else
                                warn "Bloc ${URL_PREFIX:-$INSTANCE_ID} non trouvé dans $NGINX_CONF — vérifiez manuellement"
                            fi
                        fi
                    fi

                    # Sudoers
                    for sf in "/etc/sudoers.d/game-commander-${GAME_ID}" \
                              "/etc/sudoers.d/game-commander-${INSTANCE_ID}" \
                              "/etc/sudoers.d/${GC_SERVICE}"; do
                        if [[ -f "$sf" ]]; then
                            if ask_yn "Supprimer sudoers : ${BOLD}$sf${RESET} ?"; then
                                run rm -f "$sf"
                                ok "Sudoers supprimé"
                            fi
                        fi
                    done

                    # Cron backup
                    if [[ -n "$SYS_USER" && -n "${APP_DIR:-}" ]]; then
                        cron_count=$(crontab -u "$SYS_USER" -l 2>/dev/null \
                            | grep -c "$APP_DIR" || true)
                        if (( cron_count > 0 )); then
                            if ask_yn "Supprimer entrée cron backup de $SYS_USER ?"; then
                                run bash -c \
                                    "crontab -u '$SYS_USER' -l 2>/dev/null \
                                     | grep -v '$APP_DIR' \
                                     | crontab -u '$SYS_USER' -"
                                ok "Entrée cron supprimée"
                            fi
                        fi
                    fi

                    # Dossiers
                    HOME_DIR=$(eval echo "~${SYS_USER:-root}")
                    remove_dir_safe "${APP_DIR:-}"    "répertoire Game Commander" "$cfg"
                    remove_dir_safe "${SERVER_DIR:-}" "répertoire serveur jeu"    "$cfg"
                    if [[ -n "${DATA_DIR:-}" && "${DATA_DIR:-}" != "${SERVER_DIR:-}" ]]; then
                        remove_dir_safe "${DATA_DIR:-}" "répertoire données jeu"  "$cfg"
                    fi

                    STEAMCMD_DIR="$HOME_DIR/steamcmd"
                    if [[ -d "$STEAMCMD_DIR" ]]; then
                        others=$(shared_by_others "$STEAMCMD_DIR" "$cfg")
                        if [[ -n "$others" ]]; then
                            info "SteamCMD conservé — utilisé aussi par : $others"
                        else
                            remove_dir "$STEAMCMD_DIR" "SteamCMD"
                        fi
                    fi

                    if [[ -n "${BACKUP_DIR:-}" && -d "${BACKUP_DIR:-}" ]]; then
                        others=$(shared_by_others "${BACKUP_DIR:-}" "$cfg")
                        if [[ -n "$others" ]]; then
                            info "Sauvegardes conservées — utilisées aussi par : $others"
                        else
                            remove_dir "$BACKUP_DIR" "répertoire sauvegardes"
                        fi
                    fi
                fi
                ok "Terminé : $INSTANCE_ID"

                    # ── Désinstallation Wine si plus aucune instance Enshrouded ──
                    if [[ "${GAME_ID:-}" == "enshrouded" && "$gc_action" == "2" ]]; then
                        _remaining=$(find /home /opt /root -maxdepth 5 -name "deploy_config.env" 2>/dev/null \
                            | xargs grep -l 'GAME_ID="enshrouded"' 2>/dev/null | wc -l)
                        _amp_enshrouded=$(find /home /root /opt -maxdepth 6 \
                            -name "instances.json" -path "*/.ampdata/*" 2>/dev/null \
                            | xargs grep -l '"Enshrouded"' 2>/dev/null | wc -l)
                        if (( _remaining == 0 && _amp_enshrouded == 0 )); then
                            if ask_yn "Plus aucune instance Enshrouded — désinstaller Wine64/Xvfb ?"; then
                                run apt-get remove -y wine64 xvfb 2>/dev/null \
                                    && ok "Wine64/Xvfb désinstallés" \
                                    || warn "Désinstallation Wine incomplète"
                                run apt-get autoremove -y 2>/dev/null || true
                            fi
                        else
                            (( _remaining > 0 )) && \
                                info "Wine conservé — $_remaining autre(s) instance(s) Enshrouded (Game Commander)"
                            (( _amp_enshrouded > 0 )) && \
                                info "Wine conservé — $_amp_enshrouded instance(s) Enshrouded détectée(s) dans AMP"
                        fi
                    fi
            done
        fi
    fi
fi

# ═══════════════════════════════════════════════════════════════════════════════
#  PARTIE B — Applications Flask génériques (systemd)
# ═══════════════════════════════════════════════════════════════════════════════
hdr "B — Recherche applications Flask génériques (systemd)"

declare -a ALREADY_HANDLED=()
for cfg in "${DEPLOY_CONFIGS[@]:-}"; do
    [[ -z "$cfg" ]] && continue
    _dir=$(grep '^APP_DIR=' "$cfg" 2>/dev/null | cut -d= -f2- | tr -d '"')
    [[ -n "$_dir" ]] && ALREADY_HANDLED+=("$_dir")
done

declare -a FL_NAMES=() FL_STATES=() FL_WORK_DIRS=() FL_USERS=() FL_PORTS=() FL_NGINX=()

while IFS= read -r svc; do
    unit_file="/etc/systemd/system/${svc}"
    [[ ! -f "$unit_file" ]] && unit_file="/lib/systemd/system/${svc}"
    [[ ! -f "$unit_file" ]] && continue
    exec_line=$(grep -i '^ExecStart=' "$unit_file" 2>/dev/null | head -1)
    echo "$exec_line" | grep -qiE 'python|gunicorn|uvicorn|flask' || continue
    work_dir=$(grep '^WorkingDirectory=' "$unit_file" 2>/dev/null | head -1 | cut -d= -f2-)
    [[ -z "$work_dir" ]] && continue
    already=false
    for handled in "${ALREADY_HANDLED[@]:-}"; do
        [[ "$handled" == "$work_dir" ]] && already=true && break
    done
    $already && continue
    is_flask=false
    [[ -f "$work_dir/app.py"  ]] && is_flask=true
    [[ -f "$work_dir/wsgi.py" ]] && is_flask=true
    grep -qiE 'flask|gunicorn' "$work_dir/requirements.txt" 2>/dev/null && is_flask=true
    $is_flask || continue
    state=$(systemctl is-active "${svc%.service}" 2>/dev/null || echo "inactive")
    svc_user=$(grep '^User=' "$unit_file" 2>/dev/null | head -1 | cut -d= -f2-)
    [[ -z "$svc_user" ]] && svc_user="root"
    port=""
    [[ -f "$work_dir/game.json" ]] && \
        port=$(python3 -c \
            "import json,sys; d=json.load(open('$work_dir/game.json')); \
             print(d.get('web',{}).get('flask_port',''))" 2>/dev/null || true)
    [[ -z "$port" ]] && port=$(grep -oP '(?<=port=)\d+' "$work_dir/app.py" 2>/dev/null | tail -1 || true)
    [[ -z "$port" ]] && port="?"
    nginx_file=""
    [[ "$port" != "?" ]] && \
        nginx_file=$(grep -rl "127.0.0.1:${port}" \
            /etc/nginx/conf.d/ /etc/nginx/sites-enabled/ 2>/dev/null | head -1 || true)
    FL_NAMES+=("${svc%.service}")
    FL_STATES+=("$state")
    FL_WORK_DIRS+=("$work_dir")
    FL_USERS+=("$svc_user")
    FL_PORTS+=("$port")
    FL_NGINX+=("$nginx_file")
done < <(systemctl list-unit-files --type=service --no-legend 2>/dev/null \
         | awk '{print $1}' | grep -v '@')

if [[ ${#FL_NAMES[@]} -eq 0 ]]; then
    info "Aucune application Flask générique trouvée."
else
    echo ""
    for i in "${!FL_NAMES[@]}"; do
        case "${FL_STATES[$i]}" in
            active) st="${GREEN}● actif${RESET}"   ;;
            failed) st="${RED}✗ échoué${RESET}"    ;;
            *)      st="${DIM}○ inactif${RESET}"   ;;
        esac
        echo -e "  ${BOLD}[B$((i+1))]${RESET}  ${FL_NAMES[$i]}"
        echo -e "         État       : $st"
        echo -e "         Répertoire : ${FL_WORK_DIRS[$i]}  $(du -sh "${FL_WORK_DIRS[$i]}" 2>/dev/null | cut -f1)"
        echo -e "         Utilisateur: ${FL_USERS[$i]}"
        echo -e "         Port       : ${FL_PORTS[$i]}"
        [[ -n "${FL_NGINX[$i]}" ]] && echo -e "         Nginx      : ${FL_NGINX[$i]}"
        sep
    done

    echo -e "  Entrez les numéros à traiter (ex: ${BOLD}B1 B2${RESET}), ${BOLD}all${RESET} pour tout, ${BOLD}skip${RESET} pour passer :"
    echo -en "  ${YELLOW}?  Sélection : ${RESET}"
    read -r fl_sel

    if [[ "$fl_sel" != "skip" && -n "$fl_sel" ]]; then
        declare -a FL_SELECTED=()
        if [[ "$fl_sel" == "all" ]]; then
            for i in "${!FL_NAMES[@]}"; do FL_SELECTED+=($i); done
        else
            for tok in $fl_sel; do
                tok="${tok^^}"; tok="${tok#B}"
                if [[ "$tok" =~ ^[0-9]+$ ]] && (( tok >= 1 && tok <= ${#FL_NAMES[@]} )); then
                    FL_SELECTED+=($((tok-1)))
                else
                    warn "Numéro invalide : $tok — ignoré"
                fi
            done
        fi

        if [[ ${#FL_SELECTED[@]} -gt 0 ]]; then
            echo ""
            echo -e "  Que souhaitez-vous faire ?"
            echo -e "    ${BOLD}1${RESET}) Stopper uniquement"
            echo -e "    ${BOLD}2${RESET}) Désinstaller complètement"
            echo -en "  ${YELLOW}?  Choix : ${RESET}"
            read -r fl_action

            for idx in "${FL_SELECTED[@]}"; do
                svc="${FL_NAMES[$idx]}"
                work="${FL_WORK_DIRS[$idx]}"
                nginx="${FL_NGINX[$idx]}"
                echo ""
                hdr "Traitement : $svc"
                stop_and_disable "$svc"
                if [[ "$fl_action" == "2" ]]; then
                    if [[ -n "$nginx" && -f "$nginx" ]]; then
                        _port="${FL_PORTS[$idx]}"
                        _loc_count=$(grep -c '^\s*location ' "$nginx" 2>/dev/null || echo 0)
                        _has_port=$(grep -c "127.0.0.1:${_port}" "$nginx" 2>/dev/null || echo 0)
                        if (( _loc_count <= 2 && _has_port > 0 )); then
                            ask_yn "Supprimer vhost Nginx : ${BOLD}$nginx${RESET} (seule instance) ?" && \
                                { run rm -f "$nginx"; ok "Vhost supprimé"
                                  run nginx -t 2>/dev/null && run systemctl reload nginx || true; }
                        elif (( _has_port > 0 )); then
                            ask_yn "Retirer le bloc port ${_port} du vhost ${BOLD}$nginx${RESET} (partagé) ?" && \
                                { cp "$nginx" "${nginx}.bak.$(date +%Y%m%d%H%M%S)"
                                  python3 -c "
import re
with open('$nginx') as f: c = f.read()
c = re.sub(r'\n?[ \t]*# ── Game Commander[^\n]*\n.*?location [^\{]+\{[^}]*proxy_pass[^}]*${_port}[^}]*\}[^\n]*\n?[ \t]*location [^\{]+/static[^}]*\}[ \t]*\n?[ \t]*# ─+\n?', '\n', c, flags=re.DOTALL)
with open('$nginx','w') as f: f.write(c)
"
                                  ok "Bloc port ${_port} retiré"
                                  run nginx -t 2>/dev/null && run systemctl reload nginx || true; }
                        fi
                    fi
                    for sf in /etc/sudoers.d/*; do
                        [[ -f "$sf" ]] || continue
                        grep -q "$work\|$svc" "$sf" 2>/dev/null || continue
                        ask_yn "Supprimer sudoers : ${BOLD}$sf${RESET} ?" && \
                            { run rm -f "$sf"; ok "Sudoers supprimé"; }
                    done
                    remove_dir "$work" "répertoire application"
                fi
                ok "Terminé : $svc"
            done
        fi
    fi
fi

# ═══════════════════════════════════════════════════════════════════════════════
#  PARTIE C — Processus orphelins
# ═══════════════════════════════════════════════════════════════════════════════
hdr "C — Processus orphelins en mémoire"

SAFE_PIDS_FILE=$(mktemp)
systemctl show $(systemctl list-units --type=service --no-legend 2>/dev/null \
    | awk '{print $1}') -p MainPID 2>/dev/null \
    | grep -v '=0$' | grep -oP '(?<=)\d+' > "$SAFE_PIDS_FILE" || true

is_safe_pid() { grep -qxF "$1" "$SAFE_PIDS_FILE" 2>/dev/null; }

is_amp_process() {
    local pid="$1" cur="$1" depth=0
    while [[ "$cur" =~ ^[0-9]+$ ]] && (( cur > 1 && depth < 8 )); do
        [[ ! -r "/proc/${cur}/cmdline" ]] && return 1
        local cmdline
        cmdline=$(tr '\0' ' ' < "/proc/${cur}/cmdline" 2>/dev/null) || true
        echo "$cmdline" | grep -qiE 'ampdata|cubecoders|ampinstmgr' && return 0
        [[ ! -r "/proc/${cur}/stat" ]] && return 1
        cur=$(awk '{print $4}' "/proc/${cur}/stat" 2>/dev/null) || cur=1
        (( depth++ ))
    done
    return 1
}

ORPHAN_FILE=$(mktemp)

while IFS= read -r psline; do
    pid=$(echo  "$psline" | awk '{print $1}')
    user=$(echo "$psline" | awk '{print $2}')
    cmd=$(echo  "$psline" | awk '{for(i=3;i<=NF;i++) printf $i" "; print ""}' | xargs)
    [[ ! "$pid" =~ ^[0-9]+$ ]] && continue
    (( pid <= 1 ))              && continue
    [[ "$pid" == "$$" ]]        && continue
    echo "$cmd" | grep -qE 'game_commander|uninstall_flask|grep' && continue
    is_safe_pid "$pid" && continue
    is_amp_process "$pid" && continue
    desc=""
    if echo "$cmd" | grep -qiE 'python[0-9.]*.*(app|wsgi|main)\.py|gunicorn|uvicorn'; then
        wdir=$(readlink -f "/proc/${pid}/cwd" 2>/dev/null || echo "")
        app_name=""
        if [[ -n "$wdir" && -f "$wdir/game.json" ]]; then
            app_name=$(python3 -c \
                "import json; d=json.load(open('$wdir/game.json')); \
                 print(d.get('name','?')+' — '+d.get('subtitle',''))" 2>/dev/null || true)
        fi
        desc="Flask/Python"
        [[ -n "$app_name" ]] && desc="$desc ($app_name)"
        [[ -n "$wdir"     ]] && desc="$desc  [${wdir}]"
    elif echo "$cmd" | grep -qiP \
        'valheim_server\.x86_64|enshrouded_server|bedrock_server|(?<!\w)java(?!\w).*nogui'; then
        binary=$(echo "$cmd" | grep -oP \
            'valheim_server\.x86_64|enshrouded_server|bedrock_server|java' | head -1)
        desc="Serveur de jeu ($binary)"
    else
        continue
    fi
    echo "${pid}|${user}|${desc}|$(echo "$cmd" | cut -c1-80)" >> "$ORPHAN_FILE"
done < <(ps -eo pid,user,cmd --no-headers 2>/dev/null | grep -v ' Z ')

rm -f "$SAFE_PIDS_FILE"

orphan_count=$(wc -l < "$ORPHAN_FILE" 2>/dev/null || echo 0)

if (( orphan_count == 0 )); then
    ok "Aucun processus orphelin détecté."
    rm -f "$ORPHAN_FILE"
else
    echo ""
    warn "${orphan_count} processus orphelin(s) trouvé(s) :"
    echo ""
    declare -a O_PIDS=() O_USERS=() O_DESCS=() O_CMDS=()
    while IFS='|' read -r o_pid o_user o_desc o_cmd; do
        O_PIDS+=("$o_pid"); O_USERS+=("$o_user")
        O_DESCS+=("$o_desc"); O_CMDS+=("$o_cmd")
    done < "$ORPHAN_FILE"
    rm -f "$ORPHAN_FILE"

    for i in "${!O_PIDS[@]}"; do
        echo -e "  ${BOLD}[C$((i+1))]${RESET}  PID ${BOLD}${O_PIDS[$i]}${RESET}  — ${O_DESCS[$i]}"
        echo -e "         Utilisateur : ${O_USERS[$i]}"
        echo -e "         Commande    : ${DIM}${O_CMDS[$i]}${RESET}"
        sep
    done

    echo -e "  Numéros à terminer (ex: ${BOLD}C1 C2${RESET}), ${BOLD}all${RESET} pour tout, ${BOLD}skip${RESET} pour passer :"
    echo -en "  ${YELLOW}?  Sélection : ${RESET}"
    read -r kill_sel

    if [[ "$kill_sel" != "skip" && -n "$kill_sel" ]]; then
        declare -a KILL_IDX=()
        if [[ "$kill_sel" == "all" ]]; then
            for i in "${!O_PIDS[@]}"; do KILL_IDX+=($i); done
        else
            for tok in $kill_sel; do
                tok="${tok^^}"; tok="${tok#C}"
                if [[ "$tok" =~ ^[0-9]+$ ]] && (( tok >= 1 && tok <= ${#O_PIDS[@]} )); then
                    KILL_IDX+=($((tok-1)))
                else
                    warn "Numéro invalide : $tok — ignoré"
                fi
            done
        fi

        if (( ${#KILL_IDX[@]} > 0 )); then
            echo ""
            echo -e "  Signal :"
            echo -e "    ${BOLD}1${RESET}) SIGTERM  — arrêt propre (recommandé)"
            echo -e "    ${BOLD}2${RESET}) SIGKILL  — arrêt forcé"
            echo -en "  ${YELLOW}?  Choix : ${RESET}"
            read -r sig_choice
            KILL_SIG="-15"
            [[ "${sig_choice:-1}" == "2" ]] && KILL_SIG="-9"

            for idx in "${KILL_IDX[@]}"; do
                pid="${O_PIDS[$idx]}"
                desc="${O_DESCS[$idx]}"
                if ! kill -0 "$pid" 2>/dev/null; then
                    warn "PID $pid déjà terminé"
                    continue
                fi
                info "Envoi signal $KILL_SIG → PID $pid ($desc)..."
                run kill "$KILL_SIG" "$pid" || true
                if ! $DRY_RUN; then
                    sleep 2
                    if kill -0 "$pid" 2>/dev/null; then
                        warn "PID $pid toujours actif — kill -9 $pid pour forcer"
                    else
                        ok "PID $pid terminé"
                    fi
                fi
            done
        fi
    fi
fi

echo ""
hdr "Terminé"
$DRY_RUN && warn "DRY-RUN — aucune modification n'a été effectuée"
echo ""

} # fin cmd_uninstall
