#!/usr/bin/env python3
"""
Game Commander — app.py
Flask factory. Lit game.json, enregistre toutes les routes communes,
charge conditionnellement les modules par jeu (mods, config).
"""
import os, json, importlib, subprocess
from flask import Flask, request, jsonify, session, redirect, render_template, send_file
import bcrypt

# ── Chargement de la config jeu ────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(_HERE, 'game.json')) as f:
    GAME = json.load(f)

PREFIX      = GAME['web']['url_prefix'].rstrip('/')
GAME_ID     = GAME['id']
MODULE_ID   = GAME.get('module_id') or GAME_ID.replace('-', '_')
TEMPLATE_ID = GAME.get('template_id') or MODULE_ID
THEME_NAME  = GAME.get('theme', {}).get('name', MODULE_ID)

# ── Application Flask ──────────────────────────────────────────────────────────
app = Flask(
    __name__,
    template_folder='templates',
    static_folder='static',
    static_url_path=f'{PREFIX}/static',
)
app.secret_key = os.environ.get('GAME_COMMANDER_SECRET')
if not app.secret_key:
    raise RuntimeError('Variable GAME_COMMANDER_SECRET non définie.')

app.config['GAME']   = GAME
app.config['PREFIX'] = PREFIX

# ── Modules core ──────────────────────────────────────────────────────────────
from core import auth, server, metrics, saves

metrics.init(os.path.join(_HERE, 'metrics.log'))

# ── Modules jeu (chargement conditionnel) ─────────────────────────────────────
mods_module   = None
config_module = None

if GAME['features'].get('mods'):
    try:
        mods_module = importlib.import_module(f'games.{MODULE_ID}.mods')
    except ImportError as e:
        print(f'[WARN] Module mods introuvable pour {GAME_ID}: {e}')

if GAME['features'].get('config'):
    try:
        config_module = importlib.import_module(f'games.{MODULE_ID}.config')
    except ImportError as e:
        print(f'[WARN] Module config introuvable pour {GAME_ID}: {e}')

minecraft_admins_module = None
if GAME_ID in ('minecraft', 'minecraft-fabric'):
    try:
        minecraft_admins_module = importlib.import_module(f'games.{MODULE_ID}.admins')
    except ImportError as e:
        print(f'[WARN] Module admins introuvable pour {GAME_ID}: {e}')

# ── Context processor Jinja2 ──────────────────────────────────────────────────
@app.context_processor
def inject_globals():
    return {
        'game': GAME,
        'prefix': PREFIX,
        'game_id': GAME_ID,
        'module_id': MODULE_ID,
        'template_id': TEMPLATE_ID,
        'theme_name': THEME_NAME,
    }

# ─────────────────────────────────────────────────────────────────────────────
# ROUTES PAGES
# ─────────────────────────────────────────────────────────────────────────────
@app.route(f'{PREFIX}/')
@app.route(f'{PREFIX}')
def index():
    return redirect(f'{PREFIX}/app' if session.get('username') else f'{PREFIX}/login')

@app.route(f'{PREFIX}/login')
def login_page():
    return render_template(f'games/{TEMPLATE_ID}/login.html')

@app.route(f'{PREFIX}/logout')
def logout():
    session.clear()
    return redirect(f'{PREFIX}/login')

@app.route(f'{PREFIX}/app')
@auth.require_auth
def app_page():
    return render_template(f'games/{TEMPLATE_ID}/app.html')

# ─────────────────────────────────────────────────────────────────────────────
# API — AUTH
# ─────────────────────────────────────────────────────────────────────────────
@app.route(f'{PREFIX}/api/login', methods=['POST'])
def api_login():
    data     = request.get_json() or {}
    username = data.get('username', '').strip()
    password = data.get('password', '')
    if not username or not password:
        return jsonify({'error': 'missing_fields'}), 400
    if not auth.verify_password(username, password):
        return jsonify({'error': 'invalid_credentials', 'message': 'Identifiants incorrects'}), 401
    session.permanent  = True
    session['username'] = username
    return jsonify({'ok': True, 'redirect': f'{PREFIX}/app'})

