"""
Lecture seule du Hub Game Commander.
Agrège les statuts d'instances et l'état du monitor CPU.
"""
from __future__ import annotations

import json
import os
import pwd
import sys
import time
import zipfile
from datetime import datetime
from pathlib import Path

import bcrypt
import requests
from flask import current_app

MAIN_SCRIPT_ENV = os.environ.get("GC_HUB_MAIN_SCRIPT", "/home/vhserver/gc/game_commander.sh")
ROOT_DIR = Path(MAIN_SCRIPT_ENV).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from shared import hostctl, hostops, instanceenv


def _manifest_path() -> Path:
    return Path(current_app.config["HUB_MANIFEST"])


def _cpu_monitor_path() -> Path:
    return Path(current_app.config["CPU_MONITOR_STATE"])


def _main_script_path() -> Path:
    return Path(current_app.config["MAIN_SCRIPT"])


def _host_cli_path() -> Path:
    return Path(current_app.config["HOST_CLI"])


def _action_log_dir() -> Path:
    configured = current_app.config.get("ACTION_LOG_DIR")
    local_dir = Path(current_app.root_path) / "action-logs"
    legacy_dir = Path(current_app.root_path).parent / "action-logs"
    if configured:
        path = Path(configured)
        if path.resolve() == legacy_dir.resolve():
            legacy_log = legacy_dir / "hub-actions.log"
            local_log = local_dir / "hub-actions.log"
            if local_log.is_file() and local_log.stat().st_size > 0:
                if not legacy_log.is_file() or legacy_log.stat().st_size == 0:
                    return local_dir
        return path
    return local_dir


def _global_log_path() -> Path:
    return _action_log_dir() / "hub-actions.log"


def _append_action_log(instance_name: str, action: str, ok: bool, message: str, source: str = "Hub") -> None:
    log_dir = _action_log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    status = "OK" if ok else "ERR"
    origin = f" [{source}]" if source else ""
    content = (message or "").strip() or "(aucun détail)"
    with _global_log_path().open("a", encoding="utf-8") as fh:
        fh.write(f"[{timestamp}] {status}{origin} {instance_name} {action}\n")
        for line in content.splitlines():
            fh.write(f"  {line}\n")
        fh.write("\n")


def get_global_console(max_lines: int = 240) -> list[str]:
    path = _global_log_path()
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return lines[-max_lines:]


def purge_global_console() -> tuple[bool, str]:
    log_dir = _action_log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    path = _global_log_path()
    path.write_text("", encoding="utf-8")
    return True, "Console Hub purgée"


def archive_global_console() -> tuple[bool, str]:
    path = _global_log_path()
    if not path.is_file() or not path.read_text(encoding="utf-8", errors="replace").strip():
        return False, "Aucun log Hub à archiver"
    log_dir = _action_log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_path = log_dir / f"hub-actions_{stamp}.zip"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.write(path, arcname="hub-actions.log")
    return True, f"Archive créée : {archive_path.name}"


def _load_manifest() -> dict:
    path = _manifest_path()
    if not path.is_file():
        return {"instances": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"instances": []}


def _load_cpu_monitor() -> dict:
    path = _cpu_monitor_path()
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _instance_app_dir(instance_name: str) -> Path:
    return Path.home() / f"game-commander-{instance_name}"


def _instance_config_file(instance_name: str) -> Path:
    resolved = hostctl.resolve_instance_config(instance_name)
    if resolved:
        return resolved
    return _instance_app_dir(instance_name) / "deploy_config.env"


def _load_instance_env(instance_name: str) -> dict:
    env_path = _instance_config_file(instance_name)
    return instanceenv.parse_env_file(env_path)


def _instance_entry(instance_name: str) -> dict | None:
    for item in _load_manifest().get("instances", []):
        if item.get("name") == instance_name:
            return item
    return None


def _payload_instance_card(payload: dict, instance_name: str) -> dict | None:
    for item in payload.get("instances", []):
        if item.get("name") == instance_name:
            return item
    return None


def _instance_service(instance_name: str) -> str | None:
    return _load_instance_env(instance_name).get("GAME_SERVICE")


