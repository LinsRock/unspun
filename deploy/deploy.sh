#!/usr/bin/env bash
# Runs ON THE VPS (invoked by CI over SSH). Expects:
#   ~/unspun/.env          runtime secrets (never in the repo)
#   $APP_VERSION exported by the caller; image overrides only for changed artifacts
set -euo pipefail

cd "$(dirname "$0")"

export APP_VERSION="${APP_VERSION:?target application version is required}"
export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-unspun}"

compose=(docker compose --env-file "${UNSPUN_DEPLOY_ENV_FILE:-$HOME/unspun/.env}"
  -f compose.yml -f compose.prod.yml)

current_image() {
  local container image
  container=$("${compose[@]}" ps -q "$1")
  if [ -z "$container" ]; then
    echo "no running $1 image to reuse; supply an explicit image" >&2
    return 1
  fi
  image=$(docker inspect -f '{{.Config.Image}}' "$container")
  if [[ ! "$image" =~ :[0-9a-f]{40}$ && ! "$image" =~ @sha256:[0-9a-f]{64}$ ]]; then
    echo "refusing to reuse a mutable $1 image; supply an immutable image" >&2
    return 1
  fi
  printf '%s\n' "$image"
}

# Resolve both references before pull/migrate. Never guess an absent artifact
# from :latest, a default development image, or a previous Git commit tag.
SERVER_IMAGE="${SERVER_IMAGE:-$(current_image api)}"
export SERVER_IMAGE
WEB_IMAGE="${WEB_IMAGE:-$(current_image web)}"
export WEB_IMAGE

migration_name="$COMPOSE_PROJECT_NAME-migration"
deployment_token="$APP_VERSION-$$-$(date +%s)"
migration_pid=""

interrupt() {
  trap '' INT TERM
  echo "deployment interrupted; remaining steps were not run" >&2
  if [ -n "$migration_pid" ]; then
    kill "$migration_pid" 2>/dev/null || true
    wait "$migration_pid" 2>/dev/null || true
    owner=$(docker inspect -f '{{ index .Config.Labels "io.unspun.deployment" }}' \
      "$migration_name" 2>/dev/null || true)
    if [ "$owner" = "$deployment_token" ]; then
      docker rm -f "$migration_name" >/dev/null 2>&1 || true
    fi
  fi
  exit "$1"
}
trap 'interrupt 130' INT
trap 'interrupt 143' TERM

echo "deploying SERVER_IMAGE=$SERVER_IMAGE WEB_IMAGE=$WEB_IMAGE"

# Release images use immutable commit tags; cached rollback images stay usable.
"${compose[@]}" pull --policy missing
"${compose[@]}" up -d --wait --wait-timeout 120 db

# A one-off container uses the target API image without starting the API or
# its dependencies. A fixed name also refuses overlapping migration runs.
# Keep the old API available: R1 migrations must remain additive/compatible.
"${compose[@]}" run -T --rm --no-deps --name "$migration_name" \
  --label "io.unspun.deployment=$deployment_token" api alembic upgrade head &
migration_pid=$!
if wait "$migration_pid"; then
  migration_pid=""
else
  status=$?
  migration_pid=""
  echo "migration failed; target services were not started" >&2
  exit "$status"
fi

# Never restart the legacy paid loop, including when rolling back an image.
# Approved R1 consumers must be wired separately through their rollout PR.
"${compose[@]}" up -d --remove-orphans --scale worker=0

# Smoke check through the same loopback port cloudflared uses. RSSHub is
# internal-only, so its container healthcheck is the only signal we have;
# surface it here instead of letting a wedged instance sit unnoticed.
for i in $(seq 1 10); do
  health=$(curl -fsS "${UNSPUN_DEPLOY_HEALTH_URL:-http://localhost:8080/api/health}" || true)
  if grep -q '"status":"ok"' <<<"$health" &&
    grep -Fq "\"version\":\"$APP_VERSION\"" <<<"$health"; then
    echo "health check passed"
    for j in $(seq 1 20); do
      rsshub_id=$("${compose[@]}" ps -q rsshub)
      rsshub_health=$(docker inspect -f '{{.State.Health.Status}}' "$rsshub_id" 2>/dev/null || echo missing)
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
curl -fsS "${UNSPUN_DEPLOY_HEALTH_URL:-http://localhost:8080/api/health}" >&2 || true
exit 1
