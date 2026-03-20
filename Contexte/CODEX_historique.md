# CODEX_historique.md — Game Commander
> Fichier de mémoire pour Codex. Lire intégralement avant toute modification.
> Mettre à jour après chaque correction ou décision importante.

---

## Contexte du projet

**Game Commander** — Interface web Flask autonome (sans AMP) pour gérer des serveurs de jeux
dédiés (Valheim, Enshrouded, Minecraft Java, Minecraft Fabric, Terraria) sur un VPS Hetzner Ubuntu 24.04.

- **Utilisateur système :** `gameserver`
- **Domaine :** `gaming.example.com` (multi-instances sous le même domaine)
- **URLs :** `gaming.example.com/<instance>` (ex: `/valheim2`, `/enshrouded2`)
- **Nginx conf :** `/etc/nginx/conf.d/gaming.example.com.conf` — fichier **partagé** entre toutes les instances
- **Registrar DNS :** registrar DNS générique
- **Instances Game Commander actives :**
  - aucune actuellement
- **Autres instances sur le même serveur (AMP) :**
  - `amp-valheim-01` — Valheim AMP (port AMP 8081)
  - `amp-enshrouded-01` — Enshrouded AMP (port AMP 8082, ports jeu 15636/15637)

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

### [2026-03-19] Observation Discord encore à surveiller
- Une notification Discord fantôme a encore été observée sous la forme :
  - `minecraft-fabric: 19-03-2026 ... - Mise a jour [Hub]`
- Contexte important :
  - aucune instance `minecraft-fabric` n'existe plus sur l'hôte
  - le symptôme n'a pas été revu pendant les actions normales Hub/Commander après
    resynchronisation
  - d'après l'observation utilisateur, il apparaît surtout pendant certaines commandes `git`
- Hypothèse retenue pour l'instant :
  - reliquat d'un ancien process ou d'un chemin non UI encore vivant au moment des pushes
- Décision de contexte :
  - ne pas considérer le bug comme reproduit de façon stable tant qu'il n'apparaît pas hors
    de ce contexte `git`
  - si le symptôme revient, tracer en priorité le process émetteur au moment exact de
    l'envoi Discord

### [2026-03-14] Session de validation Soulmask / attach / sauvegardes
**État général validé :**
- Le mode `attach` est validé en réel sur Soulmask :
  - déploiement Commander-only sur un service jeu existant
  - aucun nouveau service jeu créé
  - `start/stop/restart` via l'UI OK
- Le premier lot `save manager` est validé en réel :
  - onglet `Sauvegardes`
  - navigation lecture seule
  - téléchargement fichier
  - téléchargement dossier en zip
- Le panneau `Connexion` a été déplacé en haut du dashboard et le layout est à conserver pour tous les jeux.

**Soulmask — état retenu :**
- Déploiement OK
- UI OK
- Restart/config OK
- Connexion jeu finalement validée
- Le serveur est joignable après ouverture correcte des ports côté réseau externe
- Le serveur est visible via le code unique Steam et la connexion en jeu a été validée

**Soulmask — observations runtime :**
- Le démarrage et l'arrêt sont lents
- La charge CPU juste après `start/restart` peut être très élevée puis redescendre après stabilisation
- La RAM observée autour de 8.2 GiB RSS est réelle, pas un bug d'affichage Game Commander

**Soulmask — joueurs connectés :**
- Le cas simple 1 joueur connecté est validé :
  - le panneau apparaît
  - le joueur remonte
  - le compteur global `Joueurs` suit bien le provider générique
- Le suivi multi-joueurs est encore en cours de fiabilisation
- Décision technique retenue :
  - ne plus considérer `Login request ... ?Name=...` comme source fiable du pseudo connecté
  - corréler plutôt `Netuid` / SteamID et pseudo via les lignes `FirstLoginGame`, `player ready`, `player leave world`

**Fichiers locaux non poussés à conserver hors Git :**
- `env/fix_testsoul.sh`

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

