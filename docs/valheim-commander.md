# Valheim Commander

Documentation utilisateur de l'interface Game Commander pour une instance `Valheim`.

## Menus

### Dashboard

Le `Dashboard` regroupe les informations de supervision immédiates :

- statut du serveur
- boutons `Démarrer` / `Redémarrer` / `Arrêter`
- métriques CPU / RAM
- graphe d'activité
- `Joueurs connectés`

Le panneau `Joueurs connectés` affiche les joueurs actuellement vus dans les logs du serveur.
Depuis ce panneau, il est possible de :

- ajouter ou retirer un admin
- ajouter ou retirer une whitelist
- bannir ou débannir un joueur

Ces actions écrivent dans les fichiers Valheim dédiés (`adminlist.txt`, `permittedlist.txt`,
`bannedlist.txt`).

### Configuration

Le menu `Configuration` regroupe les réglages principaux de l'instance.

Il contient notamment :

- `Mise à jour serveur`
- `Monde actif`
- `Sauvegardes`
- `World Modifiers`
- `BetterNetworking` si le mod est installé
- `ValheimPlus` si le plugin est installé

#### Monde actif

Le panneau `Monde actif` permet de choisir la partie Valheim qui sera utilisée au prochain
démarrage du serveur.

Important :

- `Fichiers` peut montrer plusieurs mondes dans `worlds_local`
- mais un seul `monde actif` est utilisé par le serveur à la fois
- changer le monde actif modifie la configuration de l'instance
- un redémarrage du serveur est ensuite nécessaire pour charger ce nouveau monde

#### Sauvegardes

Le panneau `Sauvegardes` gère les **archives zip** de backup de l'instance.

Actions disponibles :

- `Sauvegarder maintenant`
- télécharger un backup
- uploader un backup
- restaurer un backup
- supprimer un backup

Important :

- un backup Valheim normal ne sauvegarde **pas** tout le dossier `worlds_local`
- il sauvegarde uniquement le **monde actif** de l'instance
- les fichiers inclus sont :
  - `<WORLD_NAME>.db`
  - `<WORLD_NAME>.fwl`
  - `<WORLD_NAME>.db.old`
  - `<WORLD_NAME>.fwl.old`

Conséquence :

- si plusieurs mondes existent dans `worlds_local`, le bouton `Sauvegarder maintenant` ne prend
  que celui sélectionné comme `Monde actif`

Lors d'une restauration :

- un avertissement est affiché si des fichiers vont être écrasés
- le serveur peut être arrêté avant restauration
- un backup de sécurité est créé avant écrasement

#### World Modifiers

Le panneau `World Modifiers` permet de lire et modifier les paramètres de monde Valheim.

Ces réglages sont liés au monde actuellement sélectionné dans `Monde actif`.

### Fichiers

Le menu `Fichiers` donne accès au gestionnaire de fichiers de sauvegarde.

Pour Valheim :

- il affiche le contenu du dossier de mondes (`worlds_local` ou `worlds`)
- il peut donc montrer plusieurs mondes en parallèle
- on peut télécharger, uploader ou supprimer des fichiers

Important :

- `Fichiers` montre les fichiers bruts présents sur disque
- `Configuration / Sauvegardes` gère des **archives zip**

Suppression protégée :

- supprimer le `.db` ou le `.fwl` du monde actif déclenche un avertissement spécial
- si nécessaire, le serveur est arrêté avant suppression
- un snapshot de sécurité du monde courant est créé avant suppression

### Utilisateurs

Le menu `Utilisateurs` regroupe la gestion des fichiers d'accès Valheim :

- `Admins Valheim`
- `Joueurs bannis`
- `Whitelist`

Chaque panneau permet l'ajout manuel d'un `SteamID64` ainsi que la suppression d'entrées existantes.

### Mods

Le menu `Mods` est spécifique à Valheim quand `BepInEx` est installé.

Il permet :

- la recherche de mods Thunderstore
- l'installation de mods
- la suppression de mods
- l'accès à certaines configurations de mods quand elles sont supportées

Exemple :

- le panneau `BetterNetworking` n'apparaît que si le mod est réellement installé/configuré
- le panneau `ValheimPlus` n'apparaît que si le plugin `ValheimPlus.dll` est réellement présent

### Console

Le menu `Console` permet de consulter les logs récents du serveur.

Il est surtout utile pour :

- diagnostiquer un démarrage
- vérifier une erreur de mod
- confirmer des connexions/déconnexions

## Résumé utile

- `Dashboard` : état en direct du serveur
- `Configuration` : réglages et backups de l'instance
- `Fichiers` : fichiers bruts du dossier de mondes
- `Utilisateurs` : admins / bans / whitelist
- `Mods` : gestion BepInEx / Thunderstore
- `Console` : logs serveur
