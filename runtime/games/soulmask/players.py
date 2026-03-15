"""
games/soulmask/players.py — Joueurs connectés via parsing journalctl.

Patterns suivis :
  Connexion prête : "player ready. Addr:..., Netuid:..., Name:<name>"
  Join réussi      : "Join succeeded: <name>"
  Déconnexion      : "CloseBunch ... Name=<name>"
"""
import re
import subprocess
import time

import psutil


_RE_READY = re.compile(r'player ready\..*?Netuid:(\d+), Name:([^\s,]+)')
_RE_FIRST_LOGIN = re.compile(r'FirstLoginGame: Addr:[^,]+, Netuid:(\d+), Name:([^\s,]+)')
_RE_JOIN = re.compile(r'Join succeeded:\s*([^\s,]+)')
_RE_CLOSE = re.compile(r'CloseBunch.*Name=([^\s,]+)')
_RE_GENERIC_CLOSE = re.compile(r'Bunch\.bClose == true.*ConditionalCleanUp')
_RE_LEAVE_WORLD = re.compile(r'player leave world\.\s*(\d+)')


def get_players():
    try:
        cmd = ['journalctl', '-u', _service_name(), '--no-pager', '-o', 'cat']
        since_arg = _current_session_since()
        if since_arg:
            cmd.extend(['--since', since_arg])
        else:
            cmd.extend(['--since', '2 hours ago'])
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
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


def _current_session_since():
    try:
        result = subprocess.run(
            ['systemctl', 'show', _service_name(), '--property=MainPID'],
            capture_output=True, text=True, timeout=3
        )
        pid = 0
        for line in result.stdout.splitlines():
            if line.startswith('MainPID='):
                pid = int(line.split('=', 1)[1].strip() or '0')
                break
        if pid <= 0:
            return None
        started = psutil.Process(pid).create_time()
        return f"@{max(int(started) - 5, 0)}"
    except Exception:
        return None
