#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "Usage: $0 IMAGE_REF BACKEND_PUBLIC_IP" >&2
  exit 64
fi

IMAGE_REF="$1"
BACKEND_PUBLIC_IP="$2"
APP_DIR="/srv/finora"
PARAMETER_PREFIX="/finora/production"

bash "$APP_DIR/deploy/production/bootstrap-host.sh"

parameter() {
  aws ssm get-parameter --with-decryption --name "$PARAMETER_PREFIX/$1" \
    --query 'Parameter.Value' --output text
}

export FINORA_BACKEND_IMAGE="$IMAGE_REF"
export DJANGO_SECRET_KEY="$(parameter DJANGO_SECRET_KEY)"
export POSTGRES_PASSWORD="$(parameter POSTGRES_PASSWORD)"
export GEMINI_API_KEY="$(parameter GEMINI_API_KEY)"
export DEMO_USER_PASSWORD="$(parameter DEMO_USER_PASSWORD)"
export DJANGO_ALLOWED_HOSTS="$BACKEND_PUBLIC_IP"
export DJANGO_CSRF_TRUSTED_ORIGINS="https://$BACKEND_PUBLIC_IP"

mkdir -p "$APP_DIR/data/backups"
envsubst < "$APP_DIR/deploy/production/runtime.env.template" > "$APP_DIR/.env.production"
chmod 600 "$APP_DIR/.env.production"

cd "$APP_DIR"
CERTBOT_EMAIL=""
if [[ -f /etc/finora/certbot-email ]]; then
  CERTBOT_EMAIL="$(< /etc/finora/certbot-email)"
fi
if [[ ! -f "/etc/letsencrypt/live/$BACKEND_PUBLIC_IP/fullchain.pem" ]]; then
  "$APP_DIR/deploy/production/configure-nginx.sh" \
    "$BACKEND_PUBLIC_IP" "$CERTBOT_EMAIL"
fi
if docker compose --env-file .env.production -f docker-compose.production.yml ps postgres --status running -q | grep -q .; then
  docker compose --env-file .env.production -f docker-compose.production.yml exec -T postgres \
    pg_dump -U finora finora > "data/backups/pre-deploy-$(date -u +%Y%m%dT%H%M%SZ).sql"
fi
docker compose --env-file .env.production -f docker-compose.production.yml pull
docker compose --env-file .env.production -f docker-compose.production.yml up -d --remove-orphans

for _ in $(seq 1 24); do
  if curl --fail --silent "https://$BACKEND_PUBLIC_IP/api/health/" >/dev/null; then
    exit 0
  fi
  sleep 5
done

echo "Django health check did not become ready" >&2
exit 1
