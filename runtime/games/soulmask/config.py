"""
games/soulmask/config.py — Lecture/écriture de soulmask_server.json.
"""
import json
import os
from flask import current_app


def _cfg_path():
    install_dir = current_app.config['GAME']['server']['install_dir']
    return os.path.join(install_dir, 'soulmask_server.json')


def _defaults():
    install_dir = current_app.config['GAME']['server']['install_dir']
    saved_dir = os.path.join(install_dir, 'WS', 'Saved')
    return {
        'server_name': current_app.config['GAME']['name'],
        'max_players': current_app.config['GAME']['server'].get('max_players', 50),
        'password': '',
        'admin_password': '',
        'mode': 'pve',
        'port': current_app.config['GAME']['server'].get('port', 8777),
        'query_port': 27015,
        'echo_port': 18888,
        'backup_enabled': True,
        'saving_enabled': True,
        'backup_interval': 7200,
        'log_dir': os.path.join(saved_dir, 'Logs'),
        'saved_dir': saved_dir,
    }


def read_config():
    path = _cfg_path()
    data = _defaults()
    if os.path.exists(path):
        try:
            data.update(json.loads(open(path, encoding='utf-8').read()))
        except Exception as e:
            return {}, str(e)
    return data, None


def write_config(new_data):
    path = _cfg_path()
    try:
        current, err = read_config()
        if err:
            return False, err
        current.update(new_data or {})
        ok, err = _validate(current)
        if not ok:
            return False, err
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(current, f, indent=2)
            f.write('\n')
        return True, None
    except Exception as e:
        return False, str(e)


def _validate(data):
    ints = {
        'port': (1, 65535),
        'query_port': (1, 65535),
        'echo_port': (1, 65535),
        'max_players': (1, 100),
        'backup_interval': (60, 86400),
    }
    for key, (min_v, max_v) in ints.items():
        try:
            value = int(data.get(key, 0))
        except ValueError:
            return False, f'{key} doit être un entier'
        if not (min_v <= value <= max_v):
            return False, f'{key} doit être entre {min_v} et {max_v}'
    if data.get('mode') not in {'pve', 'pvp'}:
        return False, 'mode invalide'
    if not data.get('server_name', '').strip():
        return False, 'server_name requis'
    return True, None
