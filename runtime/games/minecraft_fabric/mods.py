"""
games/minecraft_fabric/mods.py — Intégration Modrinth pour Fabric.
"""
import json
import os
import zipfile
from io import BytesIO
from pathlib import Path

import requests as http
from flask import current_app

MODRINTH_API = 'https://api.modrinth.com/v2'
ALLOWED_HOSTS = {'api.modrinth.com', 'cdn.modrinth.com'}
BUILTIN_DEPENDENCIES = {'fabricloader', 'minecraft', 'java'}


def _mods_cfg():
    return current_app.config['GAME']['mods']


def _mods_dir():
    return _mods_cfg()['mods_path']


def _meta():
    path = _mods_cfg().get('meta_path')
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def _headers():
    return {'User-Agent': 'GameCommander/1.0'}


def _validate_url(url):
    from urllib.parse import urlparse
    host = urlparse(url).netloc.lower()
    if host not in ALLOWED_HOSTS:
        raise ValueError(f'URL non autorisée : {host}')


def search_mods(query):
    if not query.strip():
        return []

    meta = _meta()
    mc_version = meta.get('minecraft_version')
    loader = _mods_cfg().get('loader', 'fabric')

    r = http.get(
        f'{MODRINTH_API}/search',
        params={'query': query, 'limit': 30, 'index': 'relevance'},
        headers=_headers(),
        timeout=15,
    )
    r.raise_for_status()
    hits = r.json().get('hits', [])

    results = []
    for hit in hits:
        if hit.get('project_type') != 'mod':
            continue
        categories = set(hit.get('categories') or [])
        if loader not in categories:
            continue
        versions = set(hit.get('versions') or [])
        if mc_version and mc_version not in versions:
            continue
        if hit.get('server_side') == 'unsupported':
            continue

        results.append({
            'name': hit.get('title') or hit.get('slug'),
            'namespace': hit.get('project_id'),
            'description': (hit.get('description') or '')[:160],
            'version': hit.get('latest_version'),
            'downloads': hit.get('downloads'),
            'icon_url': hit.get('icon_url'),
            'deprecated': False,
        })
    return results


def get_installed_mods():
    mods_dir = Path(_mods_dir())
    if not mods_dir.is_dir():
        return []

    mods = []
    for entry in sorted(mods_dir.glob('*.jar')):
        mods.append({'name': entry.name, 'file': entry.name})
    return mods


def install_mod(namespace, name, version):
    if not namespace or not version:
        return False, 'Projet ou version manquant'

    try:
        mods_dir = Path(_mods_dir())
        mods_dir.mkdir(parents=True, exist_ok=True)
        installed = []
        _install_version(version, namespace, mods_dir, installed, set())
        if not installed:
            return True, f'{name or namespace} déjà installé'
        return True, f"{name or namespace} installé ({', '.join(installed)})"
    except Exception as e:
        return False, str(e)


def remove_mod(mod_name):
    if not mod_name:
        return False, 'Nom de mod invalide'

    target = Path(_mods_dir()) / mod_name
    if not target.is_file():
        return False, 'Mod introuvable'
    try:
        target.unlink()
        return True, f'{mod_name} supprimé'
    except Exception as e:
        return False, str(e)


def _install_version(version_id, project_id, mods_dir, installed, visited):
    key = (project_id, version_id)
    if key in visited:
        return
    visited.add(key)

    version_data = _get_version(version_id)
    if version_data.get('project_id') != project_id:
        raise ValueError('Version Modrinth incohérente')

    for dep in version_data.get('dependencies') or []:
        if dep.get('dependency_type') != 'required':
            continue
        dep_project = dep.get('project_id')
        dep_version = dep.get('version_id')
        if not dep_project:
            continue
        if not dep_version:
            resolved = _resolve_project_version(dep_project)
            dep_version = resolved['id']
            dep_project = resolved['project_id']
        _install_version(dep_version, dep_project, mods_dir, installed, visited)

    primary = _select_primary_file(version_data)
    target = mods_dir / primary['filename']
    if target.exists():
        return

    tmp_target = mods_dir / f'.{primary["filename"]}.part'
    _download_file(primary['url'], tmp_target)
    try:
        for dep_ref in _fabric_declared_dependencies(tmp_target, mods_dir):
            resolved = _resolve_project_version(dep_ref)
            _install_version(resolved['id'], resolved['project_id'], mods_dir, installed, visited)
        tmp_target.replace(target)
    except Exception:
        tmp_target.unlink(missing_ok=True)
        raise
    installed.append(primary['filename'])


def _get_version(version_id):
    r = http.get(f'{MODRINTH_API}/version/{version_id}', headers=_headers(), timeout=15)
    r.raise_for_status()
    return r.json()


def _resolve_project_version(project_id):
    meta = _meta()
    mc_version = meta.get('minecraft_version')
    loader = _mods_cfg().get('loader', 'fabric')
    params = {}
    if loader:
        params['loaders'] = json.dumps([loader])
    if mc_version:
        params['game_versions'] = json.dumps([mc_version])

    r = http.get(
        f'{MODRINTH_API}/project/{project_id}/version',
        params=params,
        headers=_headers(),
        timeout=15,
    )
    r.raise_for_status()
    versions = r.json()
    if not versions:
        raise ValueError(f'Aucune version compatible trouvée pour la dépendance {project_id}')
    return versions[0]


def _select_primary_file(version_data):
    files = version_data.get('files') or []
    primary = next((f for f in files if f.get('primary')), None) or (files[0] if files else None)
    if not primary:
        raise ValueError('Aucun fichier téléchargeable')
    _validate_url(primary.get('url', ''))
    return primary


def _download_file(url, target):
    with http.get(url, headers=_headers(), timeout=60, stream=True) as resp:
        resp.raise_for_status()
        with open(target, 'wb') as f:
            for chunk in resp.iter_content(65536):
                f.write(chunk)


def _fabric_declared_dependencies(jar_path, mods_dir):
    metadata, bundled = _read_fabric_metadata(jar_path)
    if not metadata:
        return []

    available = BUILTIN_DEPENDENCIES | bundled | _installed_mod_ids(mods_dir)
    depends = metadata.get('depends') or {}
    return sorted(dep_id for dep_id in depends if dep_id not in available)


def _installed_mod_ids(mods_dir):
    ids = set()
    mods_dir = Path(mods_dir)
    if not mods_dir.is_dir():
        return ids
    for jar in mods_dir.glob('*.jar'):
        metadata, bundled = _read_fabric_metadata(jar)
        ids |= bundled
        if metadata:
            ids |= _declared_mod_ids(metadata)
    return ids


def _read_fabric_metadata(jar_path):
    try:
        with zipfile.ZipFile(jar_path) as zf:
            metadata = json.loads(zf.read('fabric.mod.json'))
            bundled = _bundled_mod_ids(zf, metadata)
            return metadata, bundled
    except Exception:
        return None, set()


def _bundled_mod_ids(zf, metadata):
    ids = set()
    for entry in metadata.get('jars') or []:
        nested_path = entry.get('file')
        if not nested_path:
            continue
        try:
            nested_bytes = zf.read(nested_path)
            with zipfile.ZipFile(BytesIO(nested_bytes)) as nested:
                nested_meta = json.loads(nested.read('fabric.mod.json'))
            ids |= _declared_mod_ids(nested_meta)
        except Exception:
            continue
    return ids


def _declared_mod_ids(metadata):
    ids = set()
    mod_id = metadata.get('id')
    if mod_id:
        ids.add(mod_id)
    for provided in metadata.get('provides') or []:
        if provided:
            ids.add(provided)
    return ids
