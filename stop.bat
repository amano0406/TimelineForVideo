@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "COMPOSE_PROJECT_NAME=timelineforvideo"
set "LEGACY_COMPOSE_PROJECT_NAME=video2timeline"

docker volume inspect "%LEGACY_COMPOSE_PROJECT_NAME%_app-data" >nul 2>&1
if not errorlevel 1 (
  docker volume inspect "%COMPOSE_PROJECT_NAME%_app-data" >nul 2>&1
  if errorlevel 1 set "COMPOSE_PROJECT_NAME=%LEGACY_COMPOSE_PROJECT_NAME%"
)

docker compose down