def _instance_admin_login(instance_name: str) -> str:
    env = _load_instance_env(instance_name)
    return (env.get("ADMIN_LOGIN") or "admin").strip() or "admin"


def _instance_users_file(instance_name: str) -> Path:
    return _instance_app_dir(instance_name) / "users.json"


def _instance_game_json(instance_name: str) -> Path:
    return _instance_app_dir(instance_name) / "game.json"


def _default_sys_user() -> str:
    return pwd.getpwuid(_main_script_path().stat().st_uid).pw_name


def _build_instance_card(inst: dict, cpu_monitor: dict, alerts_by_instance: dict, cpu_instances: dict) -> dict:
    name = inst.get("name", "?")
    prefix = inst.get("prefix", "/")
    port = int(inst.get("flask_port") or 0)
    status = _fetch_instance_hub_status(port, prefix) if port else {}
    state = int(status.get("state") or 0)
    players = (status.get("metrics") or {}).get("players") or {"value": 0, "max": 0}
    return {
        "name": name,
        "game": inst.get("game", "?"),
        "prefix": prefix,
        "admin_login": _instance_admin_login(name),
        "state": state,
        "players": players,
        "cpu_alert": alerts_by_instance.get(name),
        "cpu_monitor": {
            "updated_at": cpu_monitor.get("updated_at"),
            "instance": cpu_instances.get(name),
        } if cpu_instances.get(name) else None,
    }


def _fetch_instance_hub_status(port: int, prefix: str) -> dict:
    try:
        response = requests.get(
            f"http://127.0.0.1:{port}{prefix}/api/hub-status",
            timeout=1.5,
        )
        if not response.ok:
            return {}
        return response.json()
    except Exception:
        return {}


def _monitor_status(cpu_monitor: dict, instances: list[dict]) -> tuple[str, str]:
    monitored_count = sum(1 for inst in instances if inst.get("cpu_monitor"))
    if monitored_count == 0:
        return "Monitor indisponible", "Aucune donnée CPU détaillée reçue depuis les instances."
    updated_at = cpu_monitor.get("updated_at", 0) or 0
    age_seconds = max(0, int(time.time() - updated_at)) if updated_at else None
    if any(inst.get("cpu_alert") for inst in instances):
        base = "Alerte"
    elif age_seconds is not None and age_seconds <= 180:
        base = "Stable"
    else:
        base = "Données anciennes"
    if age_seconds is None:
        meta = f"{monitored_count} instance(s) suivie(s)"
    elif age_seconds < 90:
        meta = f"{monitored_count} instance(s) suivie(s) · mise à jour il y a moins de 2 min"
    else:
        meta = f"{monitored_count} instance(s) suivie(s) · mise à jour il y a {round(age_seconds / 60)} min"
    return base, meta


def get_hub_payload() -> dict:
    manifest = _load_manifest()
    cpu_monitor = _load_cpu_monitor()
    alerts_by_instance = cpu_monitor.get("alerts_by_instance") or {}
    cpu_instances = cpu_monitor.get("instances") or {}
    cards = []
    for inst in sorted(manifest.get("instances", []), key=lambda item: ((item.get("game") or "").lower(), (item.get("name") or "").lower())):
        cards.append(_build_instance_card(inst, cpu_monitor, alerts_by_instance, cpu_instances))
    monitor_status, monitor_meta = _monitor_status(cpu_monitor, cards)
    return {
        "monitor": {
            "status": monitor_status,
            "meta": monitor_meta,
        },
        "instances": cards,
    }


def _wait_until_instance_offline(instance_name: str, timeout: int = 180) -> tuple[bool, dict]:
    deadline = time.time() + timeout
    last_payload = get_hub_payload()
    while time.time() < deadline:
        payload = get_hub_payload()
        card = _payload_instance_card(payload, instance_name)
        last_payload = payload
        if card and int(card.get("state") or 0) == 0:
            return True, payload
        time.sleep(2)
    return False, last_payload


