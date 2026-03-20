"""Interactive configuration flow — replaces lib/deploy_configure.sh."""
from __future__ import annotations

from pathlib import Path

_here = Path(__file__).resolve().parent.parent
import sys
if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))

from shared import console, deployenv, deployplan, instanceenv
from shared.deployconfig import DeployConfig


# ── Internal helpers ──────────────────────────────────────────────────────────

def _apply_env_dict(cfg: DeployConfig, d: dict[str, str]) -> None:
    """Merge a flat env dict back into cfg (only non-empty values overwrite)."""
    for key, val in d.items():
        if not val:
            continue
        attr = key.lower()
        if hasattr(cfg, attr):
            existing = getattr(cfg, attr)
            if isinstance(existing, bool):
                setattr(cfg, attr, val.lower() in ("true", "1", "yes"))
            else:
                setattr(cfg, attr, val)


def _warn_port_conflicts(cfg: DeployConfig) -> None:
    conflicts = deployplan.describe_port_conflicts(
        game_id=cfg.game_id,
        server_port=int(cfg.server_port or "0"),
        query_port=int(cfg.query_port or "0"),
        echo_port=int(cfg.echo_port or "0"),
        game_service=cfg.game_service,
    )
    for _proto, label, port, proto_label in conflicts:
        console.warn(f"{label} {port}/{proto_label} déjà utilisé")


# ── Configuration sub-steps ───────────────────────────────────────────────────

def _select_game(cfg: DeployConfig, script_dir: Path) -> bool:
    """Select game or confirm from config. Returns False if cancelled."""
    print()
    if not cfg.game_id:
        if cfg.deploy_mode == "attach":
            print("  \033[1mJeu du serveur existant :\033[0m")
        else:
            print("  \033[1mJeu à déployer :\033[0m")
        for line in deployplan.game_menu_lines():
            key, _, label = line.partition("|")
            print(f"  \033[0;36m[{key}]\033[0m {label}")
        print()
        choice = console.prompt("Votre choix", "1")
        accepted, game_id = deployplan.resolve_game_choice(choice, default_game_id="valheim")
        if not accepted:
            return False
        cfg.game_id = game_id
    else:
        print(f"  \033[2m  (config) Jeu : \033[1m{cfg.game_id}\033[0m")

    # Apply game defaults
    env = deployenv.apply_game_defaults(cfg.to_env())
    _apply_env_dict(cfg, env)

    # Load game metadata from deployplan.game_meta()
    meta = deployplan.game_meta(cfg.game_id)
    cfg.game_label   = meta.get("label", cfg.game_id)
    cfg.game_binary  = meta.get("game_binary", "")
    cfg.steam_appid  = meta.get("steam_appid", "")
    if not cfg.game_service:
        cfg.game_service = instanceenv.default_game_service(cfg.game_id, cfg.instance_id)
    if not cfg.gc_service:
        cfg.gc_service = f"game-commander-{cfg.instance_id}" if cfg.instance_id else ""

    console.ok(f"Jeu sélectionné : \033[1m{cfg.game_label}\033[0m")
    return True


def _configure_mode(cfg: DeployConfig) -> None:
    print()
    console.info("Mode de déploiement")
    if cfg.config_mode:
        print(f"  \033[2m  (config) Mode : \033[1m{cfg.deploy_mode}\033[0m")
    else:
        print(f"  \033[2m  (menu) Mode : \033[1m{cfg.deploy_mode}\033[0m")
    console.ok(f"Mode sélectionné : \033[1m{cfg.deploy_mode}\033[0m")


def _configure_user(cfg: DeployConfig) -> None:
    print()
    console.info("Utilisateur système")
    if cfg.config_mode:
        print(f"  \033[2m  (config) SYS_USER : \033[1m{cfg.sys_user}\033[0m")
    else:
        cfg.sys_user = console.prompt("Nom d'utilisateur", cfg.sys_user)

    exists, home_dir = deployplan.get_user_info(cfg.sys_user)
    if not exists:
        console.warn(f"L'utilisateur '{cfg.sys_user}' n'existe pas.")
        if console.confirm(f"Créer {cfg.sys_user} ?"):
            ok, msg = deployplan.create_system_user(cfg.sys_user)
            if not ok:
                console.die(f"Création de l'utilisateur échouée : {msg}")
            console.ok(f"Utilisateur {cfg.sys_user} créé")
            if not cfg.config_mode:
                import sys, io
                pw = console.prompt_secret(f"Mot de passe système pour {cfg.sys_user}")
                # feed password to stdin of set_user_password_stdin via subprocess
                import subprocess
                r = subprocess.run(
                    ["chpasswd"],
                    input=f"{cfg.sys_user}:{pw}\n",
                    text=True, check=False,
                )
                if r.returncode == 0:
                    console.ok("Mot de passe défini")
                else:
                    console.warn("Mot de passe non défini")
            exists, home_dir = deployplan.get_user_info(cfg.sys_user)
        else:
            console.die("Utilisateur requis.")

    cfg.home_dir = home_dir
    console.ok(f"Utilisateur : {cfg.sys_user} ({home_dir})")


