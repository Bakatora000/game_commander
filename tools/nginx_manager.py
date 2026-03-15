#!/usr/bin/env python3
"""
nginx_manager.py — Manipulation du fichier nginx pour Game Commander.

Sous-commandes (inject/remove — ancienne approche, conservée pour compatibilité) :
  find-conf    --domain DOMAIN
  inject       --conf FILE --instance-id ID --prefix /p --port PORT --label LABEL
  remove       --conf FILE --instance-id ID --prefix /p

Sous-commandes (manifest — nouvelle approche) :
  init          --domain DOMAIN --manifest FILE --loc-file FILE --backup-dir DIR
                Migration one-shot : crée manifest + fichier locations + ajoute l'include
                dans le fichier nginx du domaine (supprime les anciens blocs injectés).

  manifest-add  --manifest FILE --instance-id ID --prefix /p --port PORT --game LABEL
  manifest-remove --manifest FILE --instance-id ID
  manifest-check  --manifest FILE --instance-id ID   (exit 0=présent, 1=absent)

  regenerate    --manifest FILE --out FILE
                Regénère le fichier locations depuis le manifest.
"""

import argparse
import glob
import json
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════

def backup_file(src: str, dest_dir: str) -> str:
    """Copie src dans dest_dir avec horodatage. Retourne le chemin du backup."""
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    dst = Path(dest_dir) / f"{Path(src).name}.{ts}.bak"
    Path(dest_dir).mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return str(dst)


def backup_alongside(path: str) -> str:
    """Crée un backup .bak.timestamp à côté du fichier. Retourne le chemin."""
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    dst = f"{path}.bak.{ts}"
    shutil.copy2(path, dst)
    return dst


def find_ssl_block_end(content: str, ssl_pos: int) -> int:
    """
    Remonte au 'server {' parent du 'listen 443' trouvé à ssl_pos
    et retourne la position du '}' fermant. -1 si non trouvé.
    """
    start = content.rfind("server {", 0, ssl_pos)
    if start == -1:
        start = content.rfind("server{", 0, ssl_pos)
    if start == -1:
        return -1
    depth = 0
    for i in range(start, len(content)):
        if content[i] == "{":
            depth += 1
        elif content[i] == "}":
            depth -= 1
            if depth == 0:
                return i
    return -1


def build_location_block(instance_id: str, prefix: str, port: int, game: str) -> str:
    """Génère le bloc location nginx pour une instance."""
    return (
        f"\n"
        f"    # ── Game Commander — {game} ({instance_id}) ──────────────────────────────\n"
        f"    location {prefix} {{\n"
        f"        proxy_pass         http://127.0.0.1:{port};\n"
        f"        proxy_http_version 1.1;\n"
        f"        proxy_set_header   Host              $host;\n"
        f"        proxy_set_header   X-Real-IP         $remote_addr;\n"
        f"        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;\n"
        f"        proxy_set_header   X-Forwarded-Proto $scheme;\n"
        f"        client_max_body_size 2G;\n"
        f"        proxy_read_timeout 120s;\n"
        f"        proxy_send_timeout 120s;\n"
        f"    }}\n"
        f"    location {prefix}/static {{\n"
        f"        proxy_pass http://127.0.0.1:{port};\n"
        f"        expires 1h;\n"
        f"        add_header Cache-Control \"public\";\n"
        f"    }}\n"
        f"    # {'─' * 73}\n"
    )


def _is_active_conf(p: str) -> bool:
    """Exclut les backups (.bak, .old, .disabled) et les non-fichiers."""
    path = Path(p)
    return (
        path.is_file()
        and ".bak" not in path.name
        and ".old" not in path.name
        and ".disabled" not in path.name
        and not re.search(r"\.\d{8,}", path.name)
    )


