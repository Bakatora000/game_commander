"""
games/soulmask/players.py — Joueurs connectés via parsing journalctl.

Patterns suivis :
  Connexion prête : "player ready. Addr:..., Netuid:..., Name:<name>"
  Join réussi      : "Join succeeded: <name>"
  Déconnexion      : "CloseBunch ... Name=<name>"
"""
import re
import subprocess


_RE_READY = re.compile(r'player ready\..*?Netuid:(\d+), Name:([^\s,]+)')
_RE_FIRST_LOGIN = re.compile(r'FirstLoginGame: Addr:[^,]+, Netuid:(\d+), Name:([^\s,]+)')
_RE_AUTH = re.compile(r'AUTH HANDLER: Sending auth result to user (\d+) with flag success\?\s*1')
_RE_JOIN = re.compile(r'Join succeeded:\s*([^\s,]+)')
_RE_CLOSE = re.compile(r'CloseBunch.*Name=([^\s,]+)')
_RE_GENERIC_CLOSE = re.compile(r'Bunch\.bClose == true.*ConditionalCleanUp')
_RE_LEAVE_WORLD = re.compile(r'player leave world\.\s*(\d+)')


def get_players():
    try:
        result = subprocess.run(
            ['journalctl', '-u', _service_name(), '--since', '2 hours ago',
             '--no-pager', '-o', 'cat'],
            capture_output=True, text=True, timeout=5
        )
        lines = result.stdout.splitlines()
    except Exception:
        return []

    connected = []
    steam_to_name = {}

    def add_player(name, steamid=None):
        if steamid:
            old_name = steam_to_name.get(steamid)
            if old_name and old_name != name:
                remove_player_by_name(old_name)
            steam_to_name[steamid] = name
        if name and name not in connected:
            connected.append(name)

    def remove_player_by_name(name):
        if name in connected:
            connected.remove(name)

    def remove_player_by_steamid(steamid):
        name = steam_to_name.pop(steamid, None)
        if name:
            remove_player_by_name(name)

    for line in lines:
        auth = _RE_AUTH.search(line)
        if auth:
            steamid = auth.group(1).strip()
            add_player(f"Steam:{steamid}", steamid)
            continue

        first_login = _RE_FIRST_LOGIN.search(line)
        if first_login:
            add_player(first_login.group(2).strip(), first_login.group(1).strip())
            continue

        ready = _RE_READY.search(line)
        if ready:
            add_player(ready.group(2).strip(), ready.group(1).strip())
            continue

        joined = _RE_JOIN.search(line)
        if joined:
            add_player(joined.group(1).strip())
            continue

        closed = _RE_CLOSE.search(line)
        if closed:
            remove_player_by_name(closed.group(1).strip())
            continue

        leave = _RE_LEAVE_WORLD.search(line)
        if leave:
            remove_player_by_steamid(leave.group(1).strip())
            if len(connected) == 1 and not steam_to_name:
                connected.clear()
            continue

        # Soulmask logue parfois une fermeture générique sans pseudo.
        # Si un seul joueur est connecté, on peut le retirer de façon fiable.
        if _RE_GENERIC_CLOSE.search(line) and len(connected) == 1:
            connected.clear()

    return [{'name': name} for name in connected]


def _service_name():
    try:
        from flask import current_app
        return current_app.config['GAME']['server']['service']
    except Exception:
        return 'soulmask-server'
