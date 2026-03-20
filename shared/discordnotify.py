#!/usr/bin/env python3
"""Optional Discord bot notifications for host actions."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path


DEFAULT_CONFIG_PATHS = (
    "/etc/game-commander/discord.json",
    "/etc/game-commander-discord.json",
)
DISCORD_API_BASE = "https://discord.com/api/v10"

# Permission bits
PERM_VIEW_CHANNEL = 1 << 10       # 1024
PERM_READ_HISTORY = 1 << 16       # 65536
PERM_READ_ALLOW   = PERM_VIEW_CHANNEL | PERM_READ_HISTORY


def _discord_api(
    method: str,
    path: str,
    token: str,
    data: dict | None = None,
    timeout: int = 10,
) -> tuple[bool, str, dict | list | None]:
    """Generic Discord API call. Returns (ok, message, body)."""
    req = urllib.request.Request(
        f"{DISCORD_API_BASE}{path}",
        data=json.dumps(data).encode("utf-8") if data is not None else None,
        headers={
            "Authorization": f"Bot {token}",
            "Content-Type": "application/json",
            "User-Agent": "GameCommanderBot/1.0",
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            body = json.loads(raw) if raw else None
            if 200 <= resp.status < 300:
                return True, "ok", body
            return False, f"http {resp.status}", body
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read())
        except Exception:
            body = None
        return False, f"http {exc.code}", body
    except Exception as exc:
        return False, str(exc), None


def save_config(cfg: dict, path: str | Path | None = None) -> tuple[bool, str]:
    """Write discord config back to the config file."""
    target = Path(path) if path else None
    if target is None:
        env_path = os.environ.get("GC_DISCORD_CONFIG")
        if env_path:
            target = Path(env_path)
        else:
            for p in DEFAULT_CONFIG_PATHS:
                if Path(p).is_file():
                    target = Path(p)
                    break
    if target is None:
        target = Path(DEFAULT_CONFIG_PATHS[0])
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return True, str(target)
    except Exception as exc:
        return False, str(exc)


def list_guild_channels(
    guild_id: str,
    bot_token: str,
    *,
    timeout: int = 10,
) -> tuple[bool, str, list]:
    """List all channels in a guild. Returns (ok, message, channels)."""
    ok, msg, body = _discord_api("GET", f"/guilds/{guild_id}/channels", bot_token, timeout=timeout)
    if not ok:
        return False, msg, []
    return True, "ok", body or []


def find_or_create_game_category(
    guild_id: str,
    game_id: str,
    bot_token: str,
    *,
    timeout: int = 10,
) -> tuple[bool, str, str]:
    """Find existing category for game_id or create it. Returns (ok, message, category_id)."""
    category_name = game_id.lower().replace("_", "-")
    ok, msg, channels = list_guild_channels(guild_id, bot_token, timeout=timeout)
    if not ok:
        return False, msg, ""
    for ch in channels:
        if ch.get("type") == 4 and ch.get("name", "").lower() == category_name:
            return True, "existing", str(ch["id"])
    ok2, msg2, body = _discord_api(
        "POST", f"/guilds/{guild_id}/channels", bot_token,
        data={"name": category_name, "type": 4}, timeout=timeout,
    )
    if not ok2:
        return False, msg2, ""
    category_id = str((body or {}).get("id", ""))
    if not category_id:
        return False, "no category id in response", ""
    return True, "created", category_id


def create_channel(
    guild_id: str,
    name: str,
    bot_token: str,
    *,
    category_id: str | None = None,
    timeout: int = 10,
) -> tuple[bool, str, str]:
    """Create a text channel in the guild. Returns (ok, message, channel_id)."""
    payload: dict = {"name": name, "type": 0}
    if category_id:
        payload["parent_id"] = category_id
    ok, msg, body = _discord_api("POST", f"/guilds/{guild_id}/channels", bot_token, data=payload, timeout=timeout)
    if not ok:
        return False, msg, ""
    channel_id = str((body or {}).get("id", ""))
    if not channel_id:
        return False, "no channel id in response", ""
    return True, "ok", channel_id


def delete_channel(channel_id: str, bot_token: str, *, timeout: int = 10) -> tuple[bool, str]:
    """Delete a Discord channel."""
    ok, msg, _ = _discord_api("DELETE", f"/channels/{channel_id}", bot_token, timeout=timeout)
    return ok, msg


def set_permission_overwrite(
    channel_id: str,
    target_id: str,
    target_type: str,
    bot_token: str,
    *,
    allow: int = PERM_READ_ALLOW,
    deny: int = 0,
    timeout: int = 10,
) -> tuple[bool, str]:
    """Set a permission overwrite. target_type: 'role' (0) or 'member' (1)."""
    type_int = 0 if target_type == "role" else 1
    payload = {"allow": str(allow), "deny": str(deny), "type": type_int}
    ok, msg, _ = _discord_api(
        "PUT", f"/channels/{channel_id}/permissions/{target_id}",
        bot_token, data=payload, timeout=timeout,
    )
    return ok, msg


def remove_permission_overwrite(
    channel_id: str,
    target_id: str,
    bot_token: str,
    *,
    timeout: int = 10,
) -> tuple[bool, str]:
    """Remove a permission overwrite from a channel."""
    ok, msg, _ = _discord_api(
        "DELETE", f"/channels/{channel_id}/permissions/{target_id}",
        bot_token, timeout=timeout,
    )
    return ok, msg


def get_channel_overwrites(
    channel_id: str,
    bot_token: str,
    *,
    timeout: int = 10,
) -> tuple[bool, str, list]:
    """Fetch permission overwrites for a channel."""
    ok, msg, body = _discord_api("GET", f"/channels/{channel_id}", bot_token, timeout=timeout)
    if not ok:
        return False, msg, []
    overwrites = (body or {}).get("permission_overwrites") or []
    return True, "ok", overwrites


def load_config(path: str | Path | None = None) -> dict:
    candidates: list[Path] = []
    if path:
        candidates.append(Path(path))
    else:
        env_path = os.environ.get("GC_DISCORD_CONFIG")
        if env_path:
            candidates.append(Path(env_path))
        candidates.extend(Path(p) for p in DEFAULT_CONFIG_PATHS)
    for candidate in candidates:
        if not candidate.is_file():
            continue
        try:
            return json.loads(candidate.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def list_guild_members(
    guild_id: str,
    bot_token: str,
    *,
    limit: int = 1000,
    timeout: int = 10,
) -> tuple[bool, str, list]:
    """List guild members (requires GUILD_MEMBERS privileged intent).
    Returns (ok, message, members) where each member has user.id and user.username."""
    ok, msg, body = _discord_api(
        "GET", f"/guilds/{guild_id}/members?limit={limit}", bot_token, timeout=timeout,
    )
    if not ok:
        return False, msg, []
    return True, "ok", body or []


def list_guild_roles(
    guild_id: str,
    bot_token: str,
    *,
    timeout: int = 10,
) -> tuple[bool, str, list]:
    """List all roles in a guild. Returns (ok, message, roles)."""
    ok, msg, body = _discord_api("GET", f"/guilds/{guild_id}/roles", bot_token, timeout=timeout)
    if not ok:
        return False, msg, []
    return True, "ok", body or []


def test_connection(cfg: dict, *, timeout: int = 10) -> tuple[bool, str, str]:
    """Test bot token and guild access. Returns (ok, message, bot_username)."""
    token = cfg.get("bot_token", "")
    if not token:
        return False, "Bot token non configuré", ""
    ok, msg, body = _discord_api("GET", "/users/@me", token, timeout=timeout)
    if not ok:
        return False, f"Token invalide ou bot inaccessible : {msg}", ""
    bot_name = (body or {}).get("username", "")
    guild_id = cfg.get("guild_id", "").strip()
    if not guild_id:
        return True, f"Bot connecté ({bot_name}) — ID serveur non configuré", bot_name
    ok2, msg2, _ = _discord_api("GET", f"/guilds/{guild_id}/channels", token, timeout=timeout)
    if not ok2:
        return False, f"Bot connecté ({bot_name}) mais serveur inaccessible : {msg2}", bot_name
    return True, f"Bot connecté ({bot_name}) — serveur accessible ✓", bot_name


def notifications_enabled(cfg: dict) -> bool:
    return bool(cfg.get("enabled", True) and cfg.get("bot_token"))


def resolve_channel_id(cfg: dict, instance_id: str = "", game_id: str = "", event: str = "") -> str:
    instance_channels = cfg.get("instance_channels") or {}
    game_channels = cfg.get("game_channels") or {}
    event_channels = cfg.get("event_channels") or {}
    if instance_id and instance_id in instance_channels:
        return str(instance_channels[instance_id])
    if game_id and game_id in game_channels:
        return str(game_channels[game_id])
    if event and event in event_channels:
        return str(event_channels[event])
    return str(cfg.get("default_channel_id", ""))


def format_event_message(
    *,
    event: str,
    ok: bool,
    instance_id: str = "",
    game_id: str = "",
    service: str = "",
    source: str = "",
    details: str = "",
) -> str:
    subject = instance_id or game_id or service or "Game Commander"
    labels = {
        "start": "Demarrage",
        "stop": "Arret",
        "restart": "Redemarrage",
        "update": "Mise a jour",
        "deploy": "Deploiement",
        "redeploy": "Redeploiement",
        "uninstall": "Desinstallation",
        "rebalance": "Rebalance",
        "bootstrap-hub": "Initialisation du Hub",
        "discord-test": "Test Discord",
    }
    stamp = datetime.now().strftime("%d-%m-%Y %H:%M:%S")
    action = labels.get(event, "Operation")
    origin = f" [{source}]" if source else ""
    return f"{subject}: {stamp} - {action}{origin}"[:1900]


def post_channel_message(bot_token: str, channel_id: str, content: str, timeout: int = 10) -> tuple[bool, str]:
    req = urllib.request.Request(
        f"{DISCORD_API_BASE}/channels/{channel_id}/messages",
        data=json.dumps({"content": content}).encode("utf-8"),
        headers={
            "Authorization": f"Bot {bot_token}",
            "Content-Type": "application/json",
            "User-Agent": "GameCommanderBot/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            if 200 <= response.status < 300:
                return True, "sent"
            return False, f"http {response.status}"
    except urllib.error.HTTPError as exc:
        return False, f"http {exc.code}"
    except Exception as exc:
        return False, str(exc)


def notify_event(
    *,
    event: str,
    ok: bool,
    instance_id: str = "",
    game_id: str = "",
    service: str = "",
    source: str = "",
    details: str = "",
    config: dict | None = None,
) -> tuple[bool, str]:
    cfg = config if config is not None else load_config()
    if not notifications_enabled(cfg):
        return False, "disabled"
    channel_id = resolve_channel_id(cfg, instance_id=instance_id, game_id=game_id, event=event)
    if not channel_id:
        return False, "no-route"
    content = format_event_message(
        event=event,
        ok=ok,
        instance_id=instance_id,
        game_id=game_id,
        service=service,
        source=source,
        details=details,
    )
    return post_channel_message(str(cfg.get("bot_token", "")), channel_id, content)


def send_test_message(
    *,
    event: str = "discord-test",
    instance_id: str = "",
    game_id: str = "",
    source: str = "Hub",
    details: str = "Test de notification Discord Game Commander",
    config: dict | None = None,
) -> tuple[bool, str]:
    cfg = config if config is not None else load_config()
    if not notifications_enabled(cfg):
        return False, "disabled"
    channel_id = resolve_channel_id(cfg, instance_id=instance_id, game_id=game_id, event=event)
    if not channel_id:
        return False, "no-route"
    content = "[TEST] " + format_event_message(
        event=event,
        ok=True,
        instance_id=instance_id,
        game_id=game_id,
        source=source,
        details=details,
    )
    return post_channel_message(str(cfg.get("bot_token", "")), channel_id, content)


def _cli_create_channel(instance_id: str, game_id: str = "") -> int:
    """CLI entry point for deploy_step_discord_channel."""
    import sys
    cfg = load_config()
    if not cfg.get("bot_token"):
        print("Bot token non configuré", file=sys.stderr)
        return 1
    guild_id = cfg.get("guild_id", "").strip()
    if not guild_id:
        print("guild_id non configuré", file=sys.stderr)
        return 1
    existing = (cfg.get("instance_channels") or {}).get(instance_id, "")
    if existing:
        print(f"Channel déjà configuré pour {instance_id} ({existing})")
        return 0
    # Determine category: per-game if game_id provided, fallback to config
    category_id: str | None = cfg.get("category_id") or None
    if game_id:
        ok_cat, msg_cat, cat_id = find_or_create_game_category(guild_id, game_id, cfg["bot_token"])
        if ok_cat:
            category_id = cat_id
        else:
            print(f"Avertissement: catégorie '{game_id}' non trouvée/créée: {msg_cat}", file=sys.stderr)
    channel_name = instance_id.lower().replace("_", "-")
    ok, msg, channel_id = create_channel(
        guild_id, channel_name, cfg["bot_token"],
        category_id=category_id,
    )
    if not ok:
        print(f"Erreur Discord API : {msg}", file=sys.stderr)
        return 1
    cfg.setdefault("instance_channels", {})[instance_id] = channel_id
    saved, save_msg = save_config(cfg)
    if not saved:
        print(f"Channel créé ({channel_id}) mais discord.json non mis à jour : {save_msg}",
              file=sys.stderr)
        return 1
    game_label = f" [{game_id}]" if game_id else ""
    print(f"Channel #{channel_name} créé et enregistré (id: {channel_id}){game_label}")
    return 0


if __name__ == "__main__":
    import argparse, sys
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd")
    p = sub.add_parser("create-channel")
    p.add_argument("--instance", required=True)
    p.add_argument("--game", default="")
    args = parser.parse_args()
    if args.cmd == "create-channel":
        sys.exit(_cli_create_channel(args.instance, args.game))
    parser.print_help()
    sys.exit(1)
