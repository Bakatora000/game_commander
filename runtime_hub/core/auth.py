"""
Auth du Hub Game Commander.
Séparée des users.json d'instance.
"""
from __future__ import annotations

import functools
import json
import os

import bcrypt
from flask import current_app, jsonify, redirect, request, session


def _users_file():
    return os.path.join(current_app.root_path, "users.json")


def load_users():
    try:
        with open(_users_file(), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_users(data):
    with open(_users_file(), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def verify_password(username, password):
    users = load_users()
    user = users.get(username)
    if not user:
        return False
    try:
        return bcrypt.checkpw(password.encode(), user["password_hash"].encode())
    except Exception:
        return False


def get_user_perms(username):
    users = load_users()
    return users.get(username, {}).get("permissions", [])


def get_user_record(username):
    return load_users().get(username)


def has_perm(perm):
    return perm in get_user_perms(session.get("username", ""))


def hash_password(password):
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def list_accounts():
    users = load_users()
    accounts = []
    for username in sorted(users):
        entry = users.get(username, {})
        accounts.append(
            {
                "username": username,
                "email": entry.get("email", ""),
                "permissions": entry.get("permissions", []),
            }
        )
    return accounts


def change_own_password(username, current_password, new_password):
    if not username:
        return False, "Session invalide"
    if not current_password or not new_password:
        return False, "Mot de passe actuel et nouveau requis"
    if len(new_password) < 8:
        return False, "Le nouveau mot de passe doit contenir au moins 8 caractères"
    if not verify_password(username, current_password):
        return False, "Mot de passe actuel incorrect"
    users = load_users()
    if username not in users:
        return False, "Compte introuvable"
    users[username]["password_hash"] = hash_password(new_password)
    save_users(users)
    return True, ""


def update_account_email(target_username, email):
    users = load_users()
    if target_username not in users:
        return False, "Compte introuvable"
    users[target_username]["email"] = email.strip()
    save_users(users)
    return True, ""


def reset_account_password(target_username, new_password):
    if not new_password:
        return False, "Nouveau mot de passe requis"
    if len(new_password) < 8:
        return False, "Le nouveau mot de passe doit contenir au moins 8 caractères"
    users = load_users()
    if target_username not in users:
        return False, "Compte introuvable"
    users[target_username]["password_hash"] = hash_password(new_password)
    save_users(users)
    return True, ""


def require_auth(f):
    @functools.wraps(f)
    def wrapped(*args, **kwargs):
        if not session.get("username"):
            prefix = current_app.config["PREFIX"]
            if request.path.startswith(f"{prefix}/api/"):
                return jsonify({"error": "not_authenticated"}), 401
            return redirect(f"{prefix}/login")
        return f(*args, **kwargs)

    return wrapped


def require_perm(perm):
    def decorator(f):
        @functools.wraps(f)
        def wrapped(*args, **kwargs):
            if not has_perm(perm):
                return jsonify({"error": "permission_denied", "message": f"Permission requise : {perm}"}), 403
            return f(*args, **kwargs)

        return wrapped

    return decorator