def find_nginx_conf(domain: str) -> str | None:
    """Retourne le chemin du fichier nginx contenant server_name DOMAIN, ou None."""
    candidates = [
        f"/etc/nginx/conf.d/{domain}.conf",
        f"/etc/nginx/sites-enabled/{domain}.conf",
        f"/etc/nginx/sites-available/{domain}.conf",
        f"/etc/nginx/sites-available/{domain}",
    ]
    for path in candidates:
        if Path(path).is_file():
            return path

    pattern = re.compile(r"server_name\s+[^;]*\b" + re.escape(domain) + r"\b")
    search_dirs = [
        "/etc/nginx/conf.d",
        "/etc/nginx/sites-available",
        "/etc/nginx/sites-enabled",
    ]
    for d in search_dirs:
        for fpath in sorted(glob.glob(f"{d}/*")):
            if not _is_active_conf(fpath):
                continue
            try:
                content = Path(fpath).read_text()
            except (OSError, UnicodeDecodeError):
                continue
            if pattern.search(content):
                return fpath

    # Fichier 'default' (sans extension .conf)
    for default_path in [
        "/etc/nginx/sites-available/default",
        "/etc/nginx/sites-enabled/default",
    ]:
        if not Path(default_path).is_file():
            continue
        try:
            content = Path(default_path).read_text()
        except (OSError, UnicodeDecodeError):
            continue
        if pattern.search(content):
            return default_path

    return None


def load_manifest(path: str) -> dict:
    return json.loads(Path(path).read_text())


def save_manifest(path: str, manifest: dict) -> None:
    Path(path).write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")


# ══════════════════════════════════════════════════════════════════════════════
# Sous-commandes — ancienne approche (inject/remove directs)
# ══════════════════════════════════════════════════════════════════════════════

def cmd_find_conf(args):
    path = find_nginx_conf(args.domain)
    if path:
        print(path)
        return 0
    print(f"[nginx_manager] WARN: aucun fichier nginx trouvé pour '{args.domain}'",
          file=sys.stderr)
    return 1


def cmd_inject(args):
    conf_path = args.conf
    instance_id = args.instance_id
    prefix = args.prefix.rstrip("/")
    port = args.port
    label = args.label

    if not Path(conf_path).is_file():
        print(f"[nginx_manager] ERROR: fichier introuvable : {conf_path}", file=sys.stderr)
        return 1

    content = Path(conf_path).read_text()
    if f"location {prefix} " in content or f"location {prefix}/" in content:
        print(f"[nginx_manager] INFO: bloc '{prefix}' déjà présent — ignoré")
        return 0

    bak = backup_alongside(conf_path)
    print(f"[nginx_manager] Backup : {bak}")
    block = build_location_block(instance_id, prefix, port, label)

    # Stratégie 1 : bloc SSL
    ssl_match = re.search(r"listen\s+443\s+ssl", content)
    if ssl_match:
        insert_pos = find_ssl_block_end(content, ssl_match.start())
        if insert_pos > 0:
            content = content[:insert_pos] + block + "}" + content[insert_pos + 1:]
            Path(conf_path).write_text(content)
            print(f"[nginx_manager] OK: '{prefix}' injecté dans bloc SSL de {conf_path}")
            return 0

    # Stratégie 2 : avant location /
    loc_root = re.search(r"^\s{4}location\s+/\s+\{", content, re.MULTILINE)
    if loc_root:
        content = content[:loc_root.start()] + block + "\n" + content[loc_root.start():]
        Path(conf_path).write_text(content)
        print(f"[nginx_manager] OK: '{prefix}' injecté avant 'location /' dans {conf_path}")
        return 0

    # Stratégie 3 : avant la dernière }
    last_brace = content.rfind("}")
    if last_brace >= 0:
        content = content[:last_brace] + block + "}\n" + content[last_brace + 1:]
        Path(conf_path).write_text(content)
        print(f"[nginx_manager] OK: '{prefix}' injecté (fallback) dans {conf_path}")
        return 0

    print(f"[nginx_manager] ERROR: impossible d'injecter dans {conf_path}", file=sys.stderr)
    shutil.copy2(bak, conf_path)
    return 1


