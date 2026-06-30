#!/usr/bin/env bash
set -euo pipefail

DOMAIN="${DOMAIN:?Set DOMAIN, e.g. 32.199.181.8.sslip.io}"
APP_DIR="/home/ubuntu/generative-ai-vdos"
BASE_URL="https://${DOMAIN}"

echo "==> Installing certbot"
sudo apt-get update -qq
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq certbot python3-certbot-nginx

echo "==> Nginx config (HTTP, pre-cert)"
sudo cp "$APP_DIR/scripts/deploy/nginx.conf" /etc/nginx/sites-available/generative-ai-vdos
sudo ln -sf /etc/nginx/sites-available/generative-ai-vdos /etc/nginx/sites-enabled/generative-ai-vdos
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl reload nginx

echo "==> Obtaining TLS certificate for ${DOMAIN}"
sudo certbot --nginx -d "$DOMAIN" \
  --non-interactive --agree-tos --register-unsafely-without-email \
  --redirect

echo "==> Updating .env for HTTPS"
ENV_FILE="$APP_DIR/.env"

set_env() {
  local key="$1" value="$2"
  if grep -q "^${key}=" "$ENV_FILE" 2>/dev/null; then
    sudo -u ubuntu sed -i "s|^${key}=.*|${key}=${value}|" "$ENV_FILE"
  else
    echo "${key}=${value}" | sudo -u ubuntu tee -a "$ENV_FILE" >/dev/null
  fi
}

set_env FRONTEND_URL "$BASE_URL"
set_env CORS_ALLOWED_ORIGINS "$BASE_URL"
set_env COGNITO_REDIRECT_URI "${BASE_URL}/api/auth/callback"
set_env COGNITO_LOGOUT_REDIRECT_URI "$BASE_URL"
set_env DJANGO_ALLOWED_HOSTS "${DOMAIN},32.199.181.8,localhost,127.0.0.1"

echo "==> Restart app services"
sudo systemctl restart generative-ai-vdos-backend generative-ai-vdos-frontend

echo ""
echo "Done. Add these in Cognito:"
echo "  Callback URL:  ${BASE_URL}/api/auth/callback"
echo "  Sign-out URL:  ${BASE_URL}"
echo "  App URL:       ${BASE_URL}"
