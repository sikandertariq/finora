#!/usr/bin/env bash
set -euo pipefail

if ! command -v aws >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y awscli ca-certificates certbot curl gettext-base git nginx snapd

  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  cat >/etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF

  apt-get update
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi

systemctl enable --now docker nginx snapd
snap install certbot --classic || true
ln -sfn /snap/bin/certbot /usr/local/bin/certbot

mkdir -p /srv/finora/data/{postgres,redis,media,celery-beat,backups}
mkdir -p /etc/finora
chown -R ubuntu:ubuntu /srv/finora
usermod -aG docker ubuntu
printf '0 */6 * * * root /srv/finora/deploy/production/renew-certificates.sh\n' > /etc/cron.d/finora-certbot
chmod 644 /etc/cron.d/finora-certbot