def cmd_remove(args):
    conf_path = args.conf
    instance_id = args.instance_id
    prefix = args.prefix.rstrip("/")

    if not Path(conf_path).is_file():
        print(f"[nginx_manager] ERROR: fichier introuvable : {conf_path}", file=sys.stderr)
        return 1

    content = Path(conf_path).read_text()
    if f"location {prefix} " not in content and f"location {prefix}/" not in content:
        print(f"[nginx_manager] INFO: bloc '{prefix}' absent — rien à faire")
        return 0

    bak = backup_alongside(conf_path)
    print(f"[nginx_manager] Backup : {bak}")
    original = content

    # Méthode 1 : via commentaire Game Commander
    pattern1 = (
        r"\n?[ \t]*# ── Game Commander[^\n]*\(" + re.escape(instance_id) + r"\)[^\n]*\n"
        r".*?"
        r"location " + re.escape(prefix) + r"/static \{[^}]*\}[ \t]*\n?"
        r"[ \t]*# [─]+\n?"
    )
    result = re.sub(pattern1, "\n", content, flags=re.DOTALL)

    # Méthode 2 : brace-counting
    if result == content:
        m = re.search(r"\n?[ \t]*location " + re.escape(prefix) + r"\s*\{", content)
        if m:
            start = m.start()
            depth, end = 0, start
            for i in range(m.start(), len(content)):
                if content[i] == "{":
                    depth += 1
                elif content[i] == "}":
                    depth -= 1
                    if depth == 0:
                        end = i + 1
                        break
            m_static = re.search(
                r"[ \t]*\n?[ \t]*location " + re.escape(prefix) + r"/static\s*\{",
                content[end:],
            )
            if m_static:
                static_start = end + m_static.start()
                depth = 0
                for i in range(static_start, len(content)):
                    if content[i] == "{":
                        depth += 1
                    elif content[i] == "}":
                        depth -= 1
                        if depth == 0:
                            end = i + 1
                            break
            comment_m = re.search(r"\n[ \t]*# ── Game Commander[^\n]*\n", content[:start])
            if comment_m and comment_m.end() == start + 1:
                start = comment_m.start()
            trail_m = re.search(r"[ \t]*\n?[ \t]*# [─]{10,}\n?", content[end:])
            if trail_m and trail_m.start() == 0:
                end += trail_m.end()
            result = content[:start] + "\n" + content[end:]

    if result == original:
        print(f"[nginx_manager] WARN: '{prefix}' non supprimé — pattern non reconnu",
              file=sys.stderr)
        return 1

    Path(conf_path).write_text(result)
    print(f"[nginx_manager] OK: '{prefix}' ({instance_id}) retiré de {conf_path}")
    return 0


# ══════════════════════════════════════════════════════════════════════════════
# Sous-commandes — manifest
# ══════════════════════════════════════════════════════════════════════════════

