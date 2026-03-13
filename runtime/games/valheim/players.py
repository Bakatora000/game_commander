"""
games/valheim/players.py — Suivi des joueurs connectés via parsing journalctl.

Patterns Valheim (PlayFab/BepInEx) :
  Connexion (nom dispo) : "Got character ZDOID from NAME : ZDOID"
  Déconnexion (avec BetterNetworking) : "Compression: NAME[Steam_ID] disconnected"
  Déconnexion (compteur fallback) : "Player connection lost ... now 0 player(s)"
"""
import re
import subprocess
from flask import current_app


def _service():
    return current_app.config['GAME']['server']['service']


def _journal_since_start(service):
    """Retourne les lignes de journal depuis le dernier démarrage du service."""
    try:
        r = subprocess.run(
            ['journalctl', '-u', service, '--no-pager', '-o', 'short-iso',
             '--since', '1 hour ago'],
            capture_output=True, text=True, timeout=5
        )
        return r.stdout.splitlines()
    except Exception:
        return []


# Patterns
_RE_ZDOID    = re.compile(r'Got character ZDOID from (.+?) :')
_RE_BN_DISC  = re.compile(r'\[Message:Better Networking\].*?Compression: (.+?)\[(?:Steam_)?\d')
_RE_COUNT    = re.compile(r'now (\d+) player\(s\)')


def get_players():
    """
    Retourne la liste des joueurs actuellement connectés.
    Chaque entrée : {'name': str}
    """
    service = _service()
    lines = _journal_since_start(service)

    connected = []   # liste ordonnée de noms
    count_check = 0  # dernier compteur "now X player(s)"

    for line in lines:
        # Nouveau démarrage du service → reset
        if 'Game server connected' in line and not connected:
            pass  # déjà vide

        # Connexion : nom du personnage connu
        m = _RE_ZDOID.search(line)
        if m:
            name = m.group(1).strip()
            if name not in connected:
                connected.append(name)
            continue

        # Déconnexion propre (BetterNetworking, a le nom)
        m = _RE_BN_DISC.search(line)
        if m:
            name = m.group(1).strip()
            if name in connected:
                connected.remove(name)
            continue

        # Compteur de joueurs (fallback)
        m = _RE_COUNT.search(line)
        if m:
            count_check = int(m.group(1))
            if count_check == 0:
                connected.clear()

    return [{'name': n} for n in connected]
