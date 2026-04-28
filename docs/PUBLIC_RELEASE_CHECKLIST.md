# Public Release Checklist

Use this checklist before switching the repository from private to public.

## Repository Safety

- no real Hugging Face token is committed
- `.env`, `data/`, `runs/`, `uploads/`, `app-data/`, and local caches are ignored
- sample timelines are redacted
- sample files do not show local private data
- config samples use generic placeholder paths instead of personal paths
- generated ZIPs or run outputs are not tracked

## Build And Test

- `python -m unittest discover worker/tests` with `PYTHONPATH=worker/src`
- at least one real local smoke run still completes
- `jobs archive` creates the reduced ZIP package

## Runtime Checks

- `start.bat` prepares the Docker-based CLI runtime on Windows
- `start.command` prepares the Docker-based CLI runtime on macOS as an experimental source-based path
- `docker compose run --rm worker settings status` works
- token save flow works through `settings save`
- gated-model approval links still open the correct Hugging Face pages
- one file under `data/input` can complete end-to-end
- one completed job can be archived

## Documentation

- README is accurate for the current startup flow
- Japanese README is still consistent with English README
- sample timeline files reflect the current output shape
- third-party notices and model/runtime notes match current dependencies
- the current `TimelineForVideo v0.x.y Tech Preview` wording is consistent where needed
- `Windows primary / macOS experimental` wording is consistent where needed
- `Docker Desktop required`, `first-run downloads`, and `GPU best-effort` wording are consistent where needed
- speaker diarization is clearly described as optional and gated by token + approval

## Release Package

- `scripts/build-release-bundle.ps1 -Version 0.x.y` produces `TimelineForVideo-windows-local.zip`
- `SHA256SUMS.txt` is generated for the release bundle
- the bundle top folder is `TimelineForVideo-v0.x.y`
- the bundle does not include generated runs, input files, app-data, tests, Web UI files, or local caches

## Before Making The Repo Public

- run `git grep` for personal local paths and names you do not want to publish
- confirm LICENSE and copyright text are what you want
- confirm no experimental or abandoned branches contain sensitive material
- review GitHub repository settings for issue tracking, discussions, and visibility

## Post-Publish Checks

- the GitHub Release title matches the newly published `TimelineForVideo v0.x.y Tech Preview`
- `releases/latest` resolves to the newly published tag
- `TimelineForVideo-windows-local.zip` downloads from the release page
- LP primary CTA can switch to the repository's current `releases/latest` URL
