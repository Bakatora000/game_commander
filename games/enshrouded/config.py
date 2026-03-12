"""
games/enshrouded/config.py — Lecture/écriture de enshrouded_server.json.
"""
import os, json
from flask import current_app

def _cfg_path():
    install_dir = current_app.config['GAME']['server']['install_dir']
    return os.path.join(install_dir, 'enshrouded_server.json')

def read_config():
    path = _cfg_path()
    if not os.path.exists(path):
        return _default_config(), None  # Retourne les defaults si pas encore créé
    try:
        with open(path) as f:
            return json.load(f), None
    except Exception as e:
        return {}, str(e)

def write_config(new_data):
    path = _cfg_path()
    try:
        # Validation basique
        if 'slotCount' in new_data:
            slots = int(new_data['slotCount'])
            if not (1 <= slots <= 16):
                return False, 'slotCount doit être entre 1 et 16'
            new_data['slotCount'] = slots
        if 'queryPort' in new_data:
            new_data['queryPort'] = int(new_data['queryPort'])
        if 'gamePort' in new_data:
            new_data['gamePort'] = int(new_data['gamePort'])

        # Merge avec config existante
        current, _ = read_config()
        current.update(new_data)

        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            json.dump(current, f, indent=2)
        return True, None
    except Exception as e:
        return False, str(e)

def _default_config():
    return {
        'name':          'Enshrouded Server',
        'password':      '',
        'saveDirectory': './savegame',
        'logDirectory':  './logs',
        'ip':            '0.0.0.0',
        'queryPort':     15637,
        'gamePort':      15636,
        'slotCount':     16,
    }

def get_schema():
    return [
        {'key': 'name',          'label': 'Nom du serveur',  'type': 'text'},
        {'key': 'password',      'label': 'Mot de passe',    'type': 'password'},
        {'key': 'slotCount',     'label': 'Joueurs max',     'type': 'number', 'min': 1, 'max': 16},
        {'key': 'gamePort',      'label': 'Port de jeu',     'type': 'number'},
        {'key': 'queryPort',     'label': 'Port de requête', 'type': 'number'},
        {'key': 'saveDirectory', 'label': 'Dossier saves',   'type': 'text'},
    ]
