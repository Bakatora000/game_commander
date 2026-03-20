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

Operational note: systemd drop-in directories (`/etc/systemd/system/<unit>.service.d/`) are
created by cpu_affinity.sh for CPU pinning. `_stop_disable_remove_service()` in
`shared/uninstallcore.py` now removes the drop-in directory with `shutil.rmtree` on uninstall.

Operational note: the Hub Admin must NOT restart during an instance deploy. Restarting the
Hub Flask process (parent of the `subprocess.run(host_cli.py deploy-instance)` chain) breaks
the stdout pipe → tee gets SIGPIPE → bash deploy process dies → all steps after 8B are skipped.
Fix: `deploy_step_hub_service` calls hubsync with `--no-restart`; Hub only restarts during
`bootstrap-hub`, never during instance deploy.

Discord integration note: `shared/discordnotify.py` provides all Discord API functions
(notifications, channel management, permission overwrites). Config lives at
`/etc/game-commander/discord.json` (owned `root:vhserver`, `rw-r-----`). Run
`sudo chmod g+w /etc/game-commander/discord.json` so the Hub (vhserver) can write channel IDs.

Discord channel creation (on deploy and from Hub): `find_or_create_game_category()` scans
the guild channels for an existing category named after the game (`valheim`, `enshrouded`,
`terraria`…), creates it if absent, then creates the instance text channel inside it.
`send_test_message()` always prefixes `[TEST]` to distinguish test messages from real ones.

Hub Discord panel (`/commander` → Discord tab):
- configures guild_id and category_id (fallback) from the UI
- shows all instances with their channel status (create/delete buttons)
- manages read-only permissions per channel (by Discord user ID or role ID)

Operational note: an intermittent phantom Discord notification
`minecraft-fabric: ... - Mise a jour [Hub]` was observed even though no such instance
exists anymore on the host. From user observation, it appears only during some `git`
commands run while development work is in progress, not during normal Hub/Commander UI
actions. The current hypothesis is a stale/background process rather than the live
`host_cli` / Hub notification path, but this remains to be revalidated if it reappears.

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
Terraria has now also reached a usable product baseline in real conditions:
- active world selection from detected `.wld` files
- file manager and backups on the server world directory
- connected players list based on `has joined` / `has left`
- functional vanilla ban management from the Commander
- Terraria-specific advanced server options exposed from `serverconfig.txt`

Operational note: vanilla Terraria bans are not equivalent to Valheim or Minecraft roles.
There is no native whitelist/admin model comparable to those games. The useful vanilla
server-side control exposed so far is the `banlist`, which must store both player name
and IP. For connected players, the Commander correlates:
- `<ip>:<port> is connecting...`
- `<name> has joined.`
to build a valid `banlist` entry.

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
- Satisfactory: `SaveGames/` under the instance-specific Linux data dir
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

Current validated milestone: `v3.0`

Short roadmap after `v3.0`:
- keep stabilizing the separated `Hub Admin` and its guarded host actions
- start the targeted refactorization of host actions so shell becomes thinner and Python becomes the main orchestration layer
- formalize a clearer common contract per game (`config`, `players`, `users`, `saves`, `mods`, lifecycle hooks)
- keep iterating on Satisfactory and Enshrouded once the first refactor lots are in place
- continue UI/CSS/accessibility cleanup incrementally without destabilizing the validated product baseline

Roadmap status update:
- Terraria has now largely caught up to the baseline standard expected for vanilla support
- Enshrouded remains the next best candidate for deeper product work (roles, bans, possible world-slot switching abstraction)
- A later dedicated `terraria-tshock` variant remains a valid product path, but it is deferred
- `Satisfactory` now has a validated first usable product baseline:
  - managed deploy
  - systemd service
  - Commander runtime
  - save/file manager on `SaveGames`
  - backups isolated per instance
  - claim/admin actions via the native HTTPS API
  - connection info with game port and reliable port
  - validated Hub deploy on a live host (`instance_id=satisfactory`)
  - validated runtime state after deploy:
    - `satisfactory-server-satisfactory` active
    - `game-commander-satisfactory` active
    - local Commander reachable on `/satisfactory`
    - `hub-status` reachable with `state=20`
  - validated Satisfactory native admin API after claim:
    - `PasswordlessLogin` reports the server as already claimed
    - admin password login works
    - authenticated reads of server state/options work
  - retained product note:
    - after first deploy, the real game session/world creation is still finalized from the game client side on first connection
- `/commander` is no longer only a landing page:
  - it is now a dedicated Hub Admin Flask app
  - auth is separate from per-instance Commanders
  - first host actions are exposed there (`start/stop/restart`, `update --instance`, `rebalance`, `redeploy`, `uninstall`, `deploy`)
  - it now includes a single global action console for host operations
- the `v3.0` direction is now explicit:
  - keep shell for host-level provisioning and Linux integration
  - move orchestration and product logic progressively into Python
  - use the Hub Admin as the long-term host control surface

Validated `v3.0` status update after the first real Hub deploy tests:
- Hub-triggered `deploy` now exists for new instances, with a minimal non-interactive form
- Hub-triggered `deploy` required multiple hardening fixes that are now in place:
  - dedicated sudoers permission for `deploy-instance`
  - nested `sudo` avoided inside the host CLI when already running as root
  - `deploy_config.env` save now uses the real in-memory deploy values instead of default placeholders
  - `deploy --config` now fails fast if `GAME_ID` or `INSTANCE_ID` are missing instead of silently falling back to an interactive default game flow
  - partial instances left by an interrupted/failed Hub deploy can now be removed cleanly from the Hub even when `deploy_config.env` is missing or invalid
  - Hub action logs now strip ANSI color sequences before writing to the global console

Validated bootstrap note:
- a new `bootstrap-hub` entrypoint now exists for Ubuntu hosts
- it is available both through `sudo bash game_commander.sh bootstrap-hub ...` and through the repository bootstrap script `install_hub.sh`
- the intended end-state is a simple `curl | bash` installation path for the Hub Admin on a fresh server
- public documentation and the Hub deploy form no longer expose static default passwords
- the documented bootstrap flow now defaults to generating an admin password when none is supplied explicitly

Operational constraint:
- the Hub Admin is still singleton per machine
- bootstraping it for another system user on the same host rewires the same shared resources:
  - `game-commander-hub.service`
  - `/etc/sudoers.d/game-commander-hub`
  - shared Game Commander nginx files
- so a second bootstrap on the same host is a replacement/repointing operation, not a parallel multi-user Hub install

Operational note:
- during the first real Hub deploy validation, a partial `minecraft2` instance was created and then successfully removed through the Hub cleanup path
- this validated the partial-instance uninstall fallback and confirmed that existing managed instances such as `valheim-main` were not overwritten by that failed deploy path

## Adding a New Game

1. Create `runtime/games/{id}/config.py` and/or `runtime/games/{id}/mods.py` with the expected function signatures
2. Create `runtime/templates/games/{id}/app.html` and `login.html` extending the base templates
3. Create `runtime/static/themes/{id}/theme.css` and `login.css`
4. Create `runtime/game_{id}.json` with all required fields