### [11] Minecraft Fabric — validation réelle du support mods
**État validé :**
- Déploiement d'une instance Fabric OK
- UI Game Commander OK
- Connexion en jeu OK avec client Java vanilla `1.21.11`
- Installation de `Vanish` via l'UI validée
- Installation automatique de `fabric-api` validée
- Redémarrage et reconnexion au monde validés

**Bug rencontré puis corrigé :**
- L'API Modrinth ne remonte pas toujours les dépendances requises d'un mod Fabric
- Dans le cas réel `Vanish`, aucune dépendance n'était retournée par l'API, alors que le JAR
  déclarait `fabric-api` dans `fabric.mod.json`

**Solution retenue :**
- Garder la résolution de dépendances Modrinth quand elles sont présentes
- Compléter par une lecture de `fabric.mod.json` dans le JAR téléchargé pour détecter les
  dépendances Fabric manquantes
- Résoudre ensuite ces dépendances par projet/version compatible avec la version Minecraft
  et le loader de l'instance

**Conclusion de contexte :**
- Le support `minecraft-fabric` est maintenant validé en conditions réelles
- La liste des joueurs Minecraft/Fabric via parsing des logs est maintenant aussi validée en réel

---

### [12] Commande `update` — mise à jour d'instance sans réinstallation
**Constat produit :**
- Les instances déployées embarquent une copie locale de l'application Flask
- Corriger le dépôt ne met donc pas à jour automatiquement les instances déjà installées

**Solution retenue :**
- Ajouter `sudo bash game_commander.sh update`
- Cette commande :
  - détecte les instances via `deploy_config.env`
  - resynchronise le runtime depuis le dépôt
  - régénère `game.json`
  - redémarre uniquement `game-commander-<instance>`
  - ne touche pas au serveur de jeu ni au monde

**Validation réelle :**
- Test effectué sur `testfabric`
- Un marqueur UI a été modifié dans le dépôt, puis propagé avec :
  - `sudo bash /home/vhserver/gc/game_commander.sh update --instance testfabric`
- Le changement est apparu en UI sans réinstallation complète

---

### [13] Sauvegardes Minecraft — périmètre ciblé validé
**Objectif retenu :**
- Sauvegarder uniquement les données utiles du monde Minecraft et les fichiers d'administration
- Ne pas archiver tout le répertoire serveur

**Périmètre validé :**
- `world/`
- `server.properties`
- `ops.json`
- `whitelist.json`
- `banned-players.json`
- `banned-ips.json`
- `usercache.json`

**Validation réelle :**
- Test effectué sur `testfabric`
- L'archive produite contient bien `world/` et les fichiers admin attendus
- Elle n'inclut pas `mods/`, `libraries/`, `logs/` ni `fabric-server-launch.jar`

**Bug connexe corrigé :**
- Le déploiement installait `unzip` mais pas `zip`, alors que tous les scripts de sauvegarde
  utilisent `zip`
- `zip` fait maintenant partie des dépendances de base

---

### [14] Terraria — validation réelle du socle deploy + commander
**État validé :**
- Déploiement d'une instance `testterraria` OK
- Téléchargement du serveur dédié officiel Terraria OK
- UI Game Commander OK
- Nginx / préfixe `/testterraria` OK
- service systemd OK
- création du monde `testterraria.wld` validée

**Bug rencontré puis corrigé :**
- Le serveur Terraria restait bloqué sur le menu interactif `Choose World:`
- L'UI remontait alors une charge CPU très élevée, qui ne correspondait pas à un serveur Terraria sain au repos

**Cause réelle :**
- Le lancement headless basé uniquement sur `-config serverconfig.txt` n'était pas suffisamment fiable ici
- Même avec `serverconfig.txt` présent, le binaire ne partait pas correctement sans paramètres explicites de monde en ligne de commande

**Solution retenue :**
- Générer `serverconfig.txt` avec un chemin de monde complet `world=/home/gameserver/.../<monde>.wld`
- Faire lire ce fichier par `start_server.sh`, puis lancer `TerrariaServer.bin.x86_64` avec :
  - `-world`
  - `-autocreate`
  - `-worldname`
  - `-difficulty`
  - `-port`
  - `-maxplayers`
  - `-motd`
  - `-logpath`