def cmd_init(args):
    """
    Migration one-shot vers le système manifest + include.
    - Crée manifest et fichier locations s'ils n'existent pas.
    - Trouve le fichier nginx du domaine.
    - Supprime les anciens blocs Game Commander injectés (inline).
    - Ajoute include dans le bloc SSL du domaine.
    """
    domain     = args.domain
    manifest_p = Path(args.manifest)
    loc_file_p = Path(args.loc_file)
    backup_dir = args.backup_dir

    Path(backup_dir).mkdir(parents=True, exist_ok=True)

    # Manifest
    if not manifest_p.is_file():
        save_manifest(str(manifest_p), {"vhost": domain, "instances": []})
        print(f"[nginx_manager] Manifest créé : {manifest_p}")
    else:
        print(f"[nginx_manager] Manifest existant : {manifest_p}")

    # Fichier locations
    if not loc_file_p.is_file():
        loc_file_p.write_text(
            "# Game Commander — locations auto-générées — NE PAS ÉDITER MANUELLEMENT\n"
        )
        print(f"[nginx_manager] Fichier locations créé : {loc_file_p}")
    else:
        print(f"[nginx_manager] Fichier locations existant : {loc_file_p}")

    # Trouver le fichier nginx du domaine
    conf_path = find_nginx_conf(domain)
    if not conf_path:
        print(f"[nginx_manager] WARN: fichier nginx pour '{domain}' introuvable — include non ajouté",
              file=sys.stderr)
        return 0

    content = Path(conf_path).read_text()

    # Vérifier si l'include est déjà en place
    if str(loc_file_p) in content or "game-commander-locations.conf" in content:
        print(f"[nginx_manager] INFO: include déjà présent dans {conf_path}")
        return 0

    # Migration : backup + nettoyage + ajout include
    bak = backup_file(conf_path, backup_dir)
    print(f"[nginx_manager] Backup : {bak}")

    # 1. Supprimer les blocs location /mods (reliquats Game Commander)
    content = re.sub(
        r"\n?[ \t]*location\s+/mods\s*\{[^{}]*\}\n?",
        "\n",
        content,
        flags=re.DOTALL,
    )

    # 2. Supprimer les blocs Game Commander injectés (inline)
    content = re.sub(
        r"\n?[ \t]*# ── Game Commander[^\n]*\n.*?# [─]{10,}\n?",
        "\n",
        content,
        flags=re.DOTALL,
    )

    # 3. Trouver le bloc SSL du domaine et y ajouter l'include
    domain_match = re.search(r"server_name\s+[^;]*\b" + re.escape(domain) + r"\b", content)
    if not domain_match:
        print(f"[nginx_manager] WARN: server_name {domain} non trouvé après nettoyage", file=sys.stderr)
        Path(conf_path).write_text(content)
        return 0

    ssl_match = re.search(r"listen\s+443\s+ssl", content[domain_match.start():])
    if ssl_match:
        ssl_abs_pos = domain_match.start() + ssl_match.start()
        insert_pos = find_ssl_block_end(content, ssl_abs_pos)
    else:
        # Pas de SSL dans ce fichier : chercher la fermeture du bloc du domaine
        block_start = content.rfind("server {", 0, domain_match.start())
        depth, insert_pos = 0, -1
        for i in range(block_start if block_start >= 0 else 0, len(content)):
            if content[i] == "{":
                depth += 1
            elif content[i] == "}":
                depth -= 1
                if depth == 0:
                    insert_pos = i
                    break

    if insert_pos <= 0:
        print(f"[nginx_manager] WARN: impossible de trouver la fermeture du bloc — include non ajouté",
              file=sys.stderr)
        Path(conf_path).write_text(content)
        return 0

    include_line = f"\n    include {loc_file_p};\n"
    content = content[:insert_pos] + include_line + content[insert_pos:]
    Path(conf_path).write_text(content)
    print(f"[nginx_manager] OK: include ajouté dans {conf_path}")
    return 0


def cmd_manifest_add(args):
    manifest_p = Path(args.manifest)
    if not manifest_p.is_file():
        print(f"[nginx_manager] ERROR: manifest introuvable : {manifest_p}", file=sys.stderr)
        return 1
    manifest = load_manifest(str(manifest_p))
    manifest["instances"] = [
        i for i in manifest["instances"] if i["name"] != args.instance_id
    ]
    manifest["instances"].append({
        "name":       args.instance_id,
        "prefix":     args.prefix,
        "flask_port": args.port,
        "game":       args.game,
    })
    save_manifest(str(manifest_p), manifest)
    print(f"[nginx_manager] OK: {args.instance_id} ({args.prefix} → :{args.port}) ajouté")
    return 0


