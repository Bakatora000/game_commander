"""
games/valheim/world_modifiers.py
Lecture/écriture des World Modifiers Valheim.
Stockés dans world_modifiers.json, appliqués dans le script de lancement.
"""
import json, os, re
from pathlib import Path
from flask import current_app

# ── Définition des modificateurs ─────────────────────────────────────────────
MODIFIERS = [
    {'key': 'combat',       'flag': 'combat',       'label': 'Combat',
     'values': ['veryeasy','easy','normal','hard','veryhard'], 'default': 'normal'},
    {'key': 'deathpenalty', 'flag': 'deathpenalty',  'label': 'Pénalité de mort',
     'values': ['casual','veryeasy','easy','normal','hardcore','permadeath'], 'default': 'normal'},
    {'key': 'resources',    'flag': 'resources',     'label': 'Ressources',
     'values': ['muchless','less','normal','more','most'], 'default': 'normal'},
    {'key': 'raids',        'flag': 'raids',         'label': 'Raids',
     'values': ['none','muchless','less','normal','more','most'], 'default': 'normal'},
    {'key': 'portals',      'flag': 'portals',       'label': 'Portails',
     'values': ['casual','default','hard','veryhard','noportals','nobossportals'], 'default': 'default'},
]

SETKEYS = [
    {'key': 'nobuildcost',   'label': 'Pas de coût de construction'},
    {'key': 'playerevents',  'label': 'Raids basés sur les joueurs'},
    {'key': 'nofireplacedmg','label': 'Pas de danger de feu'},
    {'key': 'passivemobs',   'label': 'Monstres passifs'},
    {'key': 'nomap',         'label': 'Pas de carte'},
]

PRESETS = {
    'default':    {'combat':'normal',  'deathpenalty':'normal',   'resources':'normal', 'raids':'normal', 'portals':'default'},
    'easy':       {'combat':'easy',    'deathpenalty':'easy',    'resources':'more',   'raids':'less',    'portals':'default'},
    'hard':       {'combat':'hard',    'deathpenalty':'hard',    'resources':'less',   'raids':'more',    'portals':'default'},
    'hardcore':   {'combat':'veryhard','deathpenalty':'hardcore','resources':'normal', 'raids':'more',    'portals':'default'},
    'casual':     {'combat':'easy',    'deathpenalty':'casual',  'resources':'most',   'raids':'none',    'portals':'casual'},
    'hammer':     {'combat':'normal',  'deathpenalty':'normal',  'resources':'normal', 'raids':'none',    'portals':'default'},
    'immersive':  {'combat':'hard',    'deathpenalty':'hardcore','resources':'less',   'raids':'normal',  'portals':'veryhard'},
}

def _json_path():
    world_name = (current_app.config['GAME']['server'].get('world_name') or '').strip()
    return _named_json_path(world_name)

def _named_json_path(world_name: str):
    install_dir = current_app.config['GAME']['server']['install_dir']
    if world_name:
        safe = re.sub(r'[^A-Za-z0-9._-]+', '-', world_name).strip('-') or 'world'
        return os.path.join(install_dir, f'world_modifiers.{safe}.json')
    return os.path.join(install_dir, 'world_modifiers.json')

def _legacy_json_path():
    install_dir = current_app.config['GAME']['server']['install_dir']
    return os.path.join(install_dir, 'world_modifiers.json')

def _world_file_path():
    data_dir = current_app.config['GAME']['server'].get('data_dir') or current_app.config['GAME']['server']['install_dir']
    world_name = (current_app.config['GAME']['server'].get('world_name') or '').strip()
    if not world_name:
        return None
    root = Path(data_dir) / 'worlds_local'
    if not root.exists():
        root = Path(data_dir) / 'worlds'
    return root / f'{world_name}.fwl'

def _has_world_specific_files():
    install_dir = Path(current_app.config['GAME']['server']['install_dir'])
    return any(install_dir.glob('world_modifiers.*.json'))

def _defaults():
    defaults = {m['key']: m['default'] for m in MODIFIERS}
    defaults['setkeys'] = []
    return defaults

