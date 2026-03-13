# Game Commander

Interface web générique pour la gestion de serveurs de jeu.
Sans dépendance AMP — psutil + systemd + bcrypt.

## Déploiement

```bash
# 1. Copier un template runtime en game.json
cp runtime/game_valheim.json runtime/game.json

# 2. Créer users.json avec un compte admin
python3 -c "
import bcrypt, json
pw = input('Mot de passe admin : ').encode()
h  = bcrypt.hashpw(pw, bcrypt.gensalt()).decode()
print(json.dumps({'admin': {'password_hash': h, 'permissions': []}}, indent=2))
" > runtime/users.json

# 3. Lancer
export GAME_COMMANDER_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
python3 runtime/app.py
```

## Structure

```
game_commander.sh          ← Point d'entrée deploy/status/uninstall

lib/
  helpers.sh               ← Helpers shell partagés
  nginx.sh                 ← Fonctions Nginx
  cmd_deploy.sh            ← Orchestration du déploiement
  deploy_helpers.sh        ← Helpers de déploiement
  deploy_configure.sh      ← Configuration interactive / validations
  deploy_steps.sh          ← Étapes de déploiement
  cmd_uninstall.sh         ← Orchestration de la désinstallation
  uninstall_gc.sh          ← Désinstallation Game Commander
  uninstall_flask.sh       ← Désinstallation Flask générique
  uninstall_orphans.sh     ← Processus orphelins
  cmd_status.sh            ← Statut instances

tools/
  nginx_manager.py         ← Manifest Nginx + génération des locations
  test_tools.py            ← Tests outils Python

runtime/
  app.py                   ← Flask factory (lit game.json)
  game.json                ← Config du jeu actif (copier depuis game_*.json)
  users.json               ← Utilisateurs (bcrypt)
  metrics.log              ← Métriques append-only
  core/
    auth.py                ← Auth locale + permissions
    server.py              ← psutil + systemd
    metrics.py             ← Poller + lecture
  games/
    valheim/mods.py        ← Thunderstore + BepInEx
    valheim/config.py      ← BetterNetworking.cfg
    enshrouded/config.py   ← enshrouded_server.json
    minecraft/             ← Support Minecraft Java vanilla
    minecraft_fabric/      ← Support Minecraft Fabric + mods Modrinth
  templates/
    base/app_base.html     ← Structure commune (Jinja2 blocks)
    base/login_base.html   ← Login commun
    games/valheim/         ← Templates spécifiques Valheim
    games/enshrouded/      ← Templates spécifiques Enshrouded
  static/
    common.css             ← Layout pur (zéro couleur)
    themes/valheim/        ← Thème forge/braise
    themes/enshrouded/     ← Thème brume/sarcelle
```

## game.json — Variables clés

| Champ | Rôle |
|---|---|
| `id` | Sélectionne les templates et modules runtime/games/{id}/ |
| `server.binary` | Nom du process pour psutil |
| `server.service` | Nom du service systemd |
| `web.url_prefix` | Préfixe des routes Flask (/valheim, /enshrouded) |
| `web.flask_port` | Port d'écoute Flask |
| `features.*` | Active/désactive les onglets (mods, config, console) |
| `theme.name` | Sélectionne runtime/static/themes/{name}/ |

## Ajouter un nouveau jeu

1. Créer `runtime/games/{id}/config.py` et/ou `runtime/games/{id}/mods.py`
2. Créer `runtime/templates/games/{id}/app.html` et `login.html`
3. Créer `runtime/static/themes/{id}/theme.css` et `login.css`
4. Créer `runtime/game_{id}.json` et le copier en `runtime/game.json`

## Script de déploiement

```bash
# Interactif (demande tout)
sudo bash game_commander.sh

# Déploiement interactif
sudo bash game_commander.sh deploy

# Avec fichier de config (CI/redéploiement)
sudo bash game_commander.sh deploy --config env/deploy_config.env

# Générer un modèle de config
sudo bash game_commander.sh deploy --generate-config

# Désinstallation / statut / update
sudo bash game_commander.sh uninstall
sudo bash game_commander.sh status
sudo bash game_commander.sh update --instance testfabric
```

