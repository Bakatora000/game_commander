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
app.config["MAIN_SCRIPT"] = os.environ.get("GC_HUB_MAIN_SCRIPT", "/home/vhserver/gc/game_commander.sh")


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


@app.route(f"{PREFIX}/api/accounts")
@auth.require_auth
@auth.require_perm("view_hub")
def api_accounts():
    return jsonify({"accounts": auth.list_accounts()})


@app.route(f"{PREFIX}/api/accounts/change-password", methods=["POST"])
@auth.require_auth
@auth.require_perm("view_hub")
def api_change_own_password():
    data = request.get_json() or {}
    ok, err = auth.change_own_password(
        session.get("username", ""),
        data.get("current_password", ""),
        data.get("new_password", ""),
    )
    if not ok:
        return jsonify({"error": "invalid_request", "message": err}), 400
    return jsonify({"ok": True})


@app.route(f"{PREFIX}/api/accounts/<username>/email", methods=["POST"])
@auth.require_auth
@auth.require_perm("view_hub")
def api_update_account_email(username):
    data = request.get_json() or {}
    ok, err = auth.update_account_email(username, data.get("email", ""))
    if not ok:
        return jsonify({"error": "invalid_request", "message": err}), 400
    return jsonify({"ok": True})


@app.route(f"{PREFIX}/api/accounts/<username>/reset-password", methods=["POST"])
@auth.require_auth
@auth.require_perm("view_hub")
def api_reset_account_password(username):
    data = request.get_json() or {}
    ok, err = auth.reset_account_password(username, data.get("new_password", ""))
    if not ok:
        return jsonify({"error": "invalid_request", "message": err}), 400
    return jsonify({"ok": True})


@app.route(f"{PREFIX}/api/instances/<instance_name>/<action>", methods=["POST"])
@auth.require_auth
@auth.require_perm("manage_instances")
def api_instance_service_action(instance_name, action):
    ok, message, card = host.run_instance_service_action(instance_name, action)
    status = 200 if ok else 400
    return jsonify({"ok": ok, "message": message, "instance": card}), status


@app.route(f"{PREFIX}/api/instances/<instance_name>/update", methods=["POST"])
@auth.require_auth
@auth.require_perm("run_updates")
def api_instance_update(instance_name):
    ok, message, card = host.run_instance_update(instance_name)
    status = 200 if ok else 400
    return jsonify({"ok": ok, "message": message, "instance": card}), status


@app.route(f"{PREFIX}/api/instances/<instance_name>/redeploy", methods=["POST"])
@auth.require_auth
@auth.require_perm("manage_lifecycle")
def api_instance_redeploy(instance_name):
    ok, message, card = host.run_instance_redeploy(instance_name)
    status = 200 if ok else 400
    return jsonify({"ok": ok, "message": message, "instance": card}), status


@app.route(f"{PREFIX}/api/instances/<instance_name>/uninstall", methods=["POST"])
@auth.require_auth
@auth.require_perm("manage_lifecycle")
def api_instance_uninstall(instance_name):
    ok, message, payload = host.run_instance_uninstall(instance_name)
    status = 200 if ok else 400
    return jsonify({"ok": ok, "message": message, "payload": payload}), status


@app.route(f"{PREFIX}/api/rebalance", methods=["POST"])
@auth.require_auth
@auth.require_perm("rebalance_cpu")
def api_rebalance():
    data = request.get_json() or {}
    restart = bool(data.get("restart"))
    ok, message, payload = host.run_rebalance(restart=restart)
    status = 200 if ok else 400
    return jsonify({"ok": ok, "message": message, "payload": payload}), status


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("GC_HUB_PORT", "5090")))
