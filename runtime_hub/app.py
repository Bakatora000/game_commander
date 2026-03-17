#!/usr/bin/env python3
"""
Game Commander Hub — app.py
Interface d'administration hôte distincte des Commanders d'instance.
"""
from __future__ import annotations

import os
from flask import Flask, jsonify, redirect, render_template, request, session

from core import auth, host


PREFIX = "/commander"

app = Flask(
    __name__,
    template_folder="templates",
    static_folder="static",
    static_url_path=f"{PREFIX}/static",
)
app.secret_key = os.environ.get("GAME_COMMANDER_HUB_SECRET")
if not app.secret_key:
    raise RuntimeError("Variable GAME_COMMANDER_HUB_SECRET non définie.")

app.config["PREFIX"] = PREFIX
app.config["HUB_MANIFEST"] = os.environ.get("GC_HUB_MANIFEST", "/etc/nginx/game-commander-manifest.json")
app.config["CPU_MONITOR_STATE"] = os.environ.get("GC_HUB_CPU_MONITOR_STATE", "/var/lib/game-commander/cpu-monitor.json")


@app.context_processor
def inject_globals():
    return {"prefix": PREFIX}


@app.route(f"{PREFIX}/")
@app.route(PREFIX)
def index():
    return redirect(f"{PREFIX}/app" if session.get("username") else f"{PREFIX}/login")


@app.route(f"{PREFIX}/login")
def login_page():
    return render_template("login.html")


@app.route(f"{PREFIX}/logout")
def logout():
    session.clear()
    return redirect(f"{PREFIX}/login")


@app.route(f"{PREFIX}/app")
@auth.require_auth
@auth.require_perm("view_hub")
def app_page():
    return render_template("app.html")


@app.route(f"{PREFIX}/api/login", methods=["POST"])
def api_login():
    data = request.get_json() or {}
    username = data.get("username", "").strip()
    password = data.get("password", "")
    if not username or not password:
        return jsonify({"error": "missing_fields"}), 400
    if not auth.verify_password(username, password):
        return jsonify({"error": "invalid_credentials", "message": "Identifiants incorrects"}), 401
    session.permanent = True
    session["username"] = username
    return jsonify({"ok": True, "redirect": f"{PREFIX}/app"})


@app.route(f"{PREFIX}/api/me")
@auth.require_auth
def api_me():
    username = session.get("username", "")
    return jsonify({"username": username, "permissions": auth.get_user_perms(username)})


@app.route(f"{PREFIX}/api/instances")
@auth.require_auth
@auth.require_perm("view_hub")
def api_instances():
    return jsonify(host.get_hub_payload())


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("GC_HUB_PORT", "5090")))
