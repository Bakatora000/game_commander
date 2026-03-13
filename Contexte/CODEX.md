# CODEX.md

This file provides guidance to Codex when working with code in this repository.

## Overview

**Game Commander** is a generic Flask web interface for managing game servers (Valheim, Enshrouded, Minecraft Java, Minecraft Fabric) without AMP. It uses `psutil` + `systemd` + `bcrypt`. One instance of the app manages one game server, selected by `game.json`.

Current server state noted in project memory: no active Game Commander instance is deployed
at the moment; AMP instances still coexist on the same machine and must not be impacted by
tests or fixes.

Validated deployment note: Enshrouded discovery depends on `queryPort` (`SERVER_PORT + 1`),
not only the base game port. With a firewall range limited to `15636-15639`, use
`SERVER_PORT=15638` so the server is discoverable on `:15639`.

Operational note: orphan-process detection during uninstall must ignore any process still
attached to a systemd service cgroup. This is required for Wine-based Enshrouded servers.

Validated deployment note: Minecraft Java support provisions a vanilla `server.jar`,
`eula.txt`, `server.properties`, a Java systemd service, and the Game Commander UI.
The player client version must match the downloaded server version.

Validated deployment note: Minecraft Fabric support is now functional in real deployment.
The deploy provisions a Fabric launcher, `eula.txt`, `server.properties`, `.fabric-meta.json`,
the `mods/` directory, a Java systemd service, and the Game Commander UI. Mod installation
uses Modrinth and also reads `fabric.mod.json` inside downloaded JARs so required dependencies
such as `fabric-api` are installed automatically when Modrinth metadata is incomplete.

Validated deployment note: Minecraft Java and Minecraft Fabric also expose a connected
players list in the UI by parsing server logs (`joined the game` / `left the game`).

## Running the App

```bash
# 1. Select a game config
cp runtime/game_valheim.json runtime/game.json   # or runtime/game_enshrouded.json

# 2. Create users.json with an admin account
python3 -c "
import bcrypt, json
pw = input('Password: ').encode()
h  = bcrypt.hashpw(pw, bcrypt.gensalt()).decode()
print(json.dumps({'admin': {'password_hash': h, 'permissions': []}}, indent=2))
" > runtime/users.json

# 3. Launch
export GAME_COMMANDER_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
python3 runtime/app.py
```

The app is deployed behind Nginx (for example `gaming.example.com.conf`). Flask listens on `127.0.0.1:<flask_port>` from `runtime/game.json`.

## Deployment Script

```bash
sudo bash game_commander.sh              # interactive menu
sudo bash game_commander.sh deploy       # guided deploy
sudo bash game_commander.sh status       # show all instances
sudo bash game_commander.sh update --instance testfabric
sudo bash game_commander.sh uninstall --dry-run
```

`game_commander.sh` is now a thin entrypoint that sources the bash modules under `lib/`
(`cmd_deploy.sh`, `deploy_helpers.sh`, `deploy_configure.sh`, `deploy_steps.sh`,
`cmd_uninstall.sh`, `uninstall_gc.sh`, `uninstall_flask.sh`, `uninstall_orphans.sh`,
`cmd_update.sh`,
`cmd_status.sh`, `nginx.sh`).

Nginx management is also split out into `tools/nginx_manager.py`, which maintains a
manifest and a generated locations file rather than repeatedly editing inline blocks for
each instance.

Operational note: deployed instances are copies of the runtime app. Repository fixes do
not update existing instances automatically. The `update` command is now the supported way
to resync an installed instance runtime and regenerate its `game.json` without reinstalling
the game server itself.

## Architecture

### Config-driven game selection (`runtime/game.json`)

`runtime/app.py` reads `runtime/game.json` at startup to determine everything: routes (`web.url_prefix`), port (`web.flask_port`), which feature modules to load (`features.mods`, `features.config`, `features.console`), theme, and game-specific paths. The active `runtime/game.json` is copied from one of the `runtime/game_*.json` templates.

Key fields: `id` (public game id), `module_id` (Python module id, useful for names like `minecraft-fabric`), `template_id` (template directory id), `server.binary` (psutil lookup), `server.service` (systemd unit name), `web.admin_user` (superuser who always gets all permissions).

### Route/API structure (`runtime/app.py`)

All routes are prefixed with `PREFIX` from `game.json`. Common routes:
- `GET {PREFIX}/` → redirect to `/app` or `/login`
- `GET {PREFIX}/app` → game-specific `runtime/templates/games/{id}/app.html`
- `POST {PREFIX}/api/login` → session auth
- `GET/POST {PREFIX}/api/status`, `/api/updates`, `/api/metrics`
- `POST {PREFIX}/api/start|stop|restart` (requires perms)
- `GET/POST {PREFIX}/api/config` (loaded only if `features.config`)
- `GET/POST {PREFIX}/api/mods/*` (loaded only if `features.mods`)
- `GET/POST {PREFIX}/api/world_modifiers` (Valheim only)
- `GET {PREFIX}/api/players` (Valheim / Enshrouded / Minecraft Java / Minecraft Fabric)
- `POST {PREFIX}/api/update` → SteamCMD update in background thread

### Auth (`runtime/core/auth.py`)

Users stored in `runtime/users.json` (bcrypt hashed passwords). The `admin_user` (from `runtime/game.json`) always receives all permissions listed in `runtime/game.json["permissions"]`. Non-admin users have an explicit permission list. Two decorators: `@auth.require_auth` (session check) and `@auth.require_perm('perm_name')`.

### Server control (`runtime/core/server.py`)

Finds the game process by binary name + port via `psutil`, with a fallback to `systemctl show <service> --property=MainPID` for Wine-based games (Enshrouded runs as a `.exe` under Wine). Start/stop/restart call `sudo /usr/bin/systemctl`. Console reads from `journalctl -u <service>` with cursor-based polling.

### Metrics (`runtime/core/metrics.py`)

Append-only JSON Lines file (`metrics.log`). Background thread polls every 30s, purges entries older than 24h every ~30 minutes. `state=20` means online (AMP-compatible convention).

### Game modules (`runtime/games/{id}/`)

Each game can provide:
- `mods.py` — `search_mods(q)`, `get_installed_mods()`, `install_mod(ns, name, ver)`, `remove_mod(name)`
- `config.py` — `read_config()`, `write_config(data)`
- `players.py` — `get_players()` (returns list)
- `world_modifiers.py` — `read_modifiers()`, `write_modifiers(data)`, `get_schema()` (Valheim only)

Modules are conditionally imported at startup based on `features.*` flags. Missing modules produce a `[WARN]` log and disable the feature.

### Templates and themes

- `runtime/templates/base/app_base.html` and `login_base.html` — shared Jinja2 block structure
- `runtime/templates/games/{id}/app.html` and `login.html` — game-specific overrides
- `runtime/static/common.css` — layout only (no colors)
- `runtime/static/themes/{name}/theme.css` and `login.css` — per-game colors/branding

Jinja2 context always has: `game` (full config dict), `prefix`, `game_id`, `module_id`, `template_id`, `theme_name`.

## Versioning

At each milestone, create a git commit and push to `origin/main`. Bump the version in the `game_commander.sh` header (line 3, `v2.x`) accordingly.

Current validated milestone: `v2.1`

## Adding a New Game

1. Create `runtime/games/{id}/config.py` and/or `runtime/games/{id}/mods.py` with the expected function signatures
2. Create `runtime/templates/games/{id}/app.html` and `login.html` extending the base templates
3. Create `runtime/static/themes/{id}/theme.css` and `login.css`
4. Create `runtime/game_{id}.json` with all required fields
