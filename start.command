#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"
DOCKER_DESKTOP_URL="https://docs.docker.com/desktop/setup/install/mac-install/"
SKIP_HELP_LINK="${TIMELINEFORVIDEO_SKIP_HELP_LINK:-${VIDEO2TIMELINE_SKIP_HELP_LINK:-0}}"

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker Desktop is not installed or docker is not on PATH."
  echo "Download and install Docker Desktop here:"
  echo "  ${DOCKER_DESKTOP_URL}"
  if [ "${SKIP_HELP_LINK}" != "1" ]; then
    open "${DOCKER_DESKTOP_URL}" || true
  fi
  echo "Install Docker Desktop, start it, and try again."
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "Docker Desktop is installed but the Docker engine is not ready."
  echo "Docker Desktop setup guide:"
  echo "  ${DOCKER_DESKTOP_URL}"
  if [ "${SKIP_HELP_LINK}" != "1" ]; then
    open "${DOCKER_DESKTOP_URL}" || true
  fi
  echo "Start Docker Desktop and wait until the engine is running, then try again."
  exit 1
fi

if [ ! -f ".env" ]; then
  cp ".env.example" ".env"
  echo "Created .env from .env.example."
fi

mkdir -p data/input data/output data/app-data data/cache/huggingface data/cache/torch

echo "Building TimelineForVideo CLI runtime..."
docker compose build worker

cat <<EOF

TimelineForVideo CLI runtime is ready.
Put videos in:
  $(pwd)/data/input

Common commands:
  docker compose run --rm worker settings status
  docker compose run --rm worker jobs create --directory /data/input
  docker compose run --rm worker jobs list
  docker compose run --rm worker jobs archive --job-id job-YYYYMMDD-HHMMSS-xxxxxxxx

Results are written under:
  $(pwd)/data/output
EOF
