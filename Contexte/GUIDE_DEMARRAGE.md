# Guide De Demarrage

Ce guide s'adresse a une personne qui vient de louer un serveur Linux et veut deployer
un serveur de jeu avec `gc_2.1.0.zip`, sans etre a l'aise avec SSH au depart.

Le principe est simple :
- vous vous connectez a votre serveur
- vous copiez l'archive `gc_2.1.0.zip`
- vous lancez `game_commander.sh`
- le script installe et configure le serveur de jeu et l'interface web

## 1. Ce qu'il vous faut

- un serveur Linux Ubuntu 24.04 ou proche
- l'adresse IP du serveur
- le mot de passe `root` ou une cle SSH fournie par l'hebergeur
- l'archive `gc_2.1.0.zip`
- optionnel mais recommande : un nom de domaine

Sans nom de domaine, vous pouvez quand meme tester Game Commander en HTTP.

## 2. Comment ouvrir une console sur le serveur

Vous avez 2 options.

### Option A - Utiliser la console web de l'hebergeur

La plupart des hebergeurs cloud proposent une console web dans leur interface.
Exemples : Hetzner Console, OVH KVM/IPMI, console VPS, noVNC.

Avantage :
- rien a installer sur votre PC

Inconvenient :
- moins pratique pour copier/coller beaucoup de commandes

Si vous debutez completement, cette option suffit pour la premiere connexion.

### Option B - Utiliser SSH depuis votre ordinateur

SSH permet d'ouvrir un terminal distant sur votre serveur.

Sous Windows :
- Windows Terminal est recommande
- PowerShell fonctionne aussi
- PuTTY reste possible, mais n'est pas obligatoire

Sous macOS :
- utilisez l'application `Terminal`

Sous Linux :
- utilisez le terminal deja present

Commande type :

```bash
ssh root@IP_DU_SERVEUR
```

Exemple :

```bash
ssh root@203.0.113.10
```

Au premier acces, validez la cle du serveur puis saisissez le mot de passe si demande.

## 3. Transferer le fichier `gc_2.1.0.zip`

Vous pouvez le faire de 3 manieres.

### Methode simple - depuis la console web

Si la console de l'hebergeur permet le copier/coller de texte mais pas l'upload de fichier,
le plus simple est souvent d'utiliser SSH depuis votre PC.

### Methode standard - avec `scp`

Depuis votre ordinateur :

```bash
scp gc_2.1.0.zip root@IP_DU_SERVEUR:/root/
```

Exemple :

```bash
scp gc_2.1.0.zip root@203.0.113.10:/root/
```

### Methode graphique

Vous pouvez aussi utiliser un client SFTP :
- Windows : WinSCP
- macOS : Cyberduck
- Linux : FileZilla ou un client SFTP equivalent

Dans ce cas, envoyez `gc_2.1.0.zip` dans `/root/`.

## 4. Preparer les fichiers sur le serveur

Une fois connecte au serveur :

```bash
cd /root
apt update
apt install -y unzip
unzip gc_2.1.0.zip
```

Entrez ensuite dans le dossier extrait. Selon l'archive, le nom peut varier.

Pour voir les dossiers presents :

```bash
ls
```

Puis par exemple :

```bash
cd gc
```

Si vous voyez `game_commander.sh`, vous etes au bon endroit :

```bash
ls
```

## 5. Lancer Game Commander

Le mode le plus simple est le mode interactif :

```bash
sudo bash game_commander.sh
```

Un menu vous proposera :
- `deploy`
- `uninstall`
- `status`

Choisissez `deploy`.

## 6. Ce que le script va vous demander

Le script pose les questions principales.

### Jeu

Choisissez le jeu a deployer :
- Valheim
- Enshrouded
- Minecraft

### Utilisateur systeme Linux

Game Commander propose par defaut un utilisateur generique comme `gameserver`.

Vous pouvez :
- accepter cette valeur
- ou choisir un autre nom

Cet utilisateur servira a faire tourner le serveur de jeu et l'interface web.

### Instance

L'`instance_id` identifie votre installation.

Exemples :
- `valheim1`
- `enshrouded1`
- `minecraft1`

Cette valeur sert aussi pour :
- les noms de services systemd
- certains dossiers
- l'URL de l'interface web

### Ports

Le script propose des ports par defaut et detecte les ports deja utilises.

Exemples courants :
- Valheim : port de base jeu `2456`
- Enshrouded : port de base jeu `15636`
- Flask/Game Commander : `5002`, `5003`, `5004`, etc.

