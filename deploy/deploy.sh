#!/usr/bin/env bash
# Runs ON THE VPS (invoked by CI over SSH). Expects:
#   ~/unspun/.env          runtime secrets (never in the repo)
#   $SERVER_IMAGE / $WEB_IMAGE / $APP_VERSION exported by the caller
set -euo pipefail

cd "$(dirname "$0")"

echo "deploying SERVER_IMAGE=$SERVER_IMAGE WEB_IMAGE=$WEB_IMAGE"

docker compose --env-file "$HOME/unspun/.env" -f compose.yml -f compose.prod.yml pull
docker compose --env-file "$HOME/unspun/.env" -f compose.yml -f compose.prod.yml up -d --remove-orphans

# Migrations run from the freshly deployed image against the compose network.
docker compose --env-file "$HOME/unspun/.env" -f compose.yml -f compose.prod.yml \
  run --rm api alembic upgrade head

# Smoke check through the same loopback port cloudflared uses. RSSHub is
# internal-only, so its container healthcheck is the only signal we have;
# surface it here instead of letting a wedged instance sit unnoticed.
for i in $(seq 1 10); do
  if curl -fsS http://localhost:8080/api/health | grep -q '"status":"ok"'; then
    echo "health check passed"
    for j in $(seq 1 20); do
      rsshub_health=$(docker inspect -f '{{.State.Health.Status}}' unspun-rsshub-1 2>/dev/null || echo missing)
      [ "$rsshub_health" = "starting" ] || break
      sleep 3
    done
    echo "rsshub health: $rsshub_health"
    if [ "$rsshub_health" != "healthy" ]; then
      echo "rsshub is not healthy (non-fatal: web/api are up)" >&2
    fi
    docker image prune -f >/dev/null
    exit 0
  fi
  sleep 3
done

echo "health check FAILED" >&2
curl -fsS http://localhost:8080/api/health >&2 || true
exit 1
