"""DeployConfig — mutable state object shared across the deploy pipeline."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DeployConfig:
    # ── Core identity ──────────────────────────────────────────────────────────
    game_id: str = ""
    instance_id: str = ""
    deploy_mode: str = "managed"   # "managed" | "attach"

    # ── System user ───────────────────────────────────────────────────────────
    sys_user: str = "gameserver"
    home_dir: str = ""

    # ── Paths ─────────────────────────────────────────────────────────────────
    server_dir: str = ""
    data_dir: str = ""
    backup_dir: str = ""
    app_dir: str = ""
    src_dir: str = ""

    # ── Game config ───────────────────────────────────────────────────────────
    world_name: str = "Monde1"
    server_name: str = "Mon Serveur"
    server_password: str = ""
    server_admin_password: str = ""
    server_port: str = ""
    query_port: str = ""
    echo_port: str = ""
    max_players: str = ""
    server_mode: str = "pve"
    backup_enabled: bool = True
    saving_enabled: bool = True
    backup_interval: str = "7200"
    crossplay: bool = False
    bepinex: bool = True

    # ── Web / nginx ───────────────────────────────────────────────────────────
    domain: str = "monserveur.example.com"
    url_prefix: str = ""
    flask_port: str = ""
    ssl_mode: str = "existing"

    # ── Admin ─────────────────────────────────────────────────────────────────
    admin_login: str = "admin"
    admin_password: str = ""

    # ── Automation flags ──────────────────────────────────────────────────────
    auto_install_deps: bool = True
    auto_install_steamcmd: bool = True
    auto_install_bepinex: bool = True
    auto_update_server: bool = False
    auto_confirm: bool = False

    # ── Deploy mode control ───────────────────────────────────────────────────
    config_mode: bool = False
    config_file_deploy: str = ""

    # ── Game metadata (set by _select_game) ───────────────────────────────────
    game_label: str = ""
    game_binary: str = ""
    steam_appid: str = ""
    game_service: str = ""

    # ── Runtime state (set during deploy) ─────────────────────────────────────
    gc_service: str = ""
    deploy_app: bool = True
    gc_bepinex_path: str = ""
    gc_force_playfab: bool = False
    steamcmd_path: str = ""
    config_save: str = ""
    logfile: str = ""

    # ── helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _b(v: bool) -> str:
        return "true" if v else "false"

    def to_env(self) -> dict[str, str]:
        """Return a flat string-valued dict usable by deploypost/deployplan."""
        b = self._b
        return {
            "GAME_ID":               self.game_id,
            "INSTANCE_ID":           self.instance_id,
            "DEPLOY_MODE":           self.deploy_mode,
            "SYS_USER":              self.sys_user,
            "SERVER_DIR":            self.server_dir,
            "DATA_DIR":              self.data_dir,
            "BACKUP_DIR":            self.backup_dir,
            "APP_DIR":               self.app_dir,
            "SRC_DIR":               self.src_dir,
            "GAME_SERVICE":          self.game_service,
            "SERVER_NAME":           self.server_name,
            "SERVER_PASSWORD":       self.server_password,
            "SERVER_ADMIN_PASSWORD": self.server_admin_password,
            "SERVER_PORT":           self.server_port,
            "QUERY_PORT":            self.query_port,
            "ECHO_PORT":             self.echo_port,
            "MAX_PLAYERS":           self.max_players,
            "SERVER_MODE":           self.server_mode,
            "BACKUP_ENABLED":        b(self.backup_enabled),
            "SAVING_ENABLED":        b(self.saving_enabled),
            "BACKUP_INTERVAL":       self.backup_interval,
            "WORLD_NAME":            self.world_name,
            "CROSSPLAY":             b(self.crossplay),
            "BEPINEX":               b(self.bepinex),
            "DOMAIN":                self.domain,
            "URL_PREFIX":            self.url_prefix,
            "FLASK_PORT":            self.flask_port,
            "SSL_MODE":              self.ssl_mode,
            "ADMIN_LOGIN":           self.admin_login,
            "ADMIN_PASSWORD":        self.admin_password,
            "AUTO_INSTALL_DEPS":     b(self.auto_install_deps),
            "AUTO_INSTALL_STEAMCMD": b(self.auto_install_steamcmd),
            "AUTO_INSTALL_BEPINEX":  b(self.auto_install_bepinex),
            "AUTO_UPDATE_SERVER":    b(self.auto_update_server),
            "AUTO_CONFIRM":          b(self.auto_confirm),
            "GAME_LABEL":            self.game_label,
            "GAME_BINARY":           self.game_binary,
            "STEAM_APPID":           self.steam_appid,
        }

    @classmethod
    def from_env(cls, env: dict[str, str]) -> "DeployConfig":
        def bv(v: str) -> bool:
            return v.lower() in ("true", "1", "yes")

        c = cls()
        c.game_id                = env.get("GAME_ID", "")
        c.instance_id            = env.get("INSTANCE_ID", "")
        c.deploy_mode            = env.get("DEPLOY_MODE", "managed")
        c.sys_user               = env.get("SYS_USER", "gameserver")
        c.server_dir             = env.get("SERVER_DIR", "")
        c.data_dir               = env.get("DATA_DIR", "")
        c.backup_dir             = env.get("BACKUP_DIR", "")
        c.app_dir                = env.get("APP_DIR", "")
        c.src_dir                = env.get("SRC_DIR", "")
        c.game_service           = env.get("GAME_SERVICE", "")
        c.server_name            = env.get("SERVER_NAME", "Mon Serveur")
        c.server_password        = env.get("SERVER_PASSWORD", "")
        c.server_admin_password  = env.get("SERVER_ADMIN_PASSWORD", "")
        c.server_port            = env.get("SERVER_PORT", "")
        c.query_port             = env.get("QUERY_PORT", "")
        c.echo_port              = env.get("ECHO_PORT", "")
        c.max_players            = env.get("MAX_PLAYERS", "")
        c.server_mode            = env.get("SERVER_MODE", "pve")
        c.backup_enabled         = bv(env.get("BACKUP_ENABLED", "true"))
        c.saving_enabled         = bv(env.get("SAVING_ENABLED", "true"))
        c.backup_interval        = env.get("BACKUP_INTERVAL", "7200")
        c.world_name             = env.get("WORLD_NAME", "Monde1")
        c.crossplay              = bv(env.get("CROSSPLAY", "false"))
        c.bepinex                = bv(env.get("BEPINEX", "true"))
        c.domain                 = env.get("DOMAIN", "monserveur.example.com")
        c.url_prefix             = env.get("URL_PREFIX", "")
        c.flask_port             = env.get("FLASK_PORT", "")
        c.ssl_mode               = env.get("SSL_MODE", "existing")
        c.admin_login            = env.get("ADMIN_LOGIN", "admin")
        c.admin_password         = env.get("ADMIN_PASSWORD", "")
        c.auto_install_deps      = bv(env.get("AUTO_INSTALL_DEPS", "true"))
        c.auto_install_steamcmd  = bv(env.get("AUTO_INSTALL_STEAMCMD", "true"))
        c.auto_install_bepinex   = bv(env.get("AUTO_INSTALL_BEPINEX", "true"))
        c.auto_update_server     = bv(env.get("AUTO_UPDATE_SERVER", "false"))
        c.auto_confirm           = bv(env.get("AUTO_CONFIRM", "false"))
        c.game_label             = env.get("GAME_LABEL", "")
        c.game_binary            = env.get("GAME_BINARY", "")
        c.steam_appid            = env.get("STEAM_APPID", "")
        return c