@app.route(f'{PREFIX}/api/me')
@auth.require_auth
def api_me():
    username = session.get('username', '')
    return jsonify({'username': username, 'permissions': auth.get_user_perms(username)})

# ─────────────────────────────────────────────────────────────────────────────
# API — SERVEUR
# ─────────────────────────────────────────────────────────────────────────────
@app.route(f'{PREFIX}/api/status')
@auth.require_auth
def api_status():
    return jsonify(server.get_status())

@app.route(f'{PREFIX}/api/hub-status')
def api_hub_status():
    status = server.get_status()
    return jsonify({
        'state': status.get('state', 0),
        'metrics': {
            'players': (status.get('metrics') or {}).get('players', {'value': 0, 'max': 0}),
        },
    })

@app.route(f'{PREFIX}/api/updates')
@auth.require_auth
def api_updates():
    after_cursor = request.args.get('cursor') or None
    entries, cursor = server.get_console_entries(n=80, after_cursor=after_cursor)
    return jsonify({
        'entries': entries,
        'cursor':  cursor,
        'status':  server.get_status(),
    })

@app.route(f'{PREFIX}/api/metrics')
@auth.require_auth
def api_metrics():
    minutes = max(5, min(request.args.get('minutes', 60, type=int), 1440))
    return jsonify(metrics.metrics_read(minutes))

@app.route(f'{PREFIX}/api/start', methods=['POST'])
@auth.require_auth
@auth.require_perm('start_server')
def api_start():
    ok, err = server.start()
    return jsonify({'ok': True}) if ok else (jsonify({'error': err}), 502)

@app.route(f'{PREFIX}/api/stop', methods=['POST'])
@auth.require_auth
@auth.require_perm('stop_server')
def api_stop():
    ok, err = server.stop()
    return jsonify({'ok': True}) if ok else (jsonify({'error': err}), 502)

@app.route(f'{PREFIX}/api/restart', methods=['POST'])
@auth.require_auth
@auth.require_perm('restart_server')
def api_restart():
    ok, err = server.restart()
    return jsonify({'ok': True}) if ok else (jsonify({'error': err}), 502)

@app.route(f'{PREFIX}/api/console', methods=['POST'])
@auth.require_auth
@auth.require_perm('console')
def api_console():
    cmd = (request.get_json() or {}).get('command', '').strip()
    if not cmd:
        return jsonify({'error': 'empty_command'}), 400
    ok, result = server.send_console_command(cmd)
    return jsonify({'ok': ok, 'result': result})

# ─────────────────────────────────────────────────────────────────────────────
# API — SAUVEGARDES
# ─────────────────────────────────────────────────────────────────────────────
@app.route(f'{PREFIX}/api/saves')
@auth.require_auth
@auth.require_perm('manage_saves')
def api_saves():
    root_id = request.args.get('root', '').strip()
    rel_path = request.args.get('path', '')
    roots = saves.get_save_roots()

    if not root_id:
        return jsonify({'roots': roots})

    try:
        data, err = saves.list_entries(root_id, rel_path)
    except ValueError:
        return jsonify({'error': 'invalid_path', 'roots': roots}), 400
    if err:
        return jsonify({'error': err, 'roots': roots}), 404
    data['roots'] = roots
    return jsonify(data)


@app.route(f'{PREFIX}/api/saves/download')
@auth.require_auth
@auth.require_perm('manage_saves')
def api_saves_download():
    root_id = request.args.get('root', '').strip()
    rel_path = request.args.get('path', '')
    try:
        target, filename, err = saves.get_download_target(root_id, rel_path)
    except ValueError:
        return jsonify({'error': 'invalid_path'}), 400
    if err:
        return jsonify({'error': err}), 404
    return send_file(target, as_attachment=True, download_name=filename)


