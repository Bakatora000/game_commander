# BUGS.md — Game Commander
> Tracker de bugs, solutions essayées, et régressions connues.
> Mettre à jour dès qu'un bug est rencontré ou résolu.

---

## Format d'entrée

```
### [ID] Titre court
- **Statut :** Résolu | En cours | Connu
- **Composant :** script / core / frontend / nginx / systemd
- **Instance(s) affectée(s) :** valheim8, enshrouded2, etc.
- **Symptôme :** Ce que l'utilisateur observe
- **Cause racine :** Ce qui le provoque réellement
- **Solutions essayées :**
  - ❌ Tentative échouée ou régression
  - ✅ Solution retenue
- **Régression connue :** Ce qu'il ne faut PAS faire
```

---

## Bugs résolus

### [19] Satisfactory — connexion impossible tant que le `ReliablePort` n'était pas correctement modélisé
- **Statut :** Résolu
- **Composant :** `lib/deploy_steps.sh` + support `satisfactory`
- **Instance(s) affectée(s) :** `satisfactory`
- **Symptôme :**
  - claim du serveur possible
  - mais connexion joueur impossible ou instable
  - puis erreurs du type `Failed to connect to the server API`
- **Cause racine :**
  - le support initial traitait le second port comme un pseudo port `admin/query`
  - alors que Satisfactory attend un vrai `ReliablePort`
  - et ce port doit aussi être ouvert côté firewall
- **Solutions essayées :**
  - ❌ raisonner uniquement avec le port jeu
  - ❌ présenter le second port comme un simple port admin
  - ✅ lancer le serveur avec `-ReliablePort=...`
  - ✅ rappeler explicitement à la fin du déploiement que ce port doit être ouvert
- **Régression connue :** Pour Satisfactory, ne pas traiter le second port comme un détail facultatif ; sans `ReliablePort` correctement configuré et ouvert, le join n'est pas fiable.

### [20] Hub Admin — le Hub dépendait trop des logins d'instance et mélangeait les rôles
- **Statut :** Résolu
- **Composant :** `runtime_hub/*`
- **Instance(s) affectée(s) :** global
- **Symptôme :**
  - `/commander` devenait une interface d'exploitation hôte
  - mais sans modèle d'auth/permissions vraiment distinct de celui des Commanders d'instance
- **Cause racine :**
  - le Hub était historiquement pensé comme un simple point d'entrée/landing page
  - alors que son périmètre produit a évolué vers un vrai rôle `admin hôte`
- **Solutions essayées :**
  - ❌ conserver une simple page agrégée sans auth dédiée
  - ✅ créer un Flask Hub séparé avec son propre `users.json`
  - ✅ introduire des permissions Hub dédiées
  - ✅ commencer à exposer les actions hôte depuis ce Hub
- **Régression connue :** Ne pas redonner au Hub un comportement dépendant des comptes d'instance ; l'admin hôte et l'admin jeu doivent rester séparés.

### [17] Terraria — bannir un joueur via le Commander n'empêchait pas la reconnexion
- **Statut :** Résolu
- **Composant :** `runtime/games/terraria/admins.py` + `runtime/games/terraria/players.py`
- **Instance(s) affectée(s) :** `terraria`
- **Symptôme :**
  - Le bouton `Bannir` ajoutait bien une entrée visible dans l'UI
  - mais le joueur pouvait se reconnecter après redémarrage du serveur
- **Cause racine :**
  - En vanilla Terraria, écrire seulement le pseudo dans `banlist.txt` ne suffit pas
  - la banlist utile doit stocker le nom **et** l'IP du joueur
  - le Commander ne corrélait initialement que le nom, pas l'IP
- **Solutions essayées :**
  - ❌ Écrire uniquement le pseudo dans `banlist.txt`
  - ✅ Corréler les lignes de logs :
    - `<ip>:<port> is connecting...`
    - `<name> has joined.`
  - ✅ Stocker ensuite une entrée valide `// <name>` + `<ip>` dans `banlist.txt`
  - ✅ Afficher aussi l'IP dans le panneau `Joueurs bannis`
