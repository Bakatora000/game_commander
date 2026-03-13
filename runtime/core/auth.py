"""
core/auth.py — Authentification locale (bcrypt + users.json) et contrôle d'accès.
"""
import os, json, functools
import bcrypt
from flask import session, request, jsonify, redirect, current_app


def _users_file():
    return os.path.join(current_app.root_path, 'users.json')

def load_users():
    try:
        with open(_users_file()) as f:
            return json.load(f)
    except Exception:
        return {}

def save_users(data):
    with open(_users_file(), 'w') as f:
        json.dump(data, f, indent=2)

def verify_password(username, password):
    users = load_users()
    user  = users.get(username)
    if not user:
        return False
    try:
        return bcrypt.checkpw(password.encode(), user['password_hash'].encode())
    except Exception:
        return False

def get_user_perms(username):
    game       = current_app.config['GAME']
    admin_user = game['web']['admin_user']
    if username == admin_user:
        return game['permissions'] + ['admin']
    users = load_users()
    return users.get(username, {}).get('permissions', [])

def has_perm(perm):
    return perm in get_user_perms(session.get('username', ''))

def require_auth(f):
    @functools.wraps(f)
    def wrapped(*args, **kwargs):
        if not session.get('username'):
            prefix = current_app.config['PREFIX']
            if request.path.startswith(f'{prefix}/api/'):
                return jsonify({'error': 'not_authenticated'}), 401
            return redirect(f'{prefix}/login')
        return f(*args, **kwargs)
    return wrapped

def require_perm(perm):
    def decorator(f):
        @functools.wraps(f)
        def wrapped(*args, **kwargs):
            if not has_perm(perm):
                return jsonify({'error': 'permission_denied',
                                'message': f'Permission requise : {perm}'}), 403
            return f(*args, **kwargs)
        return wrapped
    return decorator
