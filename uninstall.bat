@echo off
setlocal EnableExtensions EnableDelayedExpansion

cd /d "%~dp0"

where docker >nul 2>&1
if errorlevel 1 (
  echo docker.exe was not found on PATH.
  echo Install Docker Desktop first, then try again.
  exit /b 1
)

docker info >nul 2>&1
if errorlevel 1 (
  echo Docker Desktop is installed but the Docker engine is not ready.
  echo Start Docker Desktop and wait until the engine is running, then try again.
  exit /b 1
)

echo.
echo TimelineForVideo uninstall
echo.
echo This will remove Docker containers and images built for this project.
echo It will not delete original videos under data\input.
echo.

call :confirm_yes "Continue with uninstall? (y/n): "
if errorlevel 1 (
  echo Uninstall canceled.
  exit /b 1
)

echo.
echo Stopping and removing Docker resources...
docker compose -f docker-compose.yml -f docker-compose.gpu.yml down --rmi local --remove-orphans <nul
if errorlevel 1 (
  echo Docker cleanup failed.
  exit /b 1
)

echo Docker resources removed.

if exist "data\output" (
  echo.
  call :confirm_yes "Delete generated outputs under data\output? (y/n): "
  if not errorlevel 1 (
    rmdir /s /q "data\output"
    echo Deleted data\output.
  ) else (
    echo Kept data\output.
  )
)

if exist "data\app-data" (
  echo.
  echo data\app-data includes saved settings and Hugging Face token.
  call :confirm_yes "Delete saved settings and token under data\app-data? (y/n): "
  if not errorlevel 1 (
    rmdir /s /q "data\app-data"
    echo Deleted data\app-data.
  ) else (
    echo Kept data\app-data.
  )
)

if exist "data\cache" (
  echo.
  call :confirm_yes "Delete model caches under data\cache? (y/n): "
  if not errorlevel 1 (
    rmdir /s /q "data\cache"
    echo Deleted data\cache.
  ) else (
    echo Kept data\cache.
  )
)

if exist ".env" (
  echo.
  call :confirm_yes "Delete local .env as well? (y/n): "
  if not errorlevel 1 (
    del /q ".env"
    echo Deleted .env.
  ) else (
    echo Kept .env.
  )
)

echo.
echo Uninstall completed.
exit /b 0

:confirm_yes
set "PROMPT_TEXT=%~1"
echo %PROMPT_TEXT%
choice /c yn /n
if errorlevel 2 exit /b 1
if errorlevel 1 exit /b 0
exit /b 1