- **Régression connue :** Pour Terraria vanilla, ne pas modéliser la banlist comme une simple liste de pseudos.

### [18] Terraria — reconnexions dupliquées dans `Joueurs connectés`
- **Statut :** Résolu
- **Composant :** `runtime/games/terraria/players.py`
- **Instance(s) affectée(s) :** `terraria`
- **Symptôme :**
  - après `join -> left -> join`, le même joueur apparaissait en double
  - une ligne supplémentaire était ajoutée à chaque reconnexion
- **Cause racine :**
  - le parser conservait une trace d'ordre historique des connexions, au lieu de reconstruire strictement l'ensemble courant des joueurs connectés
- **Solutions essayées :**
  - ❌ Conserver un tableau d'ordre puis filtrer après coup
  - ✅ Recalculer la liste finale uniquement à partir des joueurs encore présents dans l'état courant
- **Régression connue :** Pour les jeux basés sur un parser de logs, toujours reconstruire l'état final courant, pas l'historique de toutes les connexions.

### [16] Valheim PlayFab — `SteamID` absent de la liste joueurs malgré un joueur connecté
- **Statut :** Résolu
- **Composant :** `runtime/games/valheim/players.py`
- **Instance(s) affectée(s) :** `valheim2`
- **Symptôme :**
  - Le panneau `Joueurs connectés` affiche bien le nom du joueur
  - mais aucun `SteamID` n'est rattaché au joueur
  - donc les actions `Ajouter admin`, `Whitelister`, `Bannir` n'apparaissent pas
- **Cause racine :**
  - Sur une instance Valheim PlayFab réelle, le `SteamID` n'était pas logué via
    `Got connection SteamID ...`
  - Le pattern utile observé était :
    `PlayFab socket with remote ID ... received local Platform ID Steam_<steamid>`
- **Solutions essayées :**
  - ❌ Se baser uniquement sur `Got connection SteamID ...`
  - ✅ Supporter aussi le pattern PlayFab `local Platform ID Steam_<steamid>`
  - ✅ Gérer aussi le cas où le nom du personnage et le `SteamID` arrivent dans un ordre inversé
- **Régression connue :** Pour Valheim PlayFab, ne pas supposer que `SteamID` remonte toujours via `Got connection SteamID ...`.

### [15] Soulmask — suivi des joueurs encore irrégulier selon les patterns de logs
- **Statut :** En cours
- **Composant :** `runtime/games/soulmask/players.py`
- **Instance(s) affectée(s) :** `testsoul`
- **Symptôme :**
  - Le panneau `Joueurs connectés` peut être vide alors qu'un joueur est en ligne
  - Des noms incohérents peuvent apparaître si l'on se base sur les premières lignes de login
  - Le cas multi-joueurs n'est pas encore considéré comme fiable
- **Cause racine :**
  - Soulmask n'émet pas un pattern unique et stable pour toute la séquence de connexion
  - `Login request ... ?Name=...` ne représente pas forcément le nom final à afficher
  - Les logs utiles sont répartis entre `FirstLoginGame`, `player ready`, `Join succeeded`, `player leave world`
- **Solutions essayées :**
  - ❌ Utiliser `Login request` comme source directe du pseudo connecté
  - ❌ Fallback simple "s'il n'y a qu'un joueur, le retirer sur fermeture générique" — insuffisant pour le multi-joueurs
  - ✅ Orienter le parser vers une corrélation `Netuid/SteamID <-> pseudo`
  - ✅ Utiliser `player leave world. <steamid>` comme signal de sortie plus fiable
- **Régression connue :** Ne pas considérer le support multi-joueurs Soulmask comme totalement validé tant que la corrélation SteamID/pseudo n'est pas stabilisée sur plusieurs cas réels.

