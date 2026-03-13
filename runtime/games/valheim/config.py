"""
games/valheim/config.py — Lecture/écriture du fichier BetterNetworking.cfg (INI).
"""
import os, re
from flask import current_app

def _cfg_path():
    bepinex = current_app.config['GAME']['mods']['bepinex_path']
    return os.path.join(bepinex, 'config', 'CW_Jesse.BetterNetworking.cfg')

def read_config():
    path = _cfg_path()
    if not os.path.exists(path):
        return {}, f'Fichier introuvable : {path}'
    result = {}
    current_section = None
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                m = re.match(r'^\[(.+)\]$', line)
                if m:
                    current_section = m.group(1)
                    result[current_section] = {}
                    continue
                m = re.match(r'^([^=]+)\s*=\s*(.*)$', line)
                if m and current_section:
                    key = m.group(1).strip()
                    val = m.group(2).strip()
                    result[current_section][key] = val
        return result, None
    except Exception as e:
        return {}, str(e)

def write_config(new_data):
    """
    new_data = { "Section": { "Key": "Value" } }
    Met à jour les valeurs existantes, préserve les commentaires.
    """
    path = _cfg_path()
    if not os.path.exists(path):
        return False, f'Fichier introuvable : {path}'
    try:
        with open(path) as f:
            lines = f.readlines()

        current_section = None
        output = []
        for line in lines:
            stripped = line.strip()
            m = re.match(r'^\[(.+)\]$', stripped)
            if m:
                current_section = m.group(1)
                output.append(line)
                continue
            m = re.match(r'^([^=]+)\s*=\s*(.*)$', stripped)
            if m and current_section and current_section in new_data:
                key = m.group(1).strip()
                if key in new_data[current_section]:
                    output.append(f'{key} = {new_data[current_section][key]}\n')
                    continue
            output.append(line)

        with open(path, 'w') as f:
            f.writelines(output)
        return True, None
    except Exception as e:
        return False, str(e)

def get_schema():
    """Retourne les champs éditables avec leur type et valeurs acceptables."""
    return [
        {'section': 'Dedicated Server', 'key': 'Force Crossplay',
         'label': 'Force Crossplay', 'type': 'select',
         'options': ['vanilla', 'playfab', 'steamworks']},
        {'section': 'Dedicated Server', 'key': 'Player Limit',
         'label': 'Limite joueurs', 'type': 'number'},
        {'section': 'Networking', 'key': 'Compression Enabled',
         'label': 'Compression', 'type': 'select', 'options': ['true', 'false']},
        {'section': 'Networking', 'key': 'Update Rate',
         'label': 'Fréquence màj', 'type': 'select',
         'options': ['_100', '_75', '_50']},
        {'section': 'Networking', 'key': 'Queue Size',
         'label': 'Taille file', 'type': 'select',
         'options': ['_80KB', '_64KB', '_48KB', '_32KB', '_vanilla']},
        {'section': 'Networking (Steamworks)', 'key': 'Minimum Send Rate',
         'label': 'Débit min', 'type': 'select',
         'options': ['_1024KB', '_768KB', '_512KB', '_256KB', '_150KB']},
        {'section': 'Networking (Steamworks)', 'key': 'Maximum Send Rate',
         'label': 'Débit max', 'type': 'select',
         'options': ['_1024KB', '_768KB', '_512KB', '_256KB', '_150KB']},
        {'section': 'Logging', 'key': 'Log Level',
         'label': 'Niveau log', 'type': 'select',
         'options': ['warning', 'message', 'info']},
    ]
