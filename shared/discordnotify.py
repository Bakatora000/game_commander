#!/usr/bin/env python3
"""Optional Discord bot notifications for host actions."""
from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.request
from pathlib import Path


DEFAULT_CONFIG_PATHS = (
    "/etc/game-commander/discord.json",
    "/etc/game-commander-discord.json",
)
DISCORD_API_BASE = "https://discord.com/api/v10"


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
    details: str = "",
) -> str:
    subject = instance_id or game_id or service or "Game Commander"
    content = subject
    details = (details or "").strip()
    if details:
        snippet = details[:1500]
        if len(details) > 1500:
            snippet += "\n..."
        content += f"\n```text\n{snippet}\n```"
    return content[:1900]


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
        details=details,
    )
    return post_channel_message(str(cfg.get("bot_token", "")), channel_id, content)


def send_test_message(
    *,
    event: str = "discord-test",
    instance_id: str = "",
    game_id: str = "",
    details: str = "Test de notification Discord Game Commander",
    config: dict | None = None,
) -> tuple[bool, str]:
    return notify_event(
        event=event,
        ok=True,
        instance_id=instance_id,
        game_id=game_id,
        details=details,
        config=config,
    )
