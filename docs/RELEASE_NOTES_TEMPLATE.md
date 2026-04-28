# TimelineForVideo v0.x.y Tech Preview

Local-first video-to-markdown packaging tool for LLM workflows.
This is a CLI-based local tool, not a hosted SaaS product.

## Baseline Support

- Windows
- Docker Desktop
- CLI
- CPU mode

## Optional Features

- GPU mode: NVIDIA + Docker GPU access only, best-effort
- Speaker diarization: optional, requires both a Hugging Face token and gated approval for `pyannote/speaker-diarization-community-1`

## Download

- Windows: `TimelineForVideo-windows-local.zip`
- macOS: source-based, experimental path

## What's New

- ...
- ...
- ...

## Known Limitations

- first run downloads models and takes time
- macOS is experimental
- GPU is not the baseline support path
- CLI is the primary supported path
- Docker Desktop is required

## Verification

- `python -m unittest discover worker/tests` with `PYTHONPATH=worker/src`
- one real local smoke run
- `jobs archive` ZIP package confirmed
