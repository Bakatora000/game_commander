# CODEX.md

This file provides guidance to Codex when working with code in this repository.

## Overview

**Game Commander** is now both:
- a deployment/operations shell tool (`game_commander.sh`)
- a per-instance Flask web UI
- and a shared Nginx hub entrypoint at `/commander`

One Flask instance still manages one game server, selected by `game.json`, but the normal
user-facing entrypoint is now the shared hub URL rather than direct instance URLs.

Current server state noted in project memory: Game Commander is now treated as the primary
stack. Historical coexistence constraints with older external managers should no longer
shape normal product or documentation decisions.

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

Validated deployment note: Minecraft Java and Minecraft Fabric backups now target only the
world data plus the main administrative files (`server.properties`, `ops.json`,
`whitelist.json`, `banned-players.json`, `banned-ips.json`, `usercache.json`), not the
full server directory.

Validated deployment note: Terraria vanilla support is now validated for installation,
world creation/loading, Linux systemd service, Nginx integration, and the Game Commander
UI. The startup path was hardened to pass the critical world/server parameters directly
to `TerrariaServer.bin.x86_64` rather than relying only on `-config serverconfig.txt`.
The systemd launch also uses a PTY wrapper (`script -qefc`) to avoid the high CPU behavior
seen when the Terraria server runs headless without a pseudo-terminal.

Validated deployment note: Valheim support has now reached a stable beta-test state in
real use. The current validated scope includes:
- active world selection without automatic restart
- world modifiers tied to the selected world
- BetterNetworking configuration when the mod is installed
- file manager on `worlds_local`
- manual/scheduled backups and restores
- Valheim-specific protected deletion flow for current world files
- player actions from the dashboard (`admin`, `whitelist`, `ban`)
- manual management of `adminlist.txt`, `bannedlist.txt`, and `permittedlist.txt`

Operational note: on PlayFab-backed Valheim instances, the player `SteamID` may be logged
via `received local Platform ID Steam_<id>` instead of `Got connection SteamID ...`.
The player parser must support both patterns.

Implementation note: Soulmask vanilla is now implemented and has been partially validated
in a real deployment cycle.
It adds a generic multi-port-group deployment path (`game/query/echo`) and a Soulmask
runtime/config UI based on `soulmask_server.json`.
Validated so far:
- deploy + systemd service
- Game Commander UI
- config save/apply + restart
- grouped ports (`8777/udp`, `27015/udp`, `18888/tcp`)
- launcher fix to avoid duplicated flags passed to the official startup wrapper
Remaining point to validate later:
- real in-game connection and CPU behavior with one or more players connected
Observed behavior during real validation:
- Soulmask starts and stops noticeably more slowly than the other currently supported games
- CPU must be evaluated only after a few minutes of stabilization following `start`/`restart`

## Running the App

The normal product flow is no longer “copy a template game JSON and run Flask manually”.

Operationally:
- instances are deployed through `game_commander.sh`
- `runtime/game.json` and `runtime/users.json` are generated per instance
- repository changes are propagated to an installed instance through `update --instance ...`

The app is deployed behind Nginx (for example `gaming.example.com.conf`). Flask listens on
`127.0.0.1:<flask_port>` from `runtime/game.json`. The shared Nginx entrypoint `/commander`
lists available instances and links to each instance UI.

## Deployment Script