- Exécuter le lancement Terraria derrière `script -qefc ...` pour fournir un pseudo-terminal
  au process et éviter une charge CPU anormale liée au mode headless sans TTY

**Validation réelle :**
- logs observés :
  - `Listening on port 7777`
  - `Server started`
- fichier monde créé :
  - `/home/gameserver/testterraria_data/testterraria.wld`
- charge CPU observée après stabilisation :
  - environ 8% dans l'UI Game Commander

**Conclusion de contexte :**
- Le socle Terraria est maintenant validé pour :
  - installation
  - service système
  - UI Game Commander
  - création/chargement de monde headless
- La connexion client au monde n'a pas encore été testée, faute de client côté utilisateur au moment de cette validation

---

## Décisions d'architecture

### Soulmask — plan préparatoire pour la prochaine session

Le prochain jeu prévu est **Soulmask**.

Sources de travail déjà identifiées :
- https://soulmask.fandom.com/wiki/Private_Server

Constats retenus :
- installation Linux via `steamcmd` avec AppID `3017300`
- serveur dédié lancé via `StartServer.sh`
- plusieurs ports distincts sont requis :
  - `Port` UDP
  - `QueryPort` UDP
  - `EchoPort` TCP
- données/saves sous `WS/Saved`
- logs utiles sous `WS/Saved/Logs/WS.log`

Décision d'architecture prise avant implémentation :
- ne pas ajouter un simple traitement ad hoc “Soulmask = 3 ports”
- généraliser la logique de déploiement pour gérer des **groupes de ports**
  par jeu

Objectif de cette généralisation :
- chaque jeu déclare les ports qu'il utilise avec :
  - rôle
  - protocole
  - valeur par défaut
- le mode interactif vérifie le groupe complet avant validation
- si un port du groupe est occupé, le groupe entier est considéré invalide
- le mode interactif doit proposer un groupe libre cohérent
- le mode `--config` doit valider strictement sans corriger silencieusement

Abstractions envisagées :
- `deploy_port_specs_for_game`
- `deploy_check_port_group_conflicts`
- `deploy_suggest_port_group`

Exemples de modélisation visés :
- Minecraft :
  - `game_port` → `25565/tcp`
- Enshrouded :
  - `game_port` → `15636/udp`
  - `query_port` → `15637/udp`
- Soulmask :
  - `game_port` → `8777/udp`
  - `query_port` → `27015/udp`
  - `echo_port` → `18888/tcp`

Périmètre MVP Soulmask retenu pour plus tard :
- install via SteamCMD
- service systemd
- UI Game Commander
- sauvegardes
- configuration basique

Hors périmètre initial :
- mods
- joueurs connectés
- console avancée / telnet `EchoPort`
- tuning fin de `Engine.ini`

### [15] Soulmask — validation partielle du socle deploy + commander

**Validation réelle effectuée :**
- installation de l'instance `testsoul`
- déploiement du service `soulmask-server-testsoul`
- accès à l'UI Game Commander via `/testsoul`
- sauvegarde de config `soulmask_server.json`
- modification de config depuis l'UI suivie d'un redémarrage
- vérification des ports :
  - `8777/udp`
  - `27015/udp`
  - `18888/tcp`

**Bug découvert pendant la validation :**
- le wrapper Game Commander appelait `StartServer.sh` avec des flags déjà ajoutés par le script officiel
- `StartServer.sh` appelait ensuite `WSServer.sh` en rajoutant encore `-server`, `-log`, `-forcepassthrough`, `-MULTIHOME` et `-EchoPort`
- résultat :
  - arguments dupliqués
  - `ECHO_PORT` non réellement maîtrisé par Game Commander
  - comportement de redémarrage ambigu

**Correctif retenu :**
- appeler directement `WSServer.sh` depuis `start_server.sh`
- ne passer qu'un jeu d'arguments propre et explicite
- garder `-EchoPort=${ECHO_PORT}` sous contrôle côté Game Commander