### [14] Terraria — serveur bloqué sur `Choose World:` et CPU à 100%
- **Statut :** Résolu
- **Composant :** `lib/deploy_steps.sh` + `tools/config_gen.py`
- **Instance(s) affectée(s) :** `testterraria`
- **Symptôme :**
  - Le service Terraria démarre, mais les logs montrent seulement le menu interactif `n New World`, `d <number> Delete World`, puis `Choose World:`
  - L'UI Game Commander affiche une charge CPU très élevée, proche de 100%, sans joueur connecté
- **Cause racine :**
  - Le serveur dédié Terraria ne démarrait pas réellement en mode headless exploitable
  - S'appuyer uniquement sur `-config serverconfig.txt` n'était pas suffisant ici
  - Tant que le monde n'était pas explicitement passé au binaire, le serveur retombait sur son menu interactif et bouclait
- **Solutions essayées :**
  - ❌ Générer seulement `worldpath`, `worldname`, `autocreate` dans `serverconfig.txt`
  - ❌ Ajouter uniquement `world=/.../testterraria.wld` dans `serverconfig.txt`
  - ❌ Lancer directement `TerrariaServer.bin.x86_64` sous systemd sans pseudo-terminal — charge CPU encore anormalement élevée
  - ✅ Générer `world=/.../<nom>.wld` dans `serverconfig.txt`
  - ✅ Faire démarrer `TerrariaServer.bin.x86_64` avec les paramètres critiques directement en ligne de commande via `start_server.sh` (`-world`, `-autocreate`, `-worldname`, `-difficulty`, `-port`, `-maxplayers`, `-motd`, `-logpath`)
  - ✅ Fournir un pseudo-terminal via `script -qefc ...` dans le wrapper systemd Terraria
  - ✅ Validation réelle effectuée : création du fichier `testterraria.wld`, log `Listening on port 7777`, puis `Server started`, avec charge observée redescendue autour de 8% dans l'UI
- **Régression connue :** Ne pas considérer `-config serverconfig.txt` seul comme suffisamment fiable pour un lancement headless automatique de Terraria.

### [11] Minecraft Java — erreur "Incompatible client" après déploiement réussi
- **Statut :** Résolu
- **Composant :** `lib/deploy_steps.sh` + `tools/config_gen.py`
- **Symptôme :** Le serveur Minecraft Java démarre correctement et l'UI Game Commander fonctionne, mais le client affiche `Failed to connect. Incompatible client!` si le launcher est resté sur une ancienne version.
- **Cause racine :**
  - Le déploiement télécharge le dernier `server.jar` vanilla disponible.
  - Le launcher Minecraft Java peut rester sur une version précédente du client.
- **Solutions essayées :**
  - ❌ Tenter la connexion avec un client Java resté sur `1.21` alors que le serveur installé était plus récent
  - ✅ Lancer la bonne version Java depuis le launcher, alignée sur celle demandée par le serveur
- **Régression connue :** Pour Minecraft Java, vérifier la version exacte du client avant de conclure à un bug de réseau ou de déploiement.

### [12] Minecraft Fabric — dépendances Modrinth requises non installées après ajout d'un mod
- **Statut :** Résolu
- **Composant :** `runtime/games/minecraft_fabric/mods.py`
- **Instance(s) affectée(s) :** `testfabric`
- **Symptôme :**
  - Après installation de `Vanish` depuis l'UI puis redémarrage, le serveur Fabric ne redémarre pas correctement.
  - Les logs indiquent que `fabric-api` manque alors que le mod installé en dépend.
  - Le dossier `mods/` ne contient que `vanish-1.6.6+1.21.11.jar`.
- **Cause racine :**
  - L'API Modrinth ne remonte pas toujours les dépendances requises d'un mod Fabric.
  - Dans le cas réel `Vanish`, aucune dépendance n'était exposée via l'API, alors que le JAR déclarait bien `fabric-api` dans `fabric.mod.json`.
