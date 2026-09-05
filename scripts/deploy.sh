#!/usr/bin/env bash
set -euo pipefail

if [[ $# != 2 ]]; then
  echo "Usage: $0 SSH_ALIAS PRIVATE_ENV_FILE" >&2
  exit 2
fi
astra_host=$1
astra_env=$2
test -f "$astra_env"

# Use the operator's configured alias and normal host-key verification.
ssh -o BatchMode=yes "$astra_host" 'bash -se' <<'REMOTE'
set -euo pipefail
if [[ ! -e /opt/forge-astra ]]; then
  git clone https://github.com/loud1990/forge-astra.git /opt/forge-astra
else
  cd /opt/forge-astra
  test "$(git remote get-url origin)" = https://github.com/loud1990/forge-astra.git
  test -z "$(git status --porcelain)"
  git pull --ff-only origin main
fi
docker compose version
REMOTE

# No credential values are printed or written to the public repository.
scp -q -o BatchMode=yes "$astra_env" "$astra_host:/opt/forge-astra/.env"
ssh -o BatchMode=yes "$astra_host" 'bash -se' <<'REMOTE'
set -euo pipefail
cd /opt/forge-astra
chmod 600 .env
docker compose up -d --build
docker compose ps
REMOTE
