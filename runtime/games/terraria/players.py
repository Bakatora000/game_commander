"""
games/terraria/players.py — Joueurs connectés via journalctl.

Patterns observés :
  Connexion  : <name> has joined.
  Déconnexion: <name> has left.
"""
from __future__ import annotations

import re
import subprocess

import psutil


_RE_CONNECT = re.compile(r'^\s*([0-9a-fA-F:.]+):\d+\s+is connecting\.\.\.\s*$')
_RE_JOIN = re.compile(r'^\s*(.+?) has joined\.\s*$')
_RE_LEFT = re.compile(r'^\s*(.+?) has left\.\s*$')


def _service_name():
    try:
        from flask import current_app
        return current_app.config['GAME']['server']['service']
    except Exception:
        return 'terraria-server'


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


def _journalctl_cmd():
    cmd = ['journalctl', '-u', _service_name(), '--no-pager', '-o', 'cat']
    since_arg = _current_session_since()
    if since_arg:
        cmd.extend(['--since', since_arg])
    else:
        cmd.extend(['--since', '1 hour ago'])
    return cmd


def get_players():
    try:
        result = subprocess.run(
            _journalctl_cmd(),
            capture_output=True, text=True, timeout=5
        )
        lines = result.stdout.splitlines()
    except Exception:
        return []

    players = {}
    pending_ip = None
    for line in lines:
        m = _RE_CONNECT.search(line)
        if m:
            pending_ip = m.group(1).strip()
            continue

        m = _RE_JOIN.search(line)
        if m:
            name = m.group(1).strip()
            if name:
                players[name] = pending_ip or players.get(name, {}).get('ip', '')
            pending_ip = None
            continue

        m = _RE_LEFT.search(line)
        if m:
            name = m.group(1).strip()
            players.pop(name, None)
            pending_ip = None
            continue

    return [{'name': name, 'ip': ip} for name, ip in players.items()]
