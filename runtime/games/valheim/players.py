"""
games/valheim/players.py — Suivi des joueurs connectés via parsing journalctl.

Patterns Valheim (PlayFab/BepInEx) :
  Connexion (nom dispo) : "Got character ZDOID from NAME : ZDOID"
  Connexion (SteamID) : "Got connection SteamID 7656..."
  Connexion (PlayFab) : "local Platform ID Steam_7656..."
  Déconnexion (avec BetterNetworking) : "Compression: NAME[Steam_ID] disconnected"
  Déconnexion (avec BetterNetworking, sans nom) : "Compression: [Steam_ID] disconnected"
  Déconnexion (compteur fallback) : "Player connection lost ... now 0 player(s)"
"""
import re
import subprocess
from collections import deque
from flask import current_app


def _service():
    return current_app.config['GAME']['server']['service']


def _systemctl_value(service, prop):
    try:
        r = subprocess.run(
            ['systemctl', 'show', service, '--property', prop, '--value'],
            capture_output=True, text=True, timeout=5
        )
        return (r.stdout or '').strip()
    except Exception:
        return ''


def _journal_since_start(service):
    """Retourne les lignes de journal pour l'invocation systemd courante du service."""
    try:
        invocation_id = _systemctl_value(service, 'InvocationID')
        args = ['journalctl', '-u', service, '--no-pager', '-o', 'short-iso']
        if invocation_id:
            args.append(f'_SYSTEMD_INVOCATION_ID={invocation_id}')
        else:
            main_pid = _systemctl_value(service, 'MainPID')
            if main_pid and main_pid != '0':
                args.append(f'_PID={main_pid}')
            else:
                args.extend(['--since', '1 hour ago'])
        r = subprocess.run(args, capture_output=True, text=True, timeout=5)
        return r.stdout.splitlines()
    except Exception:
        return []


# Patterns
_RE_ZDOID    = re.compile(r'Got character ZDOID from (.+?) :')
_RE_STEAMID  = re.compile(r'Got connection SteamID (\d+)')
_RE_PLATFORM = re.compile(r'local Platform ID Steam_(\d+)')
_RE_BN_DISC  = re.compile(r'\[Message:Better Networking\].*?Compression: (.+?)\[(?:Steam_)?\d')
_RE_BN_ID    = re.compile(r'\[Message:Better Networking\].*?Compression: \[(?:Steam_)?(\d+)\] disconnected')
_RE_COUNT    = re.compile(r'now (\d+) player\(s\)')


def get_players():
    """
    Retourne la liste des joueurs actuellement connectés.
    Chaque entrée : {'name': str, 'steamid': str|None}
    """
    service = _service()
    lines = _journal_since_start(service)

    connected = []   # liste ordonnée de dicts
    count_check = 0  # dernier compteur "now X player(s)"
    pending_ids = deque()
    pending_names = deque()

    def add_player(name, steamid=None):
        for entry in connected:
            if steamid and entry.get('steamid') == steamid:
                entry['name'] = name
                return
            if entry['name'] == name:
                if steamid and not entry.get('steamid'):
                    entry['steamid'] = steamid
                return
        connected.append({'name': name, 'steamid': steamid})
        if not steamid:
            pending_names.append(name)

    def attach_oldest_pending_name(steamid):
        while pending_names:
            name = pending_names.popleft()
            for entry in connected:
                if entry['name'] == name and not entry.get('steamid'):
                    entry['steamid'] = steamid
                    return True
        return False

    def remove_by_name(name):
        for i, entry in enumerate(connected):
            if entry['name'] == name:
                connected.pop(i)
                return

    def remove_by_steamid(steamid):
        for i, entry in enumerate(connected):
            if entry.get('steamid') == steamid:
                connected.pop(i)
                return

    for line in lines:
        # Nouveau démarrage du service → reset
        if 'Game server connected' in line and not connected:
            pass  # déjà vide

        m = _RE_STEAMID.search(line)
        if m:
            steamid = m.group(1).strip()
            if not attach_oldest_pending_name(steamid):
                pending_ids.append(steamid)
            continue

        m = _RE_PLATFORM.search(line)
        if m:
            steamid = m.group(1).strip()
            if not attach_oldest_pending_name(steamid):
                pending_ids.append(steamid)
            continue

        # Connexion : nom du personnage connu
        m = _RE_ZDOID.search(line)
        if m:
            name = m.group(1).strip()
            steamid = pending_ids.popleft() if pending_ids else None
            add_player(name, steamid)
            continue

        # Déconnexion propre (BetterNetworking, a le nom)
        m = _RE_BN_DISC.search(line)
        if m:
            name = m.group(1).strip()
            remove_by_name(name)
            continue

        m = _RE_BN_ID.search(line)
        if m:
            remove_by_steamid(m.group(1).strip())
            continue

        # Compteur de joueurs (fallback)
        m = _RE_COUNT.search(line)
        if m:
            count_check = int(m.group(1))
            if count_check == 0:
                connected.clear()

    return connected