def run_instance_service_action(instance_name: str, action: str) -> tuple[bool, str, dict | None]:
    if action not in {"start", "stop", "restart"}:
        return False, "Action service non autorisée", None
    instance = _instance_entry(instance_name)
    if not instance:
        return False, "Instance introuvable", None
    service = _instance_service(instance_name)
    if not service:
        return False, "Service introuvable pour cette instance", None
    host_cli = _host_cli_path()
    if not host_cli.is_file():
        return False, "CLI hôte introuvable", None
    ok, message = hostops.run_command(
        ["sudo", "/usr/bin/python3", str(host_cli), "service-action", "--service", service, "--action", action, "--source", "Hub"],
        timeout=120,
    )
    _append_action_log(instance_name, action, ok, message or hostops.service_action_success_message(action, instance_name))
    payload = get_hub_payload()
    card = next((item for item in payload["instances"] if item.get("name") == instance_name), None)
    if ok:
        return True, hostops.service_action_success_message(action, instance_name), card
    return False, message or f"Échec {action}", card


def run_instance_update(instance_name: str) -> tuple[bool, str, dict | None]:
    instance = _instance_entry(instance_name)
    if not instance:
        return False, "Instance introuvable", None
    script_path = _main_script_path()
    if not script_path.is_file():
        return False, "Script principal introuvable", None
    host_cli = _host_cli_path()
    if not host_cli.is_file():
        return False, "CLI hôte introuvable", None
    ok, message = hostops.run_command(
        ["sudo", "/usr/bin/python3", str(host_cli), "update-instance", "--main-script", str(script_path), "--instance", instance_name, "--skip-hub-sync", "--source", "Hub"],
        timeout=900,
    )
    _append_action_log(instance_name, "update", ok, message or f"Instance {instance_name} mise à jour")
    payload = get_hub_payload()
    card = next((item for item in payload["instances"] if item.get("name") == instance_name), None)
    if ok:
        return True, f"Instance {instance_name} mise à jour", card
    return False, message or "Échec update", card


def run_instance_redeploy(instance_name: str) -> tuple[bool, str, dict | None]:
    instance = _instance_entry(instance_name)
    if not instance:
        return False, "Instance introuvable", None
    script_path = _main_script_path()
    if not script_path.is_file():
        return False, "Script principal introuvable", None
    host_cli = _host_cli_path()
    if not host_cli.is_file():
        return False, "CLI hôte introuvable", None
    config_file = _instance_config_file(instance_name)
    if not config_file.is_file():
        return False, "deploy_config.env introuvable pour cette instance", None
    ok, message = hostops.run_command(
        ["sudo", "/usr/bin/python3", str(host_cli), "redeploy-instance", "--main-script", str(script_path), "--config", str(config_file), "--source", "Hub"],
        timeout=1200,
    )
    _append_action_log(instance_name, "redeploy", ok, message or f"Instance {instance_name} redéployée")
    payload = get_hub_payload()
    card = next((item for item in payload["instances"] if item.get("name") == instance_name), None)
    if ok:
        return True, f"Instance {instance_name} redéployée", card
    return False, message or "Échec redéploiement", card