### Ce que fait le script (12 étapes)

| Étape | Action |
|---|---|
| 0 | Vérification root |
| 1 | Détection OS |
| 2 | Configuration interactive (ou depuis fichier) |
| 3 | Dépendances apt + pip + SteamCMD |
| 4 | Installation serveur de jeu via SteamCMD |
| 5 | Service systemd du serveur de jeu |
| 6 | Sauvegardes automatiques (cron 3h, 7 jours) |
| 7 | Copie Game Commander + génération game.json + users.json |
| 8 | Service systemd Flask |
| 9 | Nginx (manifest + fichier locations généré + include dans le vhost) |
| 10 | SSL (certbot / existing / none) |
| 11 | Règles sudoers (systemctl + BepInEx pour Valheim) |
| 12 | Sauvegarde deploy_config.env |

### Nginx multi-instances

Le déploiement actuel ne maintient plus chaque bloc `location` directement dans le vhost
partagé. Il utilise :

- `/etc/nginx/game-commander-manifest.json` comme source de vérité des instances
- `/etc/nginx/game-commander-locations.conf` comme fichier auto-généré
- `tools/nginx_manager.py` pour initialiser, migrer, régénérer et nettoyer

Le vhost du domaine inclut ensuite ce fichier généré dans son bloc SSL.

## GitHub

Le dépôt local est prévu pour être synchronisé avec GitHub via `origin`.

Avant push, lancer :

```bash
./tools/github_preflight.sh
```

Ce script :
- vérifie que `origin` existe
- vérifie que les fichiers serveur sensibles ne sont pas trackés
- exécute `./tools/test_modularization.sh`

Un hook `pre-push` versionné est aussi fourni dans `.githooks/pre-push`.

## État de la modularisation

La modularisation bash est en place :

- `game_commander.sh` est un point d'entrée léger
- le déploiement est séparé entre orchestration, configuration et étapes
- la désinstallation est séparée entre orchestration, instances Game Commander,
  applis Flask génériques et processus orphelins
- une commande `update` permet de resynchroniser le runtime d'une instance déjà installée
  sans réinstaller le serveur de jeu
- la gestion Nginx moderne est centralisée via `tools/nginx_manager.py`

## Documentation de contexte

La documentation de contexte du projet repose désormais sur :

- `Contexte/CODEX.md` pour le contexte opérationnel concis
- `Contexte/CODEX_historique.md` pour la mémoire projet détaillée
- `Contexte/BUGS.md` pour les régressions, bugs connus et solutions validées
- `README.md` pour la vue d'ensemble du dépôt
- `Contexte/GUIDE_DEMARRAGE.md` pour une prise en main débutant côté serveur/VPS/SSH
- `env/ENV.md` pour l'organisation des fichiers `.env` locaux

### Jeux supportés

| Jeu | Steam | BepInEx | Config |
|---|---|---|---|
| Valheim | ✅ 896660 | ✅ optionnel | BetterNetworking.cfg |
| Enshrouded | ✅ 2278520 | — | enshrouded_server.json |
| Minecraft Java | ✅ vanilla | — | `server.properties` |
| Minecraft Fabric | ✅ Fabric | ✅ Modrinth | `server.properties` |

Note Minecraft Java :
- le serveur téléchargé automatiquement peut être plus récent que ton client Java local
- en cas d'erreur `Incompatible client`, il faut lancer la bonne version dans le launcher
- les sauvegardes ciblent `world/` et les fichiers admin utiles (`server.properties`, `ops.json`, `whitelist.json`, `banned-players.json`, `banned-ips.json`, `usercache.json`)

Note Minecraft Fabric :
- un client Java vanilla peut se connecter tant qu'aucun mod serveur n'exige un client moddé
- l'installation de mods passe par Modrinth
- les dépendances Fabric requises sont résolues automatiquement, y compris quand elles ne sont pas complètement déclarées dans l'API Modrinth mais présentes dans `fabric.mod.json`
- les sauvegardes ciblent `world/` et les mêmes fichiers admin utiles que Minecraft Java, sans inclure `mods/`, `libraries/` ou les binaires serveur
