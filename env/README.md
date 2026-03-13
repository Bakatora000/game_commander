# env

Ce dossier sert a stocker les fichiers de configuration de deploiement locaux.

Exemple :

```bash
sudo bash game_commander.sh deploy --generate-config
sudo bash game_commander.sh deploy --config env/deploy_config.env
```

Les fichiers `*.env` dans ce dossier sont ignores par Git.
