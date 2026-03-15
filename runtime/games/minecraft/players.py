"""
games/minecraft/players.py — Joueurs connectés via parsing journalctl.

Patterns suivis :
  Connexion  : "<name> joined the game"
  Déconnexion: "<name> left the game" ou "<name> lost connection: ..."

On reconstruit l'état courant depuis les logs récents du service.
"""
import re
import subprocess
import psutil


_RE_JOIN = re.compile(r': ([^:[]+?) joined the game$')
_RE_LOST = re.compile(r': ([^:[]+?) lost connection: .+$')
_RE_LEFT = re.compile(r': ([^:[]+?) left the game$')


def get_players():
    try:
        cmd = ['journalctl', '-u', _service_name(), '--no-pager', '-o', 'cat']
        since_arg = _current_session_since()
        if since_arg:
            cmd.extend(['--since', since_arg])
        else:
            cmd.extend(['--since', '1 hour ago'])
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        lines = result.stdout.splitlines()
    except Exception:
        return []

    connected = []

    for line in lines:
        joined = _RE_JOIN.search(line)
        if joined:
            name = joined.group(1).strip()
            if name and name not in connected:
                connected.append(name)
            continue

        lost = _RE_LOST.search(line)
        if lost:
            name = lost.group(1).strip()
            if name in connected:
                connected.remove(name)
            continue

        left = _RE_LEFT.search(line)
        if left:
            name = left.group(1).strip()
            if name in connected:
                connected.remove(name)

    return [{'name': name} for name in connected]


def _service_name():
    try:
        from flask import current_app
        return current_app.config['GAME']['server']['service']
    except Exception:
        return 'minecraft-server'


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
