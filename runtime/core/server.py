"""
core/server.py — Contrôle du serveur via psutil + systemd.
Le binaire et le service sont lus depuis game.json.
"""
import json
import os
import re
import subprocess, time
import importlib
import sys
from pathlib import Path
import psutil
from flask import current_app


def _game():
    return current_app.config['GAME']

def _app_dir() -> Path:
    return Path(current_app.root_path)

def _server_dir() -> Path:
    return Path(_game()["server"]["install_dir"])

def _deploy_cfg_path() -> Path:
    candidates = [
        _app_dir() / "deploy_config.env",
        _server_dir().parent / "deploy_config.env",
    ]
    for path in candidates:
        if path.is_file():
            return path
    return candidates[0]

def _deploy_cfg_value(key: str, default: str = "") -> str:
    path = _deploy_cfg_path()
    if not path.is_file():
        return default
    pattern = re.compile(rf'^{re.escape(key)}="?(.*?)"?$')
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        m = pattern.match(line.strip())
        if m:
            return m.group(1)
    return default

def _instance_id() -> str:
    return _deploy_cfg_value("INSTANCE_ID").strip()

def _source_root() -> str:
    return _deploy_cfg_value("SRC_DIR").strip()

def _discordnotify_module():
    try:
        return importlib.import_module("shared.discordnotify")
    except Exception:
        pass
    src_dir = _source_root()
    if src_dir and src_dir not in sys.path:
        sys.path.insert(0, src_dir)
    try:
        return importlib.import_module("shared.discordnotify")
    except Exception:
        return None

def _notify_action(event: str, ok: bool, details: str = "") -> None:
    discordnotify = _discordnotify_module()
    if not discordnotify:
        return
    try:
        discordnotify.notify_event(
            event=event,
            ok=ok,
            instance_id=_instance_id(),
            game_id=_game().get("id", ""),
            service=_game().get("server", {}).get("service", ""),
            details=(details or "").strip(),
        )
    except Exception:
        pass

def _cpu_monitor_state_path() -> Path:
    return Path(os.environ.get("GAME_COMMANDER_CPU_MONITOR_STATE", "/var/lib/game-commander/cpu-monitor.json"))

def _read_cpu_monitor_state() -> dict:
    path = _cpu_monitor_state_path()
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}

def _get_process():
    """
    Trouve le process du serveur de jeu par nom de binaire ET par port.
    Pour les jeux sous Wine (Enshrouded), le binaire .exe tourne dans le
    process tree de wine/xvfb — fallback via MainPID du service systemd.
    """
    game   = _game()
    binary = game['server']['binary']
    port   = str(game['server'].get('port', ''))

    # 1er essai : recherche directe par nom de binaire + port dans cmdline
    for p in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            name = p.info['name'] or ''
            cmd  = ' '.join(p.info['cmdline'] or [])
            if binary in name or binary in cmd:
                if not port or port in cmd:
                    return p
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    # 2e essai : via MainPID du service systemd (Wine, Enshrouded, etc.)
    service = game['server']['service']
    try:
        r = subprocess.run(
            ['systemctl', 'show', service, '--property=MainPID'],
            capture_output=True, text=True, timeout=3
        )
        for line in r.stdout.splitlines():
            if line.startswith('MainPID='):
                pid = int(line.split('=')[1].strip())
                if pid > 0:
                    return psutil.Process(pid)
    except Exception:
        pass

    return None

def _player_count():
    """Retourne le nombre de joueurs connectés si le module players est disponible."""
    try:
        game = _game()
        if not game.get('features', {}).get('players'):
            return 0
        module_id = game.get('module_id') or game.get('id', '').replace('-', '_')
        players_module = importlib.import_module(f'games.{module_id}.players')
        return len(players_module.get_players())
    except Exception:
        pass
    return 0

def get_status():
    """
    Retourne un dict de statut standardisé pour l'UI :
    { state: int, uptime: str, metrics: { cpu, ram, players } }
    State : 0=arrêté, 20=en ligne
    """
    proc = _get_process()
    if not proc:
        return {'state': 0, 'uptime': '0:00:00:00', 'metrics': {}}
    try:
        game   = _game()
        # Collecter le process principal + enfants directs
        all_procs = [proc]
        try:
            all_procs += proc.children(recursive=True)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

        # Wine re-parente les processus enfants hors de l'arbre systemd.
        # On cherche en plus tous les process du même utilisateur qui ont
        # le chemin du serveur dans leur cmdline (ex: enshrouded_server.exe)
        # Filtrer uniquement sur install_dir pour éviter de capturer
        # d'autres instances du même jeu qui partagent le même binaire.
        # Wine re-parente enshrouded_server.exe hors de l'arbre systemd.
        # Sa cmdline contient le chemin Wine "Z:\home\..." donc on cherche
        # à la fois le chemin Linux et son équivalent Wine Z:
        server_dir = game.get('server', {}).get('install_dir', '')
        seen_pids  = {p.pid for p in all_procs}
        search_paths = []
        if server_dir:
            search_paths.append(server_dir)
            # Equivalent Wine : /home/... → Z:\home\...
            wine_path = 'Z:' + server_dir.replace('/', '\\')
            search_paths.append(wine_path)
        if search_paths:
            for p in psutil.process_iter(['pid', 'cmdline']):
                try:
                    if p.pid in seen_pids:
                        continue
                    cmd = ' '.join(p.info['cmdline'] or [])
                    if any(sp in cmd for sp in search_paths):
                        all_procs.append(p)
                        seen_pids.add(p.pid)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

        # Initialiser cpu_percent (première mesure = 0, nécessaire pour la suivante)
        for p in all_procs:
            try: p.cpu_percent(interval=None)
            except Exception: pass
        time.sleep(0.5)

        cpu_total = 0.0
        ram_total = 0
        for p in all_procs:
            try:
                cpu_total += p.cpu_percent(interval=None)
                ram_total += p.memory_info().rss
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        vmem  = psutil.virtual_memory()
        max_p = game.get('server', {}).get('max_players', 10)
        uptime_s = int(time.time() - proc.create_time())
        h, r  = divmod(uptime_s, 3600)
        m, s  = divmod(r, 60)
        return {
            'state':  20,
            'uptime': f'0:{h:02d}:{m:02d}:{s:02d}',
            'metrics': {
                'cpu':     {'value': round(min(cpu_total, 100)),              'max': 100},
                'ram':     {'value': round(ram_total / 1024 / 1024),         'max': round(vmem.total / 1024 / 1024)},
                'players': {'value': _player_count(),                        'max': max_p},
            }
        }
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return {'state': 0, 'uptime': '0:00:00:00', 'metrics': {}}

