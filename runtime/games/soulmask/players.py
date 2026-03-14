"""
games/soulmask/players.py — Joueurs connectés via parsing journalctl.

Patterns suivis :
  Connexion prête : "player ready. Addr:..., Netuid:..., Name:<name>"
  Join réussi      : "Join succeeded: <name>"
  Déconnexion      : "CloseBunch ... Name=<name>"
"""
import re
import subprocess


_RE_READY = re.compile(r'player ready\..*?Name:([^\s,]+)')
_RE_JOIN = re.compile(r'Join succeeded:\s*([^\s,]+)')
_RE_LOGIN = re.compile(r'Login request: .*?\?Name=([^?\\s]+)')
_RE_CLOSE = re.compile(r'CloseBunch.*Name=([^\s,]+)')
_RE_GENERIC_CLOSE = re.compile(r'Bunch\.bClose == true.*ConditionalCleanUp')
_RE_LEAVE_WORLD = re.compile(r'player leave world\.')


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

    for line in lines:
        ready = _RE_READY.search(line)
        if ready:
            name = ready.group(1).strip()
            if name and name not in connected:
                connected.append(name)
            continue

        joined = _RE_JOIN.search(line)
        if joined:
            name = joined.group(1).strip()
            if name and name not in connected:
                connected.append(name)
            continue

        login = _RE_LOGIN.search(line)
        if login:
            name = login.group(1).strip()
            if name and name not in connected:
                connected.append(name)
            continue

        closed = _RE_CLOSE.search(line)
        if closed:
            name = closed.group(1).strip()
            if name in connected:
                connected.remove(name)
            continue

        if _RE_LEAVE_WORLD.search(line) and len(connected) == 1:
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
