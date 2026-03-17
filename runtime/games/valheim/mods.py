"""
games/valheim/mods.py — Intégration Thunderstore + BepInEx.
Recherche, installation et suppression de mods Valheim.
Sécurité : path traversal, SSRF, Zip Slip.
"""
import os, json, shutil, zipfile, tempfile, re
from datetime import datetime, timezone, timedelta
import requests as http
from flask import current_app

THUNDERSTORE_API = 'https://thunderstore.io/c/valheim/api/v1'
ALLOWED_HOSTS    = {'thunderstore.io', 'gcdn.thunderstore.io'}
_search_cache    = {'ts': None, 'data': []}
_CACHE_TTL       = 3600  # 1h
IGNORED_PLUGIN_DLLS = {
    'valheim.displaybepinexinfo.dll',
}

def _bepinex_path():
    return current_app.config['GAME']['mods']['bepinex_path']

def _plugins_dir():
    return os.path.join(_bepinex_path(), 'plugins')

# ── Sécurité ───────────────────────────────────────────────────────────────────
def _safe_path(base, rel):
    """Bloque les path traversal (../../etc)."""
    base = os.path.realpath(base)
    full = os.path.realpath(os.path.join(base, rel))
    if not full.startswith(base + os.sep) and full != base:
        raise ValueError(f'Path traversal bloqué : {rel}')
    return full

def _validate_url(url):
    """Autorise uniquement les domaines Thunderstore."""
    from urllib.parse import urlparse
    host = urlparse(url).netloc.lower()
    if host not in ALLOWED_HOSTS:
        raise ValueError(f'URL non autorisée : {host}')

def _safe_extract(zf, dest):
    """Extraction ZIP sans Zip Slip."""
    dest = os.path.realpath(dest)
    for member in zf.namelist():
        target = os.path.realpath(os.path.join(dest, member))
        if not target.startswith(dest + os.sep) and target != dest:
            raise ValueError(f'Zip Slip bloqué : {member}')
        zf.extract(member, dest)

def _normalize_mod_token(value):
    return re.sub(r'[^a-z0-9]+', '', value.lower())

def _candidate_match_tokens(namespace, name):
    tokens = {
        _normalize_mod_token(namespace),
        _normalize_mod_token(name),
        _normalize_mod_token(f'{namespace}-{name}'),
        _normalize_mod_token(f'{namespace}_{name}'),
        _normalize_mod_token(f'{namespace}.{name}'),
    }
    ignored = {'', 'valheim', 'plugin', 'plugins', 'pack', 'mod', 'mods', 'bepinex', 'temporary'}
    for raw in re.split(r'[^a-zA-Z0-9]+', f'{namespace} {name}'):
        token = _normalize_mod_token(raw)
        if len(token) >= 4 and token not in ignored:
            tokens.add(token)
    tokens.discard('')
    return tokens

def _selected_bepinex_members(names, namespace, name):
    """Sélectionne uniquement les fichiers du mod ciblé dans une archive BepInEx."""
    normalized_targets = _candidate_match_tokens(namespace, name)

    def rel_under(prefix, member):
        return member[len(prefix):] if member.startswith(prefix) else None

    exact_prefixes = [
        f'BepInEx/plugins/{namespace}-{name}/',
        f'BepInEx/plugins/{namespace}_{name}/',
        f'BepInEx/plugins/{namespace}.{name}/',
    ]
    selected = []
    for prefix in exact_prefixes:
        matches = [n for n in names if n.startswith(prefix)]
        if matches:
            return matches

    for member in names:
        rel_plugin = rel_under('BepInEx/plugins/', member)
        rel_config = rel_under('BepInEx/config/', member)
        rel = rel_plugin or rel_config
        if rel is None or not rel or rel.endswith('/'):
            continue
        token = _normalize_mod_token(os.path.basename(rel))
        parent = _normalize_mod_token(rel.split('/', 1)[0])
        if any(target and (target in token or target in parent) for target in normalized_targets):
            selected.append(member)
    return selected

# ── Recherche ──────────────────────────────────────────────────────────────────
def _get_all_packages():
    now = datetime.now(timezone.utc)
    if _search_cache['ts'] and (now - _search_cache['ts']).seconds < _CACHE_TTL:
        return _search_cache['data']
    try:
        r = http.get(f'{THUNDERSTORE_API}/package/',
                     headers={'User-Agent': 'GameCommander/1.0'},
                     timeout=10)
        r.raise_for_status()
        data = r.json()
        _search_cache['data'] = data
        _search_cache['ts']   = now
        return data
    except Exception:
        return _search_cache['data']