- **Solutions essayées :**
  - ❌ Installer `Vanish` seul puis redémarrer — boucle d'échec Fabric avec message `requires any version of fabric-api, which is missing`
  - ❌ Première implémentation basée uniquement sur les dépendances de l'API Modrinth — insuffisante en validation réelle
  - ✅ Lire aussi les dépendances déclarées dans `fabric.mod.json` après téléchargement du JAR
  - ✅ Résoudre les dépendances manquantes par slug/projet Modrinth compatible avec la version Minecraft/loader de l'instance
  - ✅ Validation réelle effectuée : installation de `Vanish` sur `testfabric`, téléchargement automatique de `fabric-api`, redémarrage OK et connexion en jeu réussie
- **Régression connue :** Pour Fabric, ne pas supposer que l'API Modrinth suffit à décrire toutes les dépendances ; le manifeste `fabric.mod.json` du JAR doit rester une source de vérité complémentaire.

### [13] Sauvegardes Minecraft — échec `zip: command not found`
- **Statut :** Résolu
- **Composant :** `lib/deploy_steps.sh`
- **Instance(s) affectée(s) :** `testfabric`
- **Symptôme :** Le script `backup_minecraft-fabric.sh` échoue avec `zip: command not found` alors que l'installation et l'instance sont correctes.
- **Cause racine :**
  - Le déploiement installait `unzip`, mais pas `zip`
  - Tous les scripts de sauvegarde utilisent pourtant `zip` pour créer les archives
- **Solutions essayées :**
  - ❌ Installer `zip` manuellement sur le serveur pour débloquer le test
  - ✅ Ajouter `zip` aux dépendances de base installées à l'étape 3
  - ✅ Validation réelle effectuée ensuite sur `testfabric`, avec archive créée correctement
- **Régression connue :** Ne pas considérer le pipeline de sauvegarde fonctionnel si `zip` n'est pas installé par défaut.

### [9] Enshrouded — serveur invisible si seuls les ports game/query contigus sont ouverts
- **Statut :** Résolu
- **Composant :** `tools/config_gen.py` + `games/enshrouded/config.py`
- **Symptôme :** Le serveur Enshrouded démarre, l'UI Game Commander fonctionne, mais le serveur n'apparaît pas dans le jeu si l'on cherche `IP:queryPort` attendu.
- **Cause racine :**
  - La génération de `enshrouded_server.json` reposait sur un ancien schéma.
  - Le format actuel du jeu stocke le mot de passe dans `userGroups[*].password`.
  - Le `queryPort` est le port pertinent pour la découverte du serveur ; avec un port de base mal choisi, on tombait hors de la plage firewall ouverte.
- **Solutions essayées :**
  - ❌ Déployer une instance Enshrouded avec `SERVER_PORT=15639` alors que seuls `15636-15639` étaient ouverts côté firewall — le `queryPort` réel devient `15640`, donc serveur non visible
  - ✅ Corriger la génération de `enshrouded_server.json` pour le format actuel du jeu
  - ✅ Utiliser `SERVER_PORT=15638` pour obtenir `queryPort=15639` quand la plage ouverte est `15636-15639`
  - ✅ Lire/écrire le mot de passe via `userGroups[*].password` côté génération et côté UI config
- **Régression connue :** Pour Enshrouded, raisonner avec `gamePort = SERVER_PORT` et `queryPort = SERVER_PORT + 1`. Si le firewall n'ouvre que jusqu'à `15639`, il faut utiliser `SERVER_PORT=15638` et non `15639`.

---

### [10] Uninstall — faux positif sur les processus orphelins pour Enshrouded sous Wine
- **Statut :** Résolu
- **Composant :** `lib/uninstall_orphans.sh`
- **Symptôme :** Lors de la désinstallation d'une autre instance, l'étape "Processus orphelins en mémoire" propose à tort le process `enshrouded_server.exe` d'une instance encore active et gérée par systemd.
- **Cause racine :**
  - Le scan des orphelins excluait seulement les `MainPID` systemd.
  - Enshrouded sous Wine fait tourner le vrai serveur comme process enfant dans le cgroup du service systemd, pas nécessairement comme `MainPID`.
- **Solutions essayées :**
  - ❌ Se baser uniquement sur `MainPID` — faux positif sur `enshrouded_server.exe`
  - ✅ Exclure tout process encore rattaché à une unité `*.service` via `/proc/<pid>/cgroup`