def run_instance_uninstall(instance_name: str) -> tuple[bool, str, dict]:
    instance = _instance_entry(instance_name)
    if not instance:
        return False, "Instance introuvable", get_hub_payload()
    script_path = _main_script_path()
    if not script_path.is_file():
        return False, "Script principal introuvable", get_hub_payload()
    host_cli = _host_cli_path()
    if not host_cli.is_file():
        return False, "CLI hôte introuvable", get_hub_payload()
    initial_payload = get_hub_payload()
    card = _payload_instance_card(initial_payload, instance_name)
    if not card:
        return False, "Instance introuvable", initial_payload
    connected_players = int(((card.get("players") or {}).get("value")) or 0)
    if connected_players > 0:
        message = f"Désinstallation refusée : {connected_players} joueur(s) encore connecté(s). Arrête d'abord le serveur ou attends que tout le monde se déconnecte."
        _append_action_log(instance_name, "uninstall", False, message)
        return False, message, initial_payload
    details: list[str] = []
    state = int(card.get("state") or 0)
    if state != 0:
        service = _instance_service(instance_name)
        if not service:
            message = "Service introuvable pour cette instance"
            _append_action_log(instance_name, "uninstall", False, message)
            return False, message, initial_payload
        details.append(f"Serveur encore en ligne (état {state})")
        details.append(f"Arrêt préalable du service {service}")
        stop_ok, stop_message = hostops.run_command(
            ["sudo", "/usr/bin/python3", str(host_cli), "service-action", "--service", service, "--action", "stop", "--source", "Hub"],
            timeout=180,
        )
        if not stop_ok:
            message = "\n".join(details + [stop_message or f"Échec arrêt préalable de {instance_name}"])
            _append_action_log(instance_name, "uninstall", False, message)
            return False, stop_message or f"Échec arrêt préalable de {instance_name}", initial_payload
        stopped, stopped_payload = _wait_until_instance_offline(instance_name, timeout=180)
        if not stopped:
            message = "\n".join(details + ["Le serveur ne s'est pas arrêté dans le délai imparti"])
            _append_action_log(instance_name, "uninstall", False, message)
            return False, "Le serveur ne s'est pas arrêté dans le délai imparti", stopped_payload
        details.append("Serveur arrêté, désinstallation en cours")
    game_label = (instance.get("game") or "").strip()
    game_id = next((gid for gid, meta in instanceenv.GAME_META.items() if meta.get("label") == game_label), "")
    cmd = ["sudo", "/usr/bin/python3", str(host_cli), "uninstall-instance", "--main-script", str(script_path), "--instance", instance_name, "--source", "Hub"]
    if game_id:
        cmd.extend(["--game-id", game_id])
    ok, message = hostops.run_command(
        cmd,
        timeout=1200,
    )
    log_message = "\n".join(details + ([message] if message else [f"Instance {instance_name} désinstallée"]))
    _append_action_log(instance_name, "uninstall", ok, log_message)
    payload = get_hub_payload()
    if ok:
        return True, f"Instance {instance_name} désinstallée", payload
    return False, message or "Échec désinstallation", payload


def run_instance_deploy(data: dict) -> tuple[bool, str, dict]:
    game_id = (data.get("game_id") or "").strip()
    instance_name = (data.get("instance") or "").strip()
    domain = (data.get("domain") or "").strip()
    url_prefix = (data.get("url_prefix") or "").strip()
    admin_password = data.get("admin_password") or ""
    if not game_id or not instance_name or not domain or not admin_password:
        return False, "Jeu, identifiant, domaine et mot de passe admin sont requis", get_hub_payload()
    if _instance_entry(instance_name) or _instance_config_file(instance_name).is_file():
        return False, "Une instance avec cet identifiant existe déjà", get_hub_payload()
    if url_prefix:
        normalized_prefix = url_prefix if url_prefix.startswith("/") else f"/{url_prefix}"
        for item in _load_manifest().get("instances", []):
            if (item.get("prefix") or "").strip() == normalized_prefix:
                return False, "Ce chemin web Commander est déjà utilisé", get_hub_payload()
    script_path = _main_script_path()
    if not script_path.is_file():
        return False, "Script principal introuvable", get_hub_payload()
    host_cli = _host_cli_path()
    if not host_cli.is_file():
        return False, "CLI hôte introuvable", get_hub_payload()
    cmd = [
        "sudo", "/usr/bin/python3", str(host_cli), "deploy-instance",
        "--main-script", str(script_path),
        "--game-id", game_id,
        "--instance", instance_name,
        "--domain", domain,
        "--admin-login", (data.get("admin_login") or "admin").strip() or "admin",
        "--admin-password", admin_password,
        "--sys-user", (data.get("sys_user") or _default_sys_user()).strip() or _default_sys_user(),
        "--source", "Hub",
    ]
    if url_prefix:
        cmd.extend(["--url-prefix", normalized_prefix])
    if data.get("server_name"):
        cmd.extend(["--server-name", str(data.get("server_name"))])
    if data.get("server_password"):
        cmd.extend(["--server-password", str(data.get("server_password"))])
    if data.get("server_port"):
        cmd.extend(["--server-port", str(data.get("server_port"))])
    if data.get("max_players"):
        cmd.extend(["--max-players", str(data.get("max_players"))])
    ok, message = hostops.run_command(cmd, timeout=1800)
    _append_action_log(instance_name, "deploy", ok, message or f"Instance {instance_name} déployée")
    payload = get_hub_payload()
    if ok:
        return True, f"Instance {instance_name} déployée", payload
    return False, message or "Échec déploiement", payload


