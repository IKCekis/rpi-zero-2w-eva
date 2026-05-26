#!/bin/bash
# deploy.sh — sync pi-device to the Raspberry Pi.
# Usage: ./deploy.sh [pi-host]
set -e
HOST="${1:-ikcekis@192.168.50.10}"
REMOTE_DIR="/home/ikcekis/pal"

echo "→ Deploying to $HOST:$REMOTE_DIR"
rsync -avz --exclude "__pycache__" --exclude "*.pyc" --exclude ".git" \
    ./ "$HOST:$REMOTE_DIR/"

echo "→ Installing Python deps (root)"
ssh "$HOST" "sudo pip3 install -r $REMOTE_DIR/requirements.txt --break-system-packages"

echo "→ Ensuring /run/pal.events exists"
ssh "$HOST" "sudo touch /run/pal.events && sudo chmod 666 /run/pal.events"

echo "→ Installing systemd services"
ssh "$HOST" "sudo cp $REMOTE_DIR/pal.service        /etc/systemd/system/"
ssh "$HOST" "sudo cp $REMOTE_DIR/ble_server.service /etc/systemd/system/"
ssh "$HOST" "sudo systemctl daemon-reload"
ssh "$HOST" "sudo systemctl enable pal.service ble_server.service"
ssh "$HOST" "sudo systemctl restart ble_server.service pal.service"

echo "✓ Done."
ssh "$HOST" "sudo systemctl status pal.service ble_server.service --no-pager -l | head -20"
