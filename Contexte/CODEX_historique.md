# CODEX_historique.md — Game Commander
> Fichier de mémoire pour Codex. Lire intégralement avant toute modification.
> Mettre à jour après chaque correction ou décision importante.

---

## Contexte du projet

**Game Commander** — Interface web Flask autonome (sans AMP) pour gérer des serveurs de jeux
dédiés (Valheim, Enshrouded, Minecraft Java) sur un VPS Hetzner Ubuntu 24.04.

- **Utilisateur système :** `gameserver`
- **Domaine :** `gaming.example.com` (multi-instances sous le même domaine)
- **URLs :** `gaming.example.com/<instance>` (ex: `/valheim2`, `/enshrouded2`)
- **Nginx conf :** `/etc/nginx/conf.d/gaming.example.com.conf` — fichier **partagé** entre toutes les instances
- **Registrar DNS :** registrar DNS générique
- **Instances Game Commander actives :**
  - aucune actuellement
- **Autres instances sur le même serveur (AMP) :**
  - `CauchemarCommu01` — Valheim AMP (port AMP 8081)
  - `Test01` — Enshrouded AMP (port AMP 8082, ports jeu 15636/15637)

---

## Architecture fichiers

```
gc/
├── Contexte/CODEX_historique.md # ce fichier
├── game_commander.sh          # point d'entrée bash, source les modules lib/
├── lib/
│   ├── helpers.sh             # logs, prompts, helpers shell communs
│   ├── nginx.sh               # wrapper bash autour de tools/nginx_manager.py
│   ├── cmd_deploy.sh          # orchestration du déploiement
│   ├── deploy_helpers.sh      # defaults, prompts, config file, logging
│   ├── deploy_configure.sh    # étape 2 interactive / validations de config
│   ├── deploy_steps.sh        # étapes 3 à 12 du déploiement
│   ├── cmd_uninstall.sh       # orchestration de la désinstallation
│   ├── uninstall_gc.sh        # désinstallation des instances Game Commander
│   ├── uninstall_flask.sh     # désinstallation des applis Flask génériques
│   ├── uninstall_orphans.sh   # détection/cleanup des processus orphelins
│   └── cmd_status.sh          # affichage de l'état des instances
├── tools/
│   ├── nginx_manager.py       # manifest nginx + génération locations + migration
│   ├── config_gen.py          # génération/config utilitaires
│   └── test_tools.py          # tests des outils Python
├── runtime/
│   ├── app.py                 # application Flask principale
│   ├── game_valheim.json      # config template Valheim
│   ├── game_enshrouded.json   # config template Enshrouded
│   ├── game_minecraft.json    # config template Minecraft
│   ├── core/
│   │   ├── auth.py            # authentification bcrypt + permissions
│   │   ├── server.py          # contrôle systemd + métriques psutil
│   │   └── metrics.py         # logging CPU/RAM/joueurs (JSON Lines, 24h)
│   ├── games/
│   │   ├── valheim/
│   │   │   ├── config.py      # lecture/écriture config Valheim
│   │   │   ├── players.py     # joueurs via journalctl
│   │   │   ├── mods.py        # gestion mods BepInEx/Thunderstore
│   │   │   └── world_modifiers.py
│   │   └── enshrouded/
│   │       ├── config.py      # lecture/écriture enshrouded_server.json
│   │       └── players.py     # joueurs via journalctl (steamid)
│   ├── static/
│   │   ├── common.css
│   │   └── themes/            # valheim, enshrouded, minecraft, dark-steel...
│   └── templates/
│       ├── base/
│       │   ├── app_base.html  # template principal (dashboard, métriques, actions)
│       │   └── login_base.html
│       └── games/             # templates spécifiques par jeu
```

---

## Bugs résolus — NE PAS RÉINTRODUIRE

### [1] wine64 absent du PATH après installation (Ubuntu 24.04)
**Symptôme :** `wine64: not found` dans journalctl malgré `apt install wine64`
**Cause :** Le paquet `wine64` sur Ubuntu 24.04 installe les libs (`/usr/lib/wine/wine64`)
mais pas de binaire dans le PATH.
**Solution dans `game_commander.sh` :** Après `apt install wine64`, vérifier si `wine64`
est dans le PATH, sinon créer un symlink :
```bash
ln -sf "$(command -v wine)" /usr/local/bin/wine64
# ou
ln -sf /usr/lib/wine/wine64 /usr/local/bin/wine64
```

---

### [2] Injection Nginx dans le mauvais bloc server (HTTP au lieu de SSL)
**Symptôme :** Bloc `location /instance` injecté dans le bloc `server { listen 80 }` qui
contient un `return 404` — les requêtes HTTPS ne le voient jamais.
**Cause :** Le Python utilisait `content.rfind('}')` qui trouve la dernière `}` du fichier,
qui est celle du bloc HTTP redirect, pas du bloc SSL.
**Solution dans `game_commander.sh` :** Cibler explicitement le bloc SSL en cherchant
`listen 443 ssl`, remonter au `server {` parent, compter les accolades pour trouver la `}`
fermante du bon bloc, et injecter juste avant.

