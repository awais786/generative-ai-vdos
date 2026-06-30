#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/home/ubuntu/generative-ai-vdos"
SERVER_IP="${SERVER_IP:?Set SERVER_IP}"

echo "==> Installing system packages"
sudo apt-get update -qq
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
  git curl build-essential ffmpeg nginx redis-server

echo "==> Installing uv"
if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh -o /tmp/uv-install.sh
  sh /tmp/uv-install.sh
fi
export PATH="$HOME/.local/bin:$PATH"

echo "==> Installing Node.js 20"
if ! command -v node >/dev/null 2>&1; then
  curl -fsSL https://deb.nodesource.com/setup_20.x -o /tmp/nodesource-setup.sh
  sudo -E bash /tmp/nodesource-setup.sh
  sudo apt-get install -y -qq nodejs
fi

echo "==> Python deps"
cd "$APP_DIR"
uv sync --extra webapp
uv pip install gunicorn

echo "==> Frontend deps + build"
cd "$APP_DIR/webapp"
npm ci
npm run build

echo "==> Django migrate + seed"
cd "$APP_DIR"
.venv/bin/python backend/manage.py migrate
.venv/bin/python backend/manage.py seed_providers

echo "==> Systemd services"
chmod +x "$APP_DIR/scripts/deploy/start-backend.sh"
sudo cp "$APP_DIR/scripts/deploy/backend.service" /etc/systemd/system/generative-ai-vdos-backend.service
sudo cp "$APP_DIR/scripts/deploy/frontend.service" /etc/systemd/system/generative-ai-vdos-frontend.service
sudo systemctl daemon-reload
sudo systemctl enable generative-ai-vdos-backend generative-ai-vdos-frontend
sudo systemctl restart generative-ai-vdos-backend generative-ai-vdos-frontend

echo "==> Nginx"
sudo cp "$APP_DIR/scripts/deploy/nginx.conf" /etc/nginx/sites-available/generative-ai-vdos
sudo ln -sf /etc/nginx/sites-available/generative-ai-vdos /etc/nginx/sites-enabled/generative-ai-vdos
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl restart nginx

echo "==> Done — app should be live at http://${SERVER_IP}"
