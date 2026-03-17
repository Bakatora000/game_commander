"""
games/valheim/valheimplus.py — Lecture/écriture de la config ValheimPlus (INI).
"""
import os
import re
from flask import current_app


def _config_dir():
    bepinex = current_app.config['GAME']['mods']['bepinex_path']
    return os.path.join(bepinex, 'config')


def _plugins_dir():
    bepinex = current_app.config['GAME']['mods']['bepinex_path']
    return os.path.join(bepinex, 'plugins')


def _plugin_present():
    plugins_dir = _plugins_dir()
    if not os.path.isdir(plugins_dir):
        return False
    candidates = [
        os.path.join(plugins_dir, 'ValheimPlus.dll'),
        os.path.join(plugins_dir, 'ValheimPlus', 'ValheimPlus.dll'),
    ]
    return any(os.path.exists(path) for path in candidates)


def _cfg_path():
    config_dir = _config_dir()
    candidates = [
        os.path.join(config_dir, 'valheim_plus.cfg'),
        os.path.join(config_dir, 'ValheimPlus.cfg'),
        os.path.join(config_dir, 'ValheimPlus.cfg'.lower()),
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    if os.path.isdir(config_dir):
        matches = sorted(
            os.path.join(config_dir, name)
            for name in os.listdir(config_dir)
            if name.lower().endswith('.cfg') and 'valheim' in name.lower() and 'plus' in name.lower()
        )
        if matches:
            return matches[0]
    return ''


def _field_type(value: str):
    lower = value.strip().lower()
    if lower in ('true', 'false'):
        return 'select', ['true', 'false']
    if lower in ('on', 'off'):
        return 'select', ['on', 'off']
    return 'text', None


def read_config():
    if not _plugin_present():
        return {}, 'Plugin ValheimPlus introuvable'
    path = _cfg_path()
    if not path:
        return {}, 'Fichier ValheimPlus introuvable'
    sections = []
    current_section = None
    current_fields = None
    try:
        with open(path, encoding='utf-8', errors='ignore') as f:
            for line in f:
                stripped = line.strip()
                if not stripped or stripped.startswith('#') or stripped.startswith(';'):
                    continue
                m = re.match(r'^\[(.+)\]$', stripped)
                if m:
                    current_section = m.group(1)
                    current_fields = []
                    sections.append({'name': current_section, 'fields': current_fields})
                    continue
                m = re.match(r'^([^=]+?)\s*=\s*(.*)$', stripped)
                if m and current_section and current_fields is not None:
                    key = m.group(1).strip()
                    value = m.group(2).strip()
                    field_type, options = _field_type(value)
                    current_fields.append({
                        'key': key,
                        'value': value,
                        'type': field_type,
                        'options': options,
                    })
        return {'path': path, 'sections': sections}, None
    except Exception as e:
        return {}, str(e)


def write_config(new_data):
    if not _plugin_present():
        return False, 'Plugin ValheimPlus introuvable'
    path = _cfg_path()
    if not path:
        return False, 'Fichier ValheimPlus introuvable'
    if not isinstance(new_data, dict):
        return False, 'Payload invalide'
    try:
        with open(path, encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()

        output = []
        current_section = None
        for line in lines:
            stripped = line.strip()
            m = re.match(r'^\[(.+)\]$', stripped)
            if m:
                current_section = m.group(1)
                output.append(line)
                continue
            m = re.match(r'^([^=]+?)\s*=\s*(.*)$', stripped)
            if m and current_section and current_section in new_data:
                key = m.group(1).strip()
                if key in new_data[current_section]:
                    output.append(f'{key} = {new_data[current_section][key]}\n')
                    continue
            output.append(line)

        with open(path, 'w', encoding='utf-8') as f:
            f.writelines(output)
        return True, None
    except Exception as e:
        return False, str(e)
