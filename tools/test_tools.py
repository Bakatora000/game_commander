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
import sys
import tempfile
import types
import unittest
import zipfile
from pathlib import Path
from flask import Flask

# Ajouter le répertoire tools/ au path pour importer les modules
TOOLS_DIR = Path(__file__).parent
ROOT_DIR = TOOLS_DIR.parent
sys.path.insert(0, str(TOOLS_DIR))
sys.path.insert(0, str(ROOT_DIR))

import nginx_manager
import config_gen
from runtime.games.minecraft import config as minecraft_config
from runtime.games.minecraft import players as minecraft_players
from runtime.games.minecraft_fabric import mods as minecraft_fabric_mods


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
            self.assertIn("location /valheim8/static {", content)
            # Doit être dans le bloc SSL, pas dans le bloc HTTP redirect
            ssl_block_end = content.index("return 404")
            inject_pos = content.index("location /valheim8")
            self.assertLess(inject_pos, ssl_block_end,
                            "Le bloc doit être injecté dans le serveur SSL, pas après")
        finally:
            os.unlink(conf)

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
            for b in Path(conf).parent.glob(Path(conf).name + ".bak.*"):
                b.unlink(missing_ok=True)

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

    def test_valheim_bepinex_section(self):
        data = self._gen_valheim()
        self.assertIn("mods", data)
        self.assertEqual(data["mods"]["platform"], "thunderstore")
        self.assertTrue(data["features"]["mods"])

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
            data_dir="", world_name="", max_players=16, port=15639,
            url_prefix="/enshrouded2", flask_port=5004, admin_user="admin",
            bepinex_path="", steam_appid="2278520", steamcmd_path="",
        ))
        self.assertEqual(rc, 0)
        data = json.loads(Path(out).read_text())
        self.assertIsNone(data["server"]["world_name"])
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

    def test_steamcmd_section(self):
        data = self._gen_valheim()
        self.assertIn("steamcmd", data)
        self.assertEqual(data["steamcmd"]["app_id"], "896660")

    def test_no_steamcmd_when_empty(self):
        data = self._gen_valheim(steam_appid="")
        self.assertNotIn("steamcmd", data)


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
        self.assertEqual(data["admin"]["password_hash"], "$2b$fakehash")

    def test_enshrouded_permissions(self):
        out = tmp_path(".json")
        config_gen.cmd_users_json(make_args(
            out=out, admin="admin", hash="$2b$fakehash", game_id="enshrouded",
        ))
        data = json.loads(Path(out).read_text())
        self.assertNotIn("install_mod", data["admin"]["permissions"])
        self.assertIn("manage_config", data["admin"]["permissions"])


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

    def _make_init_args(self, domain, manifest, loc_file, backup_dir):
        return make_args(
            domain=domain, manifest=manifest,
            loc_file=loc_file, backup_dir=backup_dir,
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

    def _make_regenerate_args(self, manifest, out):
        return make_args(manifest=manifest, out=out)

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
            nginx_manager.save_manifest(manifest, {
                "vhost": "gaming.example.com",
                "instances": [
                    {"name": "v8", "prefix": "/valheim8", "flask_port": 5002, "game": "Valheim"},
                    {"name": "e1", "prefix": "/ens1",     "flask_port": 5003, "game": "Enshrouded"},
                ],
            })
            rc = nginx_manager.cmd_regenerate(self._make_regenerate_args(manifest, loc_file))
            self.assertEqual(rc, 0)
            content = Path(loc_file).read_text()
            self.assertIn("location /valheim8 {", content)
            self.assertIn("location /ens1 {", content)
            self.assertIn("proxy_pass         http://127.0.0.1:5002", content)
            self.assertIn("proxy_pass         http://127.0.0.1:5003", content)

    def test_regenerate_empty_manifest_produces_header_only(self):
        with tempfile.TemporaryDirectory() as d:
            manifest = os.path.join(d, "manifest.json")
            loc_file = os.path.join(d, "locations.conf")
            nginx_manager.save_manifest(manifest, {"vhost": "x.com", "instances": []})
            rc = nginx_manager.cmd_regenerate(self._make_regenerate_args(manifest, loc_file))
            self.assertEqual(rc, 0)
            content = Path(loc_file).read_text()
            self.assertIn("NE PAS ÉDITER MANUELLEMENT", content)
            self.assertNotIn("location /", content)

    # ── init ─────────────────────────────────────────────────────────────────

    def test_init_creates_manifest_and_loc_file(self):
        with tempfile.TemporaryDirectory() as d:
            manifest = os.path.join(d, "manifest.json")
            loc_file = os.path.join(d, "locations.conf")
            backup_dir = os.path.join(d, "backups")
            # Pas de fichier nginx réel — init doit quand même créer manifest + loc-file
            rc = nginx_manager.cmd_init(self._make_init_args(
                "gaming.example.com", manifest, loc_file, backup_dir,
            ))
            self.assertEqual(rc, 0)
            self.assertTrue(Path(manifest).is_file())
            self.assertTrue(Path(loc_file).is_file())

    def test_init_adds_include_in_ssl_block(self):
        with tempfile.TemporaryDirectory() as d:
            # Créer un faux fichier nginx avec bloc SSL
            conf = os.path.join(d, "gaming.example.com.conf")
            Path(conf).write_text(self.NGINX_WITH_SSL)
            manifest = os.path.join(d, "manifest.json")
            loc_file = os.path.join(d, "locations.conf")
            backup_dir = os.path.join(d, "backups")

            # Patcher find_nginx_conf pour retourner notre faux fichier
            original = nginx_manager.find_nginx_conf
            nginx_manager.find_nginx_conf = lambda domain: conf
            try:
                rc = nginx_manager.cmd_init(self._make_init_args(
                    "gaming.example.com", manifest, loc_file, backup_dir,
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
            backup_dir = os.path.join(d, "backups")

            original = nginx_manager.find_nginx_conf
            nginx_manager.find_nginx_conf = lambda domain: conf
            try:
                nginx_manager.cmd_init(self._make_init_args(
                    "gaming.example.com", manifest, loc_file, backup_dir,
                ))
                rc = nginx_manager.cmd_init(self._make_init_args(
                    "gaming.example.com", manifest, loc_file, backup_dir,
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
            backup_dir = os.path.join(d, "backups")

            original = nginx_manager.find_nginx_conf
            nginx_manager.find_nginx_conf = lambda domain: conf
            try:
                nginx_manager.cmd_init(self._make_init_args(
                    "gaming.example.com", manifest, loc_file, backup_dir,
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
            backup_dir = os.path.join(d, "backups")

            original = nginx_manager.find_nginx_conf
            nginx_manager.find_nginx_conf = lambda domain: conf
            try:
                # Deploy instance 1
                nginx_manager.cmd_init(self._make_init_args(
                    "gaming.example.com", manifest, loc_file, backup_dir,
                ))
                nginx_manager.cmd_manifest_add(self._make_manifest_add_args(
                    manifest, "valheim8", "/valheim8", 5002, "Valheim",
                ))
                nginx_manager.cmd_regenerate(self._make_regenerate_args(manifest, loc_file))

                # Deploy instance 2
                nginx_manager.cmd_manifest_add(self._make_manifest_add_args(
                    manifest, "ens1", "/ens1", 5003, "Enshrouded",
                ))
                nginx_manager.cmd_regenerate(self._make_regenerate_args(manifest, loc_file))

                loc_content = Path(loc_file).read_text()
                self.assertIn("location /valheim8 {", loc_content)
                self.assertIn("location /ens1 {", loc_content)

                # Uninstall instance 1
                nginx_manager.cmd_manifest_remove(self._make_manifest_remove_args(manifest, "valheim8"))
                nginx_manager.cmd_regenerate(self._make_regenerate_args(manifest, loc_file))

                loc_content = Path(loc_file).read_text()
                self.assertNotIn("location /valheim8 {", loc_content)
                self.assertIn("location /ens1 {", loc_content)

                # Uninstall instance 2
                nginx_manager.cmd_manifest_remove(self._make_manifest_remove_args(manifest, "ens1"))
                nginx_manager.cmd_regenerate(self._make_regenerate_args(manifest, loc_file))

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
        MinecraftPlayersTests,
        MinecraftFabricModsTests,
    ]
    if len(sys.argv) > 1:
        names = sys.argv[1:]
        test_classes = [c for c in test_classes if c.__name__ in names]
        if not test_classes:
            print(f"Classes disponibles : {[c.__name__ for c in test_classes]}")
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