- **Régression connue :** Ne jamais proposer comme "orphelin" un process encore contenu dans un cgroup systemd de service actif.

### [1] wine64 absent du PATH après installation (Ubuntu 24.04)
- **Statut :** Résolu
- **Composant :** `game_commander.sh` — section install dépendances
- **Symptôme :** `wine64: not found` dans journalctl malgré `apt install wine64`
- **Cause racine :** Le paquet `wine64` sur Ubuntu 24.04 installe les libs (`/usr/lib/wine/wine64`) mais ne crée pas de binaire dans le PATH.
- **Solutions essayées :**
  - ✅ Après `apt install wine64`, vérifier si `wine64` est dans le PATH ; sinon créer un symlink :
    ```bash
    ln -sf "$(command -v wine)" /usr/local/bin/wine64
    # ou si wine n'est pas non plus dans le PATH :
    ln -sf /usr/lib/wine/wine64 /usr/local/bin/wine64
    ```
- **Régression connue :** Ne pas supposer que `apt install wine64` suffit — toujours vérifier `which wine64` après installation.

---

### [2] Injection Nginx dans le mauvais bloc server (HTTP au lieu de SSL)
- **Statut :** Résolu
- **Composant :** ancien flux Nginx inline, aujourd'hui migré vers `tools/nginx_manager.py`
- **Symptôme :** Bloc `location /instance` injecté dans `server { listen 80 }` qui contient un `return 404` — les requêtes HTTPS ne le voient jamais.
- **Cause racine :** Le code Python utilisait `content.rfind('}')` qui cible la dernière `}` du fichier, qui est celle du bloc HTTP redirect, pas du bloc SSL.
- **Solutions essayées :**
  - ❌ `rfind('}')` — cible le mauvais bloc server
  - ✅ Cibler explicitement le bloc SSL : chercher `listen 443 ssl`, remonter au `server {` parent, compter les accolades pour trouver la `}` fermante du bon bloc, injecter juste avant.
- **Régression connue :** Ne jamais utiliser `rfind('}')` dans un fichier Nginx multi-blocs.
- **Note architecture (2026-03) :** Le déploiement courant n'injecte plus chaque instance directement dans le vhost partagé. Il passe par `tools/nginx_manager.py`, un manifest (`/etc/nginx/game-commander-manifest.json`) et un fichier généré (`/etc/nginx/game-commander-locations.conf`) inclus dans le bloc SSL. Ce bug reste pertinent pour la migration initiale et les chemins legacy.

---

### [3] SERVER_PASSWORD corrompu dans les heredocs Python
- **Statut :** Résolu
- **Composant :** `game_commander.sh` — génération `enshrouded_server.json`
- **Symptôme :** `enshrouded_server.json` généré avec un mot de passe incorrect ou vide.
- **Cause racine :**
  - Cause 1 : Mot de passe interpolé directement dans un heredoc bash → caractères spéciaux (`\`, `"`, `$`) corrompaient le code Python silencieusement.
  - Cause 2 : Sur redéploiement `--config`, `SERVER_PASSWORD` est vide (non sauvegardé dans `.env`) → fichier écrasé avec mot de passe vide.
- **Solutions essayées :**
  - ❌ Interpolation directe dans heredoc — corrompt les mots de passe avec caractères spéciaux
  - ✅ Passer les valeurs via variables d'environnement + heredoc `'PYEOF'` (guillemets simples = pas d'interpolation bash)
  - ✅ Récupérer le mot de passe existant dans `enshrouded_server.json` si `SERVER_PASSWORD` est vide lors d'un redéploiement.
- **Régression connue :** Ne jamais interpoler de mots de passe dans des heredocs bash.

---

