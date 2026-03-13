"""
games/minecraft/players.py — Joueurs connectés via parsing journalctl.

Patterns suivis :
  Connexion  : "<name> joined the game"
  Déconnexion: "<name> left the game"

On reconstruit l'état courant depuis les logs récents du service.
"""
import re
import subprocess


_RE_JOIN = re.compile(r'] \[Server thread/INFO\]: ([^[]+?) joined the game$')
_RE_LEFT = re.compile(r'] \[Server thread/INFO\]: ([^[]+?) left the game$')


def get_players():
    try:
        result = subprocess.run(
            ['journalctl', '-u', _service_name(), '--since', '1 hour ago',
             '--no-pager', '-o', 'cat'],
            capture_output=True, text=True, timeout=5
        )
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