def _prepare_instance_defaults(cfg: DeployConfig) -> None:
    """Apply instance path defaults via deployplan."""
    defaults = deployplan.apply_instance_defaults(
        game_id=cfg.game_id,
        instance_id=cfg.instance_id,
        home_dir=cfg.home_dir,
        src_dir=cfg.src_dir or str(Path(__file__).resolve().parent.parent),
        server_dir=cfg.server_dir,
        data_dir=cfg.data_dir,
        backup_dir=cfg.backup_dir,
        app_dir=cfg.app_dir,
        game_service=cfg.game_service,
    )
    _apply_env_dict(cfg, defaults)


def _configure_paths(cfg: DeployConfig, script_dir: Path) -> None:
    print()
    console.info("Instance")

    prev_instance    = cfg.instance_id
    prev_server_dir  = cfg.server_dir
    prev_data_dir    = cfg.data_dir
    prev_app_dir     = cfg.app_dir
    prev_game_service = cfg.game_service

    if cfg.config_mode:
        print(f"  \033[2m  (config) INSTANCE_ID : \033[1m{cfg.instance_id}\033[0m")
    else:
        cfg.instance_id = console.prompt("Identifiant d'instance (unique par serveur)", cfg.instance_id)

    # Re-compute paths when instance_id changes
    updated = deployplan.update_instance_paths(
        game_id=cfg.game_id,
        instance_id=cfg.instance_id,
        home_dir=cfg.home_dir,
        server_dir=cfg.server_dir,
        data_dir=cfg.data_dir,
        app_dir=cfg.app_dir,
        game_service=cfg.game_service,
        prev_instance=prev_instance,
        prev_server_dir=prev_server_dir,
        prev_data_dir=prev_data_dir,
        prev_app_dir=prev_app_dir,
        prev_game_service=prev_game_service,
    )
    _apply_env_dict(cfg, updated)

    # Refresh gc_service now that instance_id is confirmed
    cfg.gc_service = f"game-commander-{cfg.instance_id}"

    console.info("Chemins")
    if cfg.config_mode:
        print(f"  \033[2m  (config) SERVER_DIR : \033[1m{cfg.server_dir}\033[0m")
        if cfg.game_id != "enshrouded":
            print(f"  \033[2m  (config) DATA_DIR   : \033[1m{cfg.data_dir}\033[0m")
        print(f"  \033[2m  (config) BACKUP_DIR : \033[1m{cfg.backup_dir}\033[0m")
        print(f"  \033[2m  (config) APP_DIR    : \033[1m{cfg.app_dir}\033[0m")
        print(f"  \033[2m  (config) SRC_DIR    : \033[1m{cfg.src_dir}\033[0m")
    else:
        cfg.server_dir = console.prompt(f"Répertoire serveur {cfg.game_label}", cfg.server_dir)
        if cfg.game_id != "enshrouded":
            cfg.data_dir = console.prompt("Répertoire données de jeu", cfg.data_dir)
        else:
            cfg.data_dir = cfg.server_dir
        cfg.backup_dir = console.prompt("Répertoire sauvegardes", cfg.backup_dir)
        cfg.app_dir    = console.prompt("Répertoire Game Commander", cfg.app_dir)
        cfg.src_dir    = console.prompt(
            "Dossier source Game Commander (racine du projet)",
            cfg.src_dir or str(script_dir),
        )

    # Check runtime sources
    resolved = deployenv.runtime_src_dir(cfg.src_dir) if cfg.src_dir else ""
    if not resolved:
        console.warn(f"runtime/app.py introuvable dans {cfg.src_dir} — Game Commander ne sera pas déployé")
        cfg.deploy_app = False
    else:
        cfg.deploy_app = True
        console.ok("Sources Game Commander trouvées")

    if cfg.deploy_mode == "attach":
        if cfg.config_mode:
            print(f"  \033[2m  (config) GAME_SERVICE : \033[1m{cfg.game_service}\033[0m")
        else:
            cfg.game_service = console.prompt(
                "Nom du service systemd existant", cfg.game_service
            )
        exists_svc, _ = deployplan.get_user_info(cfg.sys_user)  # reuse for service check
        # Use deployplan.check_port_conflict as proxy — just print status
        import subprocess
        r = subprocess.run(
            ["systemctl", "is-active", "--quiet", cfg.game_service],
            check=False,
        )
        if r.returncode == 0:
            console.ok(f"Service existant détecté : {cfg.game_service}")
        else:
            console.warn(f"Service systemd non détecté : {cfg.game_service}")