```bash
sudo bash game_commander.sh              # interactive menu
sudo bash game_commander.sh deploy       # guided deploy
sudo bash game_commander.sh attach       # attach Commander to an existing service
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
each instance. It also generates the shared static hub page served at `/commander`.

Operational note: deployed instances are copies of the runtime app. Repository fixes do
not update existing instances automatically. The `update` command is now the supported way
to resync an installed instance runtime and regenerate its `game.json` without reinstalling
the game server itself.

Validated deployment note: a new `attach` deployment mode now exists. It deploys only the
Commander runtime/UI on top of an existing game systemd service, without reinstalling the
game server or creating a new game service. This was validated in real conditions by
attaching a second Commander instance to an existing Soulmask service and exercising
`start/stop/restart` through the attached UI.

Operational note: the `update` command now preserves a custom `GAME_SERVICE`, which is
required for instances deployed in `attach` mode.

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
- `GET {PREFIX}/api/players` (Valheim / Enshrouded / Minecraft Java / Minecraft Fabric / Soulmask)
- `POST {PREFIX}/api/update` → SteamCMD update in background thread
- `GET {PREFIX}/api/saves`, `POST {PREFIX}/api/saves/upload|delete`
- `GET {PREFIX}/api/saves/download`
- `GET {PREFIX}/api/backups`, `POST {PREFIX}/api/backups/create|upload|restore|delete`
- `GET {PREFIX}/api/backups/download`

### Auth (`runtime/core/auth.py`)

Users stored in `runtime/users.json` (bcrypt hashed passwords). The `admin_user` (from `runtime/game.json`) always receives all permissions listed in `runtime/game.json["permissions"]`. Non-admin users have an explicit permission list. Two decorators: `@auth.require_auth` (session check) and `@auth.require_perm('perm_name')`.

### Server control (`runtime/core/server.py`)

Finds the game process by binary name + port via `psutil`, with a fallback to `systemctl show <service> --property=MainPID` for Wine-based games (Enshrouded runs as a `.exe` under Wine). Start/stop/restart call `sudo /usr/bin/systemctl`. Console reads from `journalctl -u <service>` with cursor-based polling.

### Metrics (`runtime/core/metrics.py`)

Append-only JSON Lines file (`metrics.log`). Background thread polls every 30s, purges entries older than 24h every ~30 minutes. `state=20` means online.

### Game modules (`runtime/games/{id}/`)

Each game can provide:
- `mods.py` — `search_mods(q)`, `get_installed_mods()`, `install_mod(ns, name, ver)`, `remove_mod(name)`
- `config.py` — `read_config()`, `write_config(data)`
- `players.py` — `get_players()` (returns list)
- `world_modifiers.py` — `read_modifiers()`, `write_modifiers(data)`, `get_schema()` (Valheim only)

Modules are conditionally imported at startup based on `features.*` flags. Missing modules produce a `[WARN]` log and disable the feature.

Current backup policy by game:
- Valheim: world files only (`.db`, `.fwl`, `.old`)
- Enshrouded: `savegame/`
- Minecraft Java / Fabric: `world/` + main admin files
- Terraria: server world/data directory
- Soulmask: `WS/Saved`

Current save manager scope:
- browse real save directories per game
- upload files into allowed save folders
- delete files/subfolders inside allowed save roots
- list backup archives
- create/download/upload/restore/delete backup archives
- restore flow stops the server if needed, creates a backup first, then restarts

### Templates and themes

- `runtime/templates/base/app_base.html` and `login_base.html` — shared Jinja2 block structure
- `runtime/templates/games/{id}/app.html` and `login.html` — game-specific overrides
- `runtime/static/common.css` — layout only (no colors)
- `runtime/static/themes/{name}/theme.css` and `login.css` — per-game colors/branding

Jinja2 context always has: `game` (full config dict), `prefix`, `game_id`, `module_id`, `template_id`, `theme_name`.

## Versioning

At each milestone, create a git commit and push to `origin/main`. Bump the version in the `game_commander.sh` header (line 3, `v2.x`) accordingly.

Current validated milestone: `v2.3`

Short roadmap after `v2.3`:
- keep beta-testing Valheim / Minecraft Java / Minecraft Fabric and fix regressions first
- propagate the Valheim-level product standard to Terraria, then Enshrouded
- keep Soulmask at its current baseline unless beta feedback reveals specific missing product features
- continue UI/CSS/accessibility cleanup incrementally after the first theme-system pass
- preserve `/commander` as the normal entrypoint and keep hub status independent from per-instance auth

## Adding a New Game

1. Create `runtime/games/{id}/config.py` and/or `runtime/games/{id}/mods.py` with the expected function signatures
2. Create `runtime/templates/games/{id}/app.html` and `login.html` extending the base templates
3. Create `runtime/static/themes/{id}/theme.css` and `login.css`
4. Create `runtime/game_{id}.json` with all required fields
