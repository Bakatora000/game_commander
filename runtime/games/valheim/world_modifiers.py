"""
games/valheim/world_modifiers.py
Lecture/écriture des World Modifiers Valheim.
Stockés dans world_modifiers.json, appliqués dans le script de lancement.
"""
import json, os, re
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
    install_dir = current_app.config['GAME']['server']['install_dir']
    return os.path.join(install_dir, 'world_modifiers.json')

def _start_script():
    install_dir = current_app.config['GAME']['server']['install_dir']
    for name in ('start_server_bepinex.sh', 'start_server.sh'):
        p = os.path.join(install_dir, name)
        if os.path.exists(p):
            return p
    return None

def read_modifiers():
    path = _json_path()
    defaults = {m['key']: m['default'] for m in MODIFIERS}
    defaults['setkeys'] = []
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