**État retenu après correctif :**
- le redémarrage applique bien les changements de config
- `max_players` a été vérifié en réel après modification
- l'instance repart correctement avec les 3 ports attendus
- la charge CPU au repos reste relativement élevée et devra être réévaluée plus tard avec un vrai joueur connecté
- comportement observé en validation réelle :
  - Soulmask met nettement plus de temps à démarrer et à s'arrêter que les autres jeux déjà validés
  - un `100%` CPU juste après `start`/`restart` ne doit pas être interprété trop vite ; il faut attendre la stabilisation

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

### Nouveau mode `attach`

Décision d'architecture validée :
- ne plus limiter Game Commander au seul modèle “installer le jeu + installer Commander”
- introduire une séparation explicite entre :
  - `managed` : Game Commander gère aussi le serveur de jeu
  - `attach` : Game Commander se branche sur un service jeu existant

Validation réelle effectuée :
- un second Commander a été attaché à un service Soulmask existant
- aucun nouveau service jeu n'a été créé
- `start/stop/restart` depuis l'UI attachée pilotent bien le service existant

Contraintes retenues pour `attach` :
- conserver `GAME_SERVICE` tel que fourni
- conserver `SERVER_DIR` / `DATA_DIR` tels que fournis
- ne pas auto-décaler les ports du serveur de jeu existant
- seul le port Flask de la nouvelle UI peut être ajusté

### Commander Hub

Nouvelle direction produit validée :
- ne plus considérer les URLs d'instances (`/valheim2`, `/testsoul`, etc.) comme seule
  porte d'entrée
- exposer un hub unique `/commander`
- y lister les instances disponibles avec accès direct à leur UI

Implémentation retenue :
- pas de nouveau service Flask dédié
- génération d'une page HTML statique via `tools/nginx_manager.py`
- publication via Nginx sur `/commander`
- chargement dynamique du `statut` et du nombre de `joueurs` depuis les APIs des
  instances existantes

Conséquence doc/produit :
- le flux nominal utilisateur devient `hub -> instance`
- la doc publique doit refléter ce point d'entrée unique plutôt que l'ancien angle
  “copier des JSON runtime à la main”

### TODO Valheim UI

Point UX laissé volontairement pour plus tard :
- dans `Fichiers > Gestionnaire de fichiers`, le sélecteur de racine affiche encore
  seulement `Mondes` quand une seule racine existe
- objectif visé : supprimer ce menu déroulant dans ce cas et afficher à la place le chemin
  relatif utile du dossier de sauvegarde, par exemple `.../worlds_local`

### Valheim PlayFab — pattern SteamID réel

- Sur l'instance Valheim PlayFab réelle `valheim2`, le `SteamID` d'un joueur connecté
  n'est pas remonté via `Got connection SteamID ...`.
- Pattern réel observé dans `journalctl` :
  - `PlayFab socket with remote ID ... received local Platform ID Steam_<steamid>`
- Le parser Valheim doit donc supporter ce pattern pour rattacher le `SteamID` au nom
  du joueur et réafficher les actions `admin` / `whitelist` / `ban` dans
  `Joueurs connectés`.

### Save manager — état actuel

Le `save manager` est maintenant implémenté dans l'UI :
- navigation dans les dossiers de sauvegarde réels par jeu
- téléchargement de fichiers et de dossiers
- upload simple de fichiers dans les dossiers de save autorisés
- suppression de fichiers/sous-dossiers
- vue séparée `Backups`
- création manuelle d'un backup
- upload/download/suppression/restauration d'archives de backup
- restauration protégée par confirmation, backup préalable et restart du service si nécessaire

Séparation conceptuelle retenue :
- `backup manager`
  - gère les archives `.zip` générées dans `BACKUP_DIR`
- `save manager`
  - gère les fichiers source réels des mondes/saves côté serveur

Politique de sauvegarde actuelle à prendre en compte :
- Valheim
  - monde serveur uniquement
  - pas les personnages client
- Enshrouded
  - `savegame/`
- Minecraft Java / Fabric
  - `world/` + fichiers admin utiles
- Terraria
  - monde serveur uniquement
  - pas les personnages client
- Soulmask
  - `WS/Saved`

### Soulmask — points encore à reprendre

- valider le cas multi-joueurs réel de façon plus complète
  - plusieurs connexions simultanées
  - départ d'un seul joueur
  - cohérence durable de la liste joueurs
