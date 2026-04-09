#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
export COMPOSE_PROJECT_NAME="timelineforvideo"
LEGACY_COMPOSE_PROJECT_NAME="video2timeline"

if docker volume inspect "${LEGACY_COMPOSE_PROJECT_NAME}_app-data" >/dev/null 2>&1; then
  if ! docker volume inspect "${COMPOSE_PROJECT_NAME}_app-data" >/dev/null 2>&1; then
    export COMPOSE_PROJECT_NAME="${LEGACY_COMPOSE_PROJECT_NAME}"
  fi
fi

docker compose down
