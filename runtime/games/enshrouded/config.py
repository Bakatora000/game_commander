"""
games/enshrouded/config.py — Lecture/écriture de enshrouded_server.json.
"""
import os, json
from flask import current_app


GAME_SETTINGS_DEFAULTS = {
    'playerHealthFactor': 1,
    'playerManaFactor': 1,
    'playerStaminaFactor': 1,
    'playerBodyHeatFactor': 1,
    'playerDivingTimeFactor': 1,
    'enableDurability': True,
    'enableStarvingDebuff': False,
    'foodBuffDurationFactor': 1,
    'fromHungerToStarving': 600000000000,
    'shroudTimeFactor': 1,
    'tombstoneMode': 'AddBackpackMaterials',
    'enableGliderTurbulences': True,
    'weatherFrequency': 'Normal',
    'fishingDifficulty': 'Normal',
    'miningDamageFactor': 1,
    'plantGrowthSpeedFactor': 1,
    'resourceDropStackAmountFactor': 1,
    'factoryProductionSpeedFactor': 1,
    'perkUpgradeRecyclingFactor': 0.5,
    'perkCostFactor': 1,
    'experienceCombatFactor': 1,
    'experienceMiningFactor': 1,
    'experienceExplorationQuestsFactor': 1,
    'randomSpawnerAmount': 'Normal',
    'aggroPoolAmount': 'Normal',
    'enemyDamageFactor': 1,
    'enemyHealthFactor': 1,
    'enemyStaminaFactor': 1,
    'enemyPerceptionRangeFactor': 1,
    'bossDamageFactor': 1,
    'bossHealthFactor': 1,
    'threatBonus': 1,
    'pacifyAllEnemies': False,
    'tamingStartleRepercussion': 'LoseSomeProgress',
    'dayTimeDuration': 1800000000000,
    'nightTimeDuration': 720000000000,
    'curseModifier': 'Normal',
}

ROOT_DEFAULTS = {
    'name': 'Enshrouded Server',
    'password': '',
    'saveDirectory': './savegame',
    'logDirectory': './logs',
    'ip': '0.0.0.0',
    'queryPort': 15637,
    'gamePort': 15636,
    'slotCount': 16,
    'voiceChatMode': 'Proximity',
    'enableVoiceChat': False,
    'enableTextChat': False,
    'gameSettingsPreset': 'Default',
}

def _cfg_path():
    install_dir = current_app.config['GAME']['server']['install_dir']
    return os.path.join(install_dir, 'enshrouded_server.json')

def read_config():
    try:
        return _normalize_for_ui(_read_raw_config()), None
    except Exception as e:
        return {}, str(e)

def write_config(new_data):
    path = _cfg_path()
    try:
        current = _read_raw_config()
        ui_data = _normalize_for_ui(current)
        ui_data.update(new_data or {})

        ok, err = _validate(ui_data)
        if not ok:
            return False, err

        password = ui_data.pop('password', '')
        current = _normalize_for_file(ui_data, password, current)

        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            json.dump(current, f, indent=2)
        return True, None
    except Exception as e:
        return False, str(e)

def _default_config():
    data = dict(ROOT_DEFAULTS)
    data['gameSettings'] = dict(GAME_SETTINGS_DEFAULTS)
    data['tags'] = []
    data['userGroups'] = []
    data['bannedAccounts'] = []
    return data


def _read_raw_config():
    path = _cfg_path()
    if not os.path.exists(path):
        return _default_config()
    with open(path) as f:
        data = json.load(f)
    merged = _default_config()
    merged.update(data)
    merged['gameSettings'] = dict(GAME_SETTINGS_DEFAULTS) | dict(data.get('gameSettings') or {})
    return merged

def _extract_password(data):
    if data.get('password'):
        return data['password']
    groups = data.get('userGroups')
    if isinstance(groups, list):
        for group in groups:
            if group.get('name', '').lower() == 'default' and group.get('password'):
                return group['password']
        if groups:
            return groups[0].get('password', '')
    return ''

def _normalize_for_ui(data):
    current = dict(data)
    current['password'] = _extract_password(current)
    if 'queryPort' in current:
        current['gamePort'] = int(current['queryPort']) - 1
    game_settings = dict(GAME_SETTINGS_DEFAULTS)
    game_settings.update(current.get('gameSettings') or {})
    current.update(game_settings)
    return current