def _modifiers_from_fwl():
    path = _world_file_path()
    if not path or not path.exists():
        return None
    try:
        data = path.read_bytes()
        text = data.decode('utf-8', errors='ignore')
    except Exception:
        return None

    result = _defaults()

    preset_match = re.search(r'\bpreset\s+([A-Za-z0-9_-]+)\b', text)
    if preset_match:
        preset = preset_match.group(1).strip().lower()
        if preset in PRESETS:
            result.update(PRESETS[preset])
            result['setkeys'] = list(PRESETS[preset].get('setkeys', []))

    toggles = {
        'nomap': 'nomap',
        'playerevents': 'playerevents',
        'nobuildcost': 'nobuildcost',
        'nofire': 'nofireplacedmg',
        'passivemobs': 'passivemobs',
    }
    for token, setkey in toggles.items():
        if re.search(rf'\b{re.escape(token)}\b', text) and setkey not in result['setkeys']:
            result['setkeys'].append(setkey)

    portal_map = [
        ('nobossportals', 'nobossportals'),
        ('noportals', 'noportals'),
    ]
    for token, value in portal_map:
        if re.search(rf'\b{re.escape(token)}\b', text):
            result['portals'] = value
            break

    # Numeric fallbacks useful for uploaded worlds with embedded settings.
    if re.search(r'\benemydamage\s+200\b', text):
        result['combat'] = 'veryhard'
    elif re.search(r'\benemydamage\s+150\b', text):
        result['combat'] = 'hard'
    elif re.search(r'\benemydamage\s+50\b', text):
        result['combat'] = 'easy'
    elif re.search(r'\benemydamage\s+25\b', text):
        result['combat'] = 'veryeasy'

    if re.search(r'\bdeathdeleteitems\b', text) and re.search(r'\bdeathskillsreset\b', text):
        result['deathpenalty'] = 'hardcore'
    elif re.search(r'\bdeathskillsreset\b', text):
        result['deathpenalty'] = 'hard'

    return result

def _start_script():
    install_dir = current_app.config['GAME']['server']['install_dir']
    for name in ('start_server_bepinex.sh', 'start_server.sh'):
        p = os.path.join(install_dir, name)
        if os.path.exists(p):
            return p
    return None

def read_modifiers():
    path = _json_path()
    defaults = _defaults()
    if not os.path.exists(path):
        legacy = _legacy_json_path()
        if path != legacy and os.path.exists(legacy) and not _has_world_specific_files():
            path = legacy
        else:
            from_fwl = _modifiers_from_fwl()
            return (from_fwl or defaults), None
    if not os.path.exists(path):
        return defaults, None
    try:
        with open(path) as f:
            return json.load(f), None
    except Exception as e:
        return defaults, str(e)

def write_modifiers(data):
    path = _json_path()
    try:
        with open(path, 'w') as f:
            json.dump(data, f, indent=2)
        err = _apply_to_start_script(data)
        return True, err
    except Exception as e:
        return False, str(e)

def _apply_to_start_script(data):
    """Met à jour la ligne exec du script de démarrage avec les modificateurs."""
    script = _start_script()
    if not script:
        return 'Script de démarrage introuvable'
    try:
        with open(script) as f:
            content = f.read()

        # Trouver la ligne exec
        m = re.search(r'^(exec \./valheim_server\S+)(.*?)$', content, re.MULTILINE)
        if not m:
            return 'Ligne exec introuvable dans le script'

        base_exec = m.group(1)
        existing_args = m.group(2)

        # Retirer tous les anciens flags modifiers/setkey/preset
        existing_args = re.sub(r'\s*-modifier\s+\S+\s+\S+', '', existing_args)
        existing_args = re.sub(r'\s*-setkey\s+\S+', '', existing_args)
        existing_args = re.sub(r'\s*-preset\s+\S+', '', existing_args)
        existing_args = existing_args.strip()

        # Construire les nouveaux flags
        new_flags = []
        for mod in MODIFIERS:
            val = data.get(mod['key'], mod['default'])
            if val != mod['default']:
                new_flags.append(f"-modifier {mod['flag']} {val}")
        for sk in SETKEYS:
            if sk['key'] in data.get('setkeys', []):
                new_flags.append(f"-setkey {sk['key']}")

        flags_str = (' ' + ' '.join(new_flags)) if new_flags else ''
        new_exec = f"{base_exec} {existing_args}{flags_str}".rstrip()

        content = re.sub(
            r'^exec \./valheim_server.*$',
            new_exec,
            content,
            flags=re.MULTILINE
        )

        with open(script, 'w') as f:
            f.write(content)
        return None
    except Exception as e:
        return str(e)

def get_schema():
    return {'modifiers': MODIFIERS, 'setkeys': SETKEYS, 'presets': list(PRESETS.keys())}