@app.route(f'{PREFIX}/api/saves/delete', methods=['POST'])
@auth.require_auth
@auth.require_perm('manage_saves')
def api_saves_delete():
    data = request.get_json() or {}
    root_id = (data.get('root') or '').strip()
    rel_path = data.get('path') or ''
    confirm_special = bool(data.get('confirm_special'))
    stop_if_running = bool(data.get('stop_if_running'))
    try:
        requirements, err = saves.get_delete_requirements(root_id, rel_path)
    except ValueError:
        return jsonify({'error': 'invalid_path'}), 400
    if err:
        return jsonify({'error': err}), 404

    server_running = server.get_status().get('state') == 20
    if requirements.get('protected'):
        if server_running and not auth.has_perm('stop_server'):
            return jsonify({
                'error': 'stop_permission_required',
                'server_running': True,
                **requirements,
            }), 403
        if not confirm_special:
            return jsonify({
                'error': 'protected_world_file',
                'server_running': server_running,
                **requirements,
            }), 409
        if server_running and not stop_if_running:
            return jsonify({
                'error': 'stop_required',
                'server_running': True,
                **requirements,
            }), 409

        server_stopped = False
        backup_created = None
        if server_running:
            ok, err = server.stop(wait=True, timeout=300)
            if not ok:
                return jsonify({'error': 'stop_failed', 'detail': err}), 502
            server_stopped = True

        backup_created, err = saves.snapshot_valheim_current_world_files()
        if err:
            return jsonify({'error': 'predelete_backup_failed', 'detail': err}), 502

        try:
            payload, err = saves.delete_save_entry(root_id, rel_path)
        except ValueError:
            return jsonify({'error': 'invalid_path'}), 400
        if err:
            return jsonify({'error': err}), 404
        return jsonify({
            'ok': True,
            'server_stopped': server_stopped,
            'backup_created': backup_created,
            **payload,
        })

    try:
        payload, err = saves.delete_save_entry(root_id, rel_path)
    except ValueError:
        return jsonify({'error': 'invalid_path'}), 400
    return jsonify({'ok': True, **payload}) if not err else (jsonify({'error': err}), 404)


@app.route(f'{PREFIX}/api/backups')
@auth.require_auth
@auth.require_perm('manage_saves')
def api_backups():
    data, err = saves.list_backups()
    return jsonify(data) if not err else (jsonify({'error': err}), 404)


@app.route(f'{PREFIX}/api/backups/download')
@auth.require_auth
@auth.require_perm('manage_saves')
def api_backups_download():
    filename = request.args.get('name', '').strip()
    try:
        target, download_name, err = saves.get_backup_download_target(filename)
    except ValueError:
        return jsonify({'error': 'invalid_backup'}), 400
    if err:
        return jsonify({'error': err}), 404
    return send_file(target, as_attachment=True, download_name=download_name)


@app.route(f'{PREFIX}/api/backups/delete', methods=['POST'])
@auth.require_auth
@auth.require_perm('manage_saves')
def api_backups_delete():
    data = request.get_json() or {}
    filename = (data.get('name') or '').strip()
    try:
        payload, err = saves.delete_backup(filename)
    except ValueError:
        return jsonify({'error': 'invalid_backup'}), 400
    return jsonify({'ok': True, **payload}) if not err else (jsonify({'error': err}), 404)


@app.route(f'{PREFIX}/api/backups/run', methods=['POST'])
@auth.require_auth
@auth.require_perm('manage_saves')
def api_backups_run():
    data, err = saves.run_backup()
    return jsonify({'ok': True, **data}) if not err else (jsonify({'error': err}), 502)


@app.route(f'{PREFIX}/api/backups/upload', methods=['POST'])
@auth.require_auth
@auth.require_perm('manage_saves')
def api_backups_upload():
    overwrite = request.form.get('overwrite', 'false').lower() == 'true'
    files = request.files.getlist('files')
    if not files:
        return jsonify({'error': 'no_files'}), 400
    try:
        data, err = saves.upload_backups(files, overwrite=overwrite)
    except ValueError as exc:
        return jsonify({'error': str(exc) or 'invalid_backup'}), 400
    if not overwrite and data.get('collision_count'):
        return jsonify({'error': 'backup_conflicts', **data}), 409
    return jsonify({'ok': True, **data}) if not err else (jsonify({'error': err}), 400)