def _normalize_for_file(data, password, existing=None):
    current = dict(existing or {})
    current.update({k: data[k] for k in ROOT_DEFAULTS if k in data and k != 'password'})

    # queryPort est la source de vérité dans les versions récentes d'Enshrouded.
    if 'gamePort' in data and 'queryPort' not in data:
        current['queryPort'] = int(data['gamePort']) + 1
    elif 'queryPort' in current:
        current['gamePort'] = int(current['queryPort']) - 1

    game_settings = dict(GAME_SETTINGS_DEFAULTS)
    game_settings.update(current.get('gameSettings') or {})
    for key in GAME_SETTINGS_DEFAULTS:
        if key in data:
            game_settings[key] = data[key]
    current['gameSettings'] = game_settings

    groups = current.get('userGroups')
    if not isinstance(groups, list) or not groups:
        groups = [{
            'name': 'Default',
            'password': '',
            'canKickBan': False,
            'canAccessInventories': True,
            'canEditWorld': True,
            'canEditBase': True,
            'canExtendBase': True,
            'reservedSlots': 0,
        }]
    groups[0]['password'] = password
    current['userGroups'] = groups
    current.setdefault('tags', [])
    current.setdefault('voiceChatMode', 'Proximity')
    current.setdefault('enableVoiceChat', False)
    current.setdefault('enableTextChat', False)
    current.setdefault('gameSettingsPreset', 'Default')
    current.setdefault('bannedAccounts', [])
    current.pop('gamePort', None)
    return current


def _validate(data):
    int_ranges = {
        'slotCount': (1, 16),
        'queryPort': (1, 65535),
        'gamePort': (1, 65535),
        'fromHungerToStarving': (300000000000, 1200000000000),
        'dayTimeDuration': (120000000000, 3600000000000),
        'nightTimeDuration': (120000000000, 3600000000000),
    }
    float_ranges = {
        'playerHealthFactor': (0.25, 4),
        'playerManaFactor': (0.25, 4),
        'playerStaminaFactor': (0.25, 4),
        'playerBodyHeatFactor': (0.5, 2),
        'playerDivingTimeFactor': (0.5, 2),
        'foodBuffDurationFactor': (0.5, 2),
        'shroudTimeFactor': (0.5, 2),
        'miningDamageFactor': (0.5, 2),
        'plantGrowthSpeedFactor': (0.25, 2),
        'resourceDropStackAmountFactor': (0.25, 2),
        'factoryProductionSpeedFactor': (0.25, 2),
        'perkUpgradeRecyclingFactor': (0, 1),
        'perkCostFactor': (0.25, 2),
        'experienceCombatFactor': (0.25, 2),
        'experienceMiningFactor': (0, 2),
        'experienceExplorationQuestsFactor': (0.25, 2),
        'enemyDamageFactor': (0.25, 5),
        'enemyHealthFactor': (0.25, 4),
        'enemyStaminaFactor': (0.5, 2),
        'enemyPerceptionRangeFactor': (0.5, 2),
        'bossDamageFactor': (0.2, 5),
        'bossHealthFactor': (0.2, 5),
        'threatBonus': (0.25, 4),
    }
    enums = {
        'gameSettingsPreset': {'Default', 'Relaxed', 'Hard', 'Survival', 'Custom'},
        'tombstoneMode': {'AddBackpackMaterials', 'Everything', 'NoTombstone'},
        'weatherFrequency': {'Disabled', 'Rare', 'Normal', 'Often'},
        'fishingDifficulty': {'VeryEasy', 'Easy', 'Normal', 'Hard', 'VeryHard'},
        'randomSpawnerAmount': {'Few', 'Normal', 'Many', 'Extreme'},
        'aggroPoolAmount': {'Few', 'Normal', 'Many', 'Extreme'},
        'tamingStartleRepercussion': {'KeepProgress', 'LoseSomeProgress', 'LoseAllProgress'},
        'curseModifier': {'Easy', 'Normal', 'Hard'},
    }
    bool_keys = {
        'enableDurability',
        'enableStarvingDebuff',
        'enableGliderTurbulences',
        'pacifyAllEnemies',
        'enableVoiceChat',
        'enableTextChat',
    }
    if not str(data.get('name', '')).strip():
        return False, 'name requis'
    for key, (min_v, max_v) in int_ranges.items():
        try:
            value = int(data.get(key, 0))
        except (TypeError, ValueError):
            return False, f'{key} doit être un entier'
        if not (min_v <= value <= max_v):
            return False, f'{key} doit être entre {min_v} et {max_v}'
    for key, (min_v, max_v) in float_ranges.items():
        try:
            value = float(data.get(key, 0))
        except (TypeError, ValueError):
            return False, f'{key} doit être numérique'
        if not (min_v <= value <= max_v):
            return False, f'{key} doit être entre {min_v} et {max_v}'
    for key, allowed in enums.items():
        if data.get(key) not in allowed:
            return False, f'{key} invalide'
    for key in bool_keys:
        if not isinstance(data.get(key), bool):
            return False, f'{key} doit être booléen'
    return True, None

def get_schema():
    return [
        {'key': 'name',          'label': 'Nom du serveur',  'type': 'text'},
        {'key': 'password',      'label': 'Mot de passe',    'type': 'password'},
        {'key': 'slotCount',     'label': 'Joueurs max',     'type': 'number', 'min': 1, 'max': 16},
        {'key': 'gamePort',      'label': 'Port de jeu',     'type': 'number'},
        {'key': 'queryPort',     'label': 'Port de requête', 'type': 'number'},
        {'key': 'saveDirectory', 'label': 'Dossier saves',   'type': 'text'},
    ]