def run_instance_admin_password_reset(instance_name: str, new_password: str) -> tuple[bool, str, dict | None]:
    instance = _instance_entry(instance_name)
    if not instance:
        return False, "Instance introuvable", None
    new_password = (new_password or "").strip()
    if len(new_password) < 8:
        return False, "Le nouveau mot de passe doit contenir au moins 8 caractères", None
    users_file = _instance_users_file(instance_name)
    game_file = _instance_game_json(instance_name)
    if not users_file.is_file():
        return False, "users.json introuvable pour cette instance", None
    if not game_file.is_file():
        return False, "game.json introuvable pour cette instance", None

    try:
        users = json.loads(users_file.read_text(encoding="utf-8"))
    except Exception:
        return False, "users.json illisible", None
    try:
        game = json.loads(game_file.read_text(encoding="utf-8"))
    except Exception:
        return False, "game.json illisible", None

    admin_login = _instance_admin_login(instance_name)
    permissions = list((users.get(admin_login) or {}).get("permissions") or game.get("permissions") or [])
    users[admin_login] = {
        "password_hash": bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode(),
        "permissions": permissions,
    }
    users_file.write_text(json.dumps(users, indent=2) + "\n", encoding="utf-8")
    try:
        uid = pwd.getpwnam((_load_instance_env(instance_name).get("SYS_USER") or "").strip() or _default_sys_user()).pw_uid
        gid = pwd.getpwnam((_load_instance_env(instance_name).get("SYS_USER") or "").strip() or _default_sys_user()).pw_gid
        os.chown(users_file, uid, gid)
    except Exception:
        pass
    try:
        users_file.chmod(0o600)
    except OSError:
        pass

    message = f"Mot de passe admin Commander réinitialisé pour {instance_name} ({admin_login})"
    _append_action_log(instance_name, "admin", True, message)
    payload = get_hub_payload()
    card = next((item for item in payload["instances"] if item.get("name") == instance_name), None)
    return True, message, card


# ── Discord channel management ───────────────────────────────────────────────

def _discord_cfg_path() -> Path:
    env = os.environ.get("GC_DISCORD_CONFIG")
    if env:
        return Path(env)
    from shared import discordnotify
    for p in discordnotify.DEFAULT_CONFIG_PATHS:
        if Path(p).is_file():
            return Path(p)
    return Path(discordnotify.DEFAULT_CONFIG_PATHS[0])


def _load_discord_cfg() -> dict:
    from shared import discordnotify
    return discordnotify.load_config()


def _save_discord_cfg(cfg: dict) -> tuple[bool, str]:
    from shared import discordnotify
    return discordnotify.save_config(cfg, _discord_cfg_path())


def get_discord_status() -> dict:
    cfg = _load_discord_cfg()
    instances = _load_manifest().get("instances", [])
    instance_channels = cfg.get("instance_channels") or {}
    result = []
    for inst in instances:
        name = inst.get("name", "")
        result.append({
            "name": name,
            "game": inst.get("game", ""),
            "channel_id": instance_channels.get(name, ""),
        })
    return {
        "configured": bool(cfg.get("bot_token")),
        "guild_id": cfg.get("guild_id", ""),
        "category_id": cfg.get("category_id", ""),
        "instances": result,
    }


def set_discord_config(data: dict) -> tuple[bool, str]:
    cfg = _load_discord_cfg()
    if "guild_id" in data:
        cfg["guild_id"] = str(data["guild_id"]).strip()
    if "category_id" in data:
        cfg["category_id"] = str(data["category_id"]).strip()
    return _save_discord_cfg(cfg)