def _configure_server(cfg: DeployConfig, script_dir: Path) -> bool:
    """Returns False if cancelled."""
    print()
    console.info(f"Configuration du serveur {cfg.game_label}")

    if cfg.config_mode:
        print(f"  \033[2m  (config) SERVER_NAME : \033[1m{cfg.server_name}\033[0m")
        print(f"  \033[2m  (config) SERVER_PASSWORD : \033[1m{'(défini)' if cfg.server_password else '(vide)'}\033[0m")
    else:
        cfg.server_name     = console.prompt("Nom du serveur", cfg.server_name)
        cfg.server_password = console.prompt_secret("Mot de passe (vide = public)", cfg.server_password)

    # Suggest free port group (managed mode only)
    if cfg.deploy_mode != "attach":
        suggested = deployplan.suggest_free_port_group(
            game_id=cfg.game_id,
            server_port=int(cfg.server_port or "0"),
            query_port=int(cfg.query_port or "0"),
            echo_port=int(cfg.echo_port or "0"),
            game_service=cfg.game_service,
        )
        if suggested.get("CONFLICT_LABEL"):
            console.warn(
                f"{suggested['CONFLICT_LABEL']} {suggested.get('CONFLICT_PORT', '')}"
                f"/{suggested.get('CONFLICT_PROTO_LABEL', '')} déjà utilisé — groupe de ports suggéré mis à jour"
            )
        _apply_env_dict(cfg, suggested)

    if cfg.config_mode:
        print(f"  \033[2m  (config) SERVER_PORT : \033[1m{cfg.server_port}\033[0m")
    else:
        cfg.server_port = console.prompt("Port principal", cfg.server_port)

    if cfg.game_id in ("soulmask", "satisfactory"):
        lbl = "Port fiable / join" if cfg.game_id == "satisfactory" else "Port Query"
        if cfg.config_mode:
            print(f"  \033[2m  (config) QUERY_PORT : \033[1m{cfg.query_port}\033[0m")
        else:
            cfg.query_port = console.prompt(lbl, cfg.query_port)
        if cfg.game_id == "soulmask":
            if cfg.config_mode:
                print(f"  \033[2m  (config) ECHO_PORT : \033[1m{cfg.echo_port}\033[0m")
            else:
                cfg.echo_port = console.prompt("Port Echo", cfg.echo_port)

    if cfg.deploy_mode != "attach":
        _warn_port_conflicts(cfg)

    if cfg.config_mode:
        print(f"  \033[2m  (config) MAX_PLAYERS : \033[1m{cfg.max_players}\033[0m")
    else:
        cfg.max_players = console.prompt("Joueurs max", cfg.max_players)

    if cfg.game_id == "valheim":
        if cfg.config_mode:
            print(f"  \033[2m  (config) WORLD_NAME : \033[1m{cfg.world_name}\033[0m")
            print(f"  \033[2m  (config) Crossplay : \033[1m{'Oui' if cfg.crossplay else 'Non'}\033[0m")
            print(f"  \033[2m  (config) BepInEx   : \033[1m{'Oui' if cfg.bepinex else 'Non'}\033[0m")
        else:
            cfg.world_name = console.prompt("Nom du monde", cfg.world_name)
            cfg.crossplay  = console.confirm("Activer le crossplay ?", "n")
            cfg.bepinex    = console.confirm("Installer BepInEx (mods) ?")

        if cfg.crossplay:
            other = deployplan.detect_other_valheim_process()
            if other:
                cfg.gc_force_playfab = True
                console.warn("Une autre instance Valheim est déjà en cours d'exécution")
                console.warn(f"  {other}")
                console.warn("Le flag -crossplay sera remplacé par -playfab (multi-instance PlayFab).")

    elif cfg.game_id == "soulmask":
        if cfg.config_mode:
            print(f"  \033[2m  (config) Mode serveur : \033[1m{cfg.server_mode}\033[0m")
            print(f"  \033[2m  (config) Backups auto : \033[1m{cfg.backup_enabled}\033[0m")
            print(f"  \033[2m  (config) Sauvegardes  : \033[1m{cfg.saving_enabled}\033[0m")
            print(f"  \033[2m  (config) Backup intervalle : \033[1m{cfg.backup_interval}\033[0m")
        else:
            cfg.server_mode    = "pve"
            cfg.backup_enabled = console.confirm("Activer les backups Soulmask ?")
            cfg.saving_enabled = console.confirm("Activer les sauvegardes périodiques ?")
        if cfg.config_mode:
            print(f"  \033[2m  (config) BACKUP_INTERVAL : \033[1m{cfg.backup_interval}\033[0m")
        else:
            cfg.backup_interval = console.prompt("Intervalle backup (secondes)", cfg.backup_interval)

    print()
    console.info("Interface web Game Commander")
    if cfg.config_mode:
        print(f"  \033[2m  (config) DOMAIN     : \033[1m{cfg.domain}\033[0m")
        print(f"  \033[2m  (config) URL_PREFIX : \033[1m{cfg.url_prefix}\033[0m")
    else:
        cfg.domain     = console.prompt("Domaine", cfg.domain)
        cfg.url_prefix = console.prompt("Préfixe URL", cfg.url_prefix).rstrip("/")

    # Check for existing prefix owner
    _conf, existing_owner = deployplan.existing_prefix_owner(cfg.domain, cfg.url_prefix)
    cfg.flask_port = str(deployplan.next_free_flask_port(int(cfg.flask_port or "0")))

    if existing_owner and not cfg.config_mode:
        console.warn(f"Le préfixe '{cfg.url_prefix}' est déjà utilisé sur {cfg.domain}")
        console.warn(f"  → proxy_pass existant : http://127.0.0.1:{existing_owner}")
        print()
        print(f"  Suggestions : \033[1m/commander\033[0m  /gc  /gameadmin  /{cfg.game_id}")
        print()
        cfg.url_prefix = console.prompt("Nouveau préfixe URL", f"/{cfg.game_id}").rstrip("/")

    if cfg.config_mode:
        print(f"  \033[2m  (config) FLASK_PORT : \033[1m{cfg.flask_port}\033[0m")
    else:
        cfg.flask_port = console.prompt("Port Flask interne", cfg.flask_port)

    # SSL mode
    if cfg.config_mode:
        print(f"  \033[2m  (config) SSL : \033[1m{cfg.ssl_mode}\033[0m")
    else:
        print("  \033[1mSSL :\033[0m")
        print("  \033[0;36m[0]\033[0m Quit")
        print("  \033[0;36m[1]\033[0m Certbot (Let's Encrypt)")
        print("  \033[0;36m[2]\033[0m HTTP uniquement")
        print("  \033[0;36m[3]\033[0m SSL déjà configuré")
        ssl_choice = console.prompt("Configuration SSL", "3")
        accepted, ssl_mode = deployplan.resolve_ssl_mode(ssl_choice)
        if not accepted:
            return False
        cfg.ssl_mode = ssl_mode

    return True