Si plusieurs serveurs tournent sur la meme machine, laissez le script choisir un port libre
ou entrez une autre valeur libre.

Important :
- il faut aussi ouvrir ces ports dans le firewall de votre hebergeur
- pour Enshrouded, le jeu utilise un port de base et un `queryPort` juste au-dessus

Exemple :
- `SERVER_PORT=15638`
- `queryPort=15639`

### Domaine et acces web

Si vous avez un domaine, vous pouvez l'utiliser.

Exemple :

```text
gaming.example.com
```

Si vous n'avez pas encore de domaine, vous pouvez quand meme faire un premier test en HTTP.

### SSL

Le script peut proposer plusieurs modes :
- `certbot` : creation automatique d'un certificat Let's Encrypt
- `existing` : reutiliser un certificat deja present
- `none` : HTTP uniquement

Si vous debutez :
- avec domaine deja pointe vers le serveur : `certbot`
- sans domaine : `none`

### Compte administrateur web

Le script vous demande :
- un login admin
- un mot de passe admin

Ce compte sert a vous connecter a l'interface web Game Commander.

## 7. Ouvrir les bons ports

Il y a souvent 2 niveaux de firewall :
- le firewall du serveur Linux
- le firewall de l'hebergeur cloud

Si votre hebergeur propose un firewall reseau, ouvrez les ports necessaires avant de tester.

Exemples :

### Valheim

- UDP `2456`
- UDP `2457`

### Enshrouded

- UDP `15636`
- UDP `15637`

### Interface web

Si vous passez par Nginx :
- TCP `80`
- TCP `443`

## 8. Fin du deploiement

Si tout se passe bien, vous aurez :
- un service systemd pour le serveur de jeu
- un service systemd pour Game Commander
- une URL web de gestion

Exemples de verification :

```bash
sudo bash game_commander.sh status
sudo systemctl status game-commander-moninstance
```

## 9. Comment se connecter a l'interface web

Exemples :

```text
https://gaming.example.com/valheim1
https://gaming.example.com/enshrouded1
```

Ou en HTTP si vous avez choisi `none` :

```text
http://IP_DU_SERVEUR/valheim1
```

Connectez-vous avec le login et le mot de passe admin definis pendant le deploy.

## 10. Commandes utiles

Afficher l'etat des instances :

```bash
sudo bash game_commander.sh status
```

Desinstaller une instance :

```bash
sudo bash game_commander.sh uninstall
```

Relancer l'outil :

```bash
sudo bash game_commander.sh
```

## 11. Si vous preferez preparer un fichier de config

Vous pouvez generer un modele :

```bash
sudo bash game_commander.sh deploy --generate-config
```

Cela cree un fichier d'exemple que vous pourrez editer, puis reutiliser avec :

```bash
sudo bash game_commander.sh deploy --config env/deploy_config.env
```

Pratique si vous voulez refaire un deploiement sans repondre a toutes les questions.

## 12. Probleme frequent : "je ne trouve pas mon serveur dans le jeu"

Verifiez dans cet ordre :

1. le service du jeu tourne bien
2. le bon port est ouvert chez l'hebergeur
3. vous cherchez le bon port
4. le mot de passe du serveur est correct

Cas particulier Enshrouded :
- le port visible dans le navigateur serveur est le `queryPort`
- en pratique c'est souvent `SERVER_PORT + 1`

## 13. Probleme frequent : "je ne sais plus quoi taper"

Revenez aux commandes de base :

```bash
pwd
ls
cd /root
cd /root/gc
sudo bash game_commander.sh
```

`pwd` affiche le dossier courant.  
`ls` affiche les fichiers.  
`cd` change de dossier.

## 14. Conseils simples

- faites votre premier test avec une seule instance
- notez les ports choisis
- notez l'URL choisie
- utilisez un mot de passe admin fort
- ne supprimez pas manuellement des fichiers systemd ou Nginx si vous debutez
- utilisez plutot `game_commander.sh uninstall`

## 15. Resume ultra-court

Depuis votre PC :

```bash
scp gc_2.1.0.zip root@IP_DU_SERVEUR:/root/
ssh root@IP_DU_SERVEUR
```

Puis sur le serveur :

```bash
cd /root
apt update
apt install -y unzip
unzip gc_2.1.0.zip
cd gc
sudo bash game_commander.sh
```

Ensuite :
- choisissez `deploy`
- repondez aux questions
- ouvrez les ports necessaires
- connectez-vous a l'URL Game Commander
