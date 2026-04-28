@echo off
setlocal EnableExtensions

cd /d "%~dp0"
set "DOCKER_DESKTOP_URL=https://docs.docker.com/desktop/setup/install/windows-install/"
set "SKIP_HELP_LINK=%TIMELINEFORVIDEO_SKIP_HELP_LINK%"
if not defined SKIP_HELP_LINK set "SKIP_HELP_LINK=%VIDEO2TIMELINE_SKIP_HELP_LINK%"

where docker >nul 2>&1
if errorlevel 1 (
  echo Docker Desktop is not installed or docker.exe is not on PATH.
  echo Download and install Docker Desktop here:
  echo   %DOCKER_DESKTOP_URL%
  if /I not "%SKIP_HELP_LINK%"=="1" start "" "%DOCKER_DESKTOP_URL%" >nul 2>&1
  echo Install Docker Desktop, start it, and try again.
  exit /b 1
)

docker info >nul 2>&1
if errorlevel 1 (
  echo Docker Desktop is installed but the Docker engine is not ready.
  echo Docker Desktop setup guide:
  echo   %DOCKER_DESKTOP_URL%
  if /I not "%SKIP_HELP_LINK%"=="1" start "" "%DOCKER_DESKTOP_URL%" >nul 2>&1
  echo Start Docker Desktop and wait until it shows the engine is running, then try again.
  exit /b 1
)

if not exist ".env" (
  copy ".env.example" ".env" >nul
  echo Created .env from .env.example.
)

if not exist "data\input" mkdir "data\input"
if not exist "data\output" mkdir "data\output"
if not exist "data\app-data" mkdir "data\app-data"
if not exist "data\cache\huggingface" mkdir "data\cache\huggingface"
if not exist "data\cache\torch" mkdir "data\cache\torch"

echo Building TimelineForVideo CLI runtime...
docker compose build worker
if errorlevel 1 (
  echo docker compose build failed.
  exit /b 1
)

echo.
echo TimelineForVideo CLI runtime is ready.
echo Put videos in:
echo   %CD%\data\input
echo.
echo Common commands:
echo   docker compose run --rm worker settings status
echo   docker compose run --rm worker jobs create --directory /data/input
echo   docker compose run --rm worker jobs list
echo   docker compose run --rm worker jobs archive --job-id job-YYYYMMDD-HHMMSS-xxxxxxxx
echo.
echo Results are written under:
echo   %CD%\data\output
