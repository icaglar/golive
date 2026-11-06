#!/usr/bin/env bash
# golive-pull: pull-based deploy for Docker Compose. Installed by the deploy skill as
# /usr/local/bin/golive-pull (mode 0755) and run by golive-pull.service every 2 minutes.
#
# Rules (see golive release model):
#  - APP_ENV (staging|prod) comes from /srv/app/.env. The server follows the git tag golive-$APP_ENV,
#    never main. release.yml moves that tag; nothing else changes what this server runs.
#  - Nothing is restarted when the tag did not move and the pulled images did not change.
#  - Any failure exits non-zero so the unit shows "failed" and monitoring can alert on it.
set -euo pipefail

APP_DIR="${GOLIVE_DIR:-/srv/app}"
log() { echo "golive-pull: $*"; }
# Heartbeat for the PullFailed alert (templates/monitoring/alerts.yml): written after every successful run.
TEXTFILE_DIR="${GOLIVE_TEXTFILE_DIR:-/var/lib/node_exporter/textfile}"
heartbeat() {
  if [ -d "$TEXTFILE_DIR" ]; then
    printf 'golive_pull_last_success_timestamp_seconds %s\n' "$(date +%s)" > "$TEXTFILE_DIR/pull.prom.$$" \
      && mv "$TEXTFILE_DIR/pull.prom.$$" "$TEXTFILE_DIR/pull.prom"
  fi
}
die() { echo "golive-pull: ERROR: $*" >&2; exit 1; }

cd "$APP_DIR" || die "cannot cd to $APP_DIR"

# One run at a time (the timer and a manual run must not overlap).
exec 9>"${TMPDIR:-/tmp}/golive-pull.lock"
flock -n 9 || { log "another run is in progress, skipping"; exit 0; }

# APP_ENV: normally injected by systemd (EnvironmentFile); fall back to reading .env for manual runs.
if [ -z "${APP_ENV:-}" ] && [ -f .env ]; then
  APP_ENV="$(sed -n 's/^APP_ENV=//p' .env | tail -n 1 | tr -d "\"'\r")"
fi
case "${APP_ENV:-}" in
  staging|prod) ;;
  *) die "APP_ENV must be 'staging' or 'prod' (set it in $APP_DIR/.env), got '${APP_ENV:-}'" ;;
esac
tag="golive-${APP_ENV}"

# Fingerprint of the images this compose project uses: their local image IDs (or "none" when not pulled yet).
fingerprint() {
  local img
  docker compose config --images 2>/dev/null | sort -u | while read -r img; do
    [ -n "$img" ] || continue
    echo "$img $(docker image inspect --format '{{.Id}}' "$img" 2>/dev/null || echo none)"
  done
}

git fetch --tags --force --quiet
if ! target="$(git rev-parse -q --verify "refs/tags/${tag}^{commit}")"; then
  log "tag $tag does not exist yet: nothing has been released to $APP_ENV, nothing to do"
  heartbeat
  exit 0
fi

current="$(git rev-parse HEAD 2>/dev/null || echo none)"
changed=0
if [ "$current" != "$target" ]; then
  log "tag $tag moved: ${current:0:12} -> ${target:0:12}"
  git checkout --force --quiet "$tag"
  changed=1
fi

before="$(fingerprint)"
docker compose pull --quiet
after="$(fingerprint)"
if [ "$before" != "$after" ]; then
  log "images changed"
  changed=1
fi

if [ "$changed" -eq 0 ]; then
  log "up to date at ${target:0:12} ($APP_ENV), nothing restarted"
  heartbeat
  exit 0
fi

# Migrations: only when the compose file defines a `migrate` service (also when it sits behind a profile).
if docker compose --profile '*' config --services 2>/dev/null | grep -qx migrate; then
  log "running migrations: docker compose run --rm migrate"
  docker compose run --rm migrate
else
  log "no migrate service in the compose file, skipping migrations"
fi

docker compose up -d --remove-orphans
docker image prune -f >/dev/null
log "deployed ${target:0:12} to $APP_ENV"
heartbeat