### [4] pkill -f "enshrouded" tue les instances AMP
- **Statut :** Résolu — RÈGLE ABSOLUE
- **Composant :** Toute commande shell sur ce serveur
- **Symptôme :** `pkill -f "enshrouded"` tue aussi `Test01` (instance AMP Enshrouded).
- **Cause racine :** `pkill -f` matche sur la ligne de commande complète — les instances AMP et Game Commander partagent le même binaire.
- **Solutions essayées :**
  - ❌ `pkill -f "enshrouded"` — tue TOUTES les instances Enshrouded du serveur
  - ✅ Stopper uniquement via systemd :
    ```bash
    systemctl disable --now <service>
    systemctl kill -s SIGKILL <service>
    ```
- **⚠️ Régression connue :** Ne **jamais** utiliser `pkill -f "enshrouded"` ni aucun `pkill` générique sur ce serveur. Les instances AMP tournent en parallèle.

---

### [5] Métriques CPU/RAM incorrectes pour Enshrouded (Wine)
- **Statut :** Résolu
- **Composant :** `runtime/core/server.py` — collecte métriques psutil
- **Symptôme :** CPU affiché à 0%, RAM à 2–32 MB alors que l'usage réel est ~20–60% CPU et ~1.5 GB RAM.
- **Cause racine :** Wine re-parente `enshrouded_server.exe` hors de l'arbre systemd.
  - `MainPID` systemd = `xvfb-run` (wrapper léger)
  - `children(recursive=True)` ne trouve pas `enshrouded_server.exe` re-parenté
  - La cmdline Wine utilise le format `Z:\home\gameserver\...` pas `/home/gameserver/...`
- **Solutions essayées :**
  - ❌ Lookup par `binary` seul — ne matche pas `enshrouded_server.exe` sous Wine
  - ❌ `children(recursive=True)` depuis MainPID — manque les process re-parentés
  - ✅ Fallback via `systemctl show --property=MainPID` si binaire non trouvé
  - ✅ Scanner tous les process dont la cmdline contient `install_dir` OU son équivalent Wine `Z:\home\gameserver\enshrouded2_server`
  - ✅ Sommer CPU+RAM de tout l'arbre (proc principal + enfants + process re-parentés)
  - ✅ Filtrer **uniquement** par `install_dir` (pas par `binary`) pour ne pas capturer l'instance AMP Enshrouded
- **Régression connue :** Filtrer par nom de binaire seul est insuffisant pour les jeux Wine.

---

### [6] Uninstall Nginx supprime le fichier de conf entier si vhost partagé
- **Statut :** Résolu
- **Composant :** ancien flux uninstall inline, aujourd'hui remplacé prioritairement par manifest Nginx
- **Symptôme :** L'uninstall proposait de supprimer `/etc/nginx/conf.d/gaming.example.com.conf` entier, cassant toutes les autres instances sur ce domaine.
- **Cause racine :** La logique de suppression ne distinguait pas fichier dédié vs fichier partagé multi-instances.
- **Solutions essayées :**
  - ❌ Suppression totale du fichier Nginx — casse toutes les autres instances
  - ✅ Compter les blocs `location` dans le fichier :
    - Si ≤ 2 blocs et que c'est notre instance → proposer suppression totale
    - Si fichier partagé → retirer uniquement le bloc `location /instance` via Python regex
- **Régression connue :** Ne jamais supprimer le fichier Nginx sans vérifier qu'il n'est pas partagé.
- **Note architecture (2026-03) :** Le chemin nominal d'uninstall retire désormais l'instance du manifest puis régénère `game-commander-locations.conf`. La suppression inline reste un fallback pour les installations plus anciennes.

---

### [7] Métriques — graphe vide durant les périodes de downtime
- **Statut :** Résolu
- **Composant :** `runtime/core/metrics.py` — thread de polling
- **Symptôme :** Le graphe s'arrête net à l'heure d'arrêt, pas de visualisation du downtime.
- **Cause racine :** Le poller n'enregistrait des points que si `state == 20` (serveur en ligne).
- **Solutions essayées :**
  - ❌ Ne logger que quand `state == 20` — crée des trous invisibles dans le graphe
  - ✅ Enregistrer des points à `cpu=0 / ram=0 / players=0 / state=0` même quand le serveur est arrêté.