@app.route(f'{PREFIX}/api/backups/restore', methods=['POST'])
@auth.require_auth
@auth.require_perm('manage_saves')
def api_backups_restore():
    data = request.get_json() or {}
    filename = (data.get('name') or '').strip()
    confirm_restore = bool(data.get('confirm_restore'))
    stop_if_running = data.get('stop_if_running', True)
    backup_before_restore = data.get('backup_before_restore', True)
    if not filename:
        return jsonify({'error': 'missing_backup'}), 400
    if not confirm_restore:
        return jsonify({'error': 'restore_confirmation_required'}), 400

    server_running = server.get_status().get('state') == 20
    server_stopped = False
    server_restarted = False
    backup_created = None
    try:
        if server_running and stop_if_running:
            ok, err = server.stop(wait=True, timeout=300)
            if not ok:
                return jsonify({'error': 'stop_failed', 'detail': err}), 502
            server_stopped = True

        if backup_before_restore:
            backup_created, err = saves.run_safety_backup("before_restore")
            if err:
                return jsonify({'error': err}), 502

        result, err = saves.restore_backup(filename)
        if err:
            return jsonify({'error': err}), 404

        if server_running and stop_if_running:
            ok, err = server.start(wait=True, timeout=300)
            if not ok:
                return jsonify({
                    'ok': False,
                    'error': 'restart_failed',
                    'detail': err,
                    'server_stopped': server_stopped,
                    'backup_created': backup_created,
                    **result,
                }), 502
            server_restarted = True

        return jsonify({
            'ok': True,
            'server_stopped': server_stopped,
            'server_restarted': server_restarted,
            'backup_created': backup_created,
            **result,
        })
    except ValueError as exc:
        return jsonify({'error': str(exc) or 'restore_failed'}), 400


@app.route(f'{PREFIX}/api/saves/analyze', methods=['POST'])
@auth.require_auth
@auth.require_perm('manage_saves')
def api_saves_analyze():
    root_id = request.form.get('root', '').strip()
    rel_path = request.form.get('path', '')
    extract_archives = request.form.get('extract_archives', 'true').lower() != 'false'
    files = request.files.getlist('files')
    if not files:
        return jsonify({'error': 'no_files'}), 400
    try:
        result, err = saves.analyze_uploads(root_id, rel_path, files, extract_archives=extract_archives)
    except ValueError as exc:
        return jsonify({'error': str(exc) or 'invalid_upload'}), 400
    if err:
        return jsonify({'error': err}), 404
    response = {
        'ok': True,
        'count': result.get('count', 0),
        'collision_count': result.get('collision_count', 0),
        'write_count': result.get('write_count', 0),
        'collisions': result.get('collisions', [])[:20],
        'added': result.get('added', [])[:20],
        'server_running': server.get_status().get('state') == 20,
    }
    saves.cleanup_upload_analysis(result)
    return jsonify(response)


@app.route(f'{PREFIX}/api/saves/upload', methods=['POST'])
@auth.require_auth
@auth.require_perm('manage_saves')
def api_saves_upload():
    root_id = request.form.get('root', '').strip()
    rel_path = request.form.get('path', '')
    overwrite = request.form.get('overwrite', 'false').lower() == 'true'
    files = request.files.getlist('files')
    if not files:
        return jsonify({'error': 'no_files'}), 400
    try:
        data, err = saves.upload_save_files(root_id, rel_path, files, overwrite=overwrite)
    except ValueError as exc:
        return jsonify({'error': str(exc) or 'invalid_upload'}), 400
    if not overwrite and data.get('collision_count'):
        return jsonify({'error': 'upload_conflicts', **data}), 409
    return jsonify({'ok': True, **data}) if not err else (jsonify({'error': err}), 404)

# ─────────────────────────────────────────────────────────────────────────────
# API — UTILISATEURS
# ─────────────────────────────────────────────────────────────────────────────
@app.route(f'{PREFIX}/api/users', methods=['GET'])
@auth.require_auth
@auth.require_perm('manage_users')
def api_get_users():
    users = auth.load_users()
    return jsonify({u: {'permissions': d.get('permissions', [])} for u, d in users.items()})

