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


def has_perm(perm):
    return perm in get_user_perms(session.get("username", ""))


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