- mieux documenter le profil CPU/RAM en charge réelle
- homogénéiser à terme la structure relative des nouveaux zips de backup

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
| amp-enshrouded-01 (AMP) | Enshrouded | 15636/UDP 15637/UDP | — | — |
| amp-valheim-01 (AMP) | Valheim | — | — | — |

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

## Milestone v2.3

Jalon de stabilisation retenu avant le gros chantier de refonte UI / thèmes.

État validé à ce stade :
- mode `attach` validé en réel
- hub `/commander` en place comme point d'entrée principal
- `save manager` ajouté à l'UI
- liste des backups avec téléchargement, restauration et suppression
- sauvegarde manuelle depuis l'UI
- upload simple des fichiers de save
- upload dédié des backups
- backup automatique avant restauration
- suppression de fichiers/dossiers de save
- Soulmask validé pour UI, backups/restauration et suivi joueurs de base
- Valheim amené à un niveau produit de référence pour les autres jeux :
  - `Configuration` fusionnée avec l'ancien onglet monde
  - sélection de monde actif
  - `World Modifiers`
  - BetterNetworking si installé
  - gestionnaire de fichiers sur `worlds_local`
  - actions joueurs `admin / whitelist / ban`
  - panneaux `adminlist.txt / bannedlist.txt / permittedlist.txt`
  - prise en compte du pattern PlayFab réel pour le `SteamID`

Point explicitement repoussé après ce jalon :
- refonte transversale UI/CSS/thèmes/accessibilité

## Roadmap post-v2.3

Priorités retenues après le gel `v2.3` :
- laisser vivre la bêta test sur Valheim et Minecraft, puis traiter les régressions au fil de l'eau
- propager ensuite le standard produit Valheim vers :
  - Terraria
  - Enshrouded
- garder Soulmask sur son socle actuel tant qu'aucun besoin produit plus précis ne remonte des tests
- continuer la rationalisation du hub `/commander` et conserver un polling de statut indépendant de l'auth par instance
- poursuivre la refonte UI/CSS/accessibilité par petites passes, sans casser le socle validé

## Terraria — montée au standard produit vanilla

Validé en réel sur l'instance `terraria` :
- déploiement corrigé avec vrai `start_server.sh` fonctionnel
- protocole de port corrigé côté résumé de déploiement (`TCP`)
- `Configuration` restructurée en sections
- options avancées `serverconfig.txt` exposées
- sélection de monde actif via les `.wld`
- `Joueurs connectés` opérationnel
- bannissement vanilla fonctionnel depuis le Commander

Point important retenu :
- pour Terraria vanilla, le bannissement fiable ne peut pas être modélisé comme une simple liste de pseudos
- il faut corréler les logs :
  - `<ip>:<port> is connecting...`
  - `<name> has joined.`
- puis écrire une entrée `nom + IP` dans `banlist.txt`

Conséquence produit :
- `banlist` : oui
- `admin` / `whitelist` : non en vanilla
- si un jour on veut ce niveau, il faudra traiter `TShock` comme un produit Terraria distinct

## Terraria TShock — note pour plus tard

Audit produit retenu :
- `TShock` ne doit pas être traité comme un simple mod Terraria
- il faut le modéliser comme un jeu/variant séparé, sur le modèle `Minecraft` / `Minecraft Fabric`
- les releases Linux officielles existent, donc un vrai `deploy` automatique est envisageable

Décision prise :
- ne pas attaquer `terraria-tshock` maintenant
- garder cette piste pour plus tard comme produit distinct :
  - `terraria`
  - `terraria-tshock`

## Prochaine cible produit

Après la stabilisation actuelle, la prochaine cible retenue n'est plus `Terraria TShock` mais `Satisfactory`.

## Satisfactory — baseline produit validée

Premier socle validé en réel :
- `deploy` / `update` connaissent maintenant `satisfactory`
- AppID SteamCMD : `1690800`
- binaire attendu : `FactoryServer.sh`
- les données d'instance sont isolées dans `DATA_DIR` via `HOME` / `XDG_CONFIG_HOME`
- le `save manager` pointe sur :
  - `.config/Epic/FactoryGame/Saved/SaveGames`