@app.route(f'{PREFIX}/api/users', methods=['POST'])
@auth.require_auth
@auth.require_perm('manage_users')
def api_save_user():
    data        = request.get_json() or {}
    username    = data.get('username', '').strip()
    password    = data.get('password', '').strip()
    permissions = data.get('permissions', [])
    admin_user  = GAME['web']['admin_user']

    if not username:
        return jsonify({'error': 'missing_username'}), 400
    if username == admin_user:
        return jsonify({'error': 'cannot_modify_admin'}), 403

    users = auth.load_users()
    if username in users and not password:
        users[username]['permissions'] = permissions
    else:
        if not password:
            return jsonify({'error': 'password_required'}), 400
        hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        users[username] = {'password_hash': hashed, 'permissions': permissions}

    auth.save_users(users)
    return jsonify({'ok': True})

@app.route(f'{PREFIX}/api/users/<username>', methods=['DELETE'])
@auth.require_auth
@auth.require_perm('manage_users')
def api_delete_user(username):
    if username == GAME['web']['admin_user']:
        return jsonify({'error': 'cannot_delete_admin'}), 403
    users = auth.load_users()
    if username not in users:
        return jsonify({'error': 'user_not_found'}), 404
    del users[username]
    auth.save_users(users)
    return jsonify({'ok': True})

# ─────────────────────────────────────────────────────────────────────────────
# API — MODS (conditionnel)
# ─────────────────────────────────────────────────────────────────────────────
if mods_module:
    @app.route(f'{PREFIX}/api/mods/search')
    @auth.require_auth
    def api_mods_search():
        q = request.args.get('q', '').strip()
        if not q:
            return jsonify({'results': []})
        return jsonify({'results': mods_module.search_mods(q)})

    @app.route(f'{PREFIX}/api/mods/installed')
    @auth.require_auth
    def api_mods_installed():
        return jsonify({'mods': mods_module.get_installed_mods()})

    @app.route(f'{PREFIX}/api/mods/install', methods=['POST'])
    @auth.require_auth
    @auth.require_perm('install_mod')
    def api_mods_install():
        data = request.get_json() or {}
        ok, msg = mods_module.install_mod(
            data.get('namespace'), data.get('name'), data.get('version')
        )
        return jsonify({'ok': True, 'message': msg}) if ok else (jsonify({'error': msg}), 400)

    @app.route(f'{PREFIX}/api/mods/<mod_name>', methods=['DELETE'])
    @auth.require_auth
    @auth.require_perm('remove_mod')
    def api_mods_remove(mod_name):
        ok, msg = mods_module.remove_mod(mod_name)
        return jsonify({'ok': True}) if ok else (jsonify({'error': msg}), 400)

# ─────────────────────────────────────────────────────────────────────────────
# API — CONFIG (conditionnel)
# ─────────────────────────────────────────────────────────────────────────────
if config_module:
    @app.route(f'{PREFIX}/api/config', methods=['GET'])
    @auth.require_auth
    def api_config_get():
        data, err = config_module.read_config()
        return jsonify(data) if not err else (jsonify({'error': err}), 500)

    @app.route(f'{PREFIX}/api/config', methods=['POST'])
    @auth.require_auth
    @auth.require_perm('manage_config')
    def api_config_save():
        ok, err = config_module.write_config(request.get_json() or {})
        return jsonify({'ok': True}) if ok else (jsonify({'error': err}), 400)

# ─────────────────────────────────────────────────────────────────────────────
# API — MISE À JOUR SERVEUR
# ─────────────────────────────────────────────────────────────────────────────
import threading as _threading

_update_state = {'running': False, 'status': 'idle', 'log': ''}