---

### [3] SERVER_PASSWORD corrompu dans les heredocs Python
**Symptôme :** `enshrouded_server.json` généré avec un mot de passe incorrect ou vide.
**Cause 1 :** Le mot de passe était interpolé directement dans le heredoc bash → les
caractères spéciaux (`\`, `"`, `$`) corrompaient le code Python silencieusement.
**Cause 2 :** Sur redéploiement `--config`, `SERVER_PASSWORD` est vide (non sauvegardé
dans le `.env`) → le fichier était écrasé avec un mot de passe vide.
**Solution :** Passer les valeurs via variables d'environnement + heredoc `'PYEOF'`
(guillemets simples = pas d'interpolation bash). Récupérer le mot de passe existant
dans `enshrouded_server.json` si `SERVER_PASSWORD` est vide lors d'un redéploiement.

---

### [4] pkill -f "enshrouded" tue les instances AMP
**Symptôme :** `pkill -f "enshrouded"` tue aussi `Test01` (instance AMP Enshrouded).
**⚠️ RÈGLE ABSOLUE :** Ne jamais utiliser `pkill -f "enshrouded"` ni aucun `pkill`
générique sur ce serveur.
**Solution pour stopper un service systemd en boucle :**
```bash
systemctl disable --now <service>
systemctl kill -s SIGKILL <service>
```

---

### [5] Métriques CPU/RAM incorrectes pour Enshrouded (Wine)
**Symptôme :** CPU affiché à 0%, RAM à 2-32MB alors que le vrai usage est ~20-60% CPU
et ~1.5GB RAM.
**Cause :** Wine re-parente `enshrouded_server.exe` hors de l'arbre systemd.
- `MainPID` systemd = `xvfb-run` (wrapper léger)
- `children(recursive=True)` ne trouve pas `enshrouded_server.exe` re-parenté
- La cmdline Wine utilise le format `Z:\home\gameserver\...` pas `/home/gameserver/...`
**Solution dans `runtime/core/server.py` :**
1. Fallback via `systemctl show --property=MainPID` si binaire non trouvé
2. Scanner tous les process dont la cmdline contient `install_dir` OU son équivalent
   Wine `Z:\home\gameserver\enshrouded2_server`
3. Sommer CPU+RAM de tout l'arbre (proc principal + enfants + process re-parentés)
4. Filtrer **uniquement** par `install_dir` (pas par `binary`) pour ne pas capturer
   l'instance AMP Enshrouded qui tourne en parallèle

---

### [6] Uninstall Nginx supprime le fichier entier si vhost partagé
**Symptôme :** L'uninstall propose de supprimer `/etc/nginx/conf.d/gaming.example.com.conf`
entier, ce qui casserait toutes les autres instances sur ce domaine.
**Solution dans `game_commander.sh` — fonction `cmd_uninstall` :**
- Compter les blocs `location` dans le fichier
- Si ≤ 2 blocs et que c'est notre instance → proposer suppression totale
- Si fichier partagé → retirer uniquement le bloc `location /instance` avec Python regex

---

### [7] Métriques graphe vides quand serveur arrêté
**Symptôme :** Le graphe s'arrête net à l'heure d'arrêt, pas de visualisation du downtime.
**Cause :** Le poller dans `runtime/core/metrics.py` n'enregistrait des points que si `state == 20`.
**Solution :** Enregistrer des points à `0/0/0` même quand le serveur est arrêté, pour
visualiser les périodes de downtime comme des creux plats dans le graphe.

---

### [8] Valheim — conflit Steam entre deux instances sur la même machine
**Symptôme :** `Steam is not initialized` / `Awake of network backend failed` quand une
deuxième instance Valheim démarre sur le même serveur.
**Solution :** Utiliser `-playfab` (crossplay PlayFab) au lieu de `-vanilla` pour la
deuxième instance. Le flag `-vanilla` tente d'initialiser Steam localement, ce qui
entre en conflit avec l'instance AMP déjà active.

---

### [9] Enshrouded — serveur invisible si le `queryPort` sort de la plage firewall ouverte
**Symptôme :** Une instance Enshrouded Game Commander démarre correctement et l'UI répond,
mais le serveur reste introuvable en jeu.
**Cause :**
- Le format actuel de `enshrouded_server.json` ne correspond plus à l'ancien schéma simple.
- Le mot de passe joueur est porté par `userGroups[*].password`.
- Le port pertinent pour la découverte est `queryPort`.
- Si on déploie avec `SERVER_PORT=15639`, alors `queryPort=15640`, donc le serveur est
  invisible si seuls `15636-15639` sont ouverts côté firewall Hetzner.
**Solution validée :**
- Générer `enshrouded_server.json` dans le format actuel du jeu
- Lire/écrire le mot de passe via `userGroups[*].password`
- Pour la plage firewall `15636-15639`, utiliser `SERVER_PORT=15638` pour obtenir
  `queryPort=15639`
- Validation réelle effectuée : serveur joignable sur `203.0.113.10:15639`

---

### [10] Uninstall — faux positif "processus orphelin" sur Enshrouded encore géré par systemd
**Symptôme :** Lors de la désinstallation d'une instance Valheim, l'outil propose de tuer
`enshrouded_server.exe` de `testensh` dans la section des processus orphelins alors que
le serveur Enshrouded fonctionne encore normalement.
**Cause :**
- Le scan des orphelins regardait surtout les `MainPID` systemd
- Sous Wine, le vrai process `enshrouded_server.exe` reste dans le cgroup systemd du
  service sans être forcément le `MainPID`
**Solution validée :**
- Exclure du scan tout PID encore rattaché à une unité `*.service` via `/proc/<pid>/cgroup`
- Résultat attendu : un Enshrouded actif n'est plus proposé comme orphelin lors de la
  désinstallation d'une autre instance

---

## Décisions d'architecture

### Nginx — vhost partagé multi-instances
Toutes les instances Game Commander sur `gaming.example.com` partagent **un seul fichier**
`/etc/nginx/conf.d/gaming.example.com.conf`.

**Ancien modèle :** injection directe d'un bloc `location /instance` dans le bloc SSL.

**Modèle actuel :**
- fichier manifest : `/etc/nginx/game-commander-manifest.json`
- fichier généré : `/etc/nginx/game-commander-locations.conf`
- migration one-shot idempotente via `tools/nginx_manager.py init`
- le vhost partagé contient un `include` vers `game-commander-locations.conf`
- le deploy ajoute/met à jour une entrée du manifest puis régénère le fichier locations
- l'uninstall retire l'entrée du manifest puis régénère le fichier locations

Le but est d'éviter les manipulations répétées et fragiles de blocs inline dans le vhost
partagé. Les anciennes corrections liées à l'injection inline restent importantes pour la
migration et pour les cas de fallback/legacy, mais la source de vérité est maintenant le
manifest Nginx.

### Modularisation du script bash

La modularisation de `game_commander.sh` est maintenant considérée comme **terminée à un
bon niveau** :
- `game_commander.sh` = point d'entrée + dispatch
- `cmd_deploy.sh` = orchestration du déploiement
- `deploy_helpers.sh` = helpers de déploiement
- `deploy_configure.sh` = collecte/validation de configuration
- `deploy_steps.sh` = exécution des étapes de déploiement
- `cmd_uninstall.sh` = orchestration de la désinstallation
- `uninstall_gc.sh`, `uninstall_flask.sh`, `uninstall_orphans.sh` = sous-domaines
  de désinstallation
- `nginx.sh` = wrappers bash Nginx

Ce qui reste à faire relève plutôt du raffinage d'architecture et des tests unitaires
supplémentaires, plus d'une extraction urgente.

### Mots de passe
- **Mot de passe jeu** (`SERVER_PASSWORD`) : en clair dans le fichier de config du jeu
  (ex: `enshrouded_server.json`). Jamais sauvegardé dans `deploy_config.env`.
- **Mot de passe admin web** (`ADMIN_PASSWORD`) : hashé bcrypt dans `users.json`.
  Pour modifier : `python3 -c "import bcrypt; print(bcrypt.hashpw(b'mdp', bcrypt.gensalt()).decode())"`

### systemd stop/restart
Utiliser `--no-block` pour éviter le timeout Flask (30s) sur les serveurs lents à s'arrêter.

### Refresh rates frontend
- Statut + compteurs : `setInterval(fetchStatus, 5000)` — 5 secondes
- Graphe métriques : `setInterval(loadChartData, 30000)` — 30 secondes
- Console : `setTimeout(pollConsole, 3000)` — 3 secondes

### États transitoires
Lors d'un stop/restart, le frontend passe immédiatement en état 40 (Arrêt en cours)
ou 30 (Redémarrage) avec bouton désactivé, et poll toutes les 3s jusqu'à stabilisation.

---

## Ports par instance

| Instance | Jeu | Ports jeu | Flask | URL |
|---|---|---|---|---|
| Test01 (AMP) | Enshrouded | 15636/UDP 15637/UDP | — | — |
| CauchemarCommu01 (AMP) | Valheim | — | — | — |

---

## Commandes utiles

```bash
# État de toutes les instances
sudo bash ~/gc/game_commander.sh status

# Logs en direct
sudo journalctl -u game-commander-enshrouded2 -f
sudo journalctl -u enshrouded-server-enshrouded2 -f

# Appliquer un fix sur runtime/core/server.py sans redéploiement
sudo cp runtime/core/server.py /home/gameserver/game-commander-enshrouded2/core/server.py
sudo systemctl restart game-commander-enshrouded2

# Vérifier l'arbre de process Wine
pstree -p $(sudo systemctl show enshrouded-server-enshrouded2 --property=MainPID | cut -d= -f2)

# Ne JAMAIS utiliser :
# pkill -f "enshrouded"   ← tue aussi l'instance AMP Test01
```