- **Régression connue :** Ne pas conditionner l'écriture de métriques à l'état du serveur.

---

### [8] Valheim — conflit Steam entre deux instances sur la même machine
- **Statut :** Résolu
- **Composant :** `runtime/game_valheim.json` — flags de démarrage du serveur
- **Symptôme :** `Steam is not initialized` / `Awake of network backend failed` au démarrage d'une deuxième instance Valheim.
- **Cause racine :** Le flag `-vanilla` tente d'initialiser Steam localement, ce qui entre en conflit avec l'instance AMP Valheim (CauchemarCommu01) déjà active.
- **Solutions essayées :**
  - ❌ `-vanilla` — conflit Steam si une autre instance Valheim tourne
  - ✅ `-playfab` (crossplay PlayFab) — n'initialise pas Steam localement, pas de conflit
- **Régression connue :** Ne jamais utiliser `-vanilla` sur une machine hébergeant déjà une instance Valheim avec Steam.

---

## Bugs connus / non résolus

### [16] Soulmask — suivi multi-joueurs à revalider en conditions réelles
- **Statut :** Ouvert
- **Composant :** `runtime/games/soulmask/players.py`
- **Symptôme :**
  - le cas simple 1 joueur est validé
  - la remontée des noms dépend encore de logs parfois tardifs ou irréguliers
  - le cas de plusieurs joueurs simultanés reste à revalider en réel
- **État actuel :**
  - la liste joueurs est exploitable pour un usage simple
  - le vrai test restant est la cohérence sur connexions/déconnexions partielles en multi

---

### [15] Soulmask — lancement avec flags dupliqués et redémarrage instable
- **Statut :** Résolu
- **Composant :** `lib/deploy_steps.sh` — génération de `start_server.sh`
- **Symptôme :**
  - Le déploiement Soulmask fonctionne et l'UI est accessible.
  - Après modification de config puis redémarrage, le serveur peut sembler repartir de façon sale ou garder une charge CPU anormale.
  - `ECHO_PORT` n'est pas réellement maîtrisé par la config Game Commander.
- **Cause racine :**
  - Le wrapper appelait `StartServer.sh` avec des flags que le script officiel rajoute déjà lui-même.
  - `StartServer.sh` lance ensuite `WSServer.sh` avec :
    - `-server`
    - `-log`
    - `-UTF8Output`
    - `-MULTIHOME=0.0.0.0`
    - `-EchoPort=18888`
    - `-forcepassthrough`
  - Résultat : duplication de plusieurs flags et `EchoPort` forcé en dur.
- **Correctif retenu :**
  - Ne plus appeler `StartServer.sh` depuis le wrapper Game Commander.
  - Appeler directement `WSServer.sh Level01_Main -server ...`
  - Passer un ensemble d'arguments propre, sans doublons, avec `-EchoPort=${ECHO_PORT}` contrôlé par la config d'instance.
- **État après correction :**
  - Redémarrage validé en réel.
  - `max_players` modifié depuis l'UI puis appliqué après restart.
  - Ports Soulmask remontés correctement :
    - `8777/udp`
    - `27015/udp`
    - `18888/tcp`
  - Point restant à surveiller : la charge CPU au repos devra être réévaluée plus tard avec au moins un joueur connecté.

---

## Tentatives à risque de régression — récapitulatif

| Tentative à éviter | Risque | Voir bug |
|---|---|---|
| `pkill -f "enshrouded"` | Tue l'instance AMP Test01 | [4] |
| `rfind('}')` dans fichier Nginx multi-blocs | Injecte dans le mauvais bloc server | [2] |
| Interpolation de mots de passe dans heredoc bash | Corrompt les caractères spéciaux | [3] |
| Suppression totale du fichier Nginx sans vérification | Casse toutes les instances du vhost | [6] |
| Filtrer les métriques Wine par binary name | Manque le process re-parenté par Wine | [5] |
| Flag `-vanilla` avec plusieurs instances Valheim | Conflit d'init Steam | [8] |
