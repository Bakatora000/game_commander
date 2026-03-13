#!/usr/bin/env bash
set -euo pipefail

python3 /home/vhserver/gc/tools/config_gen.py terraria-cfg \
  --out /home/vhserver/testterraria_server/serverconfig.txt \
  --name "Mon Serveur Terraria" \
  --port 7777 \
  --max-players 8 \
  --world-path /home/vhserver/testterraria_data \
  --world-name testterraria \
  --password "" \
  --autocreate 2 \
  --difficulty 0

cat > /home/vhserver/testterraria_server/start_server.sh <<'EOF'
#!/usr/bin/env bash
cd "/home/vhserver/testterraria_server"
CFG="/home/vhserver/testterraria_server/serverconfig.txt"

cfg_get() {
    local key="$1"
    sed -n "s/^${key}=//p" "$CFG" | head -1
}

WORLD="$(cfg_get world)"
WORLDPATH="$(cfg_get worldpath)"
WORLDNAME="$(cfg_get worldname)"
AUTOCREATE="$(cfg_get autocreate)"
DIFFICULTY="$(cfg_get difficulty)"
PORT="$(cfg_get port)"
MAXPLAYERS="$(cfg_get maxplayers)"
PASSWORD="$(cfg_get password)"
MOTD="$(cfg_get motd)"

[[ -z "$WORLD" && -n "$WORLDPATH" && -n "$WORLDNAME" ]] && WORLD="$WORLDPATH/$WORLDNAME.wld"
mkdir -p "$WORLDPATH" "/home/vhserver/testterraria_server/logs"

ARGS=(
  -world "$WORLD"
  -autocreate "${AUTOCREATE:-2}"
  -worldname "$WORLDNAME"
  -difficulty "${DIFFICULTY:-0}"
  -port "${PORT:-7777}"
  -maxplayers "${MAXPLAYERS:-8}"
  -motd "$MOTD"
  -logpath "/home/vhserver/testterraria_server/logs"
)

[[ -n "$PASSWORD" ]] && ARGS+=(-password "$PASSWORD")

exec ./TerrariaServer.bin.x86_64 "${ARGS[@]}"
EOF

cat > /home/vhserver/testterraria_server/start_server_service.sh <<'EOF'
#!/usr/bin/env bash
exec /usr/bin/script -qefc "/home/vhserver/testterraria_server/start_server.sh" /dev/null
EOF

chown vhserver:vhserver \
  /home/vhserver/testterraria_server/serverconfig.txt \
  /home/vhserver/testterraria_server/start_server.sh \
  /home/vhserver/testterraria_server/start_server_service.sh
chmod +x \
  /home/vhserver/testterraria_server/start_server.sh \
  /home/vhserver/testterraria_server/start_server_service.sh

cat > /etc/systemd/system/terraria-server-testterraria.service <<'EOF'
[Unit]
Description=Terraria Dedicated Server
After=network.target

[Service]
Type=simple
User=vhserver
WorkingDirectory=/home/vhserver/testterraria_server
ExecStart=/home/vhserver/testterraria_server/start_server_service.sh
Restart=on-failure
RestartSec=10
SuccessExitStatus=0 130 143
StandardOutput=journal
StandardError=journal
SyslogIdentifier=terraria-server-testterraria
KillSignal=SIGINT
KillMode=mixed
TimeoutStopSec=60

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl restart terraria-server-testterraria
journalctl -u terraria-server-testterraria -n 60 --no-pager