- les backups prennent ce dossier `SaveGames` complet

Points produit validés ensuite :
- le serveur doit être lancé avec :
  - port jeu
  - `ReliablePort`
- le port fiable est indispensable au join ; le simple claim ne suffit pas à valider la connectivité
- le produit rappelle maintenant explicitement les ports à ouvrir à la fin du déploiement
- le claim et l'administration passent par l'API HTTPS native du serveur
- les actions suivantes sont validées dans le Commander :
  - statut du claim
  - revendiquer le serveur
  - changer le mot de passe admin
  - définir/supprimer le mot de passe joueur
  - renommer le serveur
- le panneau `Serveur revendiqué` expose maintenant aussi :
  - nom actuel du serveur quand l'API l'expose
  - session active si disponible
  - bouton de lecture authentifiée des infos serveur via mot de passe admin

Limites restantes :
- pas encore de suivi joueurs
- pas encore de panneau gameplay avancé
- le nom du serveur n'est pas forcément lisible sans authentification admin

## [2026-03-20] Satisfactory — validation réelle du déploiement Hub

Validation effectuée sur l'instance `satisfactory`.

État retenu :
- déploiement Hub réussi après correction du chargement des métadonnées jeu dans le flux `deploy --config`
- instance enregistrée avec :
  - `GAME_ID=satisfactory`
  - `INSTANCE_ID=satisfactory`
  - `SERVER_PORT=7777`
  - `QUERY_PORT=8888`
  - `URL_PREFIX=/satisfactory`
  - `FLASK_PORT=5007`
- service jeu actif :
  - `satisfactory-server-satisfactory`
- service Commander actif :
  - `game-commander-satisfactory`
- l'instance répond localement :
  - `/satisfactory` redirige vers login
  - `/satisfactory/api/hub-status` répond avec `state=20`

Validation API Satisfactory native :
- le serveur est bien revendiqué :
  - `PasswordlessLogin` renvoie `passwordless_login_not_possible`
- l'auth admin native est valide avec le mot de passe configuré
- les lectures authentifiées `QueryServerState` / `GetServerOptions` répondent correctement

Observation produit retenue :
- le serveur est bien déployé, démarré et administrable
- la création/initialisation concrète de la vraie session de jeu reste finalisée au premier passage côté client en jeu
- ne pas traiter cet état initial (`activeSessionName` auto-généré, `isGameRunning=false` avant vraie entrée en jeu) comme un échec de déploiement

## Hub Admin — séparation des rôles

Le hub `/commander` n'est plus une simple page statique nginx :
- c'est maintenant un Flask séparé, distinct des Commanders d'instance
- auth dédiée avec son propre `users.json`
- cible : admin hôte, pas admin jeu

Premier périmètre validé :
- vue lecture seule globale
- monitor CPU et détail de répartition
- gestion des comptes Hub
- premières actions d'exploitation :
  - `start`
  - `stop`
  - `restart`
  - `update --instance`
  - `rebalance`
  - `redéployer` une instance depuis son `deploy_config.env`
  - `désinstaller` une instance depuis le Hub avec confirmation forte

## Milestone v3.0

Jalon retenu pour démarrer la rationalisation d'architecture sans réécriture globale.

État figé à ce stade :
- le standard produit est maintenant bon sur :
  - Valheim
  - Minecraft Java / Fabric
  - Terraria vanilla
  - Soulmask (socle propre)
  - Enshrouded (socle + gameplay)
  - Satisfactory (baseline exploitable + claim/admin)
- `/commander` est devenu un vrai `Hub Admin` séparé
- les rôles `admin hôte` et `admin d'instance` sont désormais distincts dans le produit
- les premières actions hôte sont disponibles depuis le Hub

Direction validée pour `v3.0` :
- garder `bash` pour la couche hôte/provisioning Linux
- migrer progressivement la logique métier et l'orchestration vers `python`
- formaliser un contrat commun par jeu
- poursuivre le Hub Admin comme surface de pilotage principale côté hôte

## Hub Admin + refacto v3.0 — validation réelle des premiers déploiements Hub