def search_mods(query):
    query = query.lower()
    packages = _get_all_packages()
    results  = []
    for pkg in packages:
        name = pkg.get('name', '').lower()
        full = f"{pkg.get('namespace','').lower()}-{name}"
        if query not in name and query not in full:
            continue
        latest = pkg.get('versions', [{}])[0]
        results.append({
            'name':        pkg.get('name'),
            'namespace':   pkg.get('owner'),
            'description': latest.get('description', '')[:120],
            'version':     latest.get('version_number'),
            'last_updated': latest.get('date_created') or latest.get('date_updated') or '',
            'downloads':   pkg.get('package_url'),
            'icon_url':    latest.get('icon'),
            'deprecated':  pkg.get('is_deprecated', False),
        })
        if len(results) >= 30:
            break
    return results

# ── Mods installés ─────────────────────────────────────────────────────────────
def get_installed_mods():
    plugins = _plugins_dir()
    if not os.path.isdir(plugins):
        return []
    mods = []
    for entry in os.scandir(plugins):
        if entry.is_dir():
            mods.append({'name': entry.name, 'folder': entry.path})
            continue
        if entry.is_file() and entry.name.lower().endswith('.dll'):
            if entry.name.lower() in IGNORED_PLUGIN_DLLS:
                continue
            mods.append({'name': entry.name[:-4], 'file': entry.path})
    return sorted(mods, key=lambda x: x['name'].lower())

# ── Installation ───────────────────────────────────────────────────────────────
def install_mod(namespace, name, version):
    if not namespace or not name or not version:
        return False, 'Paramètres manquants'

    # Validation des paramètres
    if not re.match(r'^[\w\-]+$', namespace) or not re.match(r'^[\w\-]+$', name):
        return False, 'Caractères non autorisés'

    download_url = f'https://thunderstore.io/package/download/{namespace}/{name}/{version}/'
    try:
        _validate_url(download_url)
    except ValueError as e:
        return False, str(e)

    plugins = _plugins_dir()
    os.makedirs(plugins, exist_ok=True)

    try:
        r = http.get(download_url,
                     headers={'User-Agent': 'GameCommander/1.0'},
                     timeout=60, stream=True)
        r.raise_for_status()
    except Exception as e:
        return False, f'Téléchargement échoué : {e}'

    try:
        with tempfile.TemporaryDirectory() as tmp:
            zip_path = os.path.join(tmp, 'mod.zip')
            with open(zip_path, 'wb') as f:
                for chunk in r.iter_content(65536):
                    f.write(chunk)

            with zipfile.ZipFile(zip_path) as zf:
                names = zf.namelist()
                if any(n.startswith('BepInEx/') for n in names):
                    selected_members = _selected_bepinex_members(names, namespace, name)
                    if not selected_members:
                        return False, 'Archive mod BepInEx invalide : fichiers du mod introuvables'
                    dest_base = os.path.dirname(_bepinex_path())
                    dest_root = os.path.realpath(dest_base)
                    for member in selected_members:
                        target = os.path.realpath(os.path.join(dest_base, member))
                        if not target.startswith(dest_root + os.sep) and target != dest_root:
                            raise ValueError(f'Zip Slip bloqué : {member}')
                        os.makedirs(os.path.dirname(target), exist_ok=True)
                        with zf.open(member) as src, open(target, 'wb') as dst:
                            dst.write(src.read())
                else:
                    # Flat structure → dossier plugins/{Namespace}-{Name}
                    mod_folder = _safe_path(plugins, f'{namespace}-{name}')
                    os.makedirs(mod_folder, exist_ok=True)
                    _safe_extract(zf, mod_folder)

        return True, f'{namespace}-{name} v{version} installé'
    except Exception as e:
        return False, f'Extraction échouée : {e}'

# ── Suppression ────────────────────────────────────────────────────────────────
def remove_mod(mod_name):
    if not re.match(r'^[\w\-]+$', mod_name):
        return False, 'Nom de mod invalide'
    plugins = _plugins_dir()
    try:
        target = _safe_path(plugins, mod_name)
    except ValueError as e:
        return False, str(e)

    try:
        if os.path.isdir(target):
            shutil.rmtree(target)
        elif os.path.isfile(target):
            os.remove(target)
        elif os.path.isfile(f'{target}.dll'):
            os.remove(f'{target}.dll')
        else:
            return False, 'Mod introuvable'
        return True, f'{mod_name} supprimé'
    except Exception as e:
        return False, str(e)
