#!/usr/bin/env bash
# Waits for dependencies, applies migrations, then hands off to the given command.
set -euo pipefail

log() { printf '[entrypoint] %s\n' "$*" >&2; }

wait_for() {
  local host=$1 port=$2 name=$3 attempts=${4:-60}
  log "waiting for ${name} at ${host}:${port}"
  for ((i = 1; i <= attempts; i++)); do
    if (echo >"/dev/tcp/${host}/${port}") 2>/dev/null; then
      log "${name} is up"
      return 0
    fi
    sleep 1
  done
  log "ERROR: ${name} did not become available after ${attempts}s"
  return 1
}

wait_for "${POSTGRES_HOST:-postgres}" "${POSTGRES_PORT:-5432}" postgres
wait_for "${REDIS_HOST:-redis}" "${REDIS_PORT:-6379}" redis

if [[ "${RUN_MIGRATIONS:-true}" == "true" ]]; then
  log "applying database migrations"
  alembic upgrade head
fi

log "starting: $*"
exec "$@"
