# Game Commander

Interface web générique pour la gestion de serveurs de jeu.
Sans dépendance AMP — psutil + systemd + bcrypt.

## Déploiement

```bash
# 1. Copier game_valheim.json (ou enshrouded) en game.json
cp game_valheim.json game.json

# 2. Créer users.json avec un compte admin
python3 -c "
import bcrypt, json
pw = input('Mot de passe admin : ').encode()
h  = bcrypt.hashpw(pw, bcrypt.gensalt()).decode()
print(json.dumps({'admin': {'password_hash': h, 'permissions': []}}, indent=2))
" > users.json

# 3. Lancer
export GAME_COMMANDER_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
python3 app.py
```

## Structure

```
app.py                     ← Flask factory (lit game.json)
game.json                  ← Config du jeu actif (copier depuis game_*.json)
users.json                 ← Utilisateurs (bcrypt)
metrics.log                ← Métriques append-only

core/
  auth.py                  ← Auth locale + permissions
  server.py                ← psutil + systemd
  metrics.py               ← Poller + lecture

games/
  valheim/mods.py          ← Thunderstore + BepInEx
  valheim/config.py        ← BetterNetworking.cfg
  enshrouded/config.py     ← enshrouded_server.json
  minecraft/               ← Placeholder

templates/
  base/app_base.html       ← Structure commune (Jinja2 blocks)
  base/login_base.html     ← Login commun
  games/valheim/           ← Templates spécifiques Valheim
  games/enshrouded/        ← Templates spécifiques Enshrouded

static/
  common.css               ← Layout pur (zéro couleur)
  themes/valheim/          ← Thème forge/braise
  themes/enshrouded/       ← Thème brume/sarcelle
```

## game.json — Variables clés

| Champ | Rôle |
|---|---|
| `id` | Sélectionne les templates et modules games/{id}/ |
| `server.binary` | Nom du process pour psutil |
| `server.service` | Nom du service systemd |
| `web.url_prefix` | Préfixe des routes Flask (/valheim, /enshrouded) |
| `web.flask_port` | Port d'écoute Flask |
| `features.*` | Active/désactive les onglets (mods, config, console) |
| `theme.name` | Sélectionne static/themes/{name}/ |

## Ajouter un nouveau jeu

1. Créer `games/{id}/config.py` et/ou `games/{id}/mods.py`
2. Créer `templates/games/{id}/app.html` et `login.html`
3. Créer `static/themes/{id}/theme.css` et `login.css`
4. Créer `game_{id}.json` et le copier en `game.json`

## Script de déploiement

```bash
# Interactif (demande tout)
sudo bash deploy_game_commander.sh

# Avec fichier de config (CI/redéploiement)
sudo bash deploy_game_commander.sh --config deploy_game_commander.env

# Générer un modèle de config
sudo bash deploy_game_commander.sh --generate-config
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
| 9 | Nginx (vhost ou injection dans existant) |
| 10 | SSL (certbot / existing / none) |
| 11 | Règles sudoers (systemctl + BepInEx pour Valheim) |
| 12 | Sauvegarde deploy_config.env |

### Jeux supportés

| Jeu | Steam | BepInEx | Config |
|---|---|---|---|
| Valheim | ✅ 896660 | ✅ optionnel | BetterNetworking.cfg |
| Enshrouded | ✅ 2278520 | — | enshrouded_server.json |
| Minecraft | ⚠ placeholder | — | — |
