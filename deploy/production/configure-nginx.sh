#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "Usage: $0 ELASTIC_IP CERTBOT_EMAIL" >&2
  exit 64
fi

export BACKEND_PUBLIC_HOST="$1"
CERTBOT_EMAIL="$2"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SITE_PATH="/etc/nginx/sites-available/finora"

sudo mkdir -p /var/www/certbot
envsubst '${BACKEND_PUBLIC_HOST}' \
  < "$SCRIPT_DIR/finora-http.nginx.conf.template" \
  | sudo tee "$SITE_PATH" >/dev/null
sudo ln -sfn "$SITE_PATH" /etc/nginx/sites-enabled/finora
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl reload nginx

CERTBOT_CONTACT_ARGS=(--register-unsafely-without-email)
if [[ -n "$CERTBOT_EMAIL" ]]; then
  CERTBOT_CONTACT_ARGS=(--email "$CERTBOT_EMAIL")
fi

sudo certbot certonly --webroot --non-interactive --agree-tos \
  "${CERTBOT_CONTACT_ARGS[@]}" \
  --preferred-profile shortlived \
  --webroot-path /var/www/certbot \
  --ip-address "$BACKEND_PUBLIC_HOST"

envsubst '${BACKEND_PUBLIC_HOST}' \
  < "$SCRIPT_DIR/finora-https.nginx.conf.template" \
  | sudo tee "$SITE_PATH" >/dev/null
sudo nginx -t
sudo systemctl reload nginx
