"""
games/enshrouded/players.py — Joueurs connectés via journalctl.

Enshrouded ne logue pas les noms de joueurs, uniquement les steamids.
On maintient une table peer_id → steamid pour résoudre les déconnexions.

Patterns :
  Connexion  : [online] Added peer #X (steamid:XXXXXXXXXXXXXXX)
  Déconnexion: [online] Removed peer #X
  Serveur OK : [Session] 'HostOnline' (up)!
"""
import re
import subprocess

import psutil

_RE_ADDED   = re.compile(r'\[online\] Added peer #(\d+) \(steamid:(\d+)\)')
_RE_REMOVED = re.compile(r'\[online\] Removed peer #(\d+)')
_RE_FAILED  = re.compile(r'\[online\] Session failed for peer #(\d+)')


def get_players():
    """
    Retourne la liste des joueurs connectés : [{'name': steamid}]
    Utilise journalctl sur la dernière heure.
    """
    try:
        result = subprocess.run(
            _journalctl_cmd(),
            capture_output=True, text=True, timeout=5
        )
        lines = result.stdout.splitlines()
    except Exception:
        return []

    peers = {}  # peer_id (str) → steamid (str)

    for line in lines:
        # Connexion → ajouter le peer
        m = _RE_ADDED.search(line)
        if m:
            peers[m.group(1)] = m.group(2)
            continue

        # Déconnexion → retirer le peer
        m = _RE_REMOVED.search(line)
        if m:
            peers.pop(m.group(1), None)
            continue

        # Échec de session → retirer aussi (le joueur n'a pas rejoint)
        m = _RE_FAILED.search(line)
        if m:
            peers.pop(m.group(1), None)
            continue

    return [{'name': steamid} for steamid in peers.values()]


def _journalctl_cmd():
    cmd = ['journalctl', '-u', _service_name(), '--no-pager', '-o', 'cat']
    since_arg = _current_session_since()
    if since_arg:
        cmd.extend(['--since', since_arg])
    else:
        cmd.extend(['--since', '1 hour ago'])
    return cmd


def _service_name():
    """Récupère le nom du service systemd depuis la config Flask."""
    try:
        from flask import current_app
        return current_app.config['GAME']['server']['service']
    except Exception:
        return 'enshrouded-server'


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
