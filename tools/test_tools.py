#!/usr/bin/env python3
"""
test_tools.py — Tests automatisés pour nginx_manager.py et config_gen.py

Usage :
  python3 tools/test_tools.py            # tous les tests
  python3 tools/test_tools.py NginxTests # seulement les tests nginx
"""

import json
import io
import os
import pwd
import re
import sys
import tempfile
import time
import types
import unittest
import zipfile
from pathlib import Path
from unittest import mock
from flask import Flask
from werkzeug.datastructures import FileStorage

# Ajouter le répertoire tools/ au path pour importer les modules
TOOLS_DIR = Path(__file__).parent
ROOT_DIR = TOOLS_DIR.parent
sys.path.insert(0, str(TOOLS_DIR))
sys.path.insert(0, str(ROOT_DIR))

import nginx_manager
import config_gen
from shared import appfiles, appservice, bootstraphub, cpuplan, deploybackups, deploycore, deploydeps, deployenv, deploynginx, deployplan, deploypost, deployssl, deploysudo, discordnotify, gameinstall, gameservice, hostctl, hostops, hubsync, instanceenv, redeploycore, startscripts, uninstallcore, updatecore, updatehooks
from runtime.games.minecraft import config as minecraft_config
from runtime.games.minecraft import admins as minecraft_admins
from runtime.games.minecraft import console as minecraft_console
from runtime.games.minecraft import players as minecraft_players
from runtime.games.minecraft_fabric import mods as minecraft_fabric_mods
from runtime.games.valheim import mods as valheim_mods
from runtime.games.valheim import valheimplus as valheim_valheimplus
from runtime.core import saves as core_saves
from runtime.games.valheim import worlds as valheim_worlds
from runtime.games.valheim import admins as valheim_admins
from runtime.games.valheim import players as valheim_players
from runtime.games.soulmask import players as soulmask_players
from runtime.games.soulmask import config as soulmask_config
from runtime.games.enshrouded import config as enshrouded_config
from runtime.games.enshrouded import players as enshrouded_players
from runtime.games.enshrouded import worlds as enshrouded_worlds
from runtime.games.terraria import config as terraria_config
from runtime.games.terraria import admins as terraria_admins
from runtime.games.terraria import worlds as terraria_worlds
from runtime.games.terraria import players as terraria_players
from runtime.games.satisfactory import config as satisfactory_config
from runtime.games.valheim import world_modifiers as valheim_world_modifiers
from runtime.core import server as core_server
from runtime_hub.core import auth as hub_auth
from runtime_hub.core import host as hub_host


# ── Helpers ────────────────────────────────────────────────────────────────────

def make_args(**kwargs):
    """Crée un objet args factice pour appeler les fonctions directement."""
    return types.SimpleNamespace(**kwargs)


def tmp_file(content: str, suffix: str = ".conf") -> str:
    """Crée un fichier temporaire avec le contenu donné. Retourne le chemin."""
    f = tempfile.NamedTemporaryFile(mode="w", suffix=suffix, delete=False)
    f.write(content)
    f.close()
    return f.name


def tmp_path(suffix: str = ".json") -> str:
    """Retourne un chemin temporaire (fichier non créé)."""
    f = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    f.close()
    os.unlink(f.name)
    return f.name


# ══════════════════════════════════════════════════════════════════════════════
# NGINX MANAGER
# ══════════════════════════════════════════════════════════════════════════════

NGINX_SSL_BLOCK = """\
server {
    server_name gaming.example.com;

    location / {
        try_files $uri $uri/ =404;
    }

    listen 443 ssl;
    ssl_certificate /etc/letsencrypt/live/gaming.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/gaming.example.com/privkey.pem;
}
server {
    if ($host = gaming.example.com) { return 301 https://$host$request_uri; }
    listen 80;
    server_name gaming.example.com;
    return 404;
}
"""

NGINX_NO_SSL = """\
server {
    listen 80;
    server_name gaming.example.com;

    location / {
        try_files $uri $uri/ =404;
    }
}
"""

NGINX_EMPTY_SERVER = """\
server {
    listen 80;
    server_name gaming.example.com;
}
"""


class NginxInjectTests(unittest.TestCase):

    # ── inject dans bloc SSL ───────────────────────────────────────────────

    def test_inject_ssl_block(self):
        """Injecte dans le bloc server SSL (listen 443)."""
        conf = tmp_file(NGINX_SSL_BLOCK)
        try:
            rc = nginx_manager.cmd_inject(make_args(
                conf=conf, instance_id="valheim8",
                prefix="/valheim8", port=5002, label="Valheim",
            ))
            self.assertEqual(rc, 0)
            content = Path(conf).read_text()
            self.assertIn("location /valheim8 {", content)
            self.assertIn("proxy_pass         http://127.0.0.1:5002;", content)
            self.assertIn("client_max_body_size 2G;", content)
            self.assertIn("location /valheim8/static {", content)
            # Doit être dans le bloc SSL, pas dans le bloc HTTP redirect
            ssl_block_end = content.index("return 404")
            inject_pos = content.index("location /valheim8")
            self.assertLess(inject_pos, ssl_block_end,
                            "Le bloc doit être injecté dans le serveur SSL, pas après")
        finally:
            os.unlink(conf)


class SharedHelpersTests(unittest.TestCase):

    def test_render_gc_service_contains_expected_fields(self):
        content = appservice.render_gc_service(
            game_label="Valheim",
            game_service="valheim-server-test",
            sys_user="vhserver",
            app_dir="/tmp/game-commander-test",
            gc_secret="abc123",
        )
        self.assertIn("Description=Game Commander — Valheim", content)
        self.assertIn("Wants=valheim-server-test.service", content)
        self.assertIn('Environment="GAME_COMMANDER_SECRET=abc123"', content)
        self.assertIn("ExecStart=/usr/bin/python3 /tmp/game-commander-test/app.py", content)

    def test_inject_no_ssl_fallback(self):
        """Injecte avant location / quand pas de SSL."""
        conf = tmp_file(NGINX_NO_SSL)
        try:
            rc = nginx_manager.cmd_inject(make_args(
                conf=conf, instance_id="valheim8",
                prefix="/valheim8", port=5002, label="Valheim",
            ))
            self.assertEqual(rc, 0)
            content = Path(conf).read_text()
            self.assertIn("location /valheim8 {", content)
            # Doit apparaître avant location /
            self.assertLess(content.index("/valheim8"), content.index("location / {"))
        finally:
            os.unlink(conf)

    def test_inject_empty_server_fallback(self):
        """Injecte avant la dernière } quand pas de location / ni SSL."""
        conf = tmp_file(NGINX_EMPTY_SERVER)
        try:
            rc = nginx_manager.cmd_inject(make_args(
                conf=conf, instance_id="valheim8",
                prefix="/valheim8", port=5002, label="Valheim",
            ))
            self.assertEqual(rc, 0)
            content = Path(conf).read_text()
            self.assertIn("location /valheim8 {", content)
        finally:
            os.unlink(conf)

    def test_inject_idempotent(self):
        """Injecter deux fois ne duplique pas le bloc."""
        conf = tmp_file(NGINX_SSL_BLOCK)
        try:
            nginx_manager.cmd_inject(make_args(
                conf=conf, instance_id="valheim8",
                prefix="/valheim8", port=5002, label="Valheim",
            ))
            nginx_manager.cmd_inject(make_args(
                conf=conf, instance_id="valheim8",
                prefix="/valheim8", port=5002, label="Valheim",
            ))
            content = Path(conf).read_text()
            self.assertEqual(content.count("location /valheim8 {"), 1,
                             "Le bloc ne doit apparaître qu'une seule fois")
        finally:
            os.unlink(conf)

    def test_inject_multiple_instances(self):
        """Plusieurs instances dans le même fichier."""
        conf = tmp_file(NGINX_SSL_BLOCK)
        try:
            nginx_manager.cmd_inject(make_args(
                conf=conf, instance_id="valheim8",
                prefix="/valheim8", port=5002, label="Valheim",
            ))
            nginx_manager.cmd_inject(make_args(
                conf=conf, instance_id="enshrouded2",
                prefix="/enshrouded2", port=5004, label="Enshrouded",
            ))
            content = Path(conf).read_text()
            self.assertIn("location /valheim8 {", content)
            self.assertIn("location /enshrouded2 {", content)
            self.assertIn("127.0.0.1:5002", content)
            self.assertIn("127.0.0.1:5004", content)
        finally:
            os.unlink(conf)

    def test_inject_creates_backup(self):
        """Un fichier .bak est créé lors de l'injection."""
        conf = tmp_file(NGINX_SSL_BLOCK)
        try:
            nginx_manager.cmd_inject(make_args(
                conf=conf, instance_id="valheim8",
                prefix="/valheim8", port=5002, label="Valheim",
            ))
            baks = list(Path(conf).parent.glob(Path(conf).name + ".bak.*"))
            self.assertEqual(len(baks), 1, "Un backup doit être créé")
        finally:
            os.unlink(conf)