def cmd_manifest_remove(args):
    manifest_p = Path(args.manifest)
    if not manifest_p.is_file():
        print(f"[nginx_manager] INFO: manifest introuvable — rien à retirer")
        return 0
    manifest = load_manifest(str(manifest_p))
    before = len(manifest["instances"])
    manifest["instances"] = [
        i for i in manifest["instances"] if i["name"] != args.instance_id
    ]
    save_manifest(str(manifest_p), manifest)
    removed = before - len(manifest["instances"])
    print(f"[nginx_manager] OK: {args.instance_id} retiré ({removed} entrée(s))")
    return 0


def cmd_manifest_check(args):
    """Exit 0 si l'instance est dans le manifest, 1 sinon."""
    manifest_p = Path(args.manifest)
    if not manifest_p.is_file():
        return 1
    manifest = load_manifest(str(manifest_p))
    found = any(i["name"] == args.instance_id for i in manifest.get("instances", []))
    return 0 if found else 1


def cmd_regenerate(args):
    manifest_p = Path(args.manifest)
    if not manifest_p.is_file():
        print(f"[nginx_manager] ERROR: manifest introuvable : {manifest_p}", file=sys.stderr)
        return 1

    manifest = load_manifest(str(manifest_p))
    instances = manifest.get("instances", [])

    lines = ["# Game Commander — locations auto-générées — NE PAS ÉDITER MANUELLEMENT"]
    for inst in instances:
        lines.append(build_location_block(
            inst["name"], inst["prefix"], inst["flask_port"], inst["game"]
        ))

    Path(args.out).write_text("\n".join(lines) + "\n")
    print(f"[nginx_manager] OK: {len(instances)} instance(s) → {args.out}")
    return 0


# ══════════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Gestion nginx pour Game Commander",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # ── Ancienne approche ──────────────────────────────────────────────────────
    p = sub.add_parser("find-conf")
    p.add_argument("--domain", required=True)

    p = sub.add_parser("inject")
    p.add_argument("--conf",        required=True)
    p.add_argument("--instance-id", required=True)
    p.add_argument("--prefix",      required=True)
    p.add_argument("--port",        required=True, type=int)
    p.add_argument("--label",       required=True)

    p = sub.add_parser("remove")
    p.add_argument("--conf",        required=True)
    p.add_argument("--instance-id", required=True)
    p.add_argument("--prefix",      required=True)

    # ── Manifest ───────────────────────────────────────────────────────────────
    p = sub.add_parser("init", help="Migration one-shot vers le système manifest")
    p.add_argument("--domain",      required=True)
    p.add_argument("--manifest",    required=True)
    p.add_argument("--loc-file",    required=True)
    p.add_argument("--backup-dir",  required=True)

    p = sub.add_parser("manifest-add")
    p.add_argument("--manifest",    required=True)
    p.add_argument("--instance-id", required=True)
    p.add_argument("--prefix",      required=True)
    p.add_argument("--port",        required=True, type=int)
    p.add_argument("--game",        required=True)

    p = sub.add_parser("manifest-remove")
    p.add_argument("--manifest",    required=True)
    p.add_argument("--instance-id", required=True)

    p = sub.add_parser("manifest-check")
    p.add_argument("--manifest",    required=True)
    p.add_argument("--instance-id", required=True)

    p = sub.add_parser("regenerate")
    p.add_argument("--manifest",    required=True)
    p.add_argument("--out",         required=True)

    args = parser.parse_args()

    dispatch = {
        "find-conf":       cmd_find_conf,
        "inject":          cmd_inject,
        "remove":          cmd_remove,
        "init":            cmd_init,
        "manifest-add":    cmd_manifest_add,
        "manifest-remove": cmd_manifest_remove,
        "manifest-check":  cmd_manifest_check,
        "regenerate":      cmd_regenerate,
    }
    sys.exit(dispatch[args.command](args))


if __name__ == "__main__":
    main()