@app.route(f'{PREFIX}/api/update', methods=['POST'])
@auth.require_auth
@auth.require_perm('restart_server')
def api_update_server():
    if _update_state['running']:
        return jsonify({'error': 'Mise à jour déjà en cours'}), 409
    steamcmd = GAME.get('steamcmd', {}).get('path', '')
    app_id   = GAME.get('steamcmd', {}).get('app_id', '')
    install_dir = GAME['server']['install_dir']
    if not steamcmd or not app_id:
        return jsonify({'error': 'steamcmd non configuré dans game.json'}), 400

    def _run():
        _update_state['running'] = True
        _update_state['status']  = 'stopping'
        _update_state['log']     = 'Arrêt du serveur...\n'
        server.stop()
        import time; time.sleep(5)
        _update_state['status'] = 'updating'
        _update_state['log'] += 'Mise à jour SteamCMD...\n'
        import subprocess
        try:
            r = subprocess.run(
                [steamcmd, '+@sSteamCmdForcePlatformType', 'linux',
                 '+login', 'anonymous',
                 '+force_install_dir', install_dir,
                 f'+app_update', app_id, 'validate', '+quit'],
                capture_output=True, text=True, timeout=1800
            )
            _update_state['log'] += r.stdout[-2000:] if r.stdout else ''
            if r.returncode == 0:
                _update_state['status'] = 'restarting'
                _update_state['log'] += 'Redémarrage...\n'
                server.start()
                _update_state['status'] = 'done'
                _update_state['log'] += 'Mise à jour terminée.\n'
            else:
                _update_state['status'] = 'error'
                _update_state['log'] += f'Erreur SteamCMD (code {r.returncode})\n'
        except Exception as e:
            _update_state['status'] = 'error'
            _update_state['log'] += f'Exception: {e}\n'
        finally:
            _update_state['running'] = False

    _threading.Thread(target=_run, daemon=True).start()
    return jsonify({'ok': True, 'message': 'Mise à jour démarrée'})

@app.route(f'{PREFIX}/api/update/status')
@auth.require_auth
def api_update_status():
    return jsonify(_update_state)

# ─────────────────────────────────────────────────────────────────────────────
# API — WORLD MODIFIERS (Valheim uniquement)
# ─────────────────────────────────────────────────────────────────────────────
if GAME_ID == 'valheim':
    try:
        import games.valheim.admins as _va
        import games.valheim.world_modifiers as _wm
        import games.valheim.worlds as _vw
        @app.route(f'{PREFIX}/api/world_modifiers', methods=['GET'])
        @auth.require_auth
        def api_wm_get():
            data, err = _wm.read_modifiers()
            schema = _wm.get_schema()
            return jsonify({'data': data, 'schema': schema})

        @app.route(f'{PREFIX}/api/world_modifiers', methods=['POST'])
        @auth.require_auth
        @auth.require_perm('manage_config')
        def api_wm_save():
            ok, err = _wm.write_modifiers(request.get_json() or {})
            return jsonify({'ok': True, 'warning': err}) if ok \
                else (jsonify({'error': err}), 400)

        @app.route(f'{PREFIX}/api/worlds', methods=['GET'])
        @auth.require_auth
        def api_valheim_worlds():
            data, err = _vw.list_worlds()
            if err:
                return jsonify({'error': err}), 400
            data['server_running'] = server.get_status().get('state') == 20
            return jsonify(data)

        @app.route(f'{PREFIX}/api/worlds/select', methods=['POST'])
        @auth.require_auth
        @auth.require_perm('manage_config')
        def api_valheim_worlds_select():
            payload = request.get_json() or {}
            world_name = (payload.get('world_name') or '').strip()
            data, err = _vw.select_world(world_name)
            if err:
                return jsonify({'error': err}), 400
            data['server_running'] = server.get_status().get('state') == 20
            return jsonify({'ok': True, **data})

        @app.route(f'{PREFIX}/api/admins', methods=['GET'])
        @auth.require_auth
        @auth.require_perm('manage_users')
        def api_valheim_admins():
            data, err = _va.list_admins()
            return jsonify(data) if not err else (jsonify({'error': err}), 400)

        @app.route(f'{PREFIX}/api/admins', methods=['POST'])
        @auth.require_auth
        @auth.require_perm('manage_users')
        def api_valheim_admins_add():
            payload = request.get_json() or {}
            data, err = _va.add_admin(payload.get('steamid', ''))
            return jsonify({'ok': True, **data}) if not err else (jsonify({'error': err}), 400)

        @app.route(f'{PREFIX}/api/admins/<steamid>', methods=['DELETE'])
        @auth.require_auth
        @auth.require_perm('manage_users')
        def api_valheim_admins_delete(steamid):
            data, err = _va.remove_admin(steamid)
            return jsonify({'ok': True, **data}) if not err else (jsonify({'error': err}), 400)

        @app.route(f'{PREFIX}/api/bans', methods=['GET'])
        @auth.require_auth
        @auth.require_perm('manage_users')
        def api_valheim_bans():
            data, err = _va.list_bans()
            return jsonify(data) if not err else (jsonify({'error': err}), 400)

        @app.route(f'{PREFIX}/api/bans', methods=['POST'])
        @auth.require_auth
        @auth.require_perm('manage_users')
        def api_valheim_bans_add():
            payload = request.get_json() or {}
            data, err = _va.add_ban(payload.get('steamid', ''))
            return jsonify({'ok': True, **data}) if not err else (jsonify({'error': err}), 400)

        @app.route(f'{PREFIX}/api/bans/<steamid>', methods=['DELETE'])
        @auth.require_auth
        @auth.require_perm('manage_users')
        def api_valheim_bans_delete(steamid):
            data, err = _va.remove_ban(steamid)
            return jsonify({'ok': True, **data}) if not err else (jsonify({'error': err}), 400)

        @app.route(f'{PREFIX}/api/whitelist', methods=['GET'])
        @auth.require_auth
        @auth.require_perm('manage_users')
        def api_valheim_whitelist():
            data, err = _va.list_whitelist()
            return jsonify(data) if not err else (jsonify({'error': err}), 400)

        @app.route(f'{PREFIX}/api/whitelist', methods=['POST'])
        @auth.require_auth
        @auth.require_perm('manage_users')
        def api_valheim_whitelist_add():
            payload = request.get_json() or {}
            data, err = _va.add_whitelist(payload.get('steamid', ''))
            return jsonify({'ok': True, **data}) if not err else (jsonify({'error': err}), 400)

        @app.route(f'{PREFIX}/api/whitelist/<steamid>', methods=['DELETE'])
        @auth.require_auth
        @auth.require_perm('manage_users')
        def api_valheim_whitelist_delete(steamid):
            data, err = _va.remove_whitelist(steamid)
            return jsonify({'ok': True, **data}) if not err else (jsonify({'error': err}), 400)
    except ImportError as e:
        print(f'[WARN] world_modifiers non chargé: {e}')

