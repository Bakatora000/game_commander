"""
core/metrics.py — Logging et lecture des métriques serveur (CPU/RAM/joueurs).
Fichier append-only JSON Lines. Purge automatique après 2h.
"""
import os, json, time, threading
from datetime import datetime, timezone, timedelta

_log_file = None
_lock     = threading.Lock()

def init(log_path):
    global _log_file
    _log_file = log_path
    # Créer le fichier s'il n'existe pas
    if not os.path.exists(log_path):
        try:
            open(log_path, 'a').close()
        except Exception as e:
            print(f'[WARN] metrics: impossible de créer {log_path}: {e}')

def metrics_append(cpu, ram, players):
    if not _log_file:
        return
    entry = {
        'ts':      datetime.now(timezone.utc).isoformat(),
        'cpu':     cpu,
        'ram':     ram,
        'players': players,
    }
    with _lock:
        with open(_log_file, 'a') as f:
            f.write(json.dumps(entry) + '\n')

def _metrics_purge():
    if not _log_file or not os.path.exists(_log_file):
        return
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    kept   = []
    with _lock:
        with open(_log_file) as f:
            for line in f:
                try:
                    e = json.loads(line)
                    if e['ts'] >= cutoff:
                        kept.append(line)
                except Exception:
                    pass
        with open(_log_file, 'w') as f:
            f.writelines(kept)

def metrics_read(minutes=60):
    if not _log_file or not os.path.exists(_log_file):
        return []
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
    result = []
    with _lock:
        with open(_log_file) as f:
            for line in f:
                try:
                    e = json.loads(line)
                    if e['ts'] >= cutoff:
                        result.append(e)
                except Exception:
                    pass
    return result

def start_poller(get_status_fn, interval=30):
    """Démarre le thread de polling en arrière-plan (défaut : 30s)."""
    _purge_counter = [0]

    def _loop():
        while True:
            try:
                status = get_status_fn()
                state  = status.get('state', 0)
                if state == 20:
                    m       = status.get('metrics', {})
                    cpu     = m.get('cpu',     {}).get('value', 0)
                    ram     = m.get('ram',     {}).get('value', 0)
                    players = m.get('players', {}).get('value', 0)
                else:
                    # Serveur arrêté ou en transition : enregistrer des zéros
                    # pour visualiser les périodes de downtime dans le graphe
                    cpu, ram, players = 0, 0, 0
                metrics_append(cpu, ram, players)
                # Purge toutes les ~30 minutes
                _purge_counter[0] += 1
                if _purge_counter[0] >= (1800 // interval):
                    _metrics_purge()
                    _purge_counter[0] = 0
            except Exception:
                pass
            time.sleep(interval)

    t = threading.Thread(target=_loop, daemon=True)
    t.start()
