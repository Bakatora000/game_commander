"""
games/satisfactory/config.py — intégration API HTTPS native Satisfactory.
"""
import os

import requests as http
import urllib3
from flask import current_app

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def _server_port():
    return int(current_app.config['GAME']['server']['port'])


def _api_url():
    return f"https://127.0.0.1:{_server_port()}/api/v1"


def _api_call(function_name, data=None, token=None, timeout=8):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    try:
        response = http.post(
            _api_url(),
            json={'function': function_name, 'data': data or {}},
            headers=headers,
            timeout=timeout,
            verify=False,
        )
    except http.exceptions.ConnectionError:
        return None, "API Satisfactory indisponible — serveur arrêté ou démarrage en cours"
    except http.exceptions.Timeout:
        return None, "API Satisfactory indisponible — délai de réponse dépassé"
    except http.exceptions.RequestException:
        return None, "API Satisfactory indisponible"
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if response.ok:
        return payload, None
    message = (
        payload.get('errorCode')
        or payload.get('errorMessage')
        or payload.get('error')
        or payload.get('message')
        or (payload.get('data') or {}).get('error')
        or response.text
        or f'HTTP {response.status_code}'
    )
    return None, message.strip()


def _extract_token(payload):
    data = payload.get('data') or {}
    return (
        data.get('authenticationToken')
        or data.get('AuthenticationToken')
        or data.get('bearerAuthenticationToken')
        or data.get('BearerAuthenticationToken')
        or payload.get('authenticationToken')
        or payload.get('AuthenticationToken')
        or payload.get('bearerAuthenticationToken')
        or payload.get('BearerAuthenticationToken')
    )


def _extract_server_name(payload):
    data = payload.get('data') or {}
    options = data.get('serverOptions') or {}
    return (
        options.get('FG.DSA.ServerName')
        or options.get('ServerName')
        or options.get('serverName')
        or data.get('serverName')
        or data.get('ServerName')
        or ''
    )


def _extract_active_session_name(payload):
    data = payload.get('data') or {}
    game_state = data.get('serverGameState') or data.get('ServerGameState') or {}
    return (
        game_state.get('activeSessionName')
        or game_state.get('ActiveSessionName')
        or data.get('activeSessionName')
        or data.get('ActiveSessionName')
        or ''
    )


def _read_public_server_info():
    info = {
        'server_name': '',
        'active_session_name': '',
    }
    payload, err = _api_call('QueryServerState')
    if not err and payload:
        info['active_session_name'] = _extract_active_session_name(payload)
    payload, err = _api_call('GetServerOptions')
    if not err and payload:
        info['server_name'] = _extract_server_name(payload)
    return info


def _passwordless_login():
    payload, err = _api_call('PasswordlessLogin', {'MinimumPrivilegeLevel': 'InitialAdmin'})
    if err:
        return None, err
    if payload.get('errorCode') or payload.get('errorMessage'):
        return None, payload.get('errorCode') or payload.get('errorMessage')
    token = _extract_token(payload)
    if not token:
        return None, "Jeton d'authentification Satisfactory manquant"
    return token, None


def _password_login(password, privilege='Administrator'):
    if not password:
        return None, 'Mot de passe admin requis'
    payload, err = _api_call('PasswordLogin', {
        'Password': password,
        'MinimumPrivilegeLevel': privilege,
    })
    if err:
        return None, err
    if payload.get('errorCode') or payload.get('errorMessage'):
        return None, payload.get('errorCode') or payload.get('errorMessage')
    token = _extract_token(payload)
    if not token:
        return None, "Jeton d'authentification Satisfactory manquant"
    return token, None


def _admin_session(password):
    token, err = _password_login(password, 'Administrator')
    if err:
        return None, err
    return token, None


def read_config():
    return get_claim_status()


def write_config(_new_data):
    return False, "Utilise les actions dédiées Satisfactory"


def get_claim_status():
    try:
        token, err = _passwordless_login()
        if not err:
            info = _read_public_server_info()
            return {
                'reachable': True,
                'claimed': False,
                'status_label': 'Non revendiqué',
                'server_name': info.get('server_name', ''),
                'active_session_name': info.get('active_session_name', ''),
                'message': 'Le serveur peut encore être revendiqué.',
            }, None
        lowered = err.lower()
        if (
            'passwordless_login_not_possible' in lowered
            or 'claimed' in lowered
            or 'password' in lowered
            or 'privilege' in lowered
            or 'already' in lowered
        ):
            info = _read_public_server_info()
            return {
                'reachable': True,
                'claimed': True,
                'status_label': 'Revendiqué',
                'server_name': info.get('server_name', ''),
                'active_session_name': info.get('active_session_name', ''),
                'message': 'Le serveur est déjà revendiqué. Utilise le mot de passe admin pour le gérer.',
            }, None
        return {
            'reachable': False,
            'claimed': None,
            'status_label': 'Injoignable',
            'server_name': '',
            'active_session_name': '',
            'message': err,
        }, None
    except Exception as exc:
        return {
            'reachable': False,
            'claimed': None,
            'status_label': 'Injoignable',
            'server_name': '',
            'active_session_name': '',
            'message': str(exc),
        }, None


def claim_server(server_name, admin_password):
    server_name = (server_name or '').strip()
    if not server_name:
        return None, 'Nom du serveur requis'
    if not admin_password:
        return None, 'Mot de passe admin requis'
    token, err = _passwordless_login()
    if err:
        return None, err
    payload, err = _api_call('ClaimServer', {
        'ServerName': server_name,
        'AdminPassword': admin_password,
    }, token=token)
    if err:
        return None, err
    return {
        'server_name': _extract_server_name(payload) or server_name,
        'message': 'Serveur revendiqué',
    }, None


def rename_server(current_admin_password, server_name):
    server_name = (server_name or '').strip()
    if not server_name:
        return None, 'Nom du serveur requis'
    token, err = _admin_session(current_admin_password)
    if err:
        return None, err
    payload, err = _api_call('RenameServer', {'ServerName': server_name}, token=token)
    if err:
        return None, err
    return {
        'server_name': _extract_server_name(payload) or server_name,
        'message': 'Nom du serveur mis à jour',
    }, None


def set_admin_password(current_admin_password, new_admin_password):
    if not new_admin_password:
        return None, 'Nouveau mot de passe admin requis'
    token, err = _admin_session(current_admin_password)
    if err:
        return None, err
    _payload, err = _api_call('SetAdminPassword', {'Password': new_admin_password}, token=token)
    if err:
        return None, err
    return {'message': 'Mot de passe admin mis à jour'}, None


def set_client_password(current_admin_password, client_password):
    token, err = _admin_session(current_admin_password)
    if err:
        return None, err
    _payload, err = _api_call('SetClientPassword', {'Password': client_password or ''}, token=token)
    if err:
        return None, err
    return {
        'message': 'Mot de passe joueur mis à jour' if client_password else 'Mot de passe joueur supprimé',
    }, None