if GAME_ID == 'enshrouded':
    try:
        import games.enshrouded.worlds as _ew

        @app.route(f'{PREFIX}/api/worlds', methods=['GET'])
        @auth.require_auth
        def api_enshrouded_worlds():
            data, err = _ew.list_worlds()
            if err:
                return jsonify({'error': err}), 400
            data['server_running'] = server.get_status().get('state') == 20
            return jsonify(data)
    except ImportError as e:
        print(f'[WARN] worlds Enshrouded non chargé: {e}')

if GAME_ID == 'terraria':
    try:
        import games.terraria.worlds as _tw

        @app.route(f'{PREFIX}/api/worlds', methods=['GET'])
        @auth.require_auth
        def api_terraria_worlds():
            data, err = _tw.list_worlds()
            if err:
                return jsonify({'error': err}), 400
            data['server_running'] = server.get_status().get('state') == 20
            return jsonify(data)

        @app.route(f'{PREFIX}/api/worlds/select', methods=['POST'])
        @auth.require_auth
        @auth.require_perm('manage_config')
        def api_terraria_worlds_select():
            payload = request.get_json() or {}
            world_name = (payload.get('world_name') or '').strip()
            data, err = _tw.select_world(world_name)
            if err:
                return jsonify({'error': err}), 400
            data['server_running'] = server.get_status().get('state') == 20
            return jsonify({'ok': True, **data})
    except ImportError as e:
        print(f'[WARN] worlds Terraria non chargé: {e}')