def _configure_admin(cfg: DeployConfig) -> None:
    print()
    console.info("Compte administrateur Game Commander")
    if cfg.config_mode:
        print(f"  \033[2m  (config) ADMIN_LOGIN : \033[1m{cfg.admin_login}\033[0m")
        print(f"  \033[2m  (config) ADMIN_PASSWORD : \033[1m{'(défini)' if cfg.admin_password else '(vide)'}\033[0m")
    else:
        cfg.admin_login = console.prompt("Identifiant admin", cfg.admin_login)
        if not cfg.admin_password:
            cfg.admin_password = console.prompt_secret(f"Mot de passe pour {cfg.admin_login}")

    if cfg.config_mode and not cfg.admin_password:
        users_file = Path(cfg.app_dir or "") / "users.json"
        if users_file.is_file():
            console.info("ADMIN_PASSWORD absent du fichier de config — users.json existant conservé")
            return

    if not cfg.admin_password:
        console.die("Mot de passe admin obligatoire.")


def _print_summary(cfg: DeployConfig) -> None:
    console.hdr("RÉCAPITULATIF")
    print()
    for line in deployplan.render_summary(cfg.to_env()):
        if not line:
            continue
        label, _, value = line.partition(": ")
        print(f"  \033[1m{label}:\033[0m {value}")
    print()
    console.sep()


# ── Public entry point ────────────────────────────────────────────────────────

def run_configure(cfg: DeployConfig, script_dir: Path) -> bool:
    """
    Run the interactive configuration flow.
    Returns True if the user confirmed and deploy should proceed, False to abort.
    """
    console.hdr("ÉTAPE 2 : Configuration")

    if not _select_game(cfg, script_dir):
        return False

    _configure_mode(cfg)
    _configure_user(cfg)
    _prepare_instance_defaults(cfg)
    _configure_paths(cfg, script_dir)

    if not _configure_server(cfg, script_dir):
        return False

    _configure_admin(cfg)
    _print_summary(cfg)

    if cfg.auto_confirm:
        console.ok("Confirmation automatique (AUTO_CONFIRM=true)")
    elif not console.confirm("Lancer l'installation ?"):
        console.die("Annulé.")

    return True