class HostCtlTests(unittest.TestCase):

    def test_parse_env_file_reads_simple_pairs(self):
        with tempfile.TemporaryDirectory() as d:
            env_path = Path(d) / "deploy_config.env"
            env_path.write_text('INSTANCE_ID="valheim2"\nGAME_ID="valheim"\n', encoding="utf-8")
            data = hostctl.parse_env_file(env_path)
            self.assertEqual(data["INSTANCE_ID"], "valheim2")
            self.assertEqual(data["GAME_ID"], "valheim")

    def test_discover_instance_configs_filters_non_gc_envs(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            good_dir = root / "game-commander-valheim2"
            bad_dir = root / "other"
            good_dir.mkdir()
            bad_dir.mkdir()
            (good_dir / "deploy_config.env").write_text(
                'INSTANCE_ID="valheim2"\nGAME_ID="valheim"\n',
                encoding="utf-8",
            )
            (bad_dir / "deploy_config.env").write_text(
                'INSTANCE_ID="ghost"\n',
                encoding="utf-8",
            )
            configs = hostctl.discover_instance_configs(search_roots=[str(root)])
            self.assertEqual(configs, [(good_dir / "deploy_config.env").resolve()])

    def test_resolve_instance_config_returns_matching_config(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            first_dir = root / "game-commander-a"
            second_dir = root / "game-commander-b"
            first_dir.mkdir()
            second_dir.mkdir()
            (first_dir / "deploy_config.env").write_text(
                'INSTANCE_ID="alpha"\nGAME_ID="valheim"\n',
                encoding="utf-8",
            )
            target = second_dir / "deploy_config.env"
            target.write_text(
                'INSTANCE_ID="beta"\nGAME_ID="satisfactory"\n',
                encoding="utf-8",
            )
            resolved = hostctl.resolve_instance_config("beta", search_roots=[str(root)])
            self.assertEqual(resolved, target.resolve())


class InstanceEnvTests(unittest.TestCase):

    def test_default_game_service_uses_game_prefix(self):
        self.assertEqual(instanceenv.default_game_service("valheim", "valheim2"), "valheim-server-valheim2")
        self.assertEqual(instanceenv.default_game_service("minecraft-fabric", "fabric"), "minecraft-fabric-server-fabric")

    def test_load_instance_record_applies_defaults(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d) / "deploy_config.env"
            cfg.write_text(
                'INSTANCE_ID="enshrouded2"\n'
                'GAME_ID="enshrouded"\n'
                'APP_DIR="/home/vhserver/game-commander-enshrouded2"\n',
                encoding="utf-8",
            )
            record = instanceenv.load_instance_record(cfg)
            self.assertEqual(record["game_label"], "Enshrouded")
            self.assertEqual(record["game_binary"], "enshrouded_server.exe")
            self.assertEqual(record["game_service"], "enshrouded-server-enshrouded2")


class UpdateCoreTests(unittest.TestCase):

    def test_runtime_src_dir_prefers_runtime_subdir(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            runtime = root / "runtime"
            runtime.mkdir()
            (runtime / "app.py").write_text("", encoding="utf-8")
            self.assertEqual(updatecore.runtime_src_dir(root), runtime)

    def test_run_core_update_requires_existing_app_dir(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "runtime").mkdir()
            (root / "runtime" / "app.py").write_text("", encoding="utf-8")
            cfg = root / "deploy_config.env"
            cfg.write_text(
                'INSTANCE_ID="valheim2"\n'
                'GAME_ID="valheim"\n'
                'APP_DIR="/tmp/does-not-exist-gc"\n'
                'SYS_USER="root"\n',
                encoding="utf-8",
            )
            ok, message = updatecore.run_core_update(cfg, root)
            self.assertFalse(ok)
            self.assertIn("APP_DIR introuvable", message)


class UpdateHooksTests(unittest.TestCase):

    def test_run_post_update_hooks_requires_instance(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d) / "deploy_config.env"
            cfg.write_text('GAME_ID="valheim"\n', encoding="utf-8")
            ok, message = updatehooks.run_post_update_hooks(cfg, d)
            self.assertFalse(ok)
            self.assertIn("Config d'instance incomplète", message)


class UninstallCoreTests(unittest.TestCase):

    def test_run_full_uninstall_requires_instance(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d) / "deploy_config.env"
            cfg.write_text('GAME_ID="valheim"\n', encoding="utf-8")
            ok, message = uninstallcore.run_full_uninstall(cfg, d)
            self.assertFalse(ok)
            self.assertIn("Config d'instance incomplète", message)


class HubSyncTests(unittest.TestCase):

    def test_sync_hub_service_requires_sys_user(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d) / "deploy_config.env"
            cfg.write_text('GAME_ID="valheim"\nINSTANCE_ID="v1"\n', encoding="utf-8")
            ok, message = hubsync.sync_hub_service(cfg, ROOT_DIR)
            self.assertFalse(ok)
            self.assertIn("SYS_USER manquant", message)

    def test_sync_hub_service_from_values_requires_sys_user(self):
        ok, message = hubsync.sync_hub_service_from_values(
            sys_user="",
            app_dir="/tmp/gc-test",
            admin_login="admin",
            admin_password="secret123",
            repo_root=ROOT_DIR,
        )
        self.assertFalse(ok)
        self.assertIn("SYS_USER manquant", message)


class BootstrapHubTests(unittest.TestCase):

    def test_run_bootstrap_hub_generates_password_when_missing(self):
        fake_pwd = types.SimpleNamespace(pw_dir="/home/test", pw_uid=1000, pw_gid=1000)
        with mock.patch.object(bootstraphub.pwd, "getpwnam", return_value=fake_pwd), \
             mock.patch.object(bootstraphub, "_install_dependencies", return_value=(True, ["deps ok"])), \
             mock.patch.object(bootstraphub, "_ensure_state_dir") as ensure_state, \
             mock.patch.object(bootstraphub.hubsync, "sync_hub_service_from_values", return_value=(True, ["hub ok"])) as sync_hub, \
             mock.patch.object(bootstraphub, "_bootstrap_nginx", return_value=(True, ["nginx ok"])), \
             mock.patch.object(bootstraphub.deployssl, "apply_ssl", return_value=(True, ["ssl ok"])), \
             mock.patch.object(bootstraphub, "_open_hub_ports", return_value=["ufw ok"]):
            ok, messages = bootstraphub.run_bootstrap_hub(
                repo_root=ROOT_DIR,
                sys_user="test",
                domain="gaming.example.com",
                admin_login="admin",
                admin_password="",
                ssl_mode="none",
            )
        self.assertTrue(ok)
        self.assertIn("deps ok", messages)
        self.assertIn("hub ok", messages)
        self.assertIn("nginx ok", messages)
        self.assertIn("ssl ok", messages)
        self.assertIn("ufw ok", messages)
        self.assertIn("Hub Admin : http://gaming.example.com/commander", messages)
        self.assertTrue(any(line.startswith("Mot de passe admin généré : ") for line in messages))
        ensure_state.assert_called_once_with("test")
        sync_hub.assert_called_once()


class DeployEnvTests(unittest.TestCase):

    def test_normalize_deploy_env_applies_game_defaults(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d) / "deploy_config.env"
            cfg.write_text('GAME_ID="satisfactory"\nINSTANCE_ID="sat1"\n', encoding="utf-8")
            env = deployenv.normalize_deploy_env(cfg)
            self.assertEqual(env["SERVER_PORT"], "7777")
            self.assertEqual(env["QUERY_PORT"], "8888")
            self.assertEqual(env["URL_PREFIX"], "/satisfactory")
            self.assertEqual(env["FLASK_PORT"], "5007")

    def test_prepare_managed_instance_env_builds_expected_paths(self):
        env = deployenv.prepare_managed_instance_env(
            game_id="enshrouded",
            instance_id="enshrouded2",
            sys_user="vhserver",
            repo_root="/home/vhserver/gc",
            domain="gaming.example.com",
            admin_login="admin",
            admin_password="secret123",
            url_prefix="/enshrouded2",
        )
        self.assertEqual(env["DEPLOY_MODE"], "managed")
        self.assertEqual(env["SERVER_DIR"], "/home/vhserver/enshrouded2_server")
        self.assertEqual(env["DATA_DIR"], "/home/vhserver/enshrouded2_server")
        self.assertEqual(env["APP_DIR"], "/home/vhserver/game-commander-enshrouded2")
        self.assertEqual(env["GAME_SERVICE"], "enshrouded-server-enshrouded2")
        self.assertEqual(env["URL_PREFIX"], "/enshrouded2")
        self.assertEqual(env["FLASK_PORT"], "5003")

    def test_fill_defaults_from_process_env_applies_game_defaults(self):
        with mock.patch.dict("os.environ", {"GAME_ID": "terraria", "SERVER_PORT": "", "FLASK_PORT": ""}, clear=False):
            env = deployenv.fill_defaults_from_process_env()
        self.assertEqual(env["SERVER_PORT"], "7777")
        self.assertEqual(env["URL_PREFIX"], "/terraria")
        self.assertEqual(env["FLASK_PORT"], "5006")

    def test_render_template_contains_expected_game_list(self):
        template = deployenv.render_template()
        self.assertIn('GAME_ID="valheim"', template)
        self.assertIn("minecraft-fabric", template)
        self.assertIn('AUTO_CONFIRM=true', template)

    def test_runtime_src_dir_finds_runtime_subdir(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            runtime_dir = root / "runtime"
            runtime_dir.mkdir()
            (runtime_dir / "app.py").write_text("", encoding="utf-8")
            self.assertEqual(deployenv.runtime_src_dir(root), runtime_dir)

    def test_validate_config_file_requires_game_and_instance(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d) / "deploy_config.env"
            cfg.write_text('GAME_ID="valheim"\n', encoding="utf-8")
            ok, message = deployenv.validate_config_file(cfg)
            self.assertFalse(ok)
            self.assertIn("INSTANCE_ID", message)


class RedeployCoreTests(unittest.TestCase):

    def test_run_redeploy_requires_minimal_config(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d) / "deploy_config.env"
            cfg.write_text('GAME_ID="valheim"\n', encoding="utf-8")
            ok, message = redeploycore.run_redeploy(cfg, ROOT_DIR / "game_commander.sh")
            self.assertFalse(ok)
            self.assertIn("Config de déploiement incomplète", message)


class DeployCoreTests(unittest.TestCase):

    def test_run_deploy_instance_writes_temp_config_and_runs_shell_deploy(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            script = root / "game_commander.sh"
            script.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
            captured = {}

            def fake_run(cmd, timeout=300):
                self.assertIn("deploy", cmd)
                cfg = Path(cmd[-1])
                captured["cmd"] = cmd
                captured["cfg_text"] = cfg.read_text(encoding="utf-8")
                return True, "Déploiement terminé"

            with mock.patch.object(hostops, "run_command", side_effect=fake_run):
                ok, result = deploycore.run_deploy_instance(
                    main_script=script,
                    game_id="minecraft",
                    instance_id="minecraft2",
                    sys_user="vhserver",
                    repo_root=root,
                    domain="gaming.example.com",
                    admin_login="admin",
                    admin_password="secret123",
                    url_prefix="/minecraft2",
                    server_name="Mon_serveur",
                    server_password="testtest01",
                    server_port="25565",
                    max_players="20",
                )

            self.assertTrue(ok)
            self.assertIn("Déploiement terminé", result[0])
            self.assertEqual(captured["cmd"][:3], ["/bin/bash", str(script.resolve()), "deploy"])
            self.assertIn('GAME_ID="minecraft"', captured["cfg_text"])
            self.assertIn('INSTANCE_ID="minecraft2"', captured["cfg_text"])
            self.assertIn('APP_DIR="/home/vhserver/game-commander-minecraft2"', captured["cfg_text"])
            self.assertIn('SERVER_PASSWORD="testtest01"', captured["cfg_text"])


class DeployPlanTests(unittest.TestCase):

    def test_apply_instance_defaults_uses_expected_paths(self):
        payload = deployplan.apply_instance_defaults(
            game_id="valheim",
            instance_id="",
            home_dir="/home/vhserver",
            src_dir="/home/vhserver/gc",
        )
        self.assertEqual(payload["INSTANCE_ID"], "valheim")
        self.assertEqual(payload["SERVER_DIR"], "/home/vhserver/valheim_server")
        self.assertEqual(payload["DATA_DIR"], "/home/vhserver/valheim_data")
        self.assertEqual(payload["APP_DIR"], "/home/vhserver/game-commander-valheim")
        self.assertEqual(payload["GAME_SERVICE"], "valheim-server-valheim")

    def test_apply_instance_defaults_enshrouded_uses_server_dir_for_data(self):
        payload = deployplan.apply_instance_defaults(
            game_id="enshrouded",
            instance_id="enshrouded2",
            home_dir="/home/vhserver",
            src_dir="/home/vhserver/gc",
        )
        self.assertEqual(payload["DATA_DIR"], "/home/vhserver/enshrouded2_server")

    def test_suggest_free_port_group_shifts_satisfactory_ports(self):
        with mock.patch.object(deployplan, "first_port_group_conflict", side_effect=[
            ("SERVER_PORT", "t", "Port de jeu (TCP)", 7777),
            ("SERVER_PORT", "t", "Port de jeu (TCP)", 7778),
            None,
        ]):
            payload = deployplan.suggest_free_port_group(
                game_id="satisfactory",
                server_port=7777,
                query_port=8888,
                echo_port=0,
                game_service="",
            )
        self.assertEqual(payload["SERVER_PORT"], "7779")
        self.assertEqual(payload["QUERY_PORT"], "8890")
        self.assertEqual(payload["CONFLICT_PORT"], "7777")

    def test_describe_port_conflicts_reports_owner(self):
        with (
            mock.patch.object(deployplan, "_current_service_pid", return_value=""),
            mock.patch.object(deployplan, "check_port_conflict", side_effect=[True, False, True]),
            mock.patch.object(deployplan, "port_owner", side_effect=["PID 10 (foo)", "PID 11 (bar)"]),
        ):
            conflicts = deployplan.describe_port_conflicts(
                game_id="satisfactory",
                server_port=7777,
                query_port=8888,
                game_service="",
            )
        self.assertEqual(
            conflicts,
            [
                ("Port de jeu (TCP)", "t", 7777, "PID 10 (foo)"),
                ("Port fiable / join", "t", 8888, "PID 11 (bar)"),
            ],
        )

    def test_detect_other_valheim_process_returns_first_line(self):
        with mock.patch("subprocess.run") as run:
            run.return_value = mock.Mock(stdout="1234 valheim_server.x86_64\n5678 valheim_server.x86_64\n")
            self.assertEqual(deployplan.detect_other_valheim_process(), "1234 valheim_server.x86_64")

    def test_resolve_ssl_mode(self):
        self.assertEqual(deployplan.resolve_ssl_mode("1"), (True, "certbot"))
        self.assertEqual(deployplan.resolve_ssl_mode("2"), (True, "none"))
        self.assertEqual(deployplan.resolve_ssl_mode("3"), (True, "existing"))
        self.assertEqual(deployplan.resolve_ssl_mode("0"), (False, ""))

    def test_admin_password_required(self):
        self.assertTrue(deployplan.admin_password_required("secret"))
        self.assertFalse(deployplan.admin_password_required(""))


class DeployPostTests(unittest.TestCase):

    def test_render_saved_config_includes_satisfactory_ports(self):
        env = deployenv.normalize_deploy_env(
            Path("/tmp/does-not-need-to-exist").with_name("dummy.env")
        )
        env.update(
            {
                "GAME_ID": "satisfactory",
                "INSTANCE_ID": "sat1",
                "SYS_USER": "root",
                "APP_DIR": "/tmp/game-commander-sat1",
                "DOMAIN": "gaming.example.com",
                "URL_PREFIX": "/satisfactory",
            }
        )
        text = deploypost.render_saved_config(env, "/tmp/game-commander-sat1/deploy_config.env")
        self.assertIn('QUERY_PORT="8888"', text)
        self.assertIn('GAME_ID="satisfactory"', text)

    def test_render_saved_config_persists_server_password(self):
        env = deployenv.normalize_deploy_env(
            Path("/tmp/does-not-need-to-exist").with_name("dummy.env")
        )
        env.update(
            {
                "GAME_ID": "terraria",
                "INSTANCE_ID": "terraria",
                "SYS_USER": "root",
                "APP_DIR": "/tmp/game-commander-terraria",
                "SERVER_PASSWORD": "secret123",
            }
        )
        text = deploypost.render_saved_config(env, "/tmp/game-commander-terraria/deploy_config.env")
        self.assertIn('SERVER_PASSWORD="secret123"', text)

    def test_validation_lines_include_firewall_specs(self):
        env = {
            "GAME_ID": "satisfactory",
            "INSTANCE_ID": "sat1",
            "GAME_SERVICE": "satisfactory-server-sat1",
            "APP_DIR": "/tmp/game-commander-sat1",
            "FLASK_PORT": "5007",
            "URL_PREFIX": "/satisfactory",
            "DOMAIN": "gaming.example.com",
            "SSL_MODE": "existing",
            "SERVER_PORT": "7777",
            "QUERY_PORT": "8888",
        }
        with mock.patch.object(deploypost, "_service_active", return_value=True), \
             mock.patch.object(deploypost, "_http_ok", return_value=True):
            lines = deploypost.validation_lines(env, "/tmp/game-commander-sat1/deploy_config.env")
        self.assertIn("VALIDATION_ERRORS=0", lines)
        self.assertIn("FIREWALL=7777/tcp", lines)
        self.assertIn("FIREWALL=7777/udp", lines)
        self.assertIn("FIREWALL=8888/tcp", lines)


class DeploySudoTests(unittest.TestCase):

    def test_render_instance_sudoers_includes_bepinex_rules(self):
        text = deploysudo.render_instance_sudoers(
            sys_user="gameserver",
            game_label="Valheim",
            instance_id="valheim2",
            game_service="valheim-server-valheim2",
            bepinex_path="/home/gameserver/valheim2_server/BepInEx",
        )
        self.assertIn("systemctl start valheim-server-valheim2", text)
        self.assertIn("/bin/rm -rf /home/gameserver/valheim2_server/BepInEx/plugins/*", text)


class DeployNginxTests(unittest.TestCase):

    def test_run_deploy_nginx_calls_expected_sequence(self):
        calls = []

        def fake_run(args):
            calls.append(args)
            return mock.Mock(returncode=0, stdout="", stderr="")

        with mock.patch.object(deploynginx, "_run", side_effect=fake_run):
            ok, message = deploynginx.run_deploy_nginx(
                script_dir="/repo",
                domain="gaming.example.com",
                instance_id="valheim2",
                url_prefix="/valheim2",
                flask_port="5002",
                game_label="Valheim",
            )

        self.assertTrue(ok)
        self.assertEqual(message, "Nginx reloadé")
        self.assertEqual(calls[0][:3], ["python3", "/repo/tools/nginx_manager.py", "init"])
        self.assertEqual(calls[1][:3], ["python3", "/repo/tools/nginx_manager.py", "manifest-add"])
        self.assertEqual(calls[2][:3], ["python3", "/repo/tools/nginx_manager.py", "regenerate"])
        self.assertEqual(calls[3], ["nginx", "-t"])
        self.assertEqual(calls[4], ["systemctl", "reload", "nginx"])


class GameServiceTests(unittest.TestCase):

    def test_render_game_service_contains_expected_fields(self):
        content = gameservice.render_game_service(
            game_label="Minecraft Fabric",
            service_name="minecraft-fabric-server-test",
            sys_user="vhserver",
            server_dir="/tmp/mc",
            exec_start="/tmp/mc/start_server.sh",
            cpu_affinity_line="CPUAffinity=2 6",
            cpu_weight_line="CPUWeight=200",
        )
        self.assertIn("Description=Minecraft Fabric Dedicated Server", content)
        self.assertIn("WorkingDirectory=/tmp/mc", content)
        self.assertIn("ExecStart=/tmp/mc/start_server.sh", content)
        self.assertIn("CPUAffinity=2 6", content)
        self.assertIn("CPUWeight=200", content)


class StartScriptsTests(unittest.TestCase):

    def test_render_minecraft_start_script_uses_vanilla_jar(self):
        content = startscripts.render_minecraft_start_script(server_dir="/srv/minecraft", jar_name="server.jar")
        self.assertIn('cd "/srv/minecraft"', content)
        self.assertIn("exec /usr/bin/java -Xms1G -Xmx2G -jar server.jar nogui", content)

    def test_render_minecraft_start_script_uses_fabric_jar(self):
        content = startscripts.render_minecraft_start_script(server_dir="/srv/fabric", jar_name="fabric-server-launch.jar")
        self.assertIn("fabric-server-launch.jar", content)

    def test_render_satisfactory_start_script_uses_reliable_port(self):
        content = startscripts.render_satisfactory_start_script(
            server_dir="/srv/satisfactory",
            data_dir="/srv/satisfactory-data",
            server_port="7777",
            reliable_port="8888",
        )
        self.assertIn('export HOME="/srv/satisfactory-data"', content)
        self.assertIn('export XDG_CONFIG_HOME="/srv/satisfactory-data/.config"', content)
        self.assertIn('mkdir -p "/srv/satisfactory-data/.config/Epic/FactoryGame/Saved/SaveGames/server"', content)
        self.assertIn('cd "/srv/satisfactory"', content)
        self.assertIn('exec ./FactoryServer.sh -Port="7777" -ReliablePort="8888" -unattended -log', content)

    def test_render_enshrouded_start_script_uses_wineprefix(self):
        content = startscripts.render_enshrouded_start_script(
            server_dir="/srv/enshrouded",
            home_dir="/home/gameserver",
        )
        self.assertIn("export WINEDEBUG=-all", content)
        self.assertIn('export WINEPREFIX="/home/gameserver/.wine"', content)
        self.assertIn('cd "/srv/enshrouded"', content)
        self.assertIn("exec xvfb-run --auto-servernum wine64 ./enshrouded_server.exe", content)

    def test_render_terraria_start_script_uses_serverconfig(self):
        content = startscripts.render_terraria_start_script(server_dir="/srv/terraria")
        self.assertIn('cd "/srv/terraria"', content)
        self.assertIn('CFG="/srv/terraria/serverconfig.txt"', content)
        self.assertIn('mkdir -p "$WORLDPATH" "/srv/terraria/logs"', content)
        self.assertIn('exec ./TerrariaServer.bin.x86_64 "${ARGS[@]}"', content)

    def test_render_terraria_wrapper_script_uses_script_wrapper(self):
        content = startscripts.render_terraria_wrapper_script(start_script="/srv/terraria/start_server.sh")
        self.assertIn('exec /usr/bin/script -qefc "/srv/terraria/start_server.sh" /dev/null', content)

    def test_render_soulmask_start_script_uses_json_config(self):
        content = startscripts.render_soulmask_start_script(
            server_dir="/srv/soulmask",
            cfg_path="/srv/soulmask/soulmask_server.json",
        )
        self.assertIn('cd "/srv/soulmask"', content)
        self.assertIn('CFG="/srv/soulmask/soulmask_server.json"', content)
        self.assertIn('SERVER_NAME="$(json_get \'.server_name\')"', content)
        self.assertIn('exec ./WSServer.sh Level01_Main -server "${ARGS[@]}" -log -UTF8Output -MULTIHOME=0.0.0.0 "-EchoPort=${ECHO_PORT}" -forcepassthrough', content)

    def test_render_valheim_start_script_standard(self):
        content = startscripts.render_valheim_start_script(
            server_dir="/srv/valheim",
            data_dir="/srv/valheim-data",
            server_name="Serveur",
            server_port="2456",
            world_name="Monde",
            server_password="secret",
            crossplay_flag="-crossplay",
            bepinex=False,
        )
        self.assertIn("export SteamAppId=892970", content)
        self.assertIn('export LD_LIBRARY_PATH="/srv/valheim/linux64:$LD_LIBRARY_PATH"', content)
        self.assertIn('cd "/srv/valheim"', content)
        self.assertIn('-savedir "/srv/valheim-data"', content)
        self.assertIn("-crossplay", content)

    def test_render_valheim_start_script_bepinex(self):
        content = startscripts.render_valheim_start_script(
            server_dir="/srv/valheim",
            data_dir="/srv/valheim-data",
            server_name="Serveur",
            server_port="2456",
            world_name="Monde",
            server_password="secret",
            crossplay_flag="-playfab",
            bepinex=True,
        )
        self.assertIn("export DOORSTOP_ENABLE=TRUE", content)
        self.assertIn("export DOORSTOP_INVOKE_DLL_PATH=./BepInEx/core/BepInEx.Preloader.dll", content)
        self.assertIn('export LD_PRELOAD="libdoorstop_x64.so:$LD_PRELOAD"', content)
        self.assertIn('export LD_LIBRARY_PATH="./linux64:$LD_LIBRARY_PATH"', content)
        self.assertIn("-playfab", content)


class HostOpsTests(unittest.TestCase):

    def test_service_action_cmd_validates_action(self):
        self.assertEqual(
            hostops.service_action_cmd("minecraft-server-test", "restart"),
            ["sudo", "/usr/bin/systemctl", "restart", "minecraft-server-test"],
        )
        with self.assertRaises(ValueError):
            hostops.service_action_cmd("svc", "reload")

    def test_instance_command_builders(self):
        script = "/home/vhserver/gc/game_commander.sh"
        self.assertEqual(
            hostops.update_instance_cmd(script, "valheim2"),
            ["sudo", "/bin/bash", script, "update", "--instance", "valheim2"],
        )
        self.assertEqual(
            hostops.redeploy_instance_cmd(script, "/tmp/deploy_config.env"),
            ["sudo", "/bin/bash", script, "deploy", "--config", "/tmp/deploy_config.env"],
        )
        self.assertEqual(
            hostops.uninstall_instance_cmd(script, "valheim2"),
            ["sudo", "/bin/bash", script, "uninstall", "--instance", "valheim2", "--full", "--yes"],
        )
        self.assertEqual(
            hostops.rebalance_cmd(script, restart=False),
            ["sudo", "/bin/bash", script, "rebalance"],
        )
        self.assertEqual(
            hostops.rebalance_cmd(script, restart=True),
            ["sudo", "/bin/bash", script, "rebalance", "--restart"],
        )


class DiscordNotifyTests(unittest.TestCase):

    def test_load_config_missing_returns_empty(self):
        self.assertEqual(discordnotify.load_config("/tmp/definitely_missing_gc_discord.json"), {})

    def test_resolve_channel_prefers_instance_then_default(self):
        cfg = {
            "bot_token": "token",
            "default_channel_id": "999",
            "instance_channels": {"valheim2": "123"},
            "game_channels": {"valheim": "456"},
        }
        self.assertEqual(discordnotify.resolve_channel_id(cfg, instance_id="valheim2", game_id="valheim"), "123")
        self.assertEqual(discordnotify.resolve_channel_id(cfg, instance_id="other", game_id="valheim"), "456")
        self.assertEqual(discordnotify.resolve_channel_id(cfg, instance_id="other", game_id="other"), "999")

    def test_notify_event_posts_to_discord_when_configured(self):
        cfg = {"bot_token": "token", "instance_channels": {"valheim2": "123"}}
        with mock.patch.object(discordnotify, "post_channel_message", return_value=(True, "sent")) as post_mock:
            ok, message = discordnotify.notify_event(
                event="restart",
                ok=True,
                instance_id="valheim2",
                game_id="valheim",
                details="done",
                config=cfg,
            )
        self.assertTrue(ok)
        self.assertEqual(message, "sent")
        self.assertEqual(post_mock.call_args.args[0], "token")
        self.assertEqual(post_mock.call_args.args[1], "123")
        self.assertRegex(
            post_mock.call_args.args[2],
            r"^valheim2: \d{2}-\d{2}-\d{4} \d{2}:\d{2}:\d{2} - Redemarrage$",
        )

    def test_notify_event_adds_default_action_text_when_no_details(self):
        cfg = {"bot_token": "token", "instance_channels": {"ParkAPouet": "123"}}
        with mock.patch.object(discordnotify, "post_channel_message", return_value=(True, "sent")) as post_mock:
            ok, message = discordnotify.notify_event(
                event="stop",
                ok=True,
                instance_id="ParkAPouet",
                game_id="valheim",
                details="",
                config=cfg,
            )
        self.assertTrue(ok)
        self.assertEqual(message, "sent")
        self.assertRegex(
            post_mock.call_args.args[2],
            r"^ParkAPouet: \d{2}-\d{2}-\d{4} \d{2}:\d{2}:\d{2} - Arret$",
        )

    def test_send_test_message_uses_notify_event(self):
        with mock.patch.object(discordnotify, "notify_event", return_value=(True, "sent")) as notify_mock:
            ok, message = discordnotify.send_test_message(instance_id="valheim2", game_id="valheim")
        self.assertTrue(ok)
        self.assertEqual(message, "sent")
        self.assertEqual(notify_mock.call_args.kwargs["event"], "discord-test")
        self.assertEqual(notify_mock.call_args.kwargs["source"], "Hub")


class HostCliTests(unittest.TestCase):

    def test_list_configs_uses_hostctl_discovery(self):
        with tempfile.TemporaryDirectory() as d, mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
            root = Path(d)
            inst = root / "game-commander-valheim2"
            inst.mkdir()
            (inst / "deploy_config.env").write_text('INSTANCE_ID="valheim2"\nGAME_ID="valheim"\n', encoding="utf-8")
            from tools import host_cli
            rc = host_cli.main(["list-configs", "--root", str(root)])
            self.assertEqual(rc, 0)
            self.assertIn(str((inst / "deploy_config.env").resolve()), stdout.getvalue())

    def test_resolve_config_returns_matching_path(self):
        with tempfile.TemporaryDirectory() as d, mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
            root = Path(d)
            inst = root / "game-commander-satisfactory"
            inst.mkdir()
            target = inst / "deploy_config.env"
            target.write_text('INSTANCE_ID="satisfactory"\nGAME_ID="satisfactory"\n', encoding="utf-8")
            from tools import host_cli
            rc = host_cli.main(["resolve-config", "--root", str(root), "--instance", "satisfactory"])
            self.assertEqual(rc, 0)
            self.assertEqual(stdout.getvalue().strip(), str(target.resolve()))

    def test_rebalance_runs_cpuplan_directly(self):
        with mock.patch.object(cpuplan, "detect_core_groups", return_value=["0 4", "1 5"]), \
             mock.patch.object(cpuplan, "collect_managed_instances", return_value=[{"instance_id": "valheim2", "game_id": "valheim", "service": "valheim-server-valheim2"}]), \
             mock.patch.object(cpuplan, "plan_instances", return_value=[{"instance_id": "valheim2", "game_id": "valheim", "service": "valheim-server-valheim2", "cpus": "0 4", "weight": 2}]), \
             mock.patch.object(cpuplan, "apply_plan", return_value=["CPU valheim2 (valheim) -> 0 4 [poids 200]"]), \
             mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
            from tools import host_cli
            rc = host_cli.main(["rebalance", "--main-script", str(ROOT_DIR / "game_commander.sh")])
            self.assertEqual(rc, 0)
            self.assertIn("Répartition CPU recalculée", stdout.getvalue())

    def test_update_instance_can_skip_hub_sync(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            inst = root / "game-commander-minecraft-fabric"
            inst.mkdir()
            (inst / "deploy_config.env").write_text(
                'INSTANCE_ID="minecraft-fabric"\nGAME_ID="minecraft-fabric"\n',
                encoding="utf-8",
            )
            from tools import host_cli
            with mock.patch.object(hostctl, "resolve_instance_config", return_value=inst / "deploy_config.env"), \
                 mock.patch.object(updatecore, "run_core_update", return_value=(True, ["core ok"])), \
                 mock.patch.object(updatehooks, "run_post_update_hooks", return_value=(True, ["hooks ok"])), \
                 mock.patch.object(hubsync, "sync_hub_service") as sync_hub, \
                 mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
                rc = host_cli.main([
                    "update-instance",
                    "--main-script", str(ROOT_DIR / "game_commander.sh"),
                    "--instance", "minecraft-fabric",
                    "--skip-hub-sync",
                ])
            self.assertEqual(rc, 0)
            self.assertFalse(sync_hub.called)
            self.assertIn("core ok", stdout.getvalue())

    def test_service_action_notifies_discord(self):
        from tools import host_cli
        with mock.patch.object(hostops, "run_command", return_value=(True, "ok")), \
             mock.patch.object(discordnotify, "notify_event", return_value=(True, "sent")) as notify_mock, \
             mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
            rc = host_cli.main(["service-action", "--service", "valheim-server-valheim2", "--action", "restart"])
        self.assertEqual(rc, 0)
        self.assertEqual(notify_mock.call_args.kwargs["event"], "restart")
        self.assertEqual(notify_mock.call_args.kwargs["instance_id"], "valheim2")
        self.assertIn("Discord : notification envoyee", stdout.getvalue())

    def test_deploy_instance_notifies_discord(self):
        from tools import host_cli
        with mock.patch.object(deploycore, "run_deploy_instance", return_value=(True, ["done"])), \
             mock.patch.object(discordnotify, "notify_event", return_value=(True, "sent")) as notify_mock, \
             mock.patch("pwd.getpwuid", return_value=types.SimpleNamespace(pw_name="vhserver")), \
             mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
            rc = host_cli.main([
                "deploy-instance",
                "--main-script", str(ROOT_DIR / "game_commander.sh"),
                "--game-id", "minecraft",
                "--instance", "minecraft2",
                "--domain", "gaming.example.com",
                "--admin-password", "secret123",
            ])
        self.assertEqual(rc, 0)
        self.assertEqual(notify_mock.call_args.kwargs["event"], "deploy")
        self.assertEqual(notify_mock.call_args.kwargs["instance_id"], "minecraft2")
        self.assertIn("Discord : notification envoyee", stdout.getvalue())

    def test_discord_test_command(self):
        from tools import host_cli
        with mock.patch.object(discordnotify, "send_test_message", return_value=(True, "sent")) as send_mock, \
             mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
            rc = host_cli.main(["discord-test", "--instance", "valheim2", "--game-id", "valheim"])
        self.assertEqual(rc, 0)
        self.assertEqual(send_mock.call_args.kwargs["instance_id"], "valheim2")
        self.assertEqual(send_mock.call_args.kwargs["game_id"], "valheim")
        self.assertIn("sent", stdout.getvalue())

    def test_inject_missing_file(self):
        """Retourne 1 si le fichier n'existe pas."""
        rc = nginx_manager.cmd_inject(make_args(
            conf="/tmp/fichier_inexistant_gc_test.conf",
            instance_id="x", prefix="/x", port=5000, label="X",
        ))
        self.assertEqual(rc, 1)

    # ── $host et variables nginx ────────────────────────────────────────────

    def test_inject_nginx_vars_not_interpolated(self):
        """Les variables nginx ($host, $remote_addr…) ne sont pas interpolées."""
        conf = tmp_file(NGINX_SSL_BLOCK)
        try:
            nginx_manager.cmd_inject(make_args(
                conf=conf, instance_id="valheim8",
                prefix="/valheim8", port=5002, label="Valheim",
            ))
            content = Path(conf).read_text()
            self.assertIn("$host", content)
            self.assertIn("$remote_addr", content)
            self.assertIn("$proxy_add_x_forwarded_for", content)
            self.assertIn("$scheme", content)
        finally:
            os.unlink(conf)


class NginxRemoveTests(unittest.TestCase):

    def _inject_then_remove(self, base_conf: str):
        """Helper : injecte puis supprime, retourne le contenu final."""
        conf = tmp_file(base_conf)
        try:
            nginx_manager.cmd_inject(make_args(
                conf=conf, instance_id="valheim8",
                prefix="/valheim8", port=5002, label="Valheim",
            ))
            rc = nginx_manager.cmd_remove(make_args(
                conf=conf, instance_id="valheim8", prefix="/valheim8",
            ))
            content = Path(conf).read_text()
            return rc, content
        finally:
            os.unlink(conf)
            for b in Path(conf).parent.glob(Path(conf).name + ".bak.*"):
                b.unlink(missing_ok=True)

    def test_remove_cleans_location_blocks(self):
        """Le bloc location et location/static sont supprimés."""
        rc, content = self._inject_then_remove(NGINX_SSL_BLOCK)
        self.assertEqual(rc, 0)
        self.assertNotIn("location /valheim8 {", content)
        self.assertNotIn("location /valheim8/static {", content)
        self.assertNotIn("127.0.0.1:5002", content)

    def test_remove_preserves_other_content(self):
        """Les blocs existants (location /, listen 443…) sont préservés."""
        rc, content = self._inject_then_remove(NGINX_SSL_BLOCK)
        self.assertEqual(rc, 0)
        self.assertIn("location / {", content)
        self.assertIn("listen 443 ssl", content)
        self.assertIn("server_name gaming.example.com", content)

    def test_remove_multiple_keeps_others(self):
        """Supprimer une instance ne touche pas aux autres."""
        conf = tmp_file(NGINX_SSL_BLOCK)
        try:
            nginx_manager.cmd_inject(make_args(
                conf=conf, instance_id="valheim8",
                prefix="/valheim8", port=5002, label="Valheim",
            ))
            nginx_manager.cmd_inject(make_args(
                conf=conf, instance_id="enshrouded2",
                prefix="/enshrouded2", port=5004, label="Enshrouded",
            ))
            rc = nginx_manager.cmd_remove(make_args(
                conf=conf, instance_id="valheim8", prefix="/valheim8",
            ))
            content = Path(conf).read_text()
            self.assertEqual(rc, 0)
            self.assertNotIn("location /valheim8 {", content)
            self.assertIn("location /enshrouded2 {", content)
            self.assertIn("127.0.0.1:5004", content)
        finally:
            os.unlink(conf)
            for b in Path(conf).parent.glob(Path(conf).name + ".bak.*"):
                b.unlink(missing_ok=True)

    def test_remove_absent_block_is_noop(self):
        """Supprimer un bloc absent retourne 0 sans modifier le fichier."""
        conf = tmp_file(NGINX_SSL_BLOCK)
        try:
            original = Path(conf).read_text()
            rc = nginx_manager.cmd_remove(make_args(
                conf=conf, instance_id="valheim8", prefix="/valheim8",
            ))
            self.assertEqual(rc, 0)
            self.assertEqual(Path(conf).read_text(), original)
        finally:
            os.unlink(conf)

    def test_remove_creates_backup(self):
        """Un fichier .bak est créé lors de la suppression."""
        conf = tmp_file(NGINX_SSL_BLOCK)
        try:
            nginx_manager.cmd_inject(make_args(
                conf=conf, instance_id="valheim8",
                prefix="/valheim8", port=5002, label="Valheim",
            ))
            # Supprimer les backups d'inject
            for b in Path(conf).parent.glob(Path(conf).name + ".bak.*"):
                b.unlink(missing_ok=True)
            nginx_manager.cmd_remove(make_args(
                conf=conf, instance_id="valheim8", prefix="/valheim8",
            ))
            baks = list(Path(conf).parent.glob(Path(conf).name + ".bak.*"))
            self.assertEqual(len(baks), 1, "Un backup doit être créé")
        finally:
            os.unlink(conf)
            for b in Path(conf).parent.glob(Path(conf).name + ".bak.*"):
                b.unlink(missing_ok=True)


class NginxFindConfTests(unittest.TestCase):

    def test_find_by_content(self):
        """Trouve un fichier par server_name dans le contenu."""
        conf = tmp_file(
            "server {\n    server_name testdomain.example.com;\n    listen 443 ssl;\n}\n",
            suffix=".conf",
        )
        # On ne peut pas tester sur /etc/nginx sans root — on teste la logique
        # en injectant directement dans un répertoire temporaire
        # Ce test vérifie que la fonction retourne 1 pour un domaine inconnu
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = nginx_manager.cmd_find_conf(
                make_args(domain="domaine-certainement-inexistant-gc-test-xyz.net")
            )
        self.assertEqual(rc, 1)
        os.unlink(conf)


# ══════════════════════════════════════════════════════════════════════════════
# CONFIG GEN
# ══════════════════════════════════════════════════════════════════════════════

class ConfigGenGameJsonTests(unittest.TestCase):

    def _gen_valheim(self, **kwargs):
        out = tmp_path(".json")
        defaults = dict(
            out=out, game_id="valheim", game_label="Valheim",
            game_binary="valheim_server.x86_64",
            game_service="valheim-server-valheim8",
            server_dir="/home/gameserver/valheim8_server",
            data_dir="/home/gameserver/valheim8_data",
            world_name="Monde1", max_players=10, port=5900,
            url_prefix="/valheim8", flask_port=5002, admin_user="admin",
            bepinex_path="/home/gameserver/valheim8_server/BepInEx",
            steam_appid="896660", steamcmd_path="/home/gameserver/steamcmd/steamcmd.sh",
        )
        defaults.update(kwargs)
        rc = config_gen.cmd_game_json(make_args(**defaults))
        self.assertEqual(rc, 0)
        return json.loads(Path(out).read_text())

    def test_valheim_structure(self):
        data = self._gen_valheim()
        self.assertEqual(data["id"], "valheim")
        self.assertEqual(data["server"]["binary"], "valheim_server.x86_64")
        self.assertEqual(data["server"]["world_name"], "Monde1")
        self.assertEqual(data["web"]["flask_port"], 5002)
        self.assertEqual(data["web"]["url_prefix"], "/valheim8")

    def test_valheim_permissions(self):
        data = self._gen_valheim()
        self.assertIn("install_mod", data["permissions"])
        self.assertIn("remove_mod", data["permissions"])
        self.assertIn("manage_saves", data["permissions"])

    def test_valheim_bepinex_section(self):
        data = self._gen_valheim()
        self.assertIn("mods", data)
        self.assertEqual(data["mods"]["platform"], "thunderstore")
        self.assertTrue(data["features"]["mods"])
        self.assertTrue(data["features"]["saves"])

    def test_valheim_no_bepinex(self):
        data = self._gen_valheim(bepinex_path="")
        self.assertNotIn("mods", data)
        self.assertFalse(data["features"]["mods"])

    def test_enshrouded_no_world_name(self):
        out = tmp_path(".json")
        rc = config_gen.cmd_game_json(make_args(
            out=out, game_id="enshrouded", game_label="Enshrouded",
            game_binary="enshrouded_server.exe",
            game_service="enshrouded-server-enshrouded2",
            server_dir="/home/gameserver/enshrouded2_server",
            data_dir="", world_name="", max_players=16, port=15639, query_port=None, echo_port=None,
            url_prefix="/enshrouded2", flask_port=5004, admin_user="admin",
            bepinex_path="", steam_appid="2278520", steamcmd_path="",
        ))
        self.assertEqual(rc, 0)
        data = json.loads(Path(out).read_text())
        self.assertIsNone(data["server"]["world_name"])
        self.assertEqual(data["server"]["query_port"], 15640)
        self.assertNotIn("install_mod", data["permissions"])

    def test_minecraft_fabric_support(self):
        out = tmp_path(".json")
        rc = config_gen.cmd_game_json(make_args(
            out=out, game_id="minecraft-fabric", game_label="Minecraft Fabric",
            game_binary="java", game_service="minecraft-fabric-server-test",
            server_dir="/home/gameserver/minecraft_fabric_server",
            data_dir="", world_name="", max_players=20, port=25565,
            url_prefix="/minecraft-fabric", flask_port=5005, admin_user="admin",
            bepinex_path="", steam_appid="", steamcmd_path="",
        ))
        self.assertEqual(rc, 0)
        data = json.loads(Path(out).read_text())
        self.assertEqual(data["id"], "minecraft-fabric")
        self.assertEqual(data["module_id"], "minecraft_fabric")
        self.assertTrue(data["features"]["mods"])
        self.assertEqual(data["theme"]["name"], "minecraft")
        self.assertIn("install_mod", data["permissions"])

    def test_terraria_support(self):
        out = tmp_path(".json")
        rc = config_gen.cmd_game_json(make_args(
            out=out, game_id="terraria", game_label="Terraria",
            game_binary="TerrariaServer.bin.x86_64", game_service="terraria-server-test",
            server_dir="/home/gameserver/terraria_server",
            data_dir="/home/gameserver/terraria_data", world_name="", max_players=8, port=7777,
            url_prefix="/terraria", flask_port=5006, admin_user="admin",
            bepinex_path="", steam_appid="", steamcmd_path="",
        ))
        self.assertEqual(rc, 0)
        data = json.loads(Path(out).read_text())
        self.assertEqual(data["id"], "terraria")
        self.assertEqual(data["server"]["binary"], "TerrariaServer.bin.x86_64")
        self.assertTrue(data["features"]["config"])
        self.assertTrue(data["features"]["players"])
        self.assertTrue(data["features"]["saves"])
        self.assertIn("manage_config", data["permissions"])

    def test_soulmask_support(self):
        out = tmp_path(".json")
        rc = config_gen.cmd_game_json(make_args(
            out=out, game_id="soulmask", game_label="Soulmask",
            game_binary="StartServer.sh", game_service="soulmask-server-test",
            server_dir="/home/gameserver/soulmask_server", query_port=27015, echo_port=18888,
            data_dir="/home/gameserver/soulmask_data", world_name="", max_players=50, port=8777,
            url_prefix="/soulmask", flask_port=5011, admin_user="admin",
            bepinex_path="", steam_appid="3017300", steamcmd_path="/home/gameserver/steamcmd/steamcmd.sh",
        ))
        self.assertEqual(rc, 0)
        data = json.loads(Path(out).read_text())
        self.assertEqual(data["id"], "soulmask")
        self.assertTrue(data["features"]["config"])
        self.assertFalse(data["features"]["mods"])
        self.assertEqual(data["theme"]["name"], "enshrouded")
        self.assertEqual(data["steamcmd"]["app_id"], "3017300")
        self.assertEqual(data["server"]["query_port"], 27015)
        self.assertEqual(data["server"]["echo_port"], 18888)

    def test_satisfactory_support(self):
        out = tmp_path(".json")
        rc = config_gen.cmd_game_json(make_args(
            out=out, game_id="satisfactory", game_label="Satisfactory",
            game_binary="FactoryServer.sh", game_service="satisfactory-server-test",
            server_dir="/home/gameserver/satisfactory_server",
            data_dir="/home/gameserver/satisfactory_data", world_name="", max_players=8, port=7777,
            query_port=8888, echo_port=None,
            url_prefix="/satisfactory", flask_port=5007, admin_user="admin",
            bepinex_path="", steam_appid="1690800", steamcmd_path="/home/gameserver/steamcmd/steamcmd.sh",
        ))
        self.assertEqual(rc, 0)
        data = json.loads(Path(out).read_text())
        self.assertEqual(data["id"], "satisfactory")
        self.assertEqual(data["server"]["binary"], "FactoryServer.sh")
        self.assertTrue(data["features"]["config"])
        self.assertFalse(data["features"]["players"])
        self.assertTrue(data["features"]["saves"])
        self.assertEqual(data["theme"]["name"], "enshrouded")
        self.assertEqual(data["server"]["query_port"], 8888)
        self.assertEqual(data["steamcmd"]["app_id"], "1690800")
        self.assertIn("manage_config", data["permissions"])

    def test_steamcmd_section(self):
        data = self._gen_valheim()
        self.assertIn("steamcmd", data)
        self.assertEqual(data["steamcmd"]["app_id"], "896660")

    def test_no_steamcmd_when_empty(self):
        data = self._gen_valheim(steam_appid="")
        self.assertNotIn("steamcmd", data)


class SatisfactoryConfigTests(unittest.TestCase):

    def test_satisfactory_status_unclaimed(self):
        app = Flask(__name__)
        app.config['GAME'] = {'server': {'port': 7777}}
        with app.app_context():
            original = satisfactory_config._passwordless_login
            original_info = satisfactory_config._read_public_server_info
            try:
                satisfactory_config._passwordless_login = lambda: ('tok', None)
                satisfactory_config._read_public_server_info = lambda: {
                    'server_name': 'TestSatis',
                    'active_session_name': 'Factory1',
                }
                data, err = satisfactory_config.get_claim_status()
            finally:
                satisfactory_config._passwordless_login = original
                satisfactory_config._read_public_server_info = original_info
        self.assertIsNone(err)
        self.assertTrue(data['reachable'])
        self.assertFalse(data['claimed'])
        self.assertEqual(data['server_name'], 'TestSatis')
        self.assertEqual(data['active_session_name'], 'Factory1')

    def test_satisfactory_status_claimed(self):
        app = Flask(__name__)
        app.config['GAME'] = {'server': {'port': 7777}}
        with app.app_context():
            original = satisfactory_config._passwordless_login
            try:
                satisfactory_config._passwordless_login = lambda: (None, 'Server already claimed')
                data, err = satisfactory_config.get_claim_status()
            finally:
                satisfactory_config._passwordless_login = original
        self.assertIsNone(err)
        self.assertTrue(data['reachable'])
        self.assertTrue(data['claimed'])

    def test_satisfactory_status_connection_error_is_simplified(self):
        app = Flask(__name__)
        app.config['GAME'] = {'server': {'port': 7777}}
        with app.app_context(), mock.patch.object(
            satisfactory_config.http,
            'post',
            side_effect=satisfactory_config.http.exceptions.ConnectionError('boom'),
        ):
            data, err = satisfactory_config.get_claim_status()
        self.assertIsNone(err)
        self.assertFalse(data['reachable'])
        self.assertEqual(data['status_label'], 'Injoignable')
        self.assertIn('API Satisfactory indisponible', data['message'])

    def test_satisfactory_claim_requires_fields(self):
        app = Flask(__name__)
        app.config['GAME'] = {'server': {'port': 7777}}
        with app.app_context():
            data, err = satisfactory_config.claim_server('', '')
        self.assertIsNone(data)
        self.assertIn('Nom du serveur requis', err)

    def test_satisfactory_claim_server(self):
        app = Flask(__name__)
        app.config['GAME'] = {'server': {'port': 7777}}
        with app.app_context():
            orig_login = satisfactory_config._passwordless_login
            orig_call = satisfactory_config._api_call
            try:
                satisfactory_config._passwordless_login = lambda: ('tok', None)
                satisfactory_config._api_call = lambda function_name, data=None, token=None, timeout=8: (
                    ({'data': {'serverName': data.get('ServerName')}}, None)
                    if function_name == 'ClaimServer' and token == 'tok'
                    else ({}, None)
                )
                data, err = satisfactory_config.claim_server('Mon usine', 'secret123')
            finally:
                satisfactory_config._passwordless_login = orig_login
                satisfactory_config._api_call = orig_call
        self.assertIsNone(err)
        self.assertEqual(data['server_name'], 'Mon usine')

    def test_satisfactory_set_client_password(self):
        app = Flask(__name__)
        app.config['GAME'] = {'server': {'port': 7777}}
        with app.app_context():
            orig_session = satisfactory_config._admin_session
            orig_call = satisfactory_config._api_call
            try:
                satisfactory_config._admin_session = lambda password: ('tok', None)
                satisfactory_config._api_call = lambda function_name, data=None, token=None, timeout=8: ({}, None)
                data, err = satisfactory_config.set_client_password('adminpass', '')
            finally:
                satisfactory_config._admin_session = orig_session
                satisfactory_config._api_call = orig_call
        self.assertIsNone(err)
        self.assertIn('supprimé', data['message'])

    def test_satisfactory_get_admin_server_info(self):
        app = Flask(__name__)
        app.config['GAME'] = {'server': {'port': 7777}}
        with app.app_context():
            orig_reader = satisfactory_config._read_admin_server_info
            try:
                satisfactory_config._read_admin_server_info = lambda password: (
                    {'server_name': 'TestSatis', 'active_session_name': 'Factory1'},
                    None,
                )
                data, err = satisfactory_config.get_admin_server_info('secret123')
            finally:
                satisfactory_config._read_admin_server_info = orig_reader
        self.assertIsNone(err)
        self.assertEqual(data['server_name'], 'TestSatis')
        self.assertEqual(data['active_session_name'], 'Factory1')


class ServerCpuMonitorTests(unittest.TestCase):

    def test_get_cpu_monitor_alert_reads_instance_alert(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "deploy_config.env").write_text('INSTANCE_ID="alpha"\n', encoding="utf-8")
            state_file = root / "cpu-monitor.json"
            state_file.write_text(
                json.dumps({
                    "alerts_by_instance": {
                        "alpha": {"message": "Déséquilibre CPU durable"},
                    }
                }),
                encoding="utf-8",
            )
            app = Flask(__name__, root_path=str(root))
            app.config["GAME"] = {"server": {"install_dir": str(root / "server")}}
            previous = os.environ.get("GAME_COMMANDER_CPU_MONITOR_STATE")
            os.environ["GAME_COMMANDER_CPU_MONITOR_STATE"] = str(state_file)
            try:
                with app.app_context():
                    alert = core_server.get_cpu_monitor_alert()
            finally:
                if previous is None:
                    os.environ.pop("GAME_COMMANDER_CPU_MONITOR_STATE", None)
                else:
                    os.environ["GAME_COMMANDER_CPU_MONITOR_STATE"] = previous
        self.assertEqual(alert["message"], "Déséquilibre CPU durable")

    def test_get_cpu_monitor_snapshot_reads_instance_metrics(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "deploy_config.env").write_text('INSTANCE_ID="alpha"\n', encoding="utf-8")
            state_file = root / "cpu-monitor.json"
            state_file.write_text(
                json.dumps({
                    "updated_at": 1234567890,
                    "samples_for_alert": 10,
                    "instances": {
                        "alpha": {"cpu_percent": 37.5, "affinity": "6 7", "planned_affinity": "4 5"},
                    },
                }),
                encoding="utf-8",
            )
            app = Flask(__name__, root_path=str(root))
            app.config["GAME"] = {"server": {"install_dir": str(root / "server")}}
            previous = os.environ.get("GAME_COMMANDER_CPU_MONITOR_STATE")
            os.environ["GAME_COMMANDER_CPU_MONITOR_STATE"] = str(state_file)
            try:
                with app.app_context():
                    snapshot = core_server.get_cpu_monitor_snapshot()
            finally:
                if previous is None:
                    os.environ.pop("GAME_COMMANDER_CPU_MONITOR_STATE", None)
                else:
                    os.environ["GAME_COMMANDER_CPU_MONITOR_STATE"] = previous
        self.assertEqual(snapshot["updated_at"], 1234567890)
        self.assertEqual(snapshot["instance"]["affinity"], "6 7")
        self.assertEqual(snapshot["instance"]["planned_affinity"], "4 5")


class ServerDiscordTests(unittest.TestCase):

    def test_start_notifies_discord_for_commander_actions(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "game-commander-ParkAPouet"
            root.mkdir(parents=True)
            (root / "deploy_config.env").write_text('INSTANCE_ID="ParkAPouet"\n', encoding="utf-8")
            app = Flask(__name__, root_path=str(root))
            app.config["GAME"] = {
                "id": "valheim",
                "server": {
                    "service": "valheim-server-ParkAPouet",
                    "install_dir": "/tmp/server",
                },
            }
            discord_module = types.SimpleNamespace(notify_event=mock.Mock(return_value=(True, "sent")))
            with app.app_context(), \
                 mock.patch.object(core_server, "_systemctl", return_value=(True, "")), \
                 mock.patch.object(core_server, "_discordnotify_module", return_value=discord_module):
                ok, err = core_server.start(wait=False)
            self.assertTrue(ok)
            self.assertEqual(err, "")
            discord_module.notify_event.assert_called_once()
            self.assertEqual(discord_module.notify_event.call_args.kwargs["event"], "start")
            self.assertEqual(discord_module.notify_event.call_args.kwargs["instance_id"], "ParkAPouet")
            self.assertEqual(discord_module.notify_event.call_args.kwargs["source"], "Commander")
            log_path = Path(d) / "game-commander-hub" / "action-logs" / "hub-actions.log"
            content = log_path.read_text(encoding="utf-8")
            self.assertIn("OK [Commander] ParkAPouet start", content)
            self.assertIn("Demarrage lance", content)


class HubAuthTests(unittest.TestCase):

    def test_view_hub_expands_default_permissions(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "users.json").write_text(json.dumps({
                "admin": {
                    "password_hash": hub_auth.hash_password("password123"),
                    "permissions": ["view_hub"],
                    "email": "",
                }
            }), encoding="utf-8")
            app = Flask(__name__, root_path=str(root))
            with app.app_context():
                perms = hub_auth.get_user_perms("admin")
                self.assertIn("view_hub", perms)
                self.assertIn("manage_instances", perms)
                self.assertIn("manage_lifecycle", perms)
                self.assertIn("run_updates", perms)
                self.assertIn("rebalance_cpu", perms)

    def test_change_own_password_updates_hash(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            users_path = root / "users.json"
            users_path.write_text(json.dumps({
                "admin": {
                    "password_hash": hub_auth.hash_password("oldpassword"),
                    "permissions": ["view_hub"],
                    "email": "",
                }
            }), encoding="utf-8")
            app = Flask(__name__, root_path=str(root))
            with app.app_context():
                ok, err = hub_auth.change_own_password("admin", "oldpassword", "newpassword1")
                self.assertTrue(ok, err)
                self.assertTrue(hub_auth.verify_password("admin", "newpassword1"))

    def test_update_account_email(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            users_path = root / "users.json"
            users_path.write_text(json.dumps({
                "admin": {
                    "password_hash": hub_auth.hash_password("password123"),
                    "permissions": ["view_hub"],
                    "email": "",
                }
            }), encoding="utf-8")
            app = Flask(__name__, root_path=str(root))
            with app.app_context():
                ok, err = hub_auth.update_account_email("admin", "admin@example.com")
                self.assertTrue(ok, err)
                record = hub_auth.get_user_record("admin")
                self.assertEqual(record["email"], "admin@example.com")

    def test_reset_account_password(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            users_path = root / "users.json"
            users_path.write_text(json.dumps({
                "admin": {
                    "password_hash": hub_auth.hash_password("password123"),
                    "permissions": ["view_hub"],
                    "email": "",
                }
            }), encoding="utf-8")
            app = Flask(__name__, root_path=str(root))
            with app.app_context():
                ok, err = hub_auth.reset_account_password("admin", "resetpass1")
                self.assertTrue(ok, err)
                self.assertTrue(hub_auth.verify_password("admin", "resetpass1"))


class HubHostTests(unittest.TestCase):

    def _make_app(self, root: Path, manifest_path: Path):
        app = Flask(__name__, root_path=str(root))
        app.config["HUB_MANIFEST"] = str(manifest_path)
        app.config["CPU_MONITOR_STATE"] = str(root / "cpu.json")
        app.config["MAIN_SCRIPT"] = str(root / "game_commander.sh")
        app.config["HOST_CLI"] = str(root / "host_cli.py")
        app.config["ACTION_LOG_DIR"] = str(root / "action-logs")
        return app

    def test_run_instance_service_action_uses_systemctl(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps({
                "instances": [{"name": "valheim2", "prefix": "/valheim2", "flask_port": 5002, "game": "valheim"}]
            }), encoding="utf-8")
            instance_dir = root / "game-commander-valheim2"
            instance_dir.mkdir()
            (instance_dir / "deploy_config.env").write_text('GAME_SERVICE="valheim-server-valheim2"\n', encoding="utf-8")
            (root / "host_cli.py").write_text("#!/usr/bin/env python3\n", encoding="utf-8")
            app = self._make_app(root, manifest_path)
            with app.app_context(), \
                 mock.patch.object(Path, "home", return_value=root), \
                 mock.patch.object(hostops, "run_command", return_value=(True, "")) as run_mock, \
                 mock.patch.object(hub_host, "get_hub_payload", return_value={"instances": [{"name": "valheim2"}], "monitor": {}}):
                ok, message, card = hub_host.run_instance_service_action("valheim2", "restart")
            self.assertTrue(ok)
            self.assertIn("Redémarrage", message)
            self.assertEqual(card["name"], "valheim2")
            self.assertEqual(
                run_mock.call_args.args[0],
                ["sudo", "/usr/bin/python3", str(root / "host_cli.py"), "service-action", "--service", "valheim-server-valheim2", "--action", "restart"],
            )

    def test_run_instance_update_uses_main_script(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps({
                "instances": [{"name": "valheim2", "prefix": "/valheim2", "flask_port": 5002, "game": "valheim"}]
            }), encoding="utf-8")
            script_path = root / "game_commander.sh"
            script_path.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
            (root / "host_cli.py").write_text("#!/usr/bin/env python3\n", encoding="utf-8")
            app = self._make_app(root, manifest_path)
            with app.app_context(), \
                 mock.patch.object(hostops, "run_command", return_value=(True, "")) as run_mock, \
                 mock.patch.object(hub_host, "get_hub_payload", return_value={"instances": [{"name": "valheim2"}], "monitor": {}}):
                ok, message, card = hub_host.run_instance_update("valheim2")
            self.assertTrue(ok)
            self.assertIn("mise à jour", message)
            self.assertEqual(card["name"], "valheim2")
            self.assertEqual(
                run_mock.call_args.args[0],
                ["sudo", "/usr/bin/python3", str(root / "host_cli.py"), "update-instance", "--main-script", str(script_path), "--instance", "valheim2"],
            )

    def test_run_instance_redeploy_uses_saved_config(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps({
                "instances": [{"name": "valheim2", "prefix": "/valheim2", "flask_port": 5002, "game": "valheim"}]
            }), encoding="utf-8")
            script_path = root / "game_commander.sh"
            script_path.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
            (root / "host_cli.py").write_text("#!/usr/bin/env python3\n", encoding="utf-8")
            instance_dir = root / "game-commander-valheim2"
            instance_dir.mkdir()
            config_path = instance_dir / "deploy_config.env"
            config_path.write_text('GAME_SERVICE="valheim-server-valheim2"\n', encoding="utf-8")
            app = self._make_app(root, manifest_path)
            with app.app_context(), \
                 mock.patch.object(Path, "home", return_value=root), \
                 mock.patch.object(hostops, "run_command", return_value=(True, "")) as run_mock, \
                 mock.patch.object(hub_host, "get_hub_payload", return_value={"instances": [{"name": "valheim2"}], "monitor": {}}):
                ok, message, card = hub_host.run_instance_redeploy("valheim2")
            self.assertTrue(ok)
            self.assertIn("redéployée", message)
            self.assertEqual(card["name"], "valheim2")
            self.assertEqual(
                run_mock.call_args.args[0],
                ["sudo", "/usr/bin/python3", str(root / "host_cli.py"), "redeploy-instance", "--main-script", str(script_path), "--config", str(config_path)],
            )

    def test_run_instance_deploy_uses_host_cli(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps({"instances": []}), encoding="utf-8")
            script_path = root / "game_commander.sh"
            script_path.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
            (root / "host_cli.py").write_text("#!/usr/bin/env python3\n", encoding="utf-8")
            app = self._make_app(root, manifest_path)
            with app.app_context(), \
                 mock.patch.object(hostops, "run_command", return_value=(True, "")) as run_mock, \
                 mock.patch.object(pwd, "getpwuid", return_value=types.SimpleNamespace(pw_name="vhserver")), \
                 mock.patch.object(hub_host, "get_hub_payload", return_value={"instances": [{"name": "minecraft2"}], "monitor": {}}):
                ok, message, payload = hub_host.run_instance_deploy({
                    "game_id": "minecraft",
                    "instance": "minecraft2",
                    "domain": "gaming.example.com",
                    "admin_login": "admin",
                    "admin_password": "testtest01",
                })
            self.assertTrue(ok)
            self.assertIn("déployée", message)
            self.assertEqual(payload["instances"][0]["name"], "minecraft2")
            self.assertEqual(
                run_mock.call_args.args[0],
                [
                    "sudo", "/usr/bin/python3", str(root / "host_cli.py"), "deploy-instance",
                    "--main-script", str(script_path),
                    "--game-id", "minecraft",
                    "--instance", "minecraft2",
                    "--domain", "gaming.example.com",
                    "--admin-login", "admin",
                    "--admin-password", "testtest01",
                    "--sys-user", "vhserver",
                ],
            )

    def test_run_instance_uninstall_uses_noninteractive_flags(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps({
                "instances": [{"name": "valheim2", "prefix": "/valheim2", "flask_port": 5002, "game": "valheim"}]
            }), encoding="utf-8")
            script_path = root / "game_commander.sh"
            script_path.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
            (root / "host_cli.py").write_text("#!/usr/bin/env python3\n", encoding="utf-8")
            app = self._make_app(root, manifest_path)
            with app.app_context(), \
                 mock.patch.object(hostops, "run_command", return_value=(True, "")) as run_mock, \
                 mock.patch.object(hub_host, "get_hub_payload", side_effect=[
                     {"instances": [{"name": "valheim2", "state": 0, "players": {"value": 0, "max": 10}}], "monitor": {}},
                     {"instances": [], "monitor": {}},
                 ]):
                ok, message, payload = hub_host.run_instance_uninstall("valheim2")
            self.assertTrue(ok)
            self.assertIn("désinstallée", message)
            self.assertEqual(payload["instances"], [])
            self.assertEqual(
                run_mock.call_args.args[0],
                ["sudo", "/usr/bin/python3", str(root / "host_cli.py"), "uninstall-instance", "--main-script", str(script_path), "--instance", "valheim2"],
            )

    def test_run_instance_uninstall_refuses_when_players_connected(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps({
                "instances": [{"name": "terraria", "prefix": "/terraria", "flask_port": 5007, "game": "terraria"}]
            }), encoding="utf-8")
            script_path = root / "game_commander.sh"
            script_path.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
            (root / "host_cli.py").write_text("#!/usr/bin/env python3\n", encoding="utf-8")
            app = self._make_app(root, manifest_path)
            with app.app_context(), \
                 mock.patch.object(hostops, "run_command") as run_mock, \
                 mock.patch.object(hub_host, "get_hub_payload", return_value={
                     "instances": [{"name": "terraria", "state": 20, "players": {"value": 2, "max": 8}}],
                     "monitor": {},
                 }):
                ok, message, payload = hub_host.run_instance_uninstall("terraria")
            self.assertFalse(ok)
            self.assertIn("joueur", message)
            self.assertEqual(payload["instances"][0]["name"], "terraria")
            run_mock.assert_not_called()

    def test_run_instance_uninstall_stops_service_before_uninstall(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps({
                "instances": [{"name": "terraria", "prefix": "/terraria", "flask_port": 5007, "game": "terraria"}]
            }), encoding="utf-8")
            script_path = root / "game_commander.sh"
            script_path.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
            (root / "host_cli.py").write_text("#!/usr/bin/env python3\n", encoding="utf-8")
            instance_dir = root / "game-commander-terraria"
            instance_dir.mkdir()
            (instance_dir / "deploy_config.env").write_text('GAME_SERVICE="terraria-server-terraria"\n', encoding="utf-8")
            app = self._make_app(root, manifest_path)
            with app.app_context(), \
                 mock.patch.object(Path, "home", return_value=root), \
                 mock.patch.object(hostops, "run_command", side_effect=[(True, ""), (True, "")]) as run_mock, \
                 mock.patch.object(hub_host, "get_hub_payload", side_effect=[
                     {"instances": [{"name": "terraria", "state": 20, "players": {"value": 0, "max": 8}}], "monitor": {}},
                     {"instances": [{"name": "terraria", "state": 20, "players": {"value": 0, "max": 8}}], "monitor": {}},
                     {"instances": [{"name": "terraria", "state": 0, "players": {"value": 0, "max": 8}}], "monitor": {}},
                     {"instances": [], "monitor": {}},
                 ]):
                ok, message, payload = hub_host.run_instance_uninstall("terraria")
            self.assertTrue(ok)
            self.assertIn("désinstallée", message)
            self.assertEqual(payload["instances"], [])
            self.assertEqual(
                run_mock.call_args_list[0].args[0],
                ["sudo", "/usr/bin/python3", str(root / "host_cli.py"), "service-action", "--service", "terraria-server-terraria", "--action", "stop"],
            )
            self.assertEqual(
                run_mock.call_args_list[1].args[0],
                ["sudo", "/usr/bin/python3", str(root / "host_cli.py"), "uninstall-instance", "--main-script", str(script_path), "--instance", "terraria", "--game-id", "terraria"],
            )

    def test_run_instance_admin_password_reset_updates_users_json(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps({
                "instances": [{"name": "valheim2", "prefix": "/valheim2", "flask_port": 5002, "game": "valheim"}]
            }), encoding="utf-8")
            instance_dir = root / "game-commander-valheim2"
            instance_dir.mkdir()
            (instance_dir / "deploy_config.env").write_text('ADMIN_LOGIN="adminv2"\nSYS_USER="vhserver"\n', encoding="utf-8")
            (instance_dir / "game.json").write_text(json.dumps({"permissions": ["manage_config", "console"]}), encoding="utf-8")
            (instance_dir / "users.json").write_text(json.dumps({
                "adminv2": {"password_hash": hub_auth.hash_password("oldpass123"), "permissions": ["manage_config", "console"]}
            }), encoding="utf-8")
            app = self._make_app(root, manifest_path)
            with app.app_context(), \
                 mock.patch.object(Path, "home", return_value=root), \
                 mock.patch.object(hub_host, "get_hub_payload", return_value={"instances": [{"name": "valheim2"}], "monitor": {}}):
                ok, message, card = hub_host.run_instance_admin_password_reset("valheim2", "newpass123")
            self.assertTrue(ok)
            self.assertIn("réinitialisé", message)
            self.assertEqual(card["name"], "valheim2")
            users = json.loads((instance_dir / "users.json").read_text(encoding="utf-8"))
            self.assertTrue(hub_host.bcrypt.checkpw("newpass123".encode(), users["adminv2"]["password_hash"].encode()))

    def test_get_hub_payload_reads_cpu_monitor_state(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps({
                "instances": [{"name": "valheim2", "prefix": "/valheim2", "flask_port": 5002, "game": "valheim"}]
            }), encoding="utf-8")
            (root / "cpu.json").write_text(json.dumps({
                "updated_at": time.time(),
                "instances": {
                    "valheim2": {"affinity": "4 5", "planned_affinity": "6 7", "cpu_percent": 12.5}
                }
            }), encoding="utf-8")
            app = self._make_app(root, manifest_path)
            with app.app_context(), mock.patch.object(hub_host, "_fetch_instance_hub_status", return_value={"state": 20, "metrics": {"players": {"value": 1, "max": 10}}}):
                payload = hub_host.get_hub_payload()
            self.assertEqual(payload["monitor"]["status"], "Stable")
            self.assertEqual(payload["instances"][0]["cpu_monitor"]["instance"]["affinity"], "4 5")

    def test_global_console_reads_last_lines(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps({"instances": []}), encoding="utf-8")
            app = self._make_app(root, manifest_path)
            log_dir = root / "action-logs"
            log_dir.mkdir()
            (log_dir / "hub-actions.log").write_text("line1\nline2\nline3\n", encoding="utf-8")
            with app.app_context():
                lines = hub_host.get_global_console(max_lines=2)
            self.assertEqual(lines, ["line2", "line3"])


class DeployHelpersTests(unittest.TestCase):

    def test_effective_backup_dir_uses_instance_subdirectory(self):
        path = deploybackups.effective_backup_dir("/home/vhserver/gamebackups", "valheim2")
        self.assertEqual(str(path), "/home/vhserver/gamebackups/valheim2")

    def test_render_backup_script_for_minecraft_includes_admin_files(self):
        content = deploybackups.render_backup_script(
            game_id="minecraft-fabric",
            backup_dir="/backups/minecraft-fabric",
            world_dir="/srv/mc/world",
            server_dir="/srv/mc",
        )
        self.assertIn('SERVER_DIR="/srv/mc"', content)
        self.assertIn('for f in server.properties ops.json whitelist.json', content)
        self.assertIn('PREFIX="minecraft-fabric"', content)

    def test_resolve_runtime_src_dir_accepts_repo_root(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "runtime").mkdir()
            (root / "runtime" / "app.py").write_text("print('ok')\n", encoding="utf-8")
            self.assertEqual(appfiles.resolve_runtime_src_dir(root), root / "runtime")

    def test_resolve_runtime_src_dir_accepts_runtime_dir(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "app.py").write_text("print('ok')\n", encoding="utf-8")
            self.assertEqual(appfiles.resolve_runtime_src_dir(root), root)

    def test_apply_ssl_existing_is_noop(self):
        ok, messages = deployssl.apply_ssl("existing", "gaming.example.com")
        self.assertTrue(ok)
        self.assertEqual(messages, ["SSL existant — non modifié"])

    def test_inspect_dependencies_reports_missing_from_empty_system(self):
        with mock.patch.object(deploydeps, "_is_dpkg_installed", return_value=False), \
             mock.patch.object(deploydeps, "_python_module_available", return_value=False), \
             mock.patch.object(deploydeps, "_cmd_exists", return_value=False), \
             mock.patch("subprocess.run") as run_mock:
            run_mock.return_value = mock.Mock(stdout="", returncode=0)
            payload = deploydeps.inspect_dependencies(
                deploy_mode="managed",
                steam_appid="896660",
                ssl_mode="certbot",
                game_id="enshrouded",
                home_dir="/home/gameserver",
            )
        self.assertIn("python3", payload["apt_missing"])
        self.assertIn("python3-flask", payload["python_apt_missing"])
        self.assertIn("requests", payload["python_pip_missing"])
        self.assertTrue(payload["need_i386"])
        self.assertFalse(payload["i386_enabled"])
        self.assertIn("lib32gcc-s1", payload["extra_apt_missing"])
        self.assertTrue(payload["enshrouded"]["required"])

    def test_latest_minecraft_server_url_uses_latest_release(self):
        def fake_fetch(url):
            if url.endswith("version_manifest_v2.json"):
                return {
                    "latest": {"release": "1.21.2"},
                    "versions": [{"id": "1.21.2", "url": "https://example.invalid/1.21.2.json"}],
                }
            if url == "https://example.invalid/1.21.2.json":
                return {"downloads": {"server": {"url": "https://example.invalid/server.jar"}}}
            raise AssertionError(url)

        version_id, jar_url = gameinstall.latest_minecraft_server_url(fake_fetch)
        self.assertEqual(version_id, "1.21.2")
        self.assertEqual(jar_url, "https://example.invalid/server.jar")

    def test_latest_fabric_server_meta_builds_expected_url(self):
        def fake_fetch(url):
            if url.endswith("version_manifest_v2.json"):
                return {"latest": {"release": "1.21.1"}}
            if url.endswith("/versions/loader"):
                return [{"version": "0.16.10"}]
            if url.endswith("/versions/installer"):
                return [{"version": "1.0.2"}]
            raise AssertionError(url)

        meta = gameinstall.latest_fabric_server_meta(fake_fetch)
        self.assertEqual(meta["minecraft_version"], "1.21.1")
        self.assertEqual(meta["loader_version"], "0.16.10")
        self.assertEqual(meta["installer_version"], "1.0.2")
        self.assertIn("/1.21.1/0.16.10/1.0.2/server/jar", meta["jar_url"])

    def test_install_valheim_installs_bepinex_and_strips_display_plugin(self):
        with tempfile.TemporaryDirectory() as tmp:
            server_dir = Path(tmp) / "server"
            data_dir = Path(tmp) / "data"
            server_dir.mkdir()
            data_dir.mkdir()
            (server_dir / "valheim_server.x86_64").write_text("bin", encoding="utf-8")

            bepinex_zip = Path(tmp) / "bep.zip"
            with zipfile.ZipFile(bepinex_zip, "w") as zf:
                zf.writestr("BepInExPack_Valheim/BepInEx/core/BepInEx.Preloader.dll", "core")
                zf.writestr("BepInExPack_Valheim/BepInEx/plugins/Valheim.DisplayBepInExInfo.dll", "junk")
                zf.writestr("BepInExPack_Valheim/start_game_bepinex.sh", "#!/bin/sh\n")

            def fake_download(_url, output_path):
                output_path.write_bytes(bepinex_zip.read_bytes())

            with mock.patch.object(gameinstall, "_download_file", side_effect=fake_download), \
                 mock.patch("shared.gameinstall.subprocess.run") as run_mock:
                run_mock.return_value = mock.Mock(returncode=0, stdout="", stderr="")
                messages = gameinstall.install_valheim(
                    server_dir=str(server_dir),
                    data_dir=str(data_dir),
                    sys_user="vhserver",
                    steamcmd_path="/home/vhserver/steamcmd/steamcmd.sh",
                    steam_appid="896660",
                    install_server=False,
                    install_bepinex=True,
                )

            self.assertIn("Binaire valheim_server.x86_64 vérifié", messages)
            self.assertIn("BepInEx installé", messages)
            self.assertTrue((server_dir / "BepInEx" / "core" / "BepInEx.Preloader.dll").is_file())
            self.assertFalse((server_dir / "BepInEx" / "plugins" / "Valheim.DisplayBepInExInfo.dll").exists())

    def test_install_enshrouded_uses_windows_steamcmd_and_verifies_binary(self):
        with tempfile.TemporaryDirectory() as tmp:
            server_dir = Path(tmp) / "server"
            data_dir = Path(tmp) / "data"

            def fake_run_steamcmd(**kwargs):
                server_dir.mkdir(parents=True, exist_ok=True)
                (server_dir / "enshrouded_server.exe").write_text("bin", encoding="utf-8")
                self.assertEqual(kwargs["platform"], "windows")
                return mock.Mock(returncode=0, stdout="", stderr="")

            with mock.patch.object(gameinstall, "_run_steamcmd", side_effect=fake_run_steamcmd), \
                 mock.patch("shared.gameinstall.subprocess.run") as run_mock:
                run_mock.return_value = mock.Mock(returncode=0, stdout="", stderr="")
                messages = gameinstall.install_enshrouded(
                    server_dir=str(server_dir),
                    data_dir=str(data_dir),
                    sys_user="vhserver",
                    steamcmd_path="/home/vhserver/steamcmd/steamcmd.sh",
                    steam_appid="2278520",
                )

            self.assertIn("Serveur Enshrouded téléchargé", messages)
            self.assertIn("Binaire enshrouded_server.exe vérifié", messages)

    def test_install_terraria_downloads_server_and_generates_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            server_dir = Path(tmp) / "server"
            data_dir = Path(tmp) / "data"
            script_dir = Path(tmp) / "repo"
            (script_dir / "tools").mkdir(parents=True)

            archive = Path(tmp) / "terraria.zip"
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("TerrariaServer/TerrariaServer.bin.x86_64", "bin")

            def fake_urlopen(req, timeout=20):
                url = req.full_url if hasattr(req, "full_url") else str(req)
                if url == "https://terraria.org/":
                    return io.BytesIO(
                        b'<a href="/api/download/pc-dedicated-server/terraria-server-1459.zip">download</a>'
                    )
                if url.endswith("terraria-server-1459.zip"):
                    return io.BytesIO(archive.read_bytes())
                raise AssertionError(url)

            captured_cfg_cmds = []

            def fake_run(cmd, **kwargs):
                if isinstance(cmd, list) and len(cmd) >= 4 and cmd[2].endswith("config_gen.py") and cmd[3] == "terraria-cfg":
                    captured_cfg_cmds.append(cmd)
                    out = Path(cmd[cmd.index("--out") + 1])
                    out.write_text("world=/tmp/world.wld\nworldpath=/tmp\nworldname=terraria2\n", encoding="utf-8")
                return mock.Mock(returncode=0, stdout="", stderr="")

            with mock.patch("shared.gameinstall.urllib.request.urlopen", side_effect=fake_urlopen), \
                 mock.patch("shared.gameinstall.subprocess.run", side_effect=fake_run):
                messages = gameinstall.install_terraria(
                    script_dir=str(script_dir),
                    server_dir=str(server_dir),
                    data_dir=str(data_dir),
                    sys_user="vhserver",
                    server_name="Serveur Terraria",
                    server_port="7777",
                    max_players="8",
                    server_password="secret123",
                    instance_id="terraria2",
                )

            self.assertIn("Serveur Terraria téléchargé", messages[0])
            self.assertIn("serverconfig.txt généré", messages)
            self.assertTrue((server_dir / "TerrariaServer.bin.x86_64").is_file())
            self.assertTrue((server_dir / "serverconfig.txt").is_file())
            self.assertEqual(len(captured_cfg_cmds), 1)
            cfg_cmd = captured_cfg_cmds[0]
            self.assertEqual(cfg_cmd[cfg_cmd.index("--password") + 1], "secret123")

    def test_install_soulmask_uses_linux_steamcmd_and_verifies_binary(self):
        with tempfile.TemporaryDirectory() as tmp:
            server_dir = Path(tmp) / "server"
            data_dir = Path(tmp) / "data"

            def fake_run_steamcmd(**kwargs):
                server_dir.mkdir(parents=True, exist_ok=True)
                (server_dir / "StartServer.sh").write_text("bin", encoding="utf-8")
                self.assertEqual(kwargs["platform"], "linux")
                return mock.Mock(returncode=0, stdout="", stderr="")

            with mock.patch.object(gameinstall, "_run_steamcmd", side_effect=fake_run_steamcmd), \
                 mock.patch("shared.gameinstall.subprocess.run") as run_mock:
                run_mock.return_value = mock.Mock(returncode=0, stdout="", stderr="")
                messages = gameinstall.install_soulmask(
                    server_dir=str(server_dir),
                    data_dir=str(data_dir),
                    sys_user="vhserver",
                    steamcmd_path="/home/vhserver/steamcmd/steamcmd.sh",
                    steam_appid="3017300",
                )

            self.assertIn("Serveur Soulmask téléchargé", messages)
            self.assertIn("Binaire StartServer.sh vérifié", messages)


class ConfigGenUsersJsonTests(unittest.TestCase):

    def test_valheim_permissions(self):
        out = tmp_path(".json")
        rc = config_gen.cmd_users_json(make_args(
            out=out, admin="admin", hash="$2b$fakehash", game_id="valheim",
        ))
        self.assertEqual(rc, 0)
        data = json.loads(Path(out).read_text())
        self.assertIn("admin", data)
        self.assertIn("install_mod", data["admin"]["permissions"])
        self.assertIn("manage_saves", data["admin"]["permissions"])
        self.assertEqual(data["admin"]["password_hash"], "$2b$fakehash")

    def test_enshrouded_permissions(self):
        out = tmp_path(".json")
        config_gen.cmd_users_json(make_args(
            out=out, admin="admin", hash="$2b$fakehash", game_id="enshrouded",
        ))
        data = json.loads(Path(out).read_text())
        self.assertNotIn("install_mod", data["admin"]["permissions"])
        self.assertIn("manage_saves", data["admin"]["permissions"])
        self.assertIn("manage_config", data["admin"]["permissions"])


class SaveManagerTests(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)
        self.app = Flask(__name__)
        self.app.config["GAME"] = {
            "id": "minecraft-fabric",
            "server": {
                "install_dir": str(self.root / "server"),
                "data_dir": str(self.root / "data"),
                "world_name": None,
            }
        }
        (self.root / "server" / "world" / "playerdata").mkdir(parents=True)
        (self.root / "server" / "world" / "level.dat").write_text("level")
        (self.root / "server" / "world" / "playerdata" / "abc.dat").write_text("player")

    def tearDown(self):
        self.tmpdir.cleanup()

    def _write_deploy_config(self, instance_id=None):
        lines = ['BACKUP_DIR="%s"' % (self.root / "backups")]
        if instance_id:
            lines.append('INSTANCE_ID="%s"' % instance_id)
        (self.root / "deploy_config.env").write_text(
            "\n".join(lines) + "\n",
            encoding="utf-8",
        )

    def test_get_save_roots_for_minecraft_fabric(self):
        with self.app.app_context():
            roots = core_saves.get_save_roots()
        self.assertEqual([r["id"] for r in roots], ["world", "playerdata"])
        self.assertTrue(all(r["exists"] for r in roots))

    def test_get_save_roots_for_satisfactory(self):
        self.app.config["GAME"] = {
            "id": "satisfactory",
            "server": {
                "install_dir": str(self.root / "server"),
                "data_dir": str(self.root / "data"),
                "world_name": None,
            }
        }
        savegames = self.root / "data" / ".config" / "Epic" / "FactoryGame" / "Saved" / "SaveGames" / "server"
        savegames.mkdir(parents=True, exist_ok=True)
        with self.app.app_context():
            roots = core_saves.get_save_roots()
        self.assertEqual([r["id"] for r in roots], ["savegames"])
        self.assertEqual(roots[0]["label"], "SaveGames")
        self.assertTrue(roots[0]["exists"])

    def test_list_entries_returns_directory_content(self):
        with self.app.app_context():
            data, err = core_saves.list_entries("world", "")
        self.assertIsNone(err)
        self.assertEqual(data["current_path"], "")
        names = [e["name"] for e in data["entries"]]
        self.assertIn("level.dat", names)
        self.assertIn("playerdata", names)

    def test_delete_save_entry_removes_file(self):
        target = self.root / "server" / "world" / "playerdata" / "abc.dat"
        with self.app.app_context():
            data, err = core_saves.delete_save_entry("playerdata", "abc.dat")
        self.assertIsNone(err)
        self.assertEqual(data["type"], "file")
        self.assertFalse(target.exists())

    def test_list_entries_blocks_path_traversal(self):
        with self.app.app_context():
            with self.assertRaises(ValueError):
                core_saves.list_entries("world", "../../etc")

    def test_download_directory_creates_zip(self):
        with self.app.test_request_context():
            target, filename, err = core_saves.get_download_target("world", "playerdata")
        self.assertIsNone(err)
        self.assertEqual(filename, "playerdata.zip")
        with zipfile.ZipFile(target) as zf:
            self.assertIn("playerdata/abc.dat", zf.namelist())

    def test_upload_plain_file_into_current_directory(self):
        upload = FileStorage(stream=io.BytesIO(b"newdata"), filename="new.dat")
        with self.app.app_context():
            data, err = core_saves.upload_save_files("world", "playerdata", [upload])
        self.assertIsNone(err)
        self.assertEqual(data["count"], 1)
        self.assertTrue((self.root / "server" / "world" / "playerdata" / "new.dat").exists())

    def test_upload_zip_extracts_safely(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("world/level.dat", b"123")
            zf.writestr("world/region/r.0.0.mca", b"456")
        buf.seek(0)
        upload = FileStorage(stream=buf, filename="restore.zip")
        with self.app.app_context():
            analysis, err = core_saves.analyze_uploads("world", "", [upload])
            data = core_saves.save_uploads(analysis)
        self.assertIsNone(err)
        self.assertEqual(data["count"], 1)
        self.assertIn("level.dat", data["extracted"])
        self.assertTrue((self.root / "server" / "world" / "level.dat").exists())
        self.assertTrue((self.root / "server" / "world" / "region" / "r.0.0.mca").exists())

    def test_upload_zip_blocks_traversal(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("../escape.txt", b"x")
        buf.seek(0)
        upload = FileStorage(stream=buf, filename="bad.zip")
        with self.app.app_context():
            with self.assertRaises(ValueError):
                core_saves.analyze_uploads("world", "", [upload])

    def test_upload_zip_rejects_invalid_minecraft_world_layout(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("random/file.txt", b"x")
        buf.seek(0)
        upload = FileStorage(stream=buf, filename="bad-layout.zip")
        with self.app.app_context():
            with self.assertRaises(ValueError):
                core_saves.analyze_uploads("world", "", [upload])

    def test_upload_zip_rejects_archive_restore_inside_subdirectory(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("world/level.dat", b"123")
        buf.seek(0)
        upload = FileStorage(stream=buf, filename="bad-subdir.zip")
        with self.app.app_context():
            with self.assertRaises(ValueError):
                core_saves.analyze_uploads("world", "playerdata", [upload])

    def test_analyze_upload_detects_collision(self):
        upload = FileStorage(stream=io.BytesIO(b"replacement"), filename="level.dat")
        with self.app.app_context():
            data, err = core_saves.analyze_uploads("world", "", [upload], extract_archives=False)
            core_saves.cleanup_upload_analysis(data)
        self.assertIsNone(err)
        self.assertEqual(data["collision_count"], 1)
        self.assertIn("level.dat", data["collisions"])

    def test_list_backups_returns_simplified_labels(self):
        self._write_deploy_config()
        backups = self.root / "backups"
        backups.mkdir()
        (backups / "minecraft-fabric_save_20260314_223346.zip").write_text("x")
        with self.app.app_context():
            data, err = core_saves.list_backups()
        self.assertIsNone(err)
        self.assertEqual(len(data["entries"]), 1)
        self.assertEqual(data["entries"][0]["label"], "14/03/2026 22:33:46")

    def test_list_backups_uses_instance_subdirectory_when_instance_id_is_set(self):
        self._write_deploy_config(instance_id="valheim2")
        backup_root = self.root / "backups"
        backup_root.mkdir()
        (backup_root / "MondeAncien_20260314_223346.zip").write_text("x")
        instance_dir = backup_root / "valheim2"
        instance_dir.mkdir()
        (instance_dir / "Monde2_20260314_223500.zip").write_text("y")
        self.app.config["GAME"] = {
            "id": "valheim",
            "server": {
                "install_dir": str(self.root / "server"),
                "data_dir": str(self.root / "data"),
                "world_name": "Monde2",
            }
        }
        with self.app.app_context():
            data, err = core_saves.list_backups()
        self.assertIsNone(err)
        self.assertEqual(str(instance_dir), data["backup_dir"])
        self.assertEqual(len(data["entries"]), 1)
        self.assertEqual(data["entries"][0]["name"], "Monde2_20260314_223500.zip")

    def test_list_backups_hides_safety_backups(self):
        self._write_deploy_config()
        backups = self.root / "backups"
        backups.mkdir()
        (backups / "minecraft-fabric_save_20260314_223346.zip").write_text("x")
        (backups / "gc_safety_before_restore_minecraft-fabric_20260314_223500.zip").write_text("y")
        with self.app.app_context():
            data, err = core_saves.list_backups()
        self.assertIsNone(err)
        self.assertEqual(len(data["entries"]), 1)
        self.assertEqual(data["entries"][0]["name"], "minecraft-fabric_save_20260314_223346.zip")

    def test_list_backups_valheim_uses_world_name_from_fwl(self):
        self._write_deploy_config()
        self.app.config["GAME"] = {
            "id": "valheim",
            "server": {
                "install_dir": str(self.root / "server"),
                "data_dir": str(self.root / "data"),
                "world_name": "Monde1",
            }
        }
        backups = self.root / "backups"
        backups.mkdir()
        path = backups / "Monde1_20260314_223346.zip"
        fwl = bytes([0x2B, 0, 0, 0, 0x25, 0, 0, 0, 6]) + b"Monde1" + b"\nGKbnRNIuU7"
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("Monde1.fwl", fwl)
            zf.writestr("Monde1.db", b"db")
        with self.app.app_context():
            data, err = core_saves.list_backups()
        self.assertIsNone(err)
        self.assertEqual(len(data["entries"]), 1)
        self.assertEqual(data["entries"][0]["world_name"], "Monde1")
        self.assertEqual(data["entries"][0]["label"], "Monde1 — 14/03/2026 22:33:46")

    def test_get_delete_requirements_marks_valheim_world_files_as_protected(self):
        self.app.config["GAME"] = {
            "id": "valheim",
            "server": {
                "install_dir": str(self.root / "server"),
                "data_dir": str(self.root / "data"),
                "world_name": "Monde1",
            }
        }
        worlds = self.root / "data" / "worlds_local"
        worlds.mkdir(parents=True, exist_ok=True)
        (worlds / "Monde1.db").write_text("db")
        with self.app.app_context():
            data, err = core_saves.get_delete_requirements("worlds", "Monde1.db")
        self.assertIsNone(err)
        self.assertTrue(data["protected"])
        self.assertEqual(data["world_name"], "Monde1")

    def test_snapshot_valheim_current_world_files_creates_targeted_backup(self):
        self._write_deploy_config()
        self.app.config["GAME"] = {
            "id": "valheim",
            "server": {
                "install_dir": str(self.root / "server"),
                "data_dir": str(self.root / "data"),
                "world_name": "Monde1",
            }
        }
        worlds = self.root / "data" / "worlds_local"
        worlds.mkdir(parents=True, exist_ok=True)
        (worlds / "Monde1.db").write_text("db")
        (worlds / "Monde1.fwl").write_bytes(bytes([0x2B, 0, 0, 0, 0x25, 0, 0, 0, 6]) + b"Monde1" + b"\nseed")
        (worlds / "Monde1.db.old").write_text("old")
        with self.app.app_context():
            data, err = core_saves.snapshot_valheim_current_world_files()
        self.assertIsNone(err)
        self.assertTrue(data["name"].startswith("gc_safety_predelete_valheim_Monde1_"))
        with zipfile.ZipFile(self.root / "backups" / data["name"]) as zf:
            self.assertIn("Monde1.db", zf.namelist())
            self.assertIn("Monde1.fwl", zf.namelist())
            self.assertIn("Monde1.db.old", zf.namelist())

    def test_snapshot_valheim_current_world_files_avoids_same_second_overwrite(self):
        self._write_deploy_config()
        self.app.config["GAME"] = {
            "id": "valheim",
            "server": {
                "install_dir": str(self.root / "server"),
                "data_dir": str(self.root / "data"),
                "world_name": "Monde1",
            }
        }
        worlds = self.root / "data" / "worlds_local"
        worlds.mkdir(parents=True, exist_ok=True)
        (worlds / "Monde1.db").write_text("db")
        (worlds / "Monde1.fwl").write_bytes(bytes([0x2B, 0, 0, 0, 0x25, 0, 0, 0, 6]) + b"Monde1" + b"\nseed")
        original_strftime = core_saves.time.strftime
        core_saves.time.strftime = lambda _fmt: "20260315_112233"
        try:
            with self.app.app_context():
                data1, err1 = core_saves.snapshot_valheim_current_world_files()
                data2, err2 = core_saves.snapshot_valheim_current_world_files()
        finally:
            core_saves.time.strftime = original_strftime
        self.assertIsNone(err1)
        self.assertIsNone(err2)
        self.assertNotEqual(data1["name"], data2["name"])
        self.assertTrue(data2["name"].endswith("_2.zip"))

    def test_run_safety_backup_renames_latest_backup_out_of_regular_list(self):
        self._write_deploy_config()
        original_run = core_saves.subprocess.run
        app_script = Path(self.app.root_path) / "backup_minecraft-fabric.sh"
        app_script.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")

        def fake_run(*args, **kwargs):
            backups = self.root / "backups"
            backups.mkdir(exist_ok=True)
            (backups / "minecraft-fabric_save_20260314_223346.zip").write_text("x")
            return types.SimpleNamespace(returncode=0, stdout="ok", stderr="")

        core_saves.subprocess.run = fake_run
        original_strftime = core_saves.time.strftime
        core_saves.time.strftime = lambda _fmt: "20260314_223500"
        try:
            with self.app.app_context():
                data, err = core_saves.run_safety_backup("before_restore")
                listed, _ = core_saves.list_backups()
        finally:
            core_saves.subprocess.run = original_run
            core_saves.time.strftime = original_strftime
        self.assertIsNone(err)
        self.assertTrue(data["name"].startswith("gc_safety_before_restore_minecraft-fabric_20260314_223500"))
        self.assertEqual(listed["entries"], [])

    def test_run_safety_backup_skips_valheim_when_world_files_missing(self):
        self._write_deploy_config()
        self.app.config["GAME"] = {
            "id": "valheim",
            "server": {
                "install_dir": str(self.root / "server"),
                "data_dir": str(self.root / "data"),
                "world_name": "Monde1",
            }
        }
        worlds = self.root / "data" / "worlds_local"
        worlds.mkdir(parents=True, exist_ok=True)
        with self.app.app_context():
            data, err = core_saves.run_safety_backup("before_restore")
        self.assertIsNone(err)
        self.assertTrue(data["skipped"])

    def test_get_backup_download_target_uses_backup_dir(self):
        self._write_deploy_config()
        backups = self.root / "backups"
        backups.mkdir()
        path = backups / "minecraft-fabric_save_20260314_223346.zip"
        path.write_text("x")
        with self.app.app_context():
            target, filename, err = core_saves.get_backup_download_target(path.name)
        self.assertIsNone(err)
        self.assertEqual(filename, path.name)

    def test_delete_backup_removes_zip(self):
        self._write_deploy_config()
        backups = self.root / "backups"
        backups.mkdir()
        path = backups / "minecraft-fabric_save_20260314_223346.zip"
        path.write_text("x")
        with self.app.app_context():
            data, err = core_saves.delete_backup(path.name)
        self.assertIsNone(err)
        self.assertEqual(data["deleted"], path.name)
        self.assertFalse(path.exists())

    def test_upload_backups_copies_zip_into_backup_dir(self):
        self._write_deploy_config()
        upload = FileStorage(stream=io.BytesIO(b"zipdata"), filename="import.zip")
        with self.app.app_context():
            data, err = core_saves.upload_backups([upload])
        self.assertIsNone(err)
        self.assertEqual(data["count"], 1)
        backups = list((self.root / "backups").glob("minecraft-fabric_save_*_import.zip"))
        self.assertEqual(len(backups), 1)

    def test_restore_backup_restores_world_and_admin_files(self):
        self._write_deploy_config()
        backups = self.root / "backups"
        backups.mkdir()
        path = backups / "minecraft-fabric_save_20260314_223346.zip"
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("world/level.dat", b"restored")
            zf.writestr("server.properties", b"motd=test")
        with self.app.app_context():
            data, err = core_saves.restore_backup(path.name)
        self.assertIsNone(err)
        self.assertEqual(data["collision_count"], 1)
        self.assertEqual((self.root / "server" / "world" / "level.dat").read_bytes(), b"restored")
        self.assertEqual((self.root / "server" / "server.properties").read_bytes(), b"motd=test")

    def test_restore_backup_valheim_targets_current_world_and_promotes_old_files(self):
        self._write_deploy_config()
        self.app.config["GAME"] = {
            "id": "valheim",
            "server": {
                "install_dir": str(self.root / "server"),
                "data_dir": str(self.root / "data"),
                "world_name": "Monde",
            }
        }
        worlds = self.root / "data" / "worlds_local"
        worlds.mkdir(parents=True, exist_ok=True)
        (worlds / "Monde.fwl").write_text("current", encoding="utf-8")
        backups = self.root / "backups"
        backups.mkdir()
        path = backups / "Monde1_20260315_113402.zip"
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("Monde1.db", b"db")
            zf.writestr("Monde1.fwl.old", b"old-meta")
        with self.app.app_context():
            data, err = core_saves.restore_backup(path.name)
        self.assertIsNone(err)
        self.assertEqual((worlds / "Monde.db").read_bytes(), b"db")
        self.assertEqual((worlds / "Monde.fwl.old").read_bytes(), b"old-meta")
        self.assertEqual((worlds / "Monde.fwl").read_bytes(), b"old-meta")
        self.assertFalse((worlds / "Monde1.db").exists())
        self.assertFalse((worlds / "Monde1.fwl.old").exists())
        self.assertIn("Monde.db", data["written"])
        self.assertIn("Monde.fwl", data["written"])


class ValheimWorldSelectionTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.app = Flask(__name__)
        self.app.root_path = str(self.root / "app")
        Path(self.app.root_path).mkdir(parents=True, exist_ok=True)
        (self.root / "server").mkdir()
        (self.root / "data" / "worlds_local").mkdir(parents=True)
        self.app.config["GAME"] = {
            "id": "valheim",
            "server": {
                "install_dir": str(self.root / "server"),
                "data_dir": str(self.root / "data"),
                "world_name": "Monde",
                "max_players": 10,
            }
        }
        (Path(self.app.root_path) / "game.json").write_text(json.dumps({
            "server": {"world_name": "Monde"}
        }), encoding="utf-8")
        (Path(self.app.root_path) / "deploy_config.env").write_text(
            'WORLD_NAME="Monde"\nBACKUP_DIR="' + str(self.root / "backups") + '"\n',
            encoding="utf-8",
        )
        (Path(self.app.root_path) / "backup_valheim.sh").write_text(
            '#!/usr/bin/env bash\nWORLD_NAME="Monde"\n',
            encoding="utf-8",
        )
        (self.root / "server" / "start_server.sh").write_text(
            'exec ./valheim_server.x86_64 -world "Monde" -savedir "/data"\n',
            encoding="utf-8",
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_list_worlds_returns_detected_worlds(self):
        worlds = self.root / "data" / "worlds_local"
        (worlds / "Monde.db").write_text("db")
        (worlds / "Monde2.fwl").write_text("fwl")
        with self.app.app_context():
            data, err = valheim_worlds.list_worlds()
        self.assertIsNone(err)
        self.assertEqual([w["name"] for w in data["worlds"]], ["Monde", "Monde2"])
        self.assertEqual(data["current_world"], "Monde")
        self.assertEqual(data["worlds"][0]["label"], "Monde")

    def test_list_worlds_ignores_auto_backup_world_files(self):
        worlds = self.root / "data" / "worlds_local"
        (worlds / "Cauchemar2.db").write_text("db")
        (worlds / "MondePerso.fwl").write_text("fwl")
        (worlds / "ParcEssai_backup_auto-20260315130210.db").write_text("backup")
        with self.app.app_context():
            data, err = valheim_worlds.list_worlds()
        self.assertIsNone(err)
        self.assertEqual([w["name"] for w in data["worlds"]], ["Cauchemar2", "Monde", "MondePerso"])

    def test_select_world_updates_runtime_and_scripts(self):
        worlds = self.root / "data" / "worlds_local"
        (worlds / "Monde.db").write_text("db")
        (worlds / "Monde2.fwl").write_text("fwl")
        with self.app.app_context():
            data, err = valheim_worlds.select_world("Monde2")
        self.assertIsNone(err)
        self.assertEqual(data["world_name"], "Monde2")
        self.assertEqual(self.app.config["GAME"]["server"]["world_name"], "Monde2")
        self.assertIn('"world_name": "Monde2"', (Path(self.app.root_path) / "game.json").read_text())
        self.assertIn('WORLD_NAME="Monde2"', (Path(self.app.root_path) / "deploy_config.env").read_text())
        self.assertIn('WORLD_NAME="Monde2"', (Path(self.app.root_path) / "backup_valheim.sh").read_text())
        self.assertIn('-world "Monde2"', (self.root / "server" / "start_server.sh").read_text())

    def test_list_worlds_keeps_missing_current_world_marked_absent(self):
        worlds = self.root / "data" / "worlds_local"
        (worlds / "Cauchemar2.fwl").write_text("fwl")
        with self.app.app_context():
            data, err = valheim_worlds.list_worlds()
        self.assertIsNone(err)
        self.assertEqual([w["name"] for w in data["worlds"]], ["Cauchemar2", "Monde"])
        missing = next(w for w in data["worlds"] if w["name"] == "Monde")
        self.assertFalse(missing["exists"])
        self.assertEqual(missing["label"], "Monde (absent)")

    def test_select_world_migrates_legacy_world_modifiers_to_previous_world(self):
        worlds = self.root / "data" / "worlds_local"
        (worlds / "Monde.db").write_text("db")
        (worlds / "Cauchemar2.fwl").write_text("fwl")
        legacy = self.root / "server" / "world_modifiers.json"
        legacy.write_text(json.dumps({"combat": "hardcore", "setkeys": ["nomap"]}), encoding="utf-8")
        with self.app.app_context():
            data, err = valheim_worlds.select_world("Cauchemar2")
        self.assertIsNone(err)
        migrated = self.root / "server" / "world_modifiers.Monde.json"
        self.assertTrue(migrated.exists())
        self.assertEqual(json.loads(migrated.read_text(encoding="utf-8"))["combat"], "hardcore")


class ValheimWorldModifiersTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.app = Flask(__name__)
        self.app.config["GAME"] = {
            "id": "valheim",
            "server": {
                "install_dir": str(self.root / "server"),
                "data_dir": str(self.root / "data"),
                "world_name": "Cauchemar2",
            }
        }
        (self.root / "server").mkdir(parents=True, exist_ok=True)
        (self.root / "data" / "worlds_local").mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_read_modifiers_from_fwl_when_no_json_exists(self):
        fwl = (
            bytes([0x2B, 0, 0, 0, 0x25, 0, 0, 0, 10]) + b"Cauchemar2" +
            b"\npreset hardcore\nnobossportals\nnomap\nenemydamage 200\n"
        )
        (self.root / "data" / "worlds_local" / "Cauchemar2.fwl").write_bytes(fwl)
        with self.app.app_context():
            data, err = valheim_world_modifiers.read_modifiers()
        self.assertIsNone(err)
        self.assertEqual(data["combat"], "veryhard")
        self.assertEqual(data["deathpenalty"], "hardcore")
        self.assertEqual(data["portals"], "nobossportals")
        self.assertIn("nomap", data["setkeys"])


class ValheimAdminsTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.app = Flask(__name__)
        self.app.config["GAME"] = {
            "id": "valheim",
            "server": {
                "install_dir": str(self.root / "server"),
                "data_dir": str(self.root / "data"),
                "world_name": "Monde1",
            }
        }
        (self.root / "data").mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_add_and_remove_admin(self):
        with self.app.app_context():
            data, err = valheim_admins.add_admin("76561198298757896")
            listed, err2 = valheim_admins.list_admins()
            removed, err3 = valheim_admins.remove_admin("76561198298757896")
        self.assertIsNone(err)
        self.assertIsNone(err2)
        self.assertIsNone(err3)
        self.assertFalse(data["already_present"])
        self.assertEqual(listed["entries"][0]["steamid"], "76561198298757896")
        self.assertTrue(removed["removed"])


class ValheimPlayersTests(unittest.TestCase):

    def test_tracks_connected_players_with_steamid(self):
        original_run = valheim_players.subprocess.run

        def fake_run(*args, **kwargs):
            lines = "\n".join([
                "03/15/2026 12:36:51: Got connection SteamID 11111111111111111",
                "03/15/2026 12:36:52: Got character ZDOID from PlayerOne : 123:456",
            ])
            return types.SimpleNamespace(stdout=lines)

        valheim_players.subprocess.run = fake_run
        app = Flask(__name__)
        app.config["GAME"] = {"server": {"service": "valheim-server-test"}}
        try:
            with app.app_context():
                players = valheim_players.get_players()
        finally:
            valheim_players.subprocess.run = original_run
        self.assertEqual(players, [{"name": "PlayerOne", "steamid": "11111111111111111"}])

    def test_disconnect_by_steamid_removes_player(self):
        original_run = valheim_players.subprocess.run

        def fake_run(*args, **kwargs):
            lines = "\n".join([
                "03/15/2026 12:36:51: Got connection SteamID 11111111111111111",
                "03/15/2026 12:36:52: Got character ZDOID from PlayerOne : 123:456",
                "[Message:Better Networking] Compression: [11111111111111111] disconnected",
            ])
            return types.SimpleNamespace(stdout=lines)

        valheim_players.subprocess.run = fake_run
        app = Flask(__name__)
        app.config["GAME"] = {"server": {"service": "valheim-server-test"}}
        try:
            with app.app_context():
                players = valheim_players.get_players()
        finally:
            valheim_players.subprocess.run = original_run
        self.assertEqual(players, [])

    def test_tracks_connected_players_when_name_precedes_steamid(self):
        original_run = valheim_players.subprocess.run

        def fake_run(*args, **kwargs):
            lines = "\n".join([
                "03/15/2026 12:36:51: Got character ZDOID from PlayerOne : 123:456",
                "03/15/2026 12:36:52: Got connection SteamID 11111111111111111",
            ])
            return types.SimpleNamespace(stdout=lines)

        valheim_players.subprocess.run = fake_run
        app = Flask(__name__)
        app.config["GAME"] = {"server": {"service": "valheim-server-test"}}
        try:
            with app.app_context():
                players = valheim_players.get_players()
        finally:
            valheim_players.subprocess.run = original_run
        self.assertEqual(players, [{"name": "PlayerOne", "steamid": "11111111111111111"}])

    def test_tracks_connected_players_from_playfab_platform_id(self):
        original_run = valheim_players.subprocess.run

        def fake_run(*args, **kwargs):
            lines = "\n".join([
                "03/15/2026 17:46:53: PlayFab socket with remote ID playfab/333D6B4687BBBA00 received local Platform ID Steam_22222222222222222",
                "03/15/2026 17:47:20: Got character ZDOID from PlayerTwo : 1436054514:2",
            ])
            return types.SimpleNamespace(stdout=lines)

        valheim_players.subprocess.run = fake_run
        app = Flask(__name__)
        app.config["GAME"] = {"server": {"service": "valheim-server-test"}}
        try:
            with app.app_context():
                players = valheim_players.get_players()
        finally:
            valheim_players.subprocess.run = original_run
        self.assertEqual(players, [{"name": "PlayerTwo", "steamid": "22222222222222222"}])

    def test_tracks_multiple_players_when_names_precede_steamids(self):
        original_run = valheim_players.subprocess.run

        def fake_run(*args, **kwargs):
            lines = "\n".join([
                "03/15/2026 12:36:51: Got character ZDOID from Alice : 123:456",
                "03/15/2026 12:36:52: Got character ZDOID from Bob : 123:457",
                "03/15/2026 12:36:53: Got character ZDOID from Carol : 123:458",
                "03/15/2026 12:36:54: Got connection SteamID 11111111111111111",
                "03/15/2026 12:36:55: Got connection SteamID 22222222222222222",
                "03/15/2026 12:36:56: Got connection SteamID 33333333333333333",
            ])
            return types.SimpleNamespace(stdout=lines)

        valheim_players.subprocess.run = fake_run
        app = Flask(__name__)
        app.config["GAME"] = {"server": {"service": "valheim-server-test"}}
        try:
            with app.app_context():
                players = valheim_players.get_players()
        finally:
            valheim_players.subprocess.run = original_run
        self.assertEqual(players, [
            {"name": "Alice", "steamid": "11111111111111111"},
            {"name": "Bob", "steamid": "22222222222222222"},
            {"name": "Carol", "steamid": "33333333333333333"},
        ])


class ConfigGenEnshroudedCfgTests(unittest.TestCase):

    def test_basic_generation(self):
        out = tmp_path(".json")
        rc = config_gen.cmd_enshrouded_cfg(make_args(
            out=out, name="MonServeur", password="secret",
            port=15639, max_players=16,
        ))
        self.assertEqual(rc, 0)
        data = json.loads(Path(out).read_text())
        self.assertEqual(data["name"], "MonServeur")
        self.assertEqual(data["queryPort"], 15640)
        self.assertEqual(data["slotCount"], 16)
        self.assertNotIn("gamePort", data)
        self.assertEqual(data["userGroups"][0]["password"], "secret")
        self.assertEqual(data["userGroups"][0]["name"], "Default")

    def test_password_recovery_on_redeploy(self):
        """Bug [3] : si password vide, récupérer celui du fichier existant."""
        out = tmp_path(".json")
        # Première génération avec mot de passe
        config_gen.cmd_enshrouded_cfg(make_args(
            out=out, name="MonServeur", password="motdepasse_original",
            port=15639, max_players=16,
        ))
        # Redéploiement sans mot de passe (comme lors d'un --config)
        rc = config_gen.cmd_enshrouded_cfg(make_args(
            out=out, name="MonServeur", password="",
            port=15639, max_players=16,
        ))
        self.assertEqual(rc, 0)
        data = json.loads(Path(out).read_text())
        self.assertEqual(data["userGroups"][0]["password"], "motdepasse_original",
                         "Le mot de passe existant doit être préservé sur redéploiement")

    def test_special_chars_in_password(self):
        """Bug [3] : les caractères spéciaux ne doivent pas être corrompus."""
        out = tmp_path(".json")
        password = r'P@$$w0rd\n"quoted"&special'
        config_gen.cmd_enshrouded_cfg(make_args(
            out=out, name="Test", password=password,
            port=15639, max_players=16,
        ))
        data = json.loads(Path(out).read_text())
        self.assertEqual(data["userGroups"][0]["password"], password,
                         "Les caractères spéciaux ne doivent pas être modifiés")


class ConfigGenPatchBepinexTests(unittest.TestCase):

    BEPINEX_SCRIPT = """\
#!/usr/bin/env bash
export DOORSTOP_ENABLE=TRUE
export DOORSTOP_INVOKE_DLL_PATH=./BepInEx/core/BepInEx.Preloader.dll
cd /home/gameserver/valheim_server
exec ./valheim_server.x86_64 -name "Ancien Nom" -port 2456 -world "AncienMonde" -password "ancienmdp" -savedir "/home/gameserver/data" -public 1
"""

    def test_replaces_existing_exec(self):
        script = tmp_file(self.BEPINEX_SCRIPT, suffix=".sh")
        try:
            rc = config_gen.cmd_patch_bepinex(make_args(
                script=script, name="Nouveau Nom", port=5900,
                world="NouveauMonde", password="nouveaumdp",
                savedir="/home/gameserver/valheim8_data", extra_flag="",
            ))
            self.assertEqual(rc, 0)
            content = Path(script).read_text()
            self.assertIn('"Nouveau Nom"', content)
            self.assertIn("-port 5900", content)
            self.assertIn('"NouveauMonde"', content)
            self.assertIn("-password \"nouveaumdp\"", content)
            self.assertNotIn("Ancien Nom", content)
        finally:
            os.unlink(script)

    def test_extra_flag_playfab(self):
        script = tmp_file(self.BEPINEX_SCRIPT, suffix=".sh")
        try:
            config_gen.cmd_patch_bepinex(make_args(
                script=script, name="Serveur", port=5900,
                world="Monde", password="mdp",
                savedir="/data", extra_flag="-playfab",
            ))
            content = Path(script).read_text()
            self.assertIn("-playfab", content)
        finally:
            os.unlink(script)

    def test_no_extra_flag(self):
        script = tmp_file(self.BEPINEX_SCRIPT, suffix=".sh")
        try:
            config_gen.cmd_patch_bepinex(make_args(
                script=script, name="Serveur", port=5900,
                world="Monde", password="mdp",
                savedir="/data", extra_flag="",
            ))
            content = Path(script).read_text()
            self.assertNotIn("-playfab", content)
            self.assertNotIn("-crossplay", content)
        finally:
            os.unlink(script)

    def test_missing_script_returns_error(self):
        rc = config_gen.cmd_patch_bepinex(make_args(
            script="/tmp/inexistant_gc_test.sh", name="X", port=1,
            world="W", password="p", savedir="/d", extra_flag="",
        ))
        self.assertEqual(rc, 1)

    def test_special_chars_in_password_no_corruption(self):
        """Bug [3] étendu : les caractères spéciaux dans le mot de passe."""
        script = tmp_file(self.BEPINEX_SCRIPT, suffix=".sh")
        try:
            password = 'P@ssw0rd"special'
            config_gen.cmd_patch_bepinex(make_args(
                script=script, name="Serveur", port=5900,
                world="Monde", password=password,
                savedir="/data", extra_flag="",
            ))
            content = Path(script).read_text()
            self.assertIn(password, content)
        finally:
            os.unlink(script)


class ConfigGenMinecraftPropsTests(unittest.TestCase):

    def test_basic_generation(self):
        out = tmp_path(".properties")
        rc = config_gen.cmd_minecraft_props(make_args(
            out=out, name="Mon Serveur Bloc", port=25565, max_players=20,
        ))
        self.assertEqual(rc, 0)
        content = Path(out).read_text()
        self.assertIn("motd=Mon Serveur Bloc", content)
        self.assertIn("server-port=25565", content)
        self.assertIn("max-players=20", content)


class ConfigGenTerrariaCfgTests(unittest.TestCase):

    def test_basic_generation(self):
        out = tmp_path(".txt")
        rc = config_gen.cmd_terraria_cfg(make_args(
            out=out, name="Mon Serveur Terraria", port=7777, max_players=8,
            world_path="/home/gameserver/terraria_data", world_name="testworld",
            password="secret", autocreate=2, difficulty=1,
        ))
        self.assertEqual(rc, 0)
        content = Path(out).read_text()
        self.assertIn("worldpath=/home/gameserver/terraria_data", content)
        self.assertIn("worldname=testworld", content)
        self.assertIn("world=/home/gameserver/terraria_data/testworld.wld", content)
        self.assertIn("port=7777", content)
        self.assertIn("maxplayers=8", content)
        self.assertIn("password=secret", content)
        self.assertIn("difficulty=1", content)


class ConfigGenSoulmaskCfgTests(unittest.TestCase):

    def test_basic_generation(self):
        out = tmp_path(".json")
        rc = config_gen.cmd_soulmask_cfg(make_args(
            out=out, name="Mon Serveur Soulmask", port=8777, query_port=27015,
            echo_port=18888, max_players=50, password="secret", admin_password="adminsecret",
            mode="pve", backup_enabled=True, saving_enabled=True, backup_interval=7200,
            log_dir="/srv/soulmask/logs", saved_dir="/srv/soulmask/saved",
        ))
        self.assertEqual(rc, 0)
        data = json.loads(Path(out).read_text())
        self.assertEqual(data["server_name"], "Mon Serveur Soulmask")
        self.assertEqual(data["query_port"], 27015)
        self.assertEqual(data["echo_port"], 18888)
        self.assertEqual(data["mode"], "pve")


class MinecraftConfigTests(unittest.TestCase):

    def _app(self, install_dir):
        app = Flask(__name__)
        app.config["GAME"] = {
            "name": "Minecraft",
            "server": {"install_dir": install_dir, "port": 25565, "max_players": 20},
        }
        return app

    def test_read_defaults_when_file_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            app = self._app(tmpdir)
            with app.app_context():
                data, err = minecraft_config.read_config()
            self.assertIsNone(err)
            self.assertEqual(data["Server"]["server-port"], "25565")
            self.assertEqual(data["Server"]["max-players"], "20")

    def test_write_and_read_properties(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            app = self._app(tmpdir)
            with app.app_context():
                ok, err = minecraft_config.write_config({
                    "Server": {
                        "motd": "Bloc Land",
                        "server-port": "25570",
                        "max-players": "12",
                        "difficulty": "hard",
                        "gamemode": "creative",
                        "pvp": "false",
                        "allow-nether": "true",
                        "enable-command-block": "true",
                        "spawn-monsters": "true",
                        "spawn-animals": "false",
                        "view-distance": "12",
                        "simulation-distance": "10",
                    }
                })
                self.assertTrue(ok)
                self.assertIsNone(err)
                data, err = minecraft_config.read_config()
            self.assertIsNone(err)
            self.assertEqual(data["Server"]["motd"], "Bloc Land")
            self.assertEqual(data["Server"]["server-port"], "25570")
            self.assertEqual(data["Server"]["gamemode"], "creative")

    def test_validation_rejects_invalid_port(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            app = self._app(tmpdir)
            with app.app_context():
                ok, err = minecraft_config.write_config({
                    "Server": {
                        "server-port": "99999",
                        "max-players": "20",
                        "difficulty": "easy",
                        "gamemode": "survival",
                        "pvp": "true",
                        "allow-nether": "true",
                        "enable-command-block": "false",
                        "spawn-monsters": "true",
                        "spawn-animals": "true",
                        "view-distance": "10",
                        "simulation-distance": "10",
                        "motd": "Test",
                    }
                })
            self.assertFalse(ok)
            self.assertIn("server-port", err)


class TerrariaConfigTests(unittest.TestCase):

    def _app(self, install_dir, data_dir):
        app = Flask(__name__)
        app.config["GAME"] = {
            "id": "terraria",
            "name": "Terraria",
            "server": {
                "install_dir": install_dir,
                "data_dir": data_dir,
                "port": 7777,
                "max_players": 8,
            },
        }
        return app

    def test_read_defaults_when_file_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            app = self._app(tmpdir, os.path.join(tmpdir, "worlds"))
            with app.app_context():
                data, err = terraria_config.read_config()
            self.assertIsNone(err)
            self.assertEqual(data["port"], "7777")
            self.assertEqual(data["maxplayers"], "8")

    def test_write_and_read_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            app = self._app(tmpdir, os.path.join(tmpdir, "worlds"))
            with app.app_context():
                ok, err = terraria_config.write_config({
                    "worldname": "bossrush",
                    "motd": "Bienvenue",
                    "maxplayers": "12",
                    "password": "secret",
                    "autocreate": "3",
                    "difficulty": "2",
                    "seed": "abc123",
                    "banlist": "custom-banlist.txt",
                    "secure": "1",
                    "noupnp": "1",
                    "steam": "1",
                    "lobby": "private",
                    "ip": "0.0.0.0",
                    "forcepriority": "1",
                    "disableannouncementbox": "1",
                    "announcementboxrange": "250",
                })
                self.assertTrue(ok)
                self.assertIsNone(err)
                data, err = terraria_config.read_config()
            self.assertIsNone(err)
            self.assertEqual(data["worldname"], "bossrush")
            self.assertEqual(data["motd"], "Bienvenue")
            self.assertEqual(data["difficulty"], "2")
            self.assertEqual(data["seed"], "abc123")
            self.assertEqual(data["lobby"], "private")
            self.assertEqual(data["announcementboxrange"], "250")
            self.assertEqual(data["world"], os.path.join(tmpdir, "worlds", "bossrush.wld"))

    def test_validation_rejects_invalid_difficulty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            app = self._app(tmpdir, os.path.join(tmpdir, "worlds"))
            with app.app_context():
                ok, err = terraria_config.write_config({
                    "worldname": "bossrush",
                    "motd": "Bienvenue",
                    "maxplayers": "12",
                    "password": "",
                    "autocreate": "2",
                    "difficulty": "9",
                })
            self.assertFalse(ok)
            self.assertIn("difficulty", err)

    def test_validation_rejects_invalid_lobby(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            app = self._app(tmpdir, os.path.join(tmpdir, "worlds"))
            with app.app_context():
                ok, err = terraria_config.write_config({
                    "worldname": "bossrush",
                    "motd": "Bienvenue",
                    "maxplayers": "12",
                    "password": "",
                    "autocreate": "2",
                    "difficulty": "0",
                    "lobby": "public",
                })
            self.assertFalse(ok)
            self.assertIn("lobby", err)


class TerrariaWorldsTests(unittest.TestCase):

    def _app(self, install_dir, data_dir):
        app = Flask(__name__)
        app.config["GAME"] = {
            "id": "terraria",
            "name": "Terraria",
            "server": {
                "install_dir": install_dir,
                "data_dir": data_dir,
                "port": 7777,
                "max_players": 8,
                "world_name": None,
            },
        }
        return app

    def test_list_worlds_detects_existing_world_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = os.path.join(tmpdir, "worlds")
            os.makedirs(data_dir, exist_ok=True)
            Path(os.path.join(data_dir, "alpha.wld")).write_text("", encoding="utf-8")
            Path(os.path.join(data_dir, "beta.wld")).write_text("", encoding="utf-8")
            app = self._app(tmpdir, data_dir)
            with app.app_context():
                data, err = terraria_worlds.list_worlds()
            self.assertIsNone(err)
            self.assertEqual(data["current_world"], "terraria")
            self.assertEqual([w["name"] for w in data["worlds"]], ["alpha", "beta", "terraria"])
            self.assertFalse(next(w for w in data["worlds"] if w["name"] == "terraria")["exists"])

    def test_select_world_updates_serverconfig_and_app_state(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = os.path.join(tmpdir, "worlds")
            os.makedirs(data_dir, exist_ok=True)
            Path(os.path.join(data_dir, "bossrush.wld")).write_text("", encoding="utf-8")
            app_dir = os.path.join(tmpdir, "runtime")
            os.makedirs(app_dir, exist_ok=True)
            Path(os.path.join(app_dir, "game.json")).write_text(json.dumps({
                "id": "terraria",
                "server": {
                    "world_name": None,
                },
            }), encoding="utf-8")
            Path(os.path.join(app_dir, "deploy_config.env")).write_text('WORLD_NAME="terraria"\n', encoding="utf-8")
            Path(os.path.join(app_dir, "backup_terraria.sh")).write_text('WORLD_NAME="terraria"\n', encoding="utf-8")
            app = self._app(tmpdir, data_dir)
            app.root_path = app_dir
            with app.app_context():
                ok, err = terraria_config.write_config({
                    "worldname": "terraria",
                    "motd": "Bienvenue",
                    "maxplayers": "8",
                    "password": "",
                    "autocreate": "2",
                    "difficulty": "0",
                })
                self.assertTrue(ok)
                self.assertIsNone(err)
                data, err = terraria_worlds.select_world("bossrush")
                self.assertIsNone(err)
                self.assertEqual(data["world_name"], "bossrush")
                cfg, err = terraria_config.read_config()
                self.assertIsNone(err)
                self.assertEqual(cfg["worldname"], "bossrush")
                self.assertEqual(app.config["GAME"]["server"]["world_name"], "bossrush")
                self.assertIn('WORLD_NAME="bossrush"', Path(os.path.join(app_dir, "deploy_config.env")).read_text(encoding="utf-8"))
                self.assertIn('WORLD_NAME="bossrush"', Path(os.path.join(app_dir, "backup_terraria.sh")).read_text(encoding="utf-8"))


class TerrariaPlayersTests(unittest.TestCase):

    def test_tracks_connected_players_from_logs(self):
        lines = "\n".join([
            "Server started",
            "203.0.113.10:60232 is connecting...",
            "PlayerOne has joined.",
            "Alice has joined.",
            "PlayerOne has left.",
        ])
        original = terraria_players.subprocess.run
        terraria_players.subprocess.run = lambda *args, **kwargs: types.SimpleNamespace(stdout=lines)
        try:
            players = terraria_players.get_players()
        finally:
            terraria_players.subprocess.run = original
        self.assertEqual(players, [{'name': 'Alice', 'ip': ''}])

    def test_reconnect_does_not_duplicate_player(self):
        lines = "\n".join([
            "203.0.113.10:60232 is connecting...",
            "PlayerOne has joined.",
            "PlayerOne has left.",
            "203.0.113.10:60233 is connecting...",
            "PlayerOne has joined.",
        ])
        original = terraria_players.subprocess.run
        terraria_players.subprocess.run = lambda *args, **kwargs: types.SimpleNamespace(stdout=lines)
        try:
            players = terraria_players.get_players()
        finally:
            terraria_players.subprocess.run = original
        self.assertEqual(players, [{'name': 'PlayerOne', 'ip': '203.0.113.10'}])


class TerrariaBanlistTests(unittest.TestCase):

    def _app(self, install_dir, data_dir):
        app = Flask(__name__)
        app.config["GAME"] = {
            "id": "terraria",
            "name": "Terraria",
            "server": {
                "install_dir": install_dir,
                "data_dir": data_dir,
                "port": 7777,
                "max_players": 8,
            },
        }
        return app

    def test_add_and_remove_ban(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = os.path.join(tmpdir, "worlds")
            os.makedirs(data_dir, exist_ok=True)
            app = self._app(tmpdir, data_dir)
            with app.app_context():
                ok, err = terraria_config.write_config({
                    "worldname": "terraria",
                    "motd": "Bienvenue",
                    "maxplayers": "8",
                    "password": "",
                    "autocreate": "2",
                    "difficulty": "0",
                    "banlist": "banlist.txt",
                })
                self.assertTrue(ok)
                self.assertIsNone(err)
                terraria_admins._journal_lines = lambda: [
                    "203.0.113.10:60232 is connecting...",
                    "PlayerOne has joined.",
                ]
                data, err = terraria_admins.add_ban("PlayerOne")
                self.assertIsNone(err)
                self.assertFalse(data["already_present"])
                self.assertEqual(data["ip"], "203.0.113.10")
                data, err = terraria_admins.list_bans()
                self.assertIsNone(err)
                self.assertEqual(data["entries"], [{"name": "PlayerOne", "ip": "203.0.113.10"}])
                data, err = terraria_admins.remove_ban("PlayerOne")
                self.assertIsNone(err)
                self.assertEqual(data["name"], "PlayerOne")
                data, err = terraria_admins.list_bans()
                self.assertIsNone(err)
                self.assertEqual(data["entries"], [])


class EnshroudedConfigTests(unittest.TestCase):

    def _app(self, install_dir):
        app = Flask(__name__)
        app.config["GAME"] = {
            "id": "enshrouded",
            "name": "Enshrouded",
            "server": {
                "install_dir": install_dir,
            },
        }
        return app

    def test_read_defaults_when_file_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            app = self._app(tmpdir)
            with app.app_context():
                data, err = enshrouded_config.read_config()
            self.assertIsNone(err)
            self.assertEqual(data["gameSettingsPreset"], "Default")
            self.assertEqual(data["playerHealthFactor"], 1)
            self.assertEqual(data["weatherFrequency"], "Normal")

    def test_write_and_read_gameplay_settings(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            app = self._app(tmpdir)
            with app.app_context():
                ok, err = enshrouded_config.write_config({
                    "name": "Mon Enshrouded",
                    "password": "secret",
                    "slotCount": 10,
                    "gameSettingsPreset": "Custom",
                    "playerHealthFactor": 1.5,
                    "enableStarvingDebuff": True,
                    "shroudTimeFactor": 0.5,
                    "weatherFrequency": "Often",
                    "enemyDamageFactor": 1.75,
                    "pacifyAllEnemies": False,
                })
                self.assertTrue(ok, err)
                data, err = enshrouded_config.read_config()
            self.assertIsNone(err)
            self.assertEqual(data["gameSettingsPreset"], "Custom")
            self.assertEqual(data["playerHealthFactor"], 1.5)
            self.assertTrue(data["enableStarvingDebuff"])
            self.assertEqual(data["shroudTimeFactor"], 0.5)
            self.assertEqual(data["weatherFrequency"], "Often")
            self.assertEqual(data["enemyDamageFactor"], 1.75)

    def test_validation_rejects_invalid_gameplay_value(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            app = self._app(tmpdir)
            with app.app_context():
                ok, err = enshrouded_config.write_config({
                    "gameSettingsPreset": "Custom",
                    "playerHealthFactor": 0.1,
                })
            self.assertFalse(ok)
            self.assertIn("playerHealthFactor", err)


class SoulmaskConfigTests(unittest.TestCase):

    def _app(self, install_dir, data_dir):
        app = Flask(__name__)
        app.config["GAME"] = {
            "id": "soulmask",
            "name": "Soulmask",
            "server": {
                "install_dir": install_dir,
                "data_dir": data_dir,
                "port": 8777,
                "max_players": 50,
            },
        }
        return app

    def test_read_defaults_when_file_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            app = self._app(tmpdir, os.path.join(tmpdir, "saved"))
            with app.app_context():
                data, err = soulmask_config.read_config()
            self.assertIsNone(err)
            self.assertEqual(data["port"], 8777)
            self.assertEqual(data["query_port"], 27015)
            self.assertEqual(data["echo_port"], 18888)

    def test_write_and_read_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            app = self._app(tmpdir, os.path.join(tmpdir, "saved"))
            with app.app_context():
                ok, err = soulmask_config.write_config({
                    "server_name": "tribe-land",
                    "max_players": 24,
                    "password": "secret",
                    "admin_password": "adminsecret",
                    "mode": "pvp",
                    "port": 8778,
                    "query_port": 27016,
                    "echo_port": 18889,
                    "backup_enabled": False,
                    "saving_enabled": True,
                    "backup_interval": 3600,
                })
                self.assertTrue(ok)
                self.assertIsNone(err)
                data, err = soulmask_config.read_config()
            self.assertIsNone(err)
            self.assertEqual(data["server_name"], "tribe-land")
            self.assertEqual(data["mode"], "pvp")
            self.assertEqual(data["echo_port"], 18889)

    def test_validation_rejects_invalid_mode(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            app = self._app(tmpdir, os.path.join(tmpdir, "saved"))
            with app.app_context():
                ok, err = soulmask_config.write_config({
                    "server_name": "tribe-land",
                    "max_players": 24,
                    "mode": "coop",
                    "port": 8778,
                    "query_port": 27016,
                    "echo_port": 18889,
                    "backup_interval": 3600,
                })
            self.assertFalse(ok)
            self.assertIn("mode", err)


class MinecraftPlayersTests(unittest.TestCase):

    def test_tracks_connected_players_from_logs(self):
        original_run = minecraft_players.subprocess.run

        def fake_run(*args, **kwargs):
            return types.SimpleNamespace(stdout="\n".join([
                "[15:13:54] [Server thread/INFO]: xuanphu joined the game",
                "[15:15:00] [Server thread/INFO]: alex joined the game",
                "[15:17:12] [Server thread/INFO]: xuanphu lost connection: Disconnected",
                "[15:17:12] [Server thread/INFO]: xuanphu left the game",
            ]))

        minecraft_players.subprocess.run = fake_run
        try:
            players = minecraft_players.get_players()
        finally:
            minecraft_players.subprocess.run = original_run

        self.assertEqual(players, [{'name': 'alex'}])

    def test_removes_player_on_lost_connection_without_left_line(self):
        original_run = minecraft_players.subprocess.run
        original_since = minecraft_players._current_session_since

        def fake_run(*args, **kwargs):
            return types.SimpleNamespace(stdout="\n".join([
                "[15:13:54] [Server thread/INFO]: xuanphu joined the game",
                "[15:17:12] [Server thread/INFO]: xuanphu lost connection: Timed out",
            ]))

        minecraft_players.subprocess.run = fake_run
        minecraft_players._current_session_since = lambda: None
        try:
            players = minecraft_players.get_players()
        finally:
            minecraft_players.subprocess.run = original_run
            minecraft_players._current_session_since = original_since

        self.assertEqual(players, [])

    def test_uses_current_session_when_available(self):
        original_run = minecraft_players.subprocess.run
        original_since = minecraft_players._current_session_since
        calls = []

        def fake_run(args, **kwargs):
            calls.append(args)
            return types.SimpleNamespace(stdout="")

        minecraft_players.subprocess.run = fake_run
        minecraft_players._current_session_since = lambda: "@123456"
        try:
            minecraft_players.get_players()
        finally:
            minecraft_players.subprocess.run = original_run
            minecraft_players._current_session_since = original_since

        self.assertIn("--since", calls[0])
        self.assertIn("@123456", calls[0])


class MinecraftAdminsTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.app = Flask(__name__)
        self.app.config["GAME"] = {
            "id": "minecraft",
            "server": {
                "install_dir": str(self.root / "server"),
                "data_dir": "",
                "world_name": None,
            }
        }
        server = self.root / "server"
        server.mkdir(parents=True, exist_ok=True)
        (server / "usercache.json").write_text(json.dumps([
            {"name": "Alex", "uuid": "uuid-alex"},
            {"name": "Steve", "uuid": "uuid-steve"},
        ]), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_add_and_remove_admin(self):
        with self.app.app_context():
            data, err = minecraft_admins.add_admin("Alex", 3)
            listed, err2 = minecraft_admins.list_admins()
            removed, err3 = minecraft_admins.remove_admin("Alex")
        self.assertIsNone(err)
        self.assertIsNone(err2)
        self.assertIsNone(err3)
        self.assertFalse(data["already_present"])
        self.assertEqual(listed["entries"][0]["name"], "Alex")
        self.assertEqual(listed["entries"][0]["uuid"], "uuid-alex")
        self.assertEqual(listed["entries"][0]["level"], 3)
        self.assertEqual(removed["name"], "Alex")

    def test_add_admin_updates_level_when_already_present(self):
        with self.app.app_context():
            minecraft_admins.add_admin("Alex", 2)
            data, err = minecraft_admins.add_admin("Alex", 4)
            listed, _ = minecraft_admins.list_admins()
        self.assertIsNone(err)
        self.assertTrue(data["already_present"])
        self.assertEqual(data["level"], 4)
        self.assertEqual(listed["entries"][0]["level"], 4)

    def test_add_whitelist_and_ban(self):
        with self.app.app_context():
            wl_data, wl_err = minecraft_admins.add_whitelist("Steve")
            ban_data, ban_err = minecraft_admins.add_ban("Alex")
            whitelist, _ = minecraft_admins.list_whitelist()
            bans, _ = minecraft_admins.list_bans()
        self.assertIsNone(wl_err)
        self.assertIsNone(ban_err)
        self.assertEqual(wl_data["name"], "Steve")
        self.assertEqual(ban_data["name"], "Alex")
        self.assertEqual(whitelist["entries"][0]["name"], "Steve")
        self.assertEqual(bans["entries"][0]["name"], "Alex")

    def test_add_unknown_player_is_rejected(self):
        with self.app.app_context():
            data, err = minecraft_admins.add_admin("Unknown")
        self.assertIsNone(data)
        self.assertEqual(err, "unknown_player")


class MinecraftConsoleTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.app = Flask(__name__)
        self.app.config["GAME"] = {
            "id": "minecraft",
            "server": {
                "install_dir": str(self.root / "server"),
                "data_dir": "",
                "world_name": None,
            }
        }
        server = self.root / "server"
        server.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_rcon_disabled_returns_explicit_error(self):
        (self.root / "server" / "server.properties").write_text(
            "enable-rcon=false\n",
            encoding="utf-8",
        )
        with self.app.app_context():
            ok, err = minecraft_console.send_console_command("whitelist reload")
        self.assertFalse(ok)
        self.assertEqual(err, "rcon_disabled")

    def test_missing_rcon_password_returns_explicit_error(self):
        (self.root / "server" / "server.properties").write_text(
            "enable-rcon=true\n"
            "rcon.port=25575\n"
            "rcon.password=\n",
            encoding="utf-8",
        )
        with self.app.app_context():
            ok, err = minecraft_console.send_console_command("whitelist reload")
        self.assertFalse(ok)
        self.assertEqual(err, "rcon_password_missing")


class SoulmaskPlayersTests(unittest.TestCase):

    def test_tracks_connected_players_from_logs(self):
        original_run = soulmask_players.subprocess.run
        original_since = soulmask_players._current_session_since

        def fake_run(*args, **kwargs):
            return types.SimpleNamespace(stdout="\n".join([
                "[2026.03.14-13.59.20:000][334]LogOnline: STEAM: AUTH HANDLER: Sending auth result to user 76561197981668140 with flag success? 1",
                "[2026.03.14-13.59.22:480][335]logStoreGamemode: player ready. Addr:203.0.113.10, Netuid:76561197981668140, Name:PlayerSteam",
                "[2026.03.14-14.04.33:060][614]logStoreGamemode: Display: player leave world. 76561197981668140",
            ]))

        soulmask_players.subprocess.run = fake_run
        soulmask_players._current_session_since = lambda: None
        try:
            players = soulmask_players.get_players()
        finally:
            soulmask_players.subprocess.run = original_run
            soulmask_players._current_session_since = original_since

        self.assertEqual(players, [])

    def test_ignores_auth_handler_until_real_name_is_known(self):
        original_run = soulmask_players.subprocess.run
        original_since = soulmask_players._current_session_since

        def fake_run(*args, **kwargs):
            return types.SimpleNamespace(stdout="\n".join([
                "[2026.03.14-22.54.04:332][338]LogOnline: STEAM: AUTH HANDLER: Sending auth result to user 76561197981668140 with flag success? 1",
            ]))

        soulmask_players.subprocess.run = fake_run
        soulmask_players._current_session_since = lambda: None
        try:
            players = soulmask_players.get_players()
        finally:
            soulmask_players.subprocess.run = original_run
            soulmask_players._current_session_since = original_since

        self.assertEqual(players, [])

    def test_tracks_multiple_players_and_precise_disconnect(self):
        original_run = soulmask_players.subprocess.run
        original_since = soulmask_players._current_session_since

        def fake_run(*args, **kwargs):
            return types.SimpleNamespace(stdout="\n".join([
                "[2026.03.14-13.59.22:479][335]logStoreGamemode: FirstLoginGame: Addr:203.0.113.11, Netuid:111, Name:Alice",
                "[2026.03.14-13.59.22:480][335]logStoreGamemode: player ready. Addr:203.0.113.11, Netuid:111, Name:Alice",
                "[2026.03.14-14.00.00:000][399]LogNet: Login request: ?Name=ClientOne?culture=fr-FR",
                "[2026.03.14-14.00.10:100][400]logStoreGamemode: FirstLoginGame: Addr:203.0.113.12, Netuid:222, Name:Bob",
                "[2026.03.14-14.00.10:101][400]logStoreGamemode: player ready. Addr:203.0.113.12, Netuid:222, Name:Bob",
                "[2026.03.14-14.01.00:000][500]logStoreGamemode: Display: player leave world. 111",
            ]))

        soulmask_players.subprocess.run = fake_run
        soulmask_players._current_session_since = lambda: None
        try:
            players = soulmask_players.get_players()
        finally:
            soulmask_players.subprocess.run = original_run
            soulmask_players._current_session_since = original_since

        self.assertEqual(players, [{'name': 'Bob'}])

    def test_uses_current_session_when_available(self):
        original_run = soulmask_players.subprocess.run
        original_since = soulmask_players._current_session_since
        calls = []

        def fake_run(cmd, *args, **kwargs):
            calls.append(cmd)
            return types.SimpleNamespace(stdout="")

        soulmask_players.subprocess.run = fake_run
        soulmask_players._current_session_since = lambda: "@123456"
        try:
            soulmask_players.get_players()
        finally:
            soulmask_players.subprocess.run = original_run
            soulmask_players._current_session_since = original_since


class EnshroudedPlayersTests(unittest.TestCase):

    def test_tracks_connected_players_from_logs(self):
        original_run = enshrouded_players.subprocess.run
        original_since = enshrouded_players._current_session_since

        class Result:
            stdout = (
                "[online] Added peer #1 (steamid:76561198000000001)\n"
                "[online] Added peer #2 (steamid:76561198000000002)\n"
                "[online] Removed peer #1\n"
            )

        def fake_run(*args, **kwargs):
            return Result()

        enshrouded_players.subprocess.run = fake_run
        enshrouded_players._current_session_since = lambda: None
        try:
            players = enshrouded_players.get_players()
        finally:
            enshrouded_players.subprocess.run = original_run
            enshrouded_players._current_session_since = original_since
        self.assertEqual(players, [{'name': '76561198000000002'}])

    def test_uses_current_session_when_available(self):
        original_run = enshrouded_players.subprocess.run
        original_since = enshrouded_players._current_session_since
        captured = {}

        class Result:
            stdout = ""

        def fake_run(cmd, *args, **kwargs):
            captured['cmd'] = cmd
            return Result()

        enshrouded_players.subprocess.run = fake_run
        enshrouded_players._current_session_since = lambda: "@123456"
        try:
            enshrouded_players.get_players()
        finally:
            enshrouded_players.subprocess.run = original_run
            enshrouded_players._current_session_since = original_since

        self.assertIn("--since", captured['cmd'])
        self.assertIn("@123456", captured['cmd'])


class EnshroudedWorldsTests(unittest.TestCase):

    def _app(self, install_dir):
        app = Flask(__name__)
        app.config["GAME"] = {
            "id": "enshrouded",
            "name": "Enshrouded",
            "server": {"install_dir": install_dir},
        }
        return app

    def test_list_worlds_detects_slots_and_ignores_characters(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            savegame = Path(tmpdir) / "savegame"
            savegame.mkdir(parents=True, exist_ok=True)
            for name in (
                "3ad85aea", "3ad85aea-1", "3ad85aea-index",
                "3bd85c7d", "3bd85c7d_info", "3bd85c7d_info-index",
                "characters", "characters-index",
            ):
                (savegame / name).write_text("{}", encoding="utf-8")
            (savegame / "3ad85aea-index").write_text('{"latest": 6, "deleted": false}', encoding="utf-8")
            (savegame / "3bd85c7d-index").write_text('{"latest": 2, "deleted": false}', encoding="utf-8")
            app = self._app(tmpdir)
            with app.app_context():
                data, err = enshrouded_worlds.list_worlds()
            self.assertIsNone(err)
            self.assertEqual([w["id"] for w in data["worlds"]], ["3ad85aea", "3bd85c7d"])
            self.assertEqual(data["worlds"][0]["label"], "World 1 (3ad85aea)")
            self.assertEqual(data["worlds"][1]["label"], "World 2 (3bd85c7d)")
            self.assertFalse(data["worlds"][0]["has_info"])
            self.assertTrue(data["worlds"][1]["has_info"])

        self.assertTrue(any("--since" in call and "@123456" in call for call in calls))


class MinecraftFabricModsTests(unittest.TestCase):

    def _app(self, install_dir):
        app = Flask(__name__)
        app.config["GAME"] = {
            "mods": {
                "loader": "fabric",
                "mods_path": os.path.join(install_dir, "mods"),
                "meta_path": os.path.join(install_dir, ".fabric-meta.json"),
            }
        }
        return app

    def _jar_bytes(self, fabric_mod_json):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("fabric.mod.json", json.dumps(fabric_mod_json))
        return buf.getvalue()

    def test_install_mod_pulls_required_dependency_from_fabric_mod_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, ".fabric-meta.json").write_text(json.dumps({
                "minecraft_version": "1.21.11",
                "loader": "fabric",
            }))

            app = self._app(tmpdir)
            original_get = minecraft_fabric_mods.http.get

            class FakeResp:
                def __init__(self, payload=None, content=b"jar-bytes"):
                    self._payload = payload
                    self._content = content
                def raise_for_status(self):
                    return None
                def json(self):
                    return self._payload
                def iter_content(self, _size):
                    yield self._content
                def __enter__(self):
                    return self
                def __exit__(self, exc_type, exc, tb):
                    return False

            def fake_get(url, params=None, headers=None, timeout=None, stream=False):
                if url.endswith("/version/vanish-ver"):
                    return FakeResp({
                        "id": "vanish-ver",
                        "project_id": "vanish-proj",
                        "dependencies": [],
                        "files": [{"url": "https://cdn.modrinth.com/data/vanish.jar", "filename": "vanish.jar", "primary": True}],
                    })
                if url.endswith("/project/fabric-api-proj/version"):
                    return FakeResp([{"id": "fabric-api-ver", "project_id": "fabric-api-proj"}])
                if url.endswith("/project/fabric-api/version"):
                    return FakeResp([{"id": "fabric-api-ver", "project_id": "fabric-api-proj"}])
                if url.endswith("/version/fabric-api-ver"):
                    return FakeResp({
                        "id": "fabric-api-ver",
                        "project_id": "fabric-api-proj",
                        "dependencies": [],
                        "files": [{"url": "https://cdn.modrinth.com/data/fabric-api.jar", "filename": "fabric-api.jar", "primary": True}],
                    })
                if url == "https://cdn.modrinth.com/data/vanish.jar":
                    return FakeResp(content=self._jar_bytes({
                        "id": "vanish",
                        "version": "1.6.6+1.21.11",
                        "depends": {
                            "fabricloader": ">=0.15.10",
                            "fabric-api": "*",
                            "java": ">=21",
                        },
                    }))
                if url == "https://cdn.modrinth.com/data/fabric-api.jar":
                    return FakeResp(content=self._jar_bytes({
                        "id": "fabric-api",
                        "version": "0.141.3+1.21.11",
                        "depends": {
                            "fabricloader": "*",
                            "minecraft": "1.21.11",
                        },
                    }))
                raise AssertionError(f"URL inattendue: {url}")

            minecraft_fabric_mods.http.get = fake_get
            try:
                with app.app_context():
                    ok, err = minecraft_fabric_mods.install_mod("vanish-proj", "Vanish", "vanish-ver")
                self.assertTrue(ok, err)
                self.assertTrue(Path(tmpdir, "mods", "vanish.jar").is_file())
                self.assertTrue(Path(tmpdir, "mods", "fabric-api.jar").is_file())
            finally:
                minecraft_fabric_mods.http.get = original_get


class ValheimModsTests(unittest.TestCase):

    def _app(self, bepinex_path):
        app = Flask(__name__)
        app.config["GAME"] = {
            "mods": {
                "bepinex_path": bepinex_path,
            }
        }
        return app

    def test_get_installed_mods_includes_plugin_directories_and_dlls(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            plugins = Path(tmpdir, "plugins")
            plugins.mkdir(parents=True)
            Path(plugins, "BetterNetworking").mkdir()
            Path(plugins, "CW_Jesse.BetterNetworking.dll").write_bytes(b"dll")
            Path(plugins, "README.txt").write_text("ignore")

            app = self._app(tmpdir)
            with app.app_context():
                mods = valheim_mods.get_installed_mods()

            self.assertEqual(
                [m["name"] for m in mods],
                ["BetterNetworking", "CW_Jesse.BetterNetworking"],
            )

    def test_get_installed_mods_ignores_display_bepinex_info_dll(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            plugins = Path(tmpdir, "plugins")
            plugins.mkdir(parents=True)
            Path(plugins, "Valheim.DisplayBepInExInfo.dll").write_bytes(b"dll")

            app = self._app(tmpdir)
            with app.app_context():
                mods = valheim_mods.get_installed_mods()

            self.assertEqual(mods, [])

    def test_install_mod_ignores_unrelated_bepinex_plugin_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            app = self._app(tmpdir)
            original_get = valheim_mods.http.get

            class FakeResp:
                def raise_for_status(self):
                    return None
                def iter_content(self, _size):
                    buf = io.BytesIO()
                    with zipfile.ZipFile(buf, "w") as zf:
                        zf.writestr("BepInEx/plugins/CW_Jesse-BetterNetworking_Valheim/CW_Jesse.BetterNetworking.dll", b"bn")
                        zf.writestr("BepInEx/plugins/Valheim.DisplayBepInExInfo.dll", b"bad")
                    yield buf.getvalue()

            valheim_mods.http.get = lambda *args, **kwargs: FakeResp()
            try:
                with app.app_context():
                    ok, msg = valheim_mods.install_mod("CW_Jesse", "BetterNetworking_Valheim", "1.0.0")
                self.assertTrue(ok, msg)
            finally:
                valheim_mods.http.get = original_get

            self.assertTrue(Path(tmpdir, "plugins", "CW_Jesse-BetterNetworking_Valheim", "CW_Jesse.BetterNetworking.dll").is_file())
            self.assertFalse(Path(tmpdir, "plugins", "Valheim.DisplayBepInExInfo.dll").exists())

    def test_install_mod_accepts_direct_plugin_dll_when_slug_is_longer_than_filename(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bepinex = Path(tmpdir, "BepInEx")
            bepinex.mkdir(parents=True)
            app = self._app(str(bepinex))
            original_get = valheim_mods.http.get

            class FakeResp:
                def raise_for_status(self):
                    return None
                def iter_content(self, _size):
                    buf = io.BytesIO()
                    with zipfile.ZipFile(buf, "w") as zf:
                        zf.writestr("BepInEx/plugins/ValheimPlus.dll", b"vp")
                    yield buf.getvalue()

            valheim_mods.http.get = lambda *args, **kwargs: FakeResp()
            try:
                with app.app_context():
                    ok, msg = valheim_mods.install_mod("Grantapher", "ValheimPlus_Grantapher_Temporary", "9.17.1")
                self.assertTrue(ok, msg)
            finally:
                valheim_mods.http.get = original_get

            self.assertTrue(Path(tmpdir, "BepInEx", "plugins", "ValheimPlus.dll").is_file())

    def test_remove_mod_accepts_single_dll_install(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            plugins = Path(tmpdir, "plugins")
            plugins.mkdir(parents=True)
            target = plugins / "Valheim.DisplayBepInExInfo.dll"
            target.write_bytes(b"dll")

            app = self._app(tmpdir)
            with app.app_context():
                ok, msg = valheim_mods.remove_mod("Valheim.DisplayBepInExInfo")

            self.assertTrue(ok, msg)
            self.assertFalse(target.exists())


class ValheimPlusConfigTests(unittest.TestCase):

    def _app(self, bepinex_path):
        app = Flask(__name__)
        app.config["GAME"] = {
            "mods": {
                "bepinex_path": bepinex_path,
            }
        }
        return app

    def test_read_config_finds_valheim_plus_cfg(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            plugins_dir = Path(tmpdir, "plugins")
            plugins_dir.mkdir(parents=True)
            (plugins_dir / "ValheimPlus.dll").write_bytes(b"dll")
            config_dir = Path(tmpdir, "config")
            config_dir.mkdir(parents=True)
            cfg = config_dir / "valheim_plus.cfg"
            cfg.write_text(
                "[Server]\n"
                "enabled = true\n"
                "maxPlayers = 10\n",
                encoding="utf-8",
            )
            app = self._app(tmpdir)
            with app.app_context():
                data, err = valheim_valheimplus.read_config()
            self.assertIsNone(err)
            self.assertEqual(Path(data["path"]).name, "valheim_plus.cfg")
            self.assertEqual(data["sections"][0]["name"], "Server")
            self.assertEqual(data["sections"][0]["fields"][0]["type"], "select")

    def test_read_config_requires_plugin_presence(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir, "config")
            config_dir.mkdir(parents=True)
            (config_dir / "valheim_plus.cfg").write_text("[Server]\nenabled = true\n", encoding="utf-8")
            app = self._app(tmpdir)
            with app.app_context():
                data, err = valheim_valheimplus.read_config()
            self.assertEqual(data, {})
            self.assertEqual(err, "Plugin ValheimPlus introuvable")

    def test_write_config_updates_existing_values(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            plugins_dir = Path(tmpdir, "plugins")
            plugins_dir.mkdir(parents=True)
            (plugins_dir / "ValheimPlus.dll").write_bytes(b"dll")
            config_dir = Path(tmpdir, "config")
            config_dir.mkdir(parents=True)
            cfg = config_dir / "valheim_plus.cfg"
            cfg.write_text(
                "[Server]\n"
                "enabled = true\n"
                "maxPlayers = 10\n",
                encoding="utf-8",
            )
            app = self._app(tmpdir)
            with app.app_context():
                ok, err = valheim_valheimplus.write_config({
                    "Server": {
                        "enabled": "false",
                        "maxPlayers": "20",
                    }
                })
            self.assertTrue(ok, err)
            content = cfg.read_text(encoding="utf-8")
            self.assertIn("enabled = false", content)
            self.assertIn("maxPlayers = 20", content)


# ══════════════════════════════════════════════════════════════════════════════
# Tests manifest nginx_manager
# ══════════════════════════════════════════════════════════════════════════════

class NginxManifestTests(unittest.TestCase):
    """Tests pour les sous-commandes manifest de nginx_manager."""

    NGINX_WITH_SSL = """\
server {
    listen 80;
    server_name gaming.example.com;
    return 301 https://$host$request_uri;
}
server {
    listen 443 ssl;
    server_name gaming.example.com;
    ssl_certificate /etc/ssl/cert.pem;
    ssl_certificate_key /etc/ssl/key.pem;
    location / {
        proxy_pass http://127.0.0.1:8080;
    }
}
"""

    def _make_init_args(self, domain, manifest, loc_file, hub_file, backup_dir):
        return make_args(
            domain=domain, manifest=manifest,
            loc_file=loc_file, hub_file=hub_file, hub_port=5090, backup_dir=backup_dir,
        )

    def _make_manifest_add_args(self, manifest, instance_id, prefix, port, game):
        return make_args(
            manifest=manifest, instance_id=instance_id,
            prefix=prefix, port=port, game=game,
        )

    def _make_manifest_remove_args(self, manifest, instance_id):
        return make_args(manifest=manifest, instance_id=instance_id)

    def _make_manifest_check_args(self, manifest, instance_id):
        return make_args(manifest=manifest, instance_id=instance_id)

    def _make_regenerate_args(self, manifest, out, hub_file):
        return make_args(manifest=manifest, out=out, hub_file=hub_file, hub_port=5090)

    # ── manifest-add / manifest-remove / manifest-check ──────────────────────

    def test_manifest_add_creates_entry(self):
        with tempfile.TemporaryDirectory() as d:
            manifest = os.path.join(d, "manifest.json")
            nginx_manager.save_manifest(manifest, {"vhost": "example.com", "instances": []})
            rc = nginx_manager.cmd_manifest_add(self._make_manifest_add_args(
                manifest, "valheim8", "/valheim8", 5002, "Valheim",
            ))
            self.assertEqual(rc, 0)
            data = nginx_manager.load_manifest(manifest)
            self.assertEqual(len(data["instances"]), 1)
            self.assertEqual(data["instances"][0]["name"], "valheim8")
            self.assertEqual(data["instances"][0]["flask_port"], 5002)

    def test_manifest_add_idempotent(self):
        """Ajouter deux fois la même instance ne crée pas de doublon."""
        with tempfile.TemporaryDirectory() as d:
            manifest = os.path.join(d, "manifest.json")
            nginx_manager.save_manifest(manifest, {"vhost": "x.com", "instances": []})
            for _ in range(2):
                nginx_manager.cmd_manifest_add(self._make_manifest_add_args(
                    manifest, "ens1", "/ens1", 5003, "Enshrouded",
                ))
            data = nginx_manager.load_manifest(manifest)
            self.assertEqual(len(data["instances"]), 1)

    def test_manifest_remove_deletes_entry(self):
        with tempfile.TemporaryDirectory() as d:
            manifest = os.path.join(d, "manifest.json")
            nginx_manager.save_manifest(manifest, {
                "vhost": "x.com",
                "instances": [{"name": "v8", "prefix": "/v8", "flask_port": 5001, "game": "Valheim"}],
            })
            rc = nginx_manager.cmd_manifest_remove(self._make_manifest_remove_args(manifest, "v8"))
            self.assertEqual(rc, 0)
            data = nginx_manager.load_manifest(manifest)
            self.assertEqual(len(data["instances"]), 0)

    def test_manifest_remove_missing_instance_is_noop(self):
        with tempfile.TemporaryDirectory() as d:
            manifest = os.path.join(d, "manifest.json")
            nginx_manager.save_manifest(manifest, {"vhost": "x.com", "instances": []})
            rc = nginx_manager.cmd_manifest_remove(self._make_manifest_remove_args(manifest, "ghost"))
            self.assertEqual(rc, 0)

    def test_manifest_check_present(self):
        with tempfile.TemporaryDirectory() as d:
            manifest = os.path.join(d, "manifest.json")
            nginx_manager.save_manifest(manifest, {
                "vhost": "x.com",
                "instances": [{"name": "v8", "prefix": "/v8", "flask_port": 5001, "game": "V"}],
            })
            rc = nginx_manager.cmd_manifest_check(self._make_manifest_check_args(manifest, "v8"))
            self.assertEqual(rc, 0)

    def test_manifest_check_absent(self):
        with tempfile.TemporaryDirectory() as d:
            manifest = os.path.join(d, "manifest.json")
            nginx_manager.save_manifest(manifest, {"vhost": "x.com", "instances": []})
            rc = nginx_manager.cmd_manifest_check(self._make_manifest_check_args(manifest, "ghost"))
            self.assertEqual(rc, 1)

    def test_manifest_check_no_file_returns_1(self):
        rc = nginx_manager.cmd_manifest_check(
            self._make_manifest_check_args("/tmp/gc_test_no_manifest.json", "x")
        )
        self.assertEqual(rc, 1)

    # ── regenerate ────────────────────────────────────────────────────────────

    def test_regenerate_produces_location_blocks(self):
        with tempfile.TemporaryDirectory() as d:
            manifest = os.path.join(d, "manifest.json")
            loc_file = os.path.join(d, "locations.conf")
            hub_file = os.path.join(d, "hub.html")
            nginx_manager.save_manifest(manifest, {
                "vhost": "gaming.example.com",
                "instances": [
                    {"name": "v8", "prefix": "/valheim8", "flask_port": 5002, "game": "Valheim"},
                    {"name": "e1", "prefix": "/ens1",     "flask_port": 5003, "game": "Enshrouded"},
                ],
            })
            rc = nginx_manager.cmd_regenerate(self._make_regenerate_args(manifest, loc_file, hub_file))
            self.assertEqual(rc, 0)
            content = Path(loc_file).read_text()
            hub = Path(hub_file).read_text()
            self.assertIn("location /commander {", content)
            self.assertIn("proxy_pass         http://127.0.0.1:5090", content)
            self.assertIn("location /valheim8 {", content)
            self.assertIn("location /ens1 {", content)
            self.assertIn("proxy_pass         http://127.0.0.1:5002", content)
            self.assertIn("proxy_pass         http://127.0.0.1:5003", content)
            self.assertIn("served by Flask", hub)

    def test_regenerate_empty_manifest_produces_header_only(self):
        with tempfile.TemporaryDirectory() as d:
            manifest = os.path.join(d, "manifest.json")
            loc_file = os.path.join(d, "locations.conf")
            hub_file = os.path.join(d, "hub.html")
            nginx_manager.save_manifest(manifest, {"vhost": "x.com", "instances": []})
            rc = nginx_manager.cmd_regenerate(self._make_regenerate_args(manifest, loc_file, hub_file))
            self.assertEqual(rc, 0)
            content = Path(loc_file).read_text()
            self.assertIn("NE PAS ÉDITER MANUELLEMENT", content)
            self.assertIn("location /commander {", content)
            self.assertNotIn("location /valheim8 {", content)
            self.assertIn("served by Flask", Path(hub_file).read_text())

    # ── init ─────────────────────────────────────────────────────────────────

    def test_init_creates_manifest_and_loc_file(self):
        with tempfile.TemporaryDirectory() as d:
            manifest = os.path.join(d, "manifest.json")
            loc_file = os.path.join(d, "locations.conf")
            hub_file = os.path.join(d, "hub.html")
            backup_dir = os.path.join(d, "backups")
            # Pas de fichier nginx réel — init doit quand même créer manifest + loc-file
            rc = nginx_manager.cmd_init(self._make_init_args(
                "gaming.example.com", manifest, loc_file, hub_file, backup_dir,
            ))
            self.assertEqual(rc, 0)
            self.assertTrue(Path(manifest).is_file())
            self.assertTrue(Path(loc_file).is_file())
            self.assertTrue(Path(hub_file).is_file())

    def test_init_adds_include_in_ssl_block(self):
        with tempfile.TemporaryDirectory() as d:
            # Créer un faux fichier nginx avec bloc SSL
            conf = os.path.join(d, "gaming.example.com.conf")
            Path(conf).write_text(self.NGINX_WITH_SSL)
            manifest = os.path.join(d, "manifest.json")
            loc_file = os.path.join(d, "locations.conf")
            hub_file = os.path.join(d, "hub.html")
            backup_dir = os.path.join(d, "backups")

            # Patcher find_nginx_conf pour retourner notre faux fichier
            original = nginx_manager.find_nginx_conf
            nginx_manager.find_nginx_conf = lambda domain: conf
            try:
                rc = nginx_manager.cmd_init(self._make_init_args(
                    "gaming.example.com", manifest, loc_file, hub_file, backup_dir,
                ))
            finally:
                nginx_manager.find_nginx_conf = original

            self.assertEqual(rc, 0)
            content = Path(conf).read_text()
            self.assertIn(f"include {loc_file};", content)

    def test_init_idempotent_no_duplicate_include(self):
        """Appeler init deux fois ne doit pas dupliquer l'include."""
        with tempfile.TemporaryDirectory() as d:
            conf = os.path.join(d, "gaming.example.com.conf")
            Path(conf).write_text(self.NGINX_WITH_SSL)
            manifest = os.path.join(d, "manifest.json")
            loc_file = os.path.join(d, "locations.conf")
            hub_file = os.path.join(d, "hub.html")
            backup_dir = os.path.join(d, "backups")

            original = nginx_manager.find_nginx_conf
            nginx_manager.find_nginx_conf = lambda domain: conf
            try:
                nginx_manager.cmd_init(self._make_init_args(
                    "gaming.example.com", manifest, loc_file, hub_file, backup_dir,
                ))
                rc = nginx_manager.cmd_init(self._make_init_args(
                    "gaming.example.com", manifest, loc_file, hub_file, backup_dir,
                ))
            finally:
                nginx_manager.find_nginx_conf = original

            self.assertEqual(rc, 0)
            content = Path(conf).read_text()
            self.assertEqual(content.count(f"include {loc_file};"), 1)

    def test_init_removes_old_inline_gc_blocks(self):
        """cmd_init doit supprimer les anciens blocs Game Commander inline."""
        nginx_with_old_blocks = """\
server {
    listen 443 ssl;
    server_name gaming.example.com;

    # ── Game Commander — Valheim (valheim8) ──────────────────────────────────
    location /valheim8 {
        proxy_pass http://127.0.0.1:5002;
    }
    location /valheim8/static {
        proxy_pass http://127.0.0.1:5002;
    }
    # ─────────────────────────────────────────────────────────────────────────
}
"""
        with tempfile.TemporaryDirectory() as d:
            conf = os.path.join(d, "gaming.example.com.conf")
            Path(conf).write_text(nginx_with_old_blocks)
            manifest = os.path.join(d, "manifest.json")
            loc_file = os.path.join(d, "locations.conf")
            hub_file = os.path.join(d, "hub.html")
            backup_dir = os.path.join(d, "backups")

            original = nginx_manager.find_nginx_conf
            nginx_manager.find_nginx_conf = lambda domain: conf
            try:
                nginx_manager.cmd_init(self._make_init_args(
                    "gaming.example.com", manifest, loc_file, hub_file, backup_dir,
                ))
            finally:
                nginx_manager.find_nginx_conf = original

            content = Path(conf).read_text()
            self.assertNotIn("Game Commander — Valheim", content)
            self.assertNotIn("location /valheim8 {", content)

    # ── Flux complet deploy + uninstall ──────────────────────────────────────

    def test_full_deploy_then_uninstall_flow(self):
        """Simule un deploy (init+add+regenerate) puis un uninstall (remove+regenerate)."""
        with tempfile.TemporaryDirectory() as d:
            conf = os.path.join(d, "gaming.example.com.conf")
            Path(conf).write_text(self.NGINX_WITH_SSL)
            manifest = os.path.join(d, "manifest.json")
            loc_file = os.path.join(d, "locations.conf")
            hub_file = os.path.join(d, "hub.html")
            backup_dir = os.path.join(d, "backups")

            original = nginx_manager.find_nginx_conf
            nginx_manager.find_nginx_conf = lambda domain: conf
            try:
                # Deploy instance 1
                nginx_manager.cmd_init(self._make_init_args(
                    "gaming.example.com", manifest, loc_file, hub_file, backup_dir,
                ))
                nginx_manager.cmd_manifest_add(self._make_manifest_add_args(
                    manifest, "valheim8", "/valheim8", 5002, "Valheim",
                ))
                nginx_manager.cmd_regenerate(self._make_regenerate_args(manifest, loc_file, hub_file))

                # Deploy instance 2
                nginx_manager.cmd_manifest_add(self._make_manifest_add_args(
                    manifest, "ens1", "/ens1", 5003, "Enshrouded",
                ))
                nginx_manager.cmd_regenerate(self._make_regenerate_args(manifest, loc_file, hub_file))

                loc_content = Path(loc_file).read_text()
                self.assertIn("location /valheim8 {", loc_content)
                self.assertIn("location /ens1 {", loc_content)

                # Uninstall instance 1
                nginx_manager.cmd_manifest_remove(self._make_manifest_remove_args(manifest, "valheim8"))
                nginx_manager.cmd_regenerate(self._make_regenerate_args(manifest, loc_file, hub_file))

                loc_content = Path(loc_file).read_text()
                self.assertNotIn("location /valheim8 {", loc_content)
                self.assertIn("location /ens1 {", loc_content)

                # Uninstall instance 2
                nginx_manager.cmd_manifest_remove(self._make_manifest_remove_args(manifest, "ens1"))
                nginx_manager.cmd_regenerate(self._make_regenerate_args(manifest, loc_file, hub_file))

                loc_content = Path(loc_file).read_text()
                self.assertNotIn("location /ens1 {", loc_content)
                data = nginx_manager.load_manifest(manifest)
                self.assertEqual(data["instances"], [])

                # L'include doit toujours être présent dans le conf nginx
                conf_content = Path(conf).read_text()
                self.assertIn(f"include {loc_file};", conf_content)
            finally:
                nginx_manager.find_nginx_conf = original


# ══════════════════════════════════════════════════════════════════════════════
# Runner
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # Couleurs
    GREEN = "\033[32m"
    RED   = "\033[31m"
    BOLD  = "\033[1m"
    RESET = "\033[0m"

    loader = unittest.TestLoader()
    suite  = unittest.TestSuite()

    # Charger uniquement les classes demandées en argument (ou toutes)
    test_classes = [
        NginxInjectTests,
        NginxRemoveTests,
        NginxFindConfTests,
        NginxManifestTests,
        ConfigGenGameJsonTests,
        ConfigGenUsersJsonTests,
        ConfigGenEnshroudedCfgTests,
        ConfigGenPatchBepinexTests,
        ConfigGenMinecraftPropsTests,
        MinecraftConfigTests,
        TerrariaConfigTests,
        MinecraftPlayersTests,
        MinecraftAdminsTests,
        MinecraftConsoleTests,
        MinecraftFabricModsTests,
        SaveManagerTests,
        DiscordNotifyTests,
        HostCliTests,
        BootstrapHubTests,
    ]
    if len(sys.argv) > 1:
        names = sys.argv[1:]
        test_classes = [c for c in test_classes if c.__name__ in names]
        if not test_classes:
            print(f"Classes disponibles : {[c.__name__ for c in [NginxInjectTests, NginxRemoveTests, NginxFindConfTests, NginxManifestTests, ConfigGenGameJsonTests, ConfigGenUsersJsonTests, ConfigGenEnshroudedCfgTests, ConfigGenPatchBepinexTests, ConfigGenMinecraftPropsTests, MinecraftConfigTests, TerrariaConfigTests, MinecraftPlayersTests, MinecraftAdminsTests, MinecraftConsoleTests, MinecraftFabricModsTests, SaveManagerTests, DiscordNotifyTests, HostCliTests, BootstrapHubTests]]}")
            sys.exit(1)

    for cls in test_classes:
        suite.addTests(loader.loadTestsFromTestCase(cls))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print()
    total  = result.testsRun
    failed = len(result.failures) + len(result.errors)
    passed = total - failed

    if failed == 0:
        print(f"{BOLD}{GREEN}✓ {passed}/{total} tests passés{RESET}")
    else:
        print(f"{BOLD}{RED}✗ {failed}/{total} tests échoués{RESET}")

    sys.exit(0 if failed == 0 else 1)
