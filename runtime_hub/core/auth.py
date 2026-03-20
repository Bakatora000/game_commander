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


DEFAULT_VIEW_HUB_PERMISSIONS = {
    "view_hub",
    "manage_instances",
    "manage_lifecycle",
    "run_updates",
    "rebalance_cpu",
    "manage_accounts",
}


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
    user = users.get(username, {})
    stored = set(user.get("permissions", []))
    explicit = bool(user.get("permissions_explicit"))
    if stored == {"view_hub"} and not explicit:
        return sorted(DEFAULT_VIEW_HUB_PERMISSIONS)
    return sorted(stored)


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
                "permissions": get_user_perms(username),
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


def create_account(username: str, password: str) -> tuple[bool, str]:
    username = username.strip()
    if len(username) < 2:
        return False, "Nom d'utilisateur trop court (2 caractères minimum)"
    if len(password) < 8:
        return False, "Mot de passe trop court (8 caractères minimum)"
    users = load_users()
    if username in users:
        return False, f"Le compte '{username}' existe déjà"
    # Store all default perms explicitly so granular editing works immediately
    users[username] = {
        "password_hash": hash_password(password),
        "permissions": sorted(DEFAULT_VIEW_HUB_PERMISSIONS),
        "permissions_explicit": True,
        "email": "",
    }
    save_users(users)
    return True, ""


def update_account_permissions(target_username: str, permissions: list[str], requesting_username: str) -> tuple[bool, str]:
    """Update permissions for a hub account. view_hub is always kept."""
    users = load_users()
    if target_username not in users:
        return False, "Compte introuvable"
    # view_hub is always required for hub access
    perms = sorted({"view_hub"} | (set(permissions) & set(DEFAULT_VIEW_HUB_PERMISSIONS)))
    # Prevent removing manage_accounts from the last account that has it
    if "manage_accounts" not in perms:
        others_with_manage = [
            u for u, data in users.items()
            if u != target_username and "manage_accounts" in get_user_perms(u)
        ]
        if not others_with_manage:
            return False, "Impossible : aucun autre compte n'a la permission 'Gérer les comptes'"
    users[target_username]["permissions"] = perms
    users[target_username]["permissions_explicit"] = True
    save_users(users)
    return True, ""


def delete_account(target_username: str, requesting_username: str) -> tuple[bool, str]:
    if target_username == requesting_username:
        return False, "Impossible de supprimer son propre compte"
    users = load_users()
    if target_username not in users:
        return False, "Compte introuvable"
    if len(users) <= 1:
        return False, "Impossible de supprimer le dernier compte"
    del users[target_username]
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
