# TimelineForVideo

Turn video files you already have into timeline markdown packages that are easier to hand to ChatGPT or other LLM tools.

[Japanese README](README.ja.md) | [Sample Timeline](docs/examples/sample-timeline.en.md) | [Third-Party Notices](THIRD_PARTY_NOTICES.md) | [Model and Runtime Notes](MODEL_AND_RUNTIME_NOTES.md) | [Security And Safety](docs/SECURITY_AND_SAFETY.md) | [Release Checklist](docs/PUBLIC_RELEASE_CHECKLIST.md) | [License](LICENSE)

## Public Release Status

The current public release line is `TimelineForVideo v0.4.0 Tech Preview`.

Current public contract:

- baseline support: Windows + Docker Desktop + CPU mode
- macOS: source-based experimental path
- GPU mode: optional, NVIDIA-only, best-effort
- speaker diarization: optional, requires a Hugging Face token plus gated approval for `pyannote/speaker-diarization-community-1`
- this is a local-first CLI tool, not a hosted SaaS product

## What This App Does

This app takes video files on your computer and turns them into timeline files and a ZIP package that is easier to upload to an LLM.

Inside the app, the processing is simple:

1. it listens to the speech in the video and turns it into text
2. it checks what was on the screen and extracts useful text or screen notes
3. it puts speech and screen changes into a timeline
4. it puts the final result into a ZIP file

You do not need to know model names or internal details to use it.

## Typical Uses

- meeting review
- conversation history analysis
- family or friend conversation analysis
- screen recording review
- turning old video archives into LLM-ready text material

## Basic Flow

1. put your video files under `data/input`
2. run a CLI command
3. wait for completion  
   Advanced AI processing takes some time
4. create the ZIP package with `jobs archive`
5. upload that ZIP to ChatGPT, Claude, or another LLM if you want analysis

Examples of what you can ask an LLM after that:

- summarize the meeting
- extract decisions and action items
- review how I explained things
- analyze conversation patterns
- turn video history into searchable notes

## What Is Inside The ZIP

The ZIP is intentionally compact.

Most users only need:

- `README.md`
- `TRANSCRIPTION_INFO.md`
- `timelines/<captured-datetime>.md`
- `FAILURE_REPORT.md` when some items fail or warnings need to be preserved
- `logs/worker.log` when the job includes failure or warning artifacts

Example:

```text
TimelineForVideo-export.zip
  README.md
  TRANSCRIPTION_INFO.md
  timelines/
    2026-03-26 18-00-00.md
    2026-03-25 09-14-12.md
```

Each markdown file inside `timelines/` is one video timeline.

If a job finishes with partial success, the ZIP can still be created. In that case it contains successful timelines plus the failure report and worker log.

## Reuse And Rerun Behavior

When you process files that were already processed before, the CLI checks for reusable results first.

- if reusable timelines are still available, the default behavior is to reuse them
- use `--reprocess-duplicates` when you intentionally want a fresh run
- use `settings save` before a new run when you want to change compute mode, quality, or diarization-related setup

## Internal Working Files vs ZIP Output

Inside Docker, the app keeps a larger working folder for processing, logs, and intermediate files.

That internal folder can contain:

- request and status JSON files
- worker logs
- intermediate transcript files
- screenshot notes
- temporary processing files

Those files are for the app itself. The archive ZIP is the reduced handoff package for LLM use.

## Quick Start

Windows:

```powershell
.\start.bat
```

This prepares the Docker-based CLI runtime and creates the fixed local folders.

macOS:

```bash
./start.command
```

This path is available as an experimental source-based setup in `v0.4.0`. It prepares the Docker-based CLI runtime.

Then put videos in:

```text
data/input/
```

Create and run a job:

```powershell
docker compose run --rm worker jobs create --directory /data/input
```

List jobs:

```powershell
docker compose run --rm worker jobs list
```

Create the ZIP package:

```powershell
docker compose run --rm worker jobs archive --job-id job-YYYYMMDD-HHMMSS-xxxxxxxx
```

Results are written under `data/output`.

## Requirements

- Windows for the primary supported path
- macOS only if you are comfortable with an experimental source-based setup
- Docker Desktop
- internet access on first run for container and model downloads
- optional Hugging Face token if you want `pyannote` diarization
- optional gated-model approval for `pyannote`
- NVIDIA GPU plus Docker GPU access if you want GPU mode on a best-effort basis

## Compute Modes

The public release baseline is CPU mode.

- `CPU`
  - works on more machines
  - slower
- `GPU`
  - requires NVIDIA GPU support inside Docker
  - faster for the main ML workloads
  - best-effort in the `v0.4.0` public release line

Processing quality:

- `Standard`
  - `WhisperX medium`
- `High`
  - `WhisperX large-v3`
  - available only when GPU mode is enabled and enough VRAM is detected

In this development environment, GPU execution was verified on `NVIDIA GeForce RTX 4070` with Docker GPU access.

## Supported Input Formats

Primary support:

- `.mp4`
- `.mov`
- `.m4v`
- `.avi`
- `.mkv`
- `.webm`

Actual decoding still depends on the `ffmpeg` build inside the runtime image.

## CLI

The CLI is the supported entry point.

Common commands:

- `settings status`
- `settings save`
- `jobs create`
- `jobs list`
- `jobs show`
- `jobs run`
- `jobs archive`

Example:

```powershell
docker compose run --rm worker settings status
docker compose run --rm worker settings save --token hf_xxx --terms-confirmed
docker compose run --rm worker settings save --compute-mode cpu --processing-quality standard
docker compose run --rm worker jobs create --file /data/input/clip.mp4
docker compose run --rm worker jobs create --directory /data/input
docker compose run --rm worker jobs list
docker compose run --rm worker jobs archive --job-id job-YYYYMMDD-HHMMSS-xxxxxxxx
```

`jobs archive` creates the reduced ZIP-style handoff package.

## Testing

Current test coverage is intentionally lightweight:

- Python worker unit tests
- manual smoke runs with real local jobs

Run worker unit tests:

```powershell
$env:PYTHONPATH=".\worker\src"
python -m unittest discover .\worker\tests
```

Enable commit-time lint checks:

```powershell
git config core.hooksPath .githooks
```

## License

This repository is licensed under the MIT License. See [LICENSE](LICENSE).
