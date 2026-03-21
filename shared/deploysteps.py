"""Deploy steps 3-12 — replaces lib/deploy_steps.sh."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path

_here = Path(__file__).resolve().parent.parent
import sys
if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))

from shared import (
    appfiles, appservice, console, cpuplan,
    deploybackups, deploynginx, deploypost, deployssl, deploysudo,
    discordnotify, gameinstall, gameservice, hubsync, startscripts,
)
from shared.deployconfig import DeployConfig


# ── Step 3: Dependencies ──────────────────────────────────────────────────────

def deploy_step_dependencies(cfg: DeployConfig, script_dir: Path) -> None:
    console.hdr("ÉTAPE 3 : Dépendances")

    from shared import deploydeps  # avoid circular at module load

    deps = deploydeps.inspect_dependencies(
        deploy_mode=cfg.deploy_mode,
        steam_appid=cfg.steam_appid,
        ssl_mode=cfg.ssl_mode,
        game_id=cfg.game_id,
        home_dir=cfg.home_dir,
    )

    apt_updated = False

    def apt_once() -> None:
        nonlocal apt_updated
        if not apt_updated:
            console.info("apt update...")
            subprocess.run(["apt-get", "update", "-qq"], check=True)
            apt_updated = True

    def install_pkg(pkg: str) -> None:
        r = subprocess.run(
            ["dpkg", "-l", pkg], capture_output=True, text=True, check=False
        )
        if r.returncode == 0 and "ii" in r.stdout:
            console.ok(f"{pkg} OK")
            return
        console.warn(f"{pkg} manquant")
        do_it = cfg.auto_install_deps or console.confirm(f"Installer {pkg} ?")
        if do_it:
            apt_once()
            subprocess.run(["apt-get", "install", "-y", "-qq", pkg], check=True)
            console.ok(f"{pkg} installé")
        else:
            console.warn(f"{pkg} ignoré")

    # Base apt packages
    for pkg in deps.get("apt_missing", []):
        install_pkg(pkg)

    # i386 architecture
    if deps.get("need_i386") and not deps.get("i386_enabled"):
        console.info("Activation i386...")
        subprocess.run(["dpkg", "--add-architecture", "i386"], check=True)
        apt_once()

    # Extra apt packages (steam, certbot)
    for pkg in deps.get("extra_apt_missing", []):
        install_pkg(pkg)

    # Python apt packages
    for pkg in deps.get("python_apt_missing", []):
        console.warn(f"Python: {pkg.replace('python3-', '')} manquant")
        do_it = cfg.auto_install_deps or console.confirm(f"Installer {pkg} (apt) ?")
        if do_it:
            apt_once()
            subprocess.run(["apt-get", "install", "-y", "-qq", pkg], check=True)
            console.ok(f"Python: {pkg.replace('python3-', '')} installé (apt)")

    # Python pip packages
    for pkg in deps.get("python_pip_missing", []):
        console.warn(f"Python: {pkg} manquant")
        do_it = cfg.auto_install_deps or console.confirm(f"pip install {pkg} ?")
        if do_it:
            subprocess.run(
                ["pip3", "install", pkg, "--break-system-packages", "-q"], check=True
            )
            console.ok(f"Python: {pkg} installé")

    # Enshrouded: Wine + Xvfb
    ens = deps.get("enshrouded", {})
    if ens.get("required"):
        console.info("Enshrouded requiert Wine (binaire Windows) + Xvfb...")
        if not ens.get("wine64_installed"):
            console.warn("wine64 absent — installation depuis les dépôts système...")
            apt_once()
            subprocess.run(["apt-get", "install", "-y", "-qq", "wine64", "xvfb"], check=True)
            console.ok("Wine64 + Xvfb installés")
        else:
            console.ok("Wine64 déjà présent")

        # Ensure wine64 is in PATH
        r = subprocess.run(["command", "-v", "wine64"], shell=True, capture_output=True)
        if r.returncode != 0:
            if ens.get("wine_in_path"):
                wine_bin = subprocess.run(
                    ["command", "-v", "wine"], shell=True, capture_output=True, text=True
                ).stdout.strip()
                Path("/usr/local/bin/wine64").symlink_to(wine_bin)
                console.ok("Symlink wine64 → wine créé dans /usr/local/bin")
            elif Path("/usr/lib/wine/wine64").exists():
                try:
                    Path("/usr/local/bin/wine64").symlink_to("/usr/lib/wine/wine64")
                    console.ok("Symlink wine64 → /usr/lib/wine/wine64 créé")
                except FileExistsError:
                    pass
            else:
                console.die("wine64 introuvable dans le PATH après installation — vérifiez le paquet wine")

        if not ens.get("xvfb_run_in_path"):
            apt_once()
            subprocess.run(["apt-get", "install", "-y", "-qq", "xvfb"], check=True)
            console.ok("Xvfb installé")
        else:
            console.ok("Xvfb déjà présent")

        if not ens.get("wine_prefix_exists") and cfg.home_dir:
            console.info(f"Initialisation du prefix Wine pour {cfg.sys_user}...")
            r = subprocess.run(
                ["sudo", "-u", cfg.sys_user, "bash", "-c", "WINEDEBUG=-all wineboot --init"],
                capture_output=True, check=False,
            )
            if r.returncode == 0:
                console.ok("Prefix Wine initialisé")
            else:
                console.warn("wineboot : vérifiez manuellement")

    # SteamCMD
    if deps.get("need_i386"):
        steamcmd = deps.get("steamcmd_path", "")
        if steamcmd:
            cfg.steamcmd_path = steamcmd
            console.ok(f"SteamCMD : {steamcmd}")
        else:
            console.warn("SteamCMD introuvable")
            do_steam = cfg.auto_install_steamcmd or console.confirm("Installer SteamCMD ?")
            if do_steam:
                steamcmd_dir = Path(cfg.home_dir) / "steamcmd"
                steamcmd_dir.mkdir(parents=True, exist_ok=True)
                subprocess.run(
                    ["bash", "-c",
                     f'curl -sqL "https://steamcdn-a.akamaihd.net/client/installer/steamcmd_linux.tar.gz" '
                     f'| tar -xzC "{steamcmd_dir}"'],
                    check=True,
                )
                subprocess.run(
                    ["chown", "-R", f"{cfg.sys_user}:{cfg.sys_user}", str(steamcmd_dir)],
                    check=False,
                )
                cfg.steamcmd_path = deps.get("steamcmd_home", "")
                console.ok(f"SteamCMD installé : {cfg.steamcmd_path}")
            else:
                console.die("SteamCMD requis.")


# ── Step 4: Game install ──────────────────────────────────────────────────────

def deploy_step_game_install(cfg: DeployConfig, script_dir: Path) -> None:
    if cfg.deploy_mode == "attach":
        console.hdr(f"ÉTAPE 4 : Installation {cfg.game_label}")
        console.info("Mode attach — installation/mise à jour du serveur ignorée")
        return

    # ── Soulmask ──────────────────────────────────────────────────────────────
    if cfg.game_id == "soulmask":
        console.hdr("ÉTAPE 4 : Installation Soulmask")
        Path(cfg.server_dir).mkdir(parents=True, exist_ok=True)
        Path(cfg.data_dir).mkdir(parents=True, exist_ok=True)
        subprocess.run(["chown", "-R", f"{cfg.sys_user}:{cfg.sys_user}", cfg.server_dir, cfg.data_dir], check=False)

        do_install = True
        game_bin = Path(cfg.server_dir) / cfg.game_binary
        if game_bin.is_file():
            console.ok(f"{cfg.game_label} déjà installé")
            if cfg.auto_update_server:
                print(f"  \033[2m  (config) Mise à jour → oui\033[0m")
            else:
                do_install = console.confirm("Mettre à jour depuis Steam ?", "n")

        if do_install:
            console.info(f"Téléchargement {cfg.game_label} via SteamCMD (AppID {cfg.steam_appid})...")
            console.info("Cela peut prendre plusieurs minutes...")
            try:
                msgs = gameinstall.install_soulmask(
                    server_dir=cfg.server_dir, data_dir=cfg.data_dir,
                    sys_user=cfg.sys_user, steamcmd_path=cfg.steamcmd_path,
                    steam_appid=cfg.steam_appid,
                )
                for m in msgs:
                    console.ok(m)
            except Exception as exc:
                console.die(f"Échec installation serveur Soulmask : {exc}")

        if not game_bin.is_file():
            console.die(f"Binaire {cfg.game_binary} introuvable dans {cfg.server_dir}")
        game_bin.chmod(game_bin.stat().st_mode | 0o111)
        subprocess.run(["chown", "-R", f"{cfg.sys_user}:{cfg.sys_user}", cfg.server_dir], check=False)
        console.ok(f"Binaire {cfg.game_binary} vérifié")
        return

    # ── Terraria ─────────────────────────────────────────────────────────────
    if cfg.game_id == "terraria":
        console.hdr("ÉTAPE 4 : Installation Terraria")
        Path(cfg.server_dir).mkdir(parents=True, exist_ok=True)
        Path(cfg.data_dir).mkdir(parents=True, exist_ok=True)
        subprocess.run(["chown", "-R", f"{cfg.sys_user}:{cfg.sys_user}", cfg.server_dir, cfg.data_dir], check=False)
        try:
            msgs = gameinstall.install_terraria(
                script_dir=str(script_dir), server_dir=cfg.server_dir, data_dir=cfg.data_dir,
                sys_user=cfg.sys_user, server_name=cfg.server_name, server_port=cfg.server_port,
                max_players=cfg.max_players, server_password=cfg.server_password,
                instance_id=cfg.instance_id,
            )
            for m in msgs:
                console.ok(m)
        except Exception as exc:
            console.die(f"Échec installation serveur Terraria : {exc}")
        return

    # ── Minecraft Fabric ──────────────────────────────────────────────────────
    if cfg.game_id == "minecraft-fabric":
        console.hdr("ÉTAPE 4 : Installation Minecraft Fabric")
        _install_pkg_apt("default-jre-headless", cfg)
        try:
            msgs = gameinstall.install_minecraft_fabric(
                script_dir=str(script_dir), server_dir=cfg.server_dir,
                sys_user=cfg.sys_user, server_name=cfg.server_name,
                server_port=cfg.server_port, max_players=cfg.max_players,
            )
            for m in msgs:
                console.ok(m)
        except Exception as exc:
            console.die(f"Échec installation serveur Minecraft Fabric : {exc}")
        return

    # ── Minecraft Java ────────────────────────────────────────────────────────
    if cfg.game_id == "minecraft":
        console.hdr("ÉTAPE 4 : Installation Minecraft Java")
        _install_pkg_apt("default-jre-headless", cfg)
        try:
            msgs = gameinstall.install_minecraft_java(
                script_dir=str(script_dir), server_dir=cfg.server_dir,
                sys_user=cfg.sys_user, server_name=cfg.server_name,
                server_port=cfg.server_port, max_players=cfg.max_players,
            )
            for m in msgs:
                console.ok(m)
        except Exception as exc:
            console.die(f"Échec installation serveur Minecraft Java : {exc}")
        return

    # ── Satisfactory ─────────────────────────────────────────────────────────
    if cfg.game_id == "satisfactory":
        console.hdr("ÉTAPE 4 : Installation Satisfactory")
        Path(cfg.server_dir).mkdir(parents=True, exist_ok=True)
        Path(cfg.data_dir).mkdir(parents=True, exist_ok=True)
        subprocess.run(["chown", "-R", f"{cfg.sys_user}:{cfg.sys_user}", cfg.server_dir, cfg.data_dir], check=False)

        do_install = True
        game_bin = Path(cfg.server_dir) / cfg.game_binary
        if game_bin.is_file():
            console.ok(f"{cfg.game_label} déjà installé")
            if cfg.auto_update_server:
                print(f"  \033[2m  (config) Mise à jour → oui\033[0m")
            else:
                do_install = console.confirm("Mettre à jour depuis Steam ?", "n")

        if do_install:
            console.info(f"Téléchargement {cfg.game_label} via SteamCMD (AppID {cfg.steam_appid})...")
            console.info("Cela peut prendre plusieurs minutes...")
            try:
                msgs = gameinstall.install_satisfactory(
                    server_dir=cfg.server_dir, data_dir=cfg.data_dir,
                    sys_user=cfg.sys_user, steamcmd_path=cfg.steamcmd_path,
                    steam_appid=cfg.steam_appid,
                )
                for m in msgs:
                    console.ok(m)
            except Exception as exc:
                console.die(f"Échec installation serveur Satisfactory : {exc}")
        else:
            if not game_bin.is_file():
                console.die(f"Binaire {cfg.game_binary} introuvable dans {cfg.server_dir}")
            console.ok(f"Binaire {cfg.game_binary} vérifié")
        return

    # ── Valheim ───────────────────────────────────────────────────────────────
    if cfg.game_id == "valheim":
        console.hdr("ÉTAPE 4 : Installation Valheim")
        Path(cfg.server_dir).mkdir(parents=True, exist_ok=True)
        Path(cfg.data_dir).mkdir(parents=True, exist_ok=True)
        subprocess.run(["chown", "-R", f"{cfg.sys_user}:{cfg.sys_user}", cfg.server_dir, cfg.data_dir], check=False)

        do_install = True
        game_bin = Path(cfg.server_dir) / cfg.game_binary
        if game_bin.is_file():
            console.ok(f"{cfg.game_label} déjà installé")
            if cfg.auto_update_server:
                print(f"  \033[2m  (config) Mise à jour → oui\033[0m")
            else:
                do_install = console.confirm("Mettre à jour depuis Steam ?", "n")

        install_bep = False
        if cfg.bepinex:
            if (Path(cfg.server_dir) / "BepInEx").is_dir():
                install_bep = True
            else:
                install_bep = cfg.auto_install_bepinex or console.confirm("Installer BepInEx ?")

        if do_install or install_bep:
            if do_install:
                console.info(f"Téléchargement {cfg.game_label} via SteamCMD (AppID {cfg.steam_appid})...")
                console.info("Cela peut prendre plusieurs minutes...")
            try:
                msgs = gameinstall.install_valheim(
                    server_dir=cfg.server_dir, data_dir=cfg.data_dir,
                    sys_user=cfg.sys_user, steamcmd_path=cfg.steamcmd_path,
                    steam_appid=cfg.steam_appid,
                    install_server=do_install, install_bepinex=install_bep,
                )
                for m in msgs:
                    console.ok(m)
            except Exception as exc:
                console.die(f"Échec installation serveur Valheim : {exc}")
        else:
            if not game_bin.is_file():
                console.die(f"Binaire {cfg.game_binary} introuvable dans {cfg.server_dir}")
            game_bin.chmod(game_bin.stat().st_mode | 0o111)
            subprocess.run(["chown", "-R", f"{cfg.sys_user}:{cfg.sys_user}", cfg.server_dir], check=False)
            console.ok(f"Binaire {cfg.game_binary} vérifié")
        return

    # ── Enshrouded ────────────────────────────────────────────────────────────
    if cfg.game_id == "enshrouded":
        console.hdr("ÉTAPE 4 : Installation Enshrouded")
        Path(cfg.server_dir).mkdir(parents=True, exist_ok=True)
        Path(cfg.data_dir).mkdir(parents=True, exist_ok=True)
        subprocess.run(["chown", "-R", f"{cfg.sys_user}:{cfg.sys_user}", cfg.server_dir, cfg.data_dir], check=False)

        do_install = True
        game_bin = Path(cfg.server_dir) / cfg.game_binary
        if game_bin.is_file():
            console.ok(f"{cfg.game_label} déjà installé")
            if cfg.auto_update_server:
                print(f"  \033[2m  (config) Mise à jour → oui\033[0m")
            else:
                do_install = console.confirm("Mettre à jour depuis Steam ?", "n")

        if do_install:
            console.info(f"Téléchargement {cfg.game_label} via SteamCMD (AppID {cfg.steam_appid})...")
            console.info("Cela peut prendre plusieurs minutes...")
            try:
                msgs = gameinstall.install_enshrouded(
                    server_dir=cfg.server_dir, data_dir=cfg.data_dir,
                    sys_user=cfg.sys_user, steamcmd_path=cfg.steamcmd_path,
                    steam_appid=cfg.steam_appid,
                )
                for m in msgs:
                    console.ok(m)
            except Exception as exc:
                console.die(f"Échec installation serveur Enshrouded : {exc}")
        else:
            if not game_bin.is_file():
                console.die(f"Binaire {cfg.game_binary} introuvable dans {cfg.server_dir}")
            subprocess.run(["chown", "-R", f"{cfg.sys_user}:{cfg.sys_user}", cfg.server_dir], check=False)
            console.ok(f"Binaire {cfg.game_binary} vérifié")
        return

    # ── Generic fallback ──────────────────────────────────────────────────────
    console.hdr(f"ÉTAPE 4 : Installation {cfg.game_label}")
    console.warn(f"Jeu '{cfg.game_id}' non reconnu pour l'installation automatique")


def _install_pkg_apt(pkg: str, cfg: DeployConfig) -> None:
    r = subprocess.run(
        ["dpkg", "-l", pkg], capture_output=True, text=True, check=False
    )
    if r.returncode == 0 and "ii" in r.stdout:
        console.ok(f"{pkg} OK")
        return
    console.warn(f"{pkg} manquant")
    do_it = cfg.auto_install_deps or console.confirm(f"Installer {pkg} ?")
    if do_it:
        subprocess.run(["apt-get", "install", "-y", "-qq", pkg], check=True)
        console.ok(f"{pkg} installé")
    else:
        console.warn(f"{pkg} ignoré")


# ── Step 5: Game service ──────────────────────────────────────────────────────

def deploy_step_game_service(cfg: DeployConfig, script_dir: Path) -> None:
    console.hdr(f"ÉTAPE 5 : Service {cfg.game_label}")

    if cfg.deploy_mode == "attach":
        console.info(f"Mode attach — service de jeu existant conservé : {cfg.game_service}")
        return

    cpu_affinity_line = cpuplan.affinity_line_for_instance(
        cfg.instance_id, cfg.game_id, cfg.game_service
    )
    cpu_weight = cpuplan.cpu_weight_for_game(cfg.game_id)
    cpu_weight_line = f"CPUWeight={cpu_weight}"
    if cpu_affinity_line:
        console.info(f"Affinité CPU prévue : {cpu_affinity_line.replace('CPUAffinity=', '')}")

    # Install crash-notify systemd template (idempotent, global)
    try:
        gameservice.install_crash_notify_template(str(script_dir))
    except Exception as exc:
        console.warn(f"crash-notify template non installé : {exc}")

    on_failure_notify = f"game-commander-crash-notify@{cfg.instance_id}.service"

    def install_service(exec_start: str) -> None:
        ok, msg = gameservice.install_game_service(
            game_label=cfg.game_label,
            service_name=cfg.game_service,
            sys_user=cfg.sys_user,
            server_dir=cfg.server_dir,
            exec_start=exec_start,
            cpu_affinity_line=cpu_affinity_line,
            cpu_weight_line=cpu_weight_line,
            on_failure_notify=on_failure_notify,
        )
        (console.ok if ok else console.warn)(msg)

    # ── Minecraft ─────────────────────────────────────────────────────────────
    if cfg.game_id in ("minecraft", "minecraft-fabric"):
        start_script = str(Path(cfg.server_dir) / "start_server.sh")
        # Find the jar name that gameinstall wrote
        jar_name = "server.jar"
        for p in Path(cfg.server_dir).glob("*.jar"):
            jar_name = p.name
            break
        content = startscripts.render_minecraft_start_script(
            server_dir=cfg.server_dir, jar_name=jar_name
        )
        startscripts.write_start_script(out_path=start_script, content=content, sys_user=cfg.sys_user)
        console.ok(f"Script de démarrage : {start_script}")
        install_service(start_script)
        return

    # ── Terraria ─────────────────────────────────────────────────────────────
    if cfg.game_id == "terraria":
        start_script   = str(Path(cfg.server_dir) / "start_server.sh")
        wrapper_script = str(Path(cfg.server_dir) / "start_server_service.sh")
        Path(cfg.server_dir, "logs").mkdir(parents=True, exist_ok=True)
        content = startscripts.render_terraria_start_script(server_dir=cfg.server_dir)
        startscripts.write_start_script(out_path=start_script, content=content, sys_user=cfg.sys_user)
        from shared.startscripts import render_terraria_wrapper_script
        wrapper_content = render_terraria_wrapper_script(start_script=start_script)
        startscripts.write_start_script(out_path=wrapper_script, content=wrapper_content, sys_user=cfg.sys_user)
        console.ok(f"Script de démarrage : {start_script}")
        console.ok(f"Wrapper service : {wrapper_script}")
        install_service(wrapper_script)
        return

    # ── Satisfactory ─────────────────────────────────────────────────────────
    if cfg.game_id == "satisfactory":
        start_script = str(Path(cfg.server_dir) / "start_server.sh")
        content = startscripts.render_satisfactory_start_script(
            server_dir=cfg.server_dir, data_dir=cfg.data_dir,
            server_port=cfg.server_port, reliable_port=cfg.query_port,
        )
        startscripts.write_start_script(out_path=start_script, content=content, sys_user=cfg.sys_user)
        console.ok(f"Script de démarrage : {start_script}")
        install_service(start_script)
        return

    # ── Soulmask ─────────────────────────────────────────────────────────────
    if cfg.game_id == "soulmask":
        start_script  = str(Path(cfg.server_dir) / "start_server.sh")
        soulmask_cfg  = str(Path(cfg.server_dir) / "soulmask_server.json")
        log_dir       = str(Path(cfg.server_dir) / "WS" / "Saved" / "Logs")
        saved_dir     = str(Path(cfg.server_dir) / "WS" / "Saved")
        Path(log_dir).mkdir(parents=True, exist_ok=True)
        Path(saved_dir).mkdir(parents=True, exist_ok=True)

        _write_soulmask_cfg(
            out=soulmask_cfg,
            name=cfg.server_name, port=int(cfg.server_port or "0"),
            query_port=int(cfg.query_port or "0"), echo_port=int(cfg.echo_port or "0"),
            max_players=int(cfg.max_players or "0"),
            password=cfg.server_password, admin_password=cfg.server_admin_password,
            mode=cfg.server_mode,
            backup_enabled=cfg.backup_enabled, saving_enabled=cfg.saving_enabled,
            backup_interval=int(cfg.backup_interval or "7200"),
            log_dir=log_dir, saved_dir=saved_dir,
        )
        try:
            import pwd as _pwd
            pw = _pwd.getpwnam(cfg.sys_user)
            os.chown(soulmask_cfg, pw.pw_uid, pw.pw_gid)
        except (KeyError, OSError):
            pass
        console.ok("soulmask_server.json généré")

        content = startscripts.render_soulmask_start_script(
            server_dir=cfg.server_dir, cfg_path=soulmask_cfg
        )
        startscripts.write_start_script(out_path=start_script, content=content, sys_user=cfg.sys_user)
        console.ok(f"Script de démarrage : {start_script}")
        install_service(start_script)
        return

    # ── Valheim ───────────────────────────────────────────────────────────────
    if cfg.game_id == "valheim":
        start_script = str(Path(cfg.server_dir) / "start_server.sh")
        crossplay_flag = ""
        if cfg.crossplay:
            crossplay_flag = "-crossplay"
        if cfg.gc_force_playfab:
            crossplay_flag = "-playfab"

        if cfg.bepinex:
            bepinex_native = Path(cfg.server_dir) / "start_server_bepinex.sh"
            if bepinex_native.is_file():
                console.info("start_server_bepinex.sh trouvé — injection des paramètres...")
                extra_flag = f" {crossplay_flag}".rstrip()
                _patch_bepinex(
                    script=str(bepinex_native),
                    name=cfg.server_name, port=int(cfg.server_port or "0"),
                    world=cfg.world_name, password=cfg.server_password,
                    savedir=cfg.data_dir, extra_flag=extra_flag,
                )
                bepinex_native.chmod(bepinex_native.stat().st_mode | 0o111)
                try:
                    import pwd as _pwd
                    pw = _pwd.getpwnam(cfg.sys_user)
                    os.chown(bepinex_native, pw.pw_uid, pw.pw_gid)
                except (KeyError, OSError):
                    pass
                cfg.gc_bepinex_path = str(bepinex_native)
                start_script = str(bepinex_native)
                console.ok("Paramètres injectés dans start_server_bepinex.sh")
            else:
                console.warn("start_server_bepinex.sh introuvable — script BepInEx généré")
                content = startscripts.render_valheim_start_script(
                    server_dir=cfg.server_dir, data_dir=cfg.data_dir,
                    server_name=cfg.server_name, server_port=cfg.server_port,
                    world_name=cfg.world_name, server_password=cfg.server_password,
                    crossplay_flag=crossplay_flag, bepinex=True,
                )
                startscripts.write_start_script(out_path=start_script, content=content, sys_user=cfg.sys_user)
                console.ok("Script BepInEx généré")
        else:
            content = startscripts.render_valheim_start_script(
                server_dir=cfg.server_dir, data_dir=cfg.data_dir,
                server_name=cfg.server_name, server_port=cfg.server_port,
                world_name=cfg.world_name, server_password=cfg.server_password,
                crossplay_flag=crossplay_flag, bepinex=False,
            )
            startscripts.write_start_script(out_path=start_script, content=content, sys_user=cfg.sys_user)
            console.ok("Script standard généré (sans BepInEx)")

        console.ok(f"Script de démarrage : {start_script}")
        install_service(start_script)
        return

    # ── Enshrouded ────────────────────────────────────────────────────────────
    if cfg.game_id == "enshrouded":
        start_script    = str(Path(cfg.server_dir) / "start_server.sh")
        enshrouded_cfg  = str(Path(cfg.server_dir) / "enshrouded_server.json")
        console.info("Génération de enshrouded_server.json...")
        _write_enshrouded_cfg(
            out=enshrouded_cfg,
            name=cfg.server_name, password=cfg.server_password,
            port=int(cfg.server_port or "0"), max_players=int(cfg.max_players or "0"),
        )
        try:
            import pwd as _pwd
            pw = _pwd.getpwnam(cfg.sys_user)
            os.chown(enshrouded_cfg, pw.pw_uid, pw.pw_gid)
        except (KeyError, OSError):
            pass
        console.ok("enshrouded_server.json généré")
        content = startscripts.render_enshrouded_start_script(
            server_dir=cfg.server_dir, home_dir=cfg.home_dir
        )
        startscripts.write_start_script(out_path=start_script, content=content, sys_user=cfg.sys_user)
        console.ok(f"Script de démarrage : {start_script}")
        install_service(start_script)
        return

    console.warn(f"deploy_step_game_service : jeu '{cfg.game_id}' non géré")


def _write_soulmask_cfg(*, out: str, name: str, port: int, query_port: int,
                         echo_port: int, max_players: int, password: str,
                         admin_password: str, mode: str, backup_enabled: bool,
                         saving_enabled: bool, backup_interval: int,
                         log_dir: str, saved_dir: str) -> None:
    cfg_data = {
        "server_name": name, "max_players": max_players,
        "password": password or "", "admin_password": admin_password or "",
        "mode": mode, "port": port, "query_port": query_port, "echo_port": echo_port,
        "backup_enabled": backup_enabled, "saving_enabled": saving_enabled,
        "backup_interval": backup_interval, "log_dir": log_dir, "saved_dir": saved_dir,
    }
    Path(out).write_text(json.dumps(cfg_data, indent=2) + "\n")
    print(f"[config_gen] soulmask_server.json généré : {out}")


def _write_enshrouded_cfg(*, out: str, name: str, password: str, port: int, max_players: int) -> None:
    out_path = Path(out)
    existing_password = password
    if not existing_password and out_path.is_file():
        try:
            existing = json.loads(out_path.read_text())
            for group in existing.get("userGroups", []):
                if group.get("name", "").lower() == "default" and group.get("password"):
                    existing_password = group["password"]
                    break
        except (json.JSONDecodeError, OSError):
            pass

    cfg_data = {
        "name": name, "saveDirectory": "./savegame", "logDirectory": "./logs",
        "ip": "0.0.0.0", "queryPort": port + 1, "slotCount": max_players,
        "tags": [], "voiceChatMode": "Proximity",
        "enableVoiceChat": False, "enableTextChat": False,
        "gameSettingsPreset": "Default",
        "userGroups": [{
            "name": "Default", "password": existing_password or "",
            "canKickBan": False, "canAccessInventories": True,
            "canEditWorld": True, "canEditBase": True, "canExtendBase": True,
            "reservedSlots": 0,
        }],
        "bannedAccounts": [],
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(cfg_data, indent=2) + "\n")
    print(f"[config_gen] enshrouded_server.json généré : {out}")


def _patch_bepinex(*, script: str, name: str, port: int, world: str,
                    password: str, savedir: str, extra_flag: str) -> None:
    script_path = Path(script)
    extra = f" {extra_flag}" if extra_flag.strip() else ""
    new_exec = (
        f'exec ./valheim_server.x86_64'
        f' -name "{name}"'
        f' -port {port}'
        f' -world "{world}"'
        f' -password "{password}"'
        f' -savedir "{savedir}"'
        f' -public 1{extra}'
    )
    content = script_path.read_text()
    if re.search(r"^exec \./valheim_server", content, re.MULTILINE):
        content = re.sub(
            r"^exec \./valheim_server.*$", new_exec, content, flags=re.MULTILINE
        )
    else:
        content = content.rstrip("\n") + "\n" + new_exec + "\n"
    script_path.write_text(content)


# ── Step 6: Backups ───────────────────────────────────────────────────────────

def deploy_step_backups(cfg: DeployConfig, script_dir: Path) -> None:
    console.hdr("ÉTAPE 6 : Sauvegardes automatiques")
    ok, msgs = deploybackups.install_backup_assets(
        sys_user=cfg.sys_user, app_dir=cfg.app_dir, backup_dir=cfg.backup_dir,
        instance_id=cfg.instance_id, game_id=cfg.game_id,
        server_dir=cfg.server_dir, data_dir=cfg.data_dir or cfg.server_dir,
        world_name=cfg.world_name,
    )
    for msg in (msgs if isinstance(msgs, list) else [str(msgs)]):
        (console.ok if ok else console.warn)(msg)
    if not ok:
        console.die("Échec configuration sauvegardes")


# ── Step 7: App files ─────────────────────────────────────────────────────────

def deploy_step_app_files(cfg: DeployConfig, script_dir: Path) -> None:
    console.hdr("ÉTAPE 7 : Game Commander")
    ok, msgs = appfiles.install_app_files(
        deploy_app=cfg.deploy_app, src_dir=cfg.src_dir, app_dir=cfg.app_dir,
        sys_user=cfg.sys_user, script_dir=str(script_dir),
        game_id=cfg.game_id, game_label=cfg.game_label, game_binary=cfg.game_binary,
        game_service=cfg.game_service, server_dir=cfg.server_dir,
        data_dir=cfg.data_dir or cfg.server_dir, world_name=cfg.world_name,
        max_players=cfg.max_players, server_port=cfg.server_port,
        query_port=cfg.query_port, echo_port=cfg.echo_port,
        url_prefix=cfg.url_prefix, flask_port=cfg.flask_port,
        admin_login=cfg.admin_login, admin_password=cfg.admin_password,
        bepinex=cfg.bepinex and cfg.game_id == "valheim",
        steam_appid=cfg.steam_appid, steamcmd_path=cfg.steamcmd_path,
    )
    for msg in (msgs if isinstance(msgs, list) else [str(msgs)]):
        (console.ok if ok else console.warn)(msg)
    if not ok:
        console.die("Échec installation fichiers Game Commander")


# ── Step 8: App service ───────────────────────────────────────────────────────

def deploy_step_app_service(cfg: DeployConfig, script_dir: Path) -> None:
    console.hdr("ÉTAPE 8 : Service Game Commander")
    if cfg.deploy_app:
        ok, msg = appservice.install_gc_service(
            service_name=cfg.gc_service,
            game_label=cfg.game_label,
            game_service=cfg.game_service,
            sys_user=cfg.sys_user,
            app_dir=cfg.app_dir,
        )
        if ok:
            console.ok(f"Service {cfg.gc_service} actif")
        else:
            console.err(f"{cfg.gc_service} inactif — journalctl -u {cfg.gc_service} -n 30")

    for msg in cpuplan.install_cpu_monitor(str(script_dir)):
        console.ok(msg)


# ── Step 8B: Hub service ──────────────────────────────────────────────────────

def deploy_step_hub_service(cfg: DeployConfig, script_dir: Path) -> None:
    console.hdr("ÉTAPE 8B : Hub Admin")
    if os.environ.get("GC_SKIP_HUB_SERVICE") == "1":
        console.info("Hub Admin conservé — synchro/redémarrage ignorés pour cette exécution")
        return
    ok, msgs = hubsync.sync_hub_service_from_values(
        sys_user=cfg.sys_user, app_dir=cfg.app_dir,
        admin_login=cfg.admin_login, admin_password=cfg.admin_password,
        repo_root=script_dir, restart=False,
    )
    for msg in (msgs if isinstance(msgs, list) else [str(msgs)]):
        (console.ok if ok else console.warn)(msg)
    if not ok:
        console.warn("Échec synchro Hub Admin")


# ── Step 9: Nginx ─────────────────────────────────────────────────────────────

def deploy_step_nginx(cfg: DeployConfig, script_dir: Path) -> None:
    console.hdr("ÉTAPE 9 : Nginx")
    # deploynginx.run_deploy_nginx calls nginx_manager.py and wraps manifest add
    ok, msg = deploynginx.run_deploy_nginx(
        script_dir=str(script_dir),
        domain=cfg.domain,
        instance_id=cfg.instance_id,
        url_prefix=cfg.url_prefix,
        flask_port=cfg.flask_port,
        game_label=cfg.game_label,
    )
    if ok:
        console.ok(msg)
    else:
        console.err("Vérifiez manuellement : nginx -t")
        if msg:
            console.warn(msg)


# ── Step 10: SSL ──────────────────────────────────────────────────────────────

def deploy_step_ssl(cfg: DeployConfig, script_dir: Path) -> None:
    console.hdr("ÉTAPE 10 : SSL")
    ok, lines = deployssl.apply_ssl(cfg.ssl_mode, cfg.domain)
    for line in lines:
        if not line:
            continue
        if line == "HTTP uniquement":
            console.warn(line)
        else:
            console.ok(line)
    if not ok:
        console.warn("Gestion SSL en erreur")


# ── Step 11: Sudoers ──────────────────────────────────────────────────────────

def deploy_step_sudoers(cfg: DeployConfig, script_dir: Path) -> None:
    console.hdr("ÉTAPE 11 : Permissions sudo")
    ok, msg = deploysudo.write_instance_sudoers(
        cfg.sys_user, cfg.game_label, cfg.instance_id,
        cfg.game_service, cfg.gc_bepinex_path,
    )
    if ok:
        console.ok(msg)
    else:
        console.err("Sudoers invalide — supprimé")
        console.warn(f"Erreur visudo : {msg}")
        console.warn("À créer manuellement :")
        print(f"    sudo tee /etc/sudoers.d/game-commander-{cfg.instance_id} > /dev/null << 'EOF'")
        print(f"    {cfg.sys_user} ALL=(ALL) NOPASSWD: /usr/bin/systemctl start {cfg.game_service}")
        print(f"    {cfg.sys_user} ALL=(ALL) NOPASSWD: /usr/bin/systemctl stop {cfg.game_service}")
        print(f"    {cfg.sys_user} ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart {cfg.game_service}")
        print("    EOF")


# ── Step 12: Save config ──────────────────────────────────────────────────────

def deploy_step_save_config(cfg: DeployConfig, script_dir: Path) -> None:
    config_save = str(Path(cfg.app_dir) / "deploy_config.env")
    cfg.config_save = config_save

    ok, msg = deploypost.save_deploy_config(cfg.to_env(), config_save)
    if not ok:
        console.die(f"Échec sauvegarde config : {config_save}")
    console.ok(f"Config sauvegardée : {config_save}")

    # Apply CPU plan now that config is saved
    for msg_line in cpuplan.apply_plan([], restart_running=False):
        console.ok(msg_line)


# ── Step 12B: Discord channel ─────────────────────────────────────────────────

def deploy_step_discord_channel(cfg: DeployConfig, script_dir: Path) -> None:
    console.hdr("ÉTAPE 12 : Discord")
    try:
        discord_cfg = discordnotify.load_config()
        if not discordnotify.notifications_enabled(discord_cfg):
            console.info("Discord non configuré — channel non créé")
            return
        exit_code = discordnotify._cli_create_channel(cfg.instance_id, cfg.game_id)
        if exit_code != 0:
            console.warn(f"Discord : création channel échouée (code {exit_code})")
    except Exception as exc:
        msg = str(exc)
        if "guild_id" in msg or "Bot token" in msg:
            console.info("Discord non configuré — channel non créé")
        else:
            console.warn(f"Discord : {msg}")


# ── Validation ────────────────────────────────────────────────────────────────

def deploy_step_validation(cfg: DeployConfig, script_dir: Path) -> None:
    console.hdr("VALIDATION FINALE")
    print()

    lines = deploypost.validation_lines(cfg.to_env(), cfg.config_save)
    errors = 0
    firewall_specs_list = []

    for line in lines:
        if not line:
            continue
        if line.startswith("VALIDATION_ERRORS="):
            try:
                errors = int(line.split("=", 1)[1])
            except ValueError:
                pass
        elif line.startswith("FIREWALL="):
            firewall_specs_list.append(line[len("FIREWALL="):])
        elif any(x in line for x in ("actif", "Game Commander", "Nginx")):
            if "inactif" in line or "ne " in line:
                console.warn(line)
            else:
                console.ok(line)

    print()
    console.sep()
    print()
    print("  \033[1mAccès à l'interface :\033[0m")
    proto = "https" if cfg.ssl_mode != "none" else "http"
    print(f"  \033[0;36m  {proto}://{cfg.domain}{cfg.url_prefix}\033[0m")
    print()
    print("  \033[1mCommandes utiles :\033[0m")
    print(f"    sudo systemctl status {cfg.game_service}")
    if cfg.deploy_app:
        print(f"    sudo systemctl status {cfg.gc_service}")
    print(f"    sudo journalctl -u {cfg.game_service} -f")
    if cfg.deploy_app:
        print(f"    sudo journalctl -u {cfg.gc_service} -f")
    print()
    print("  \033[1mRedéploiement rapide :\033[0m")
    print(f"    sudo ./gcctl deploy --config {cfg.config_save}")
    print()
    print("  \033[1mPorts à ouvrir (firewall) :\033[0m")
    _print_firewall_info(cfg)

    # UFW auto-open
    try:
        r_ufw = subprocess.run(["ufw", "status"], capture_output=True, text=True, check=False)
        if r_ufw.returncode == 0 and "Status: active" in r_ufw.stdout:
            console.info("UFW actif — ouverture des ports...")
            for spec in firewall_specs_list:
                r = subprocess.run(["ufw", "allow", spec], check=False)
                if r.returncode == 0:
                    console.ok(f"UFW : {spec} ouvert")
            for spec in ("80/tcp", "443/tcp"):
                subprocess.run(["ufw", "allow", spec], check=False)
                console.ok(f"UFW : {spec} ouvert")
        else:
            console.warn("UFW inactif ou absent — pensez à ouvrir les ports dans le firewall :")
            _print_firewall_manual(cfg)
    except FileNotFoundError:
        console.warn("UFW absent — pensez à ouvrir les ports dans le firewall :")
        _print_firewall_manual(cfg)

    print()
    if errors == 0:
        print("  \033[0;32m\033[1m✓ Déploiement terminé avec succès !\033[0m")
    else:
        print(f"  \033[0;33m\033[1m⚠ Déploiement terminé avec {errors} avertissement(s)\033[0m")
    print()
    if cfg.logfile:
        console.info(f"Journal complet : {cfg.logfile}")


def _print_firewall_info(cfg: DeployConfig) -> None:
    gid = cfg.game_id
    sp = cfg.server_port
    qp = cfg.query_port
    ep = cfg.echo_port
    if gid in ("minecraft", "minecraft-fabric"):
        print(f"    Jeu  : {sp}/TCP")
    elif gid == "satisfactory":
        print(f"    Jeu  : {sp}/TCP  {sp}/UDP")
        print(f"    Flux fiable / join  : {qp}/TCP")
    elif gid == "terraria":
        print(f"    Jeu  : {sp}/TCP")
    elif gid == "soulmask":
        print(f"    Jeu  : {sp}/UDP  {qp}/UDP  {ep}/TCP")
    else:
        try:
            sp_next = int(sp) + 1
        except ValueError:
            sp_next = "?"
        print(f"    Jeu  : {sp}/UDP  {sp_next}/UDP")
    print("    Web  : 80/TCP  443/TCP")


def _print_firewall_manual(cfg: DeployConfig) -> None:
    gid = cfg.game_id
    sp = cfg.server_port
    qp = cfg.query_port
    ep = cfg.echo_port
    if gid in ("minecraft", "minecraft-fabric"):
        print(f"    {sp}/TCP, 80/TCP, 443/TCP")
    elif gid == "satisfactory":
        print(f"    {sp}/TCP, {sp}/UDP, {qp}/TCP, 80/TCP, 443/TCP")
        print(f"    ({qp}/TCP est requis pour le join fiable des joueurs)")
    elif gid == "terraria":
        print(f"    {sp}/TCP, 80/TCP, 443/TCP")
    elif gid == "soulmask":
        print(f"    {sp}/UDP, {qp}/UDP, {ep}/TCP, 80/TCP, 443/TCP")
    else:
        try:
            sp_next = int(sp) + 1
        except ValueError:
            sp_next = "?"
        print(f"    {sp}/UDP, {sp_next}/UDP, 80/TCP, 443/TCP")


# ── Public entry point ────────────────────────────────────────────────────────

def run_all_steps(cfg: DeployConfig, script_dir: Path) -> None:
    deploy_step_dependencies(cfg, script_dir)
    deploy_step_game_install(cfg, script_dir)
    deploy_step_game_service(cfg, script_dir)
    deploy_step_backups(cfg, script_dir)
    deploy_step_app_files(cfg, script_dir)
    deploy_step_app_service(cfg, script_dir)
    deploy_step_hub_service(cfg, script_dir)
    deploy_step_nginx(cfg, script_dir)
    deploy_step_ssl(cfg, script_dir)
    deploy_step_sudoers(cfg, script_dir)
    deploy_step_save_config(cfg, script_dir)
    deploy_step_discord_channel(cfg, script_dir)
    deploy_step_validation(cfg, script_dir)