def create_discord_channel(instance_name: str) -> tuple[bool, str]:
    from shared import discordnotify
    cfg = _load_discord_cfg()
    if not cfg.get("bot_token"):
        return False, "Bot token non configuré"
    guild_id = cfg.get("guild_id", "").strip()
    if not guild_id:
        return False, "guild_id non configuré dans discord.json"
    channel_name = instance_name.lower().replace("_", "-")
    ok, msg, channel_id = discordnotify.create_channel(
        guild_id, channel_name, cfg["bot_token"],
        category_id=cfg.get("category_id") or None,
    )
    if not ok:
        return False, f"Erreur Discord API : {msg}"
    instance_channels = cfg.setdefault("instance_channels", {})
    instance_channels[instance_name] = channel_id
    saved, save_msg = _save_discord_cfg(cfg)
    if not saved:
        return False, f"Channel créé ({channel_id}) mais discord.json non mis à jour : {save_msg}"
    return True, f"Channel #{channel_name} créé (id: {channel_id})"


def delete_discord_channel(instance_name: str) -> tuple[bool, str]:
    from shared import discordnotify
    cfg = _load_discord_cfg()
    if not cfg.get("bot_token"):
        return False, "Bot token non configuré"
    channel_id = (cfg.get("instance_channels") or {}).get(instance_name, "")
    if not channel_id:
        return False, "Aucun channel Discord associé à cette instance"
    ok, msg = discordnotify.delete_channel(channel_id, cfg["bot_token"])
    if not ok:
        return False, f"Erreur Discord API : {msg}"
    cfg.get("instance_channels", {}).pop(instance_name, None)
    _save_discord_cfg(cfg)
    return True, f"Channel supprimé"


def get_discord_permissions(instance_name: str) -> tuple[bool, str, list]:
    from shared import discordnotify
    cfg = _load_discord_cfg()
    if not cfg.get("bot_token"):
        return False, "Bot token non configuré", []
    channel_id = (cfg.get("instance_channels") or {}).get(instance_name, "")
    if not channel_id:
        return False, "Aucun channel Discord associé à cette instance", []
    ok, msg, overwrites = discordnotify.get_channel_overwrites(channel_id, cfg["bot_token"])
    return ok, msg, overwrites


def add_discord_permission(instance_name: str, data: dict) -> tuple[bool, str]:
    from shared import discordnotify
    cfg = _load_discord_cfg()
    if not cfg.get("bot_token"):
        return False, "Bot token non configuré"
    channel_id = (cfg.get("instance_channels") or {}).get(instance_name, "")
    if not channel_id:
        return False, "Aucun channel Discord associé à cette instance"
    target_id = str(data.get("target_id", "")).strip()
    target_type = data.get("target_type", "member")
    if not target_id:
        return False, "target_id requis"
    if target_type not in ("member", "role"):
        return False, "target_type doit être 'member' ou 'role'"
    ok, msg = discordnotify.set_permission_overwrite(
        channel_id, target_id, target_type, cfg["bot_token"],
        allow=discordnotify.PERM_READ_ALLOW, deny=0,
    )
    if not ok:
        return False, f"Erreur Discord API : {msg}"
    return True, f"Accès accordé à {target_id}"


def remove_discord_permission(instance_name: str, target_id: str) -> tuple[bool, str]:
    from shared import discordnotify
    cfg = _load_discord_cfg()
    if not cfg.get("bot_token"):
        return False, "Bot token non configuré"
    channel_id = (cfg.get("instance_channels") or {}).get(instance_name, "")
    if not channel_id:
        return False, "Aucun channel Discord associé à cette instance"
    ok, msg = discordnotify.remove_permission_overwrite(channel_id, target_id, cfg["bot_token"])
    if not ok:
        return False, f"Erreur Discord API : {msg}"
    return True, "Accès retiré"


def run_rebalance(restart: bool = False) -> tuple[bool, str, dict]:
    script_path = _main_script_path()
    if not script_path.is_file():
        return False, "Script principal introuvable", get_hub_payload()
    host_cli = _host_cli_path()
    if not host_cli.is_file():
        return False, "CLI hôte introuvable", get_hub_payload()
    cmd = ["sudo", "/usr/bin/python3", str(host_cli), "rebalance", "--main-script", str(script_path), "--source", "Hub"]
    if restart:
        cmd.append("--restart")
    ok, message = hostops.run_command(cmd, timeout=900)
    payload = get_hub_payload()
    if ok:
        label = "Rebalance appliqué" if restart else "Rebalance recalculé"
        return True, label, payload
    return False, message or "Échec rebalance", payload
