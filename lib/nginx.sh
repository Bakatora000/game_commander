# ── lib/nginx.sh ─────────────────────────────────────────────────────────────
# Fonctions de gestion Nginx via manifest pour Game Commander.
# Requiert : helpers.sh chargé, $SCRIPT_DIR défini.

GC_NGINX_MANIFEST="/etc/nginx/game-commander-manifest.json"
GC_NGINX_LOC_FILE="/etc/nginx/game-commander-locations.conf"
GC_NGINX_BACKUP_DIR="/etc/nginx/backups"

# ── nginx_ensure_init ─────────────────────────────────────────────────────────
# Migration one-shot idempotente : crée le manifest + le fichier locations,
# supprime les anciens blocs inline Game Commander, et ajoute l'include dans
# le bloc SSL du domaine.
# Usage : nginx_ensure_init DOMAIN
nginx_ensure_init() {
    local domain="$1"
    python3 "$SCRIPT_DIR/tools/nginx_manager.py" init \
        --domain     "$domain" \
        --manifest   "$GC_NGINX_MANIFEST" \
        --loc-file   "$GC_NGINX_LOC_FILE" \
        --backup-dir "$GC_NGINX_BACKUP_DIR" \
    || { err "nginx_ensure_init échoué pour $domain"; return 1; }
}

# ── nginx_manifest_add ────────────────────────────────────────────────────────
# Ajoute (ou met à jour) une instance dans le manifest.
# Usage : nginx_manifest_add INSTANCE_ID PREFIX PORT GAME_LABEL
nginx_manifest_add() {
    local instance_id="$1" prefix="$2" port="$3" game="$4"
    python3 "$SCRIPT_DIR/tools/nginx_manager.py" manifest-add \
        --manifest    "$GC_NGINX_MANIFEST" \
        --instance-id "$instance_id" \
        --prefix      "$prefix" \
        --port        "$port" \
        --game        "$game" \
    || { err "nginx_manifest_add échoué pour $instance_id"; return 1; }
}

# ── nginx_manifest_remove ─────────────────────────────────────────────────────
# Retire une instance du manifest.
# Usage : nginx_manifest_remove INSTANCE_ID
nginx_manifest_remove() {
    local instance_id="$1"
    python3 "$SCRIPT_DIR/tools/nginx_manager.py" manifest-remove \
        --manifest    "$GC_NGINX_MANIFEST" \
        --instance-id "$instance_id" \
    || { err "nginx_manifest_remove échoué pour $instance_id"; return 1; }
}

# ── nginx_manifest_check ──────────────────────────────────────────────────────
# Retourne 0 si l'instance est dans le manifest, 1 sinon.
# Usage : nginx_manifest_check INSTANCE_ID
nginx_manifest_check() {
    local instance_id="$1"
    python3 "$SCRIPT_DIR/tools/nginx_manager.py" manifest-check \
        --manifest    "$GC_NGINX_MANIFEST" \
        --instance-id "$instance_id" 2>/dev/null
}

# ── nginx_regenerate_locations ────────────────────────────────────────────────
# Régénère le fichier locations depuis le manifest.
nginx_regenerate_locations() {
    python3 "$SCRIPT_DIR/tools/nginx_manager.py" regenerate \
        --manifest "$GC_NGINX_MANIFEST" \
        --out      "$GC_NGINX_LOC_FILE" \
    || { err "nginx_regenerate_locations échoué"; return 1; }
}

# ── nginx_apply ───────────────────────────────────────────────────────────────
# Teste la config nginx et recharge si OK.
nginx_apply() {
    if nginx -t 2>/dev/null; then
        systemctl reload nginx
        ok "Nginx reloadé"
    else
        err "Erreur config Nginx — vérifiez avec : nginx -t"
        return 1
    fi
}