def get_cpu_monitor_alert():
    instance_id = _instance_id()
    if not instance_id:
        return None
    data = _read_cpu_monitor_state()
    alert = (data.get("alerts_by_instance") or {}).get(instance_id)
    return alert if isinstance(alert, dict) else None

def get_cpu_monitor_snapshot():
    instance_id = _instance_id()
    if not instance_id:
        return None
    data = _read_cpu_monitor_state()
    instance = (data.get("instances") or {}).get(instance_id)
    if not isinstance(instance, dict):
        return None
    return {
        "updated_at": data.get("updated_at"),
        "samples_for_alert": data.get("samples_for_alert"),
        "instance": instance,
    }

def _service_state():
    service = _game()['server']['service']
    try:
        r = subprocess.run(
            ['systemctl', 'show', service, '--property=ActiveState,SubState'],
            capture_output=True, text=True, timeout=3
        )
        state = {}
        for line in r.stdout.splitlines():
            if '=' in line:
                k, v = line.split('=', 1)
                state[k] = v.strip()
        return state
    except Exception:
        return {}

def _wait_until_stopped(timeout=180):
    deadline = time.time() + timeout
    while time.time() < deadline:
        proc = _get_process()
        state = _service_state()
        active = state.get('ActiveState', '')
        sub = state.get('SubState', '')
        if not proc and active in {'inactive', 'failed'}:
            return True
        if active == 'inactive' and sub == 'dead':
            return True
        time.sleep(2)
    return False

def _wait_until_started(timeout=180):
    deadline = time.time() + timeout
    while time.time() < deadline:
        proc = _get_process()
        state = _service_state()
        if proc:
            return True
        if state.get('ActiveState', '') == 'active':
            return True
        time.sleep(2)
    return False

def _systemctl(action, timeout=30, no_block=False):
    service = _game()['server']['service']
    try:
        cmd = ['sudo', '/usr/bin/systemctl', action]
        if no_block:
            cmd.append('--no-block')
        cmd.append(service)
        r = subprocess.run(
            cmd,
            capture_output=True, text=True, timeout=timeout
        )
        return r.returncode == 0, r.stderr.strip()
    except Exception as e:
        return False, str(e)

def start(wait=False, timeout=180):
    ok, err = _systemctl('start', timeout=timeout, no_block=False)
    if not ok or not wait:
        _notify_action("start", ok, err)
        return ok, err
    started = _wait_until_started(timeout)
    details = '' if started else 'start_timeout'
    _notify_action("start", started, details)
    return started, details

def stop(wait=False, timeout=180):
    ok, err = _systemctl('stop', timeout=timeout, no_block=False)
    if not ok or not wait:
        _notify_action("stop", ok, err)
        return ok, err
    stopped = _wait_until_stopped(timeout)
    details = '' if stopped else 'stop_timeout'
    _notify_action("stop", stopped, details)
    return stopped, details

def restart(wait=False, timeout=180):
    ok, err = _systemctl('restart', timeout=timeout, no_block=False)
    if not ok or not wait:
        _notify_action("restart", ok, err)
        return ok, err
    started = _wait_until_started(timeout)
    details = '' if started else 'restart_timeout'
    _notify_action("restart", started, details)
    return started, details

def get_console_entries(n=100, after_cursor=None):
    """
    Lit les entrées du journal systemd du service.
    - Si after_cursor est fourni, retourne uniquement les nouvelles lignes depuis ce curseur.
    - Sinon, retourne les n dernières lignes (initialisation).
    Retourne (entries, cursor) où cursor est la position courante pour le prochain appel.
    """
    service = _game()['server']['service']
    try:
        if after_cursor:
            cmd = ['journalctl', '-u', service, '--no-pager', '-o', 'short-iso',
                   '--show-cursor', f'--after-cursor={after_cursor}']
        else:
            cmd = ['journalctl', '-u', service, f'-n{n}', '--no-pager', '-o', 'short-iso',
                   '--show-cursor']
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        lines  = r.stdout.splitlines()
        cursor = None
        entries = []
        for line in lines:
            if line.startswith('-- cursor:'):
                cursor = line.split('-- cursor:')[-1].strip()
            elif line.startswith('-- Cursor:'):
                cursor = line.split('-- Cursor:')[-1].strip()
            elif line and not line.startswith('-- '):
                entries.append({'msg': line})
        return entries, cursor
    except Exception:
        return [], None

def send_console_command(cmd):
    """Délègue au module jeu si un support console existe."""
    try:
        game = _game()
        module_id = game.get('module_id') or game.get('id', '').replace('-', '_')
        console_module = importlib.import_module(f'games.{module_id}.console')
        return console_module.send_console_command(cmd)
    except Exception:
        return False, 'Console input non supporté pour ce jeu'