Validation réelle supplémentaire atteinte :
- le Hub sait maintenant déclencher un vrai `deploy` d'instance via un formulaire minimal
- premier test réel effectué sur `minecraft2`

Bugs rencontrés puis corrigés pendant cette validation :
- le Hub n'avait pas encore la permission sudoers pour `deploy-instance`
- le CLI hôte faisait encore un `sudo` imbriqué inutile pendant le chemin `deploy-instance`
- le `deploy_config.env` écrit à la fin du déploiement repartait des valeurs par défaut au lieu des vraies valeurs du déploiement en cours
  - conséquence observée :
    - validation finale incohérente (`Service -server- : inactif`)
    - relecture future du `deploy_config.env` cassée
- un `deploy --config` invalide pouvait retomber sur le flux interactif et repartir sur `Valheim`
  - désormais, le flux échoue explicitement si `GAME_ID` ou `INSTANCE_ID` manquent
- une instance partielle visible dans le manifest/nginx mais sans `deploy_config.env` valide ne pouvait pas être désinstallée depuis le Hub
  - désormais, le Hub sait reconstruire un minimum d'informations pour supprimer proprement ce type d'instance partielle
- la console globale du Hub capturait les séquences ANSI brutes (`[0;32m`, etc.)
  - elles sont maintenant nettoyées avant écriture dans `hub-actions.log`

Conséquence produit validée :
- l'instance partielle `minecraft2` a été supprimée proprement depuis le Hub
- le nettoyage a bien retiré :
  - services systemd
  - entrée nginx/manifest
  - répertoires serveur/app/backups
- l'instance existante `valheim-main` n'a pas été corrompue par ce test raté

État retenu en fin de séance :
- `valheim-main` validée intacte
- `enshrouded2` désinstallée proprement ensuite
- Hub Admin + console globale + actions hôte = base désormais suffisamment robuste pour reprendre la refacto du `deploy` le lendemain

## Bootstrap Hub Admin sur serveur vierge

Lot poussé :
- `bootstrap-hub` a été ajouté comme point d'entrée explicite pour installer seulement le Hub Admin
- un script `install_hub.sh` a aussi été ajouté pour préparer un futur flux `curl | bash`
- le README documente maintenant ce bootstrap minimal côté Ubuntu

Validation actuelle :
- syntaxe shell OK
- helpers Python OK
- suite `tools/test_tools.py` OK
- suite `tools/test_modularization.sh` OK
- le README public n'expose plus de mot de passe statique pour le bootstrap Hub
- le formulaire de déploiement Hub n'affiche plus de mots de passe par défaut visibles

Note d'exploitation importante :
- le Hub Admin reste singleton par machine
- un test de bootstrap avec un autre utilisateur système sur le même serveur (ex. `codex` au lieu de `vhserver`) n'est pas une cohabitation parallèle
- cela remappe les mêmes ressources globales :
  - service `game-commander-hub`
  - sudoers du Hub
  - intégration nginx partagée
- donc le vrai test `curl | bash` doit se faire :
  - soit sur une machine vierge
  - soit en acceptant de remplacer temporairement le Hub déjà en place

Prochaines priorités après ce gel :
- refactoriser les actions hôte (`deploy`, `attach`, `update`, `uninstall`, `rebalance`) pour réduire la logique shell
- documenter et stabiliser le contrat commun par jeu
- continuer l'enrichissement ciblé de `Satisfactory`
- revenir ensuite sur `Enshrouded` (`rôles / accès`, `bannis`)

## Note locale testsoul

Le script non suivi [env/fix_testsoul.sh](/home/vhserver/gc/env/fix_testsoul.sh) est un utilitaire de dépannage local pour `testsoul` :
- il régénère manuellement `start_server.sh` à partir de `soulmask_server.json`
- il redémarre `soulmask-server-testsoul`
- il affiche ensuite l'état systemd et le process Soulmask

Ce script n'est pas une partie produit et doit rester hors Git sauf demande explicite.
Inutile de le rappeler systématiquement à chaque push ; ne le mentionner que s'il devient pertinent pour la tâche en cours.
