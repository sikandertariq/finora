#!/usr/bin/env bash
set -euo pipefail

sudo certbot renew --quiet --deploy-hook 'systemctl reload nginx'