if minecraft_admins_module is not None:
    @app.route(f'{PREFIX}/api/admins', methods=['GET'])
    @auth.require_auth
    @auth.require_perm('manage_users')
    def api_minecraft_admins():
        data, err = minecraft_admins_module.list_admins()
        return jsonify(data) if not err else (jsonify({'error': err}), 400)

    @app.route(f'{PREFIX}/api/admins', methods=['POST'])
    @auth.require_auth
    @auth.require_perm('manage_users')
    def api_minecraft_admins_add():
        payload = request.get_json() or {}
        data, err = minecraft_admins_module.add_admin(payload.get('name', ''), payload.get('level', 4))
        return jsonify({'ok': True, **data}) if not err else (jsonify({'error': err}), 400)

    @app.route(f'{PREFIX}/api/admins/<name>', methods=['DELETE'])
    @auth.require_auth
    @auth.require_perm('manage_users')
    def api_minecraft_admins_delete(name):
        data, err = minecraft_admins_module.remove_admin(name)
        return jsonify({'ok': True, **data}) if not err else (jsonify({'error': err}), 400)

    @app.route(f'{PREFIX}/api/bans', methods=['GET'])
    @auth.require_auth
    @auth.require_perm('manage_users')
    def api_minecraft_bans():
        data, err = minecraft_admins_module.list_bans()
        return jsonify(data) if not err else (jsonify({'error': err}), 400)

    @app.route(f'{PREFIX}/api/bans', methods=['POST'])
    @auth.require_auth
    @auth.require_perm('manage_users')
    def api_minecraft_bans_add():
        payload = request.get_json() or {}
        data, err = minecraft_admins_module.add_ban(payload.get('name', ''))
        return jsonify({'ok': True, **data}) if not err else (jsonify({'error': err}), 400)

    @app.route(f'{PREFIX}/api/bans/<name>', methods=['DELETE'])
    @auth.require_auth
    @auth.require_perm('manage_users')
    def api_minecraft_bans_delete(name):
        data, err = minecraft_admins_module.remove_ban(name)
        return jsonify({'ok': True, **data}) if not err else (jsonify({'error': err}), 400)

    @app.route(f'{PREFIX}/api/whitelist', methods=['GET'])
    @auth.require_auth
    @auth.require_perm('manage_users')
    def api_minecraft_whitelist():
        data, err = minecraft_admins_module.list_whitelist()
        return jsonify(data) if not err else (jsonify({'error': err}), 400)

    @app.route(f'{PREFIX}/api/whitelist', methods=['POST'])
    @auth.require_auth
    @auth.require_perm('manage_users')
    def api_minecraft_whitelist_add():
        payload = request.get_json() or {}
        data, err = minecraft_admins_module.add_whitelist(payload.get('name', ''))
        if err:
            return jsonify({'error': err}), 400
        reload_ok = False
        reload_err = None
        if server.get_status().get('state') == 20:
            reload_ok, reload_err = server.send_console_command('whitelist reload')
        return jsonify({'ok': True, 'reload_ok': reload_ok, 'reload_error': reload_err, **data})

    @app.route(f'{PREFIX}/api/whitelist/<name>', methods=['DELETE'])
    @auth.require_auth
    @auth.require_perm('manage_users')
    def api_minecraft_whitelist_delete(name):
        data, err = minecraft_admins_module.remove_whitelist(name)
        if err:
            return jsonify({'error': err}), 400
        reload_ok = False
        reload_err = None
        if server.get_status().get('state') == 20:
            reload_ok, reload_err = server.send_console_command('whitelist reload')
        return jsonify({'ok': True, 'reload_ok': reload_ok, 'reload_error': reload_err, **data})

# ─────────────────────────────────────────────────────────────────────────────
# API — JOUEURS CONNECTÉS (conditionnel)
# ─────────────────────────────────────────────────────────────────────────────
if GAME['features'].get('players'):
    try:
        _players_module = importlib.import_module(f'games.{MODULE_ID}.players')

        @app.route(f'{PREFIX}/api/players')
        @auth.require_auth
        def api_players():
            return jsonify({'players': _players_module.get_players()})
    except ImportError as e:
        print(f'[WARN] players non chargé pour {GAME_ID}: {e}')

# ─────────────────────────────────────────────────────────────────────────────
# DÉMARRAGE
# ─────────────────────────────────────────────────────────────────────────────
def _status_in_ctx():
    with app.app_context():
        return server.get_status()

metrics.start_poller(_status_in_ctx)

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=GAME['web']['flask_port'], debug=False)
