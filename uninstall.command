#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker Desktop is not installed or docker is not on PATH."
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "Docker Desktop is installed but the Docker engine is not ready."
  echo "Start Docker Desktop and wait until the engine is running, then try again."
  exit 1
fi

echo
echo "TimelineForVideo uninstall"
echo
echo "This will remove Docker containers and images built for this project."
echo "It will not delete original videos under data/input."
echo

confirm_yes() {
  local prompt_text="$1"
  local response
  read -r -p "${prompt_text}" response
  case "${response}" in
    y|Y|yes|YES|Yes)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

if ! confirm_yes "Continue with uninstall? (y/n): "; then
  echo "Uninstall canceled."
  exit 1
fi

echo
echo "Stopping and removing Docker resources..."
docker compose -f docker-compose.yml -f docker-compose.gpu.yml down --rmi local --remove-orphans </dev/null
echo "Docker resources removed."

if [[ -d "data/output" ]]; then
  echo
  if confirm_yes "Delete generated outputs under data/output? (y/n): "; then
    rm -rf "data/output"
    echo "Deleted data/output."
  else
    echo "Kept data/output."
  fi
fi

if [[ -d "data/app-data" ]]; then
  echo
  echo "data/app-data includes saved settings and Hugging Face token."
  if confirm_yes "Delete saved settings and token under data/app-data? (y/n): "; then
    rm -rf "data/app-data"
    echo "Deleted data/app-data."
  else
    echo "Kept data/app-data."
  fi
fi

if [[ -d "data/cache" ]]; then
  echo
  if confirm_yes "Delete model caches under data/cache? (y/n): "; then
    rm -rf "data/cache"
    echo "Deleted data/cache."
  else
    echo "Kept data/cache."
  fi
fi

if [[ -f ".env" ]]; then
  echo
  if confirm_yes "Delete local .env as well? (y/n): "; then
    rm -f ".env"
    echo "Deleted .env."
  else
    echo "Kept .env."
  fi
fi

echo
echo "Uninstall completed."
