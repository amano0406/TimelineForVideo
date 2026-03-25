# video2timeline

Local-first video-to-timeline packaging for ChatGPT and other LLM workflows.

[Japanese README](README.ja.md) | [Sample Timeline](docs/examples/sample-timeline.en.md) | [Third-Party Notices](THIRD_PARTY_NOTICES.md) | [Model and Runtime Notes](MODEL_AND_RUNTIME_NOTES.md) | [Security And Safety](docs/SECURITY_AND_SAFETY.md) | [Release Checklist](docs/PUBLIC_RELEASE_CHECKLIST.md) | [License](LICENSE)

`video2timeline` converts local video files into structured timeline packages that are easy to review, compress, and upload to ChatGPT for downstream analysis.

The primary goal of this project is to make existing video assets usable by LLMs efficiently. In practice, that means turning local video files into structured text-first materials that can be reviewed, zipped, and handed to ChatGPT or other LLM workflows for analysis.

Typical use cases:

- meeting review
- conversation history analysis
- self-review of communication patterns
- preparing ZIP packages for ChatGPT-based summarization or longitudinal analysis

## Screenshots

### Settings

![Settings](docs/screenshots/settings-en.png)

### New Job

![New Job](docs/screenshots/new-job-en.png)

### Jobs

![Jobs](docs/screenshots/jobs-en.png)

### Run Details

![Run Details](docs/screenshots/run-details-en.png)

## What It Produces

For each run, the app generates:

- a per-media `timeline.md`
- raw transcript artifacts (`raw.json`, `raw.md`)
- screen notes and screen diffs
- `cut_map.json` to preserve original timestamps when silence trimming is used internally
- `batch-*.md` and `timeline_index.jsonl` for LLM-facing export

The intended workflow is:

1. run locally
2. review the generated timeline package
3. download the completed run as a ZIP
4. upload that ZIP to ChatGPT for analysis

## Sample Timeline

The public sample below is derived from a real generated timeline, with names and sensitive details redacted.

Full sample: [docs/examples/sample-timeline.en.md](docs/examples/sample-timeline.en.md)

```md
# Video Timeline

- Source: `/shared/inputs/example/customer-followup-call.mp4`
- Media ID: `2026-03-09-12-15-56-example`
- Duration: `70.417s`

## 00:00:11.179 - 00:00:57.194
Speech:
SPEAKER_00: Hello, this is [PERSON_A]. I am following up about the return request for [ITEM_GROUP_A]. I would like to confirm why the expected materials were missing from the package.

Screen:
OCR detected text. Top lines: Please add more detail / Speech recognition did not catch that / OBS 32.0.4 - Profile: Untitled

Screen change:
Initial frame.

## 00:00:57.174 - 00:01:03.400
Speech:
SPEAKER_00: Understood. Sorry about that.

Screen:
No major screen changes detected.

Screen change:
Omitted.
```

## Key Behavior

- Local-first. No cloud transcription is required for the normal path.
- CPU and GPU modes are both available. GPU mode is faster when the worker has NVIDIA Docker GPU access.
- Silence trimming is an internal optimization. Final timelines stay aligned to original video time.
- OCR and image notes are emitted only when screen changes are meaningful enough to matter.
- Diarization runs only when the required Hugging Face token and gated-model approval are available.
- The current GUI is intentionally conservative and runs one active job at a time.

## Interfaces

- GUI is the primary interface for normal use.
- A worker-side CLI is also available for power users and automation.
- GUI and CLI both produce the same run-directory artifacts (`request.json`, `status.json`, `result.json`, `timeline.md`, `batch-*.md`).

## Requirements

- Windows or macOS
- Docker Desktop
- internet access on first run for image and model downloads
- optional Hugging Face token if you want `pyannote` diarization
- acceptance of the required gated-model terms for `pyannote`
- NVIDIA GPU + Docker GPU support if you want GPU mode

## Quick Start

Windows:

```powershell
.\start.bat
```

macOS:

```bash
./start.command
```

Then:

1. `start.bat` / `start.command` creates `.env` automatically if it does not exist
2. set your input and output paths in `.env`
3. open `http://localhost:38090`
4. complete `Settings` first
5. choose `CPU` or `GPU` mode in `Settings`
6. save your Hugging Face token if you want diarization
7. approve the required model page
8. upload files or choose a directory
9. start a job
10. download the completed ZIP package

The start script also checks:

- whether Docker Desktop is installed
- whether the Docker engine is actually running
- whether `.env` still contains placeholder paths
- whether `web` and `worker` both reach a running state
- whether the local web UI responds before the browser is opened
- whether an NVIDIA GPU is present, and if so, it starts the worker with GPU access enabled

Stop:

```powershell
.\stop.bat
```

## Supported Input Formats

Primary support:

- `.mp4`
- `.mov`
- `.m4v`
- `.avi`
- `.mkv`
- `.webm`

Actual decoding depends on the `ffmpeg` build available in the runtime image.

## Localization

The UI shell includes a language switcher in the sidebar.

Current supported locales:

- `ja`
- `en`
- `zh-CN`
- `zh-TW`
- `ko`
- `es`
- `fr`
- `de`
- `pt`

Browser language is used as the default when possible. Manual selection is stored in a cookie. Supported language aliases and regional mappings are defined in [web/Resources/Locales/languages.json](web/Resources/Locales/languages.json).

## CLI

The repository also includes a worker CLI for direct local execution and automation.

Current commands include:

- `settings status`
- `settings save`
- `jobs create`
- `jobs list`
- `jobs show`
- `jobs run`
- `scan`
- `compare-images`
- `run-job`
- `daemon`

Example:

```powershell
$env:PYTHONPATH=".\worker\src"
python -m video2timeline_worker settings status
python -m video2timeline_worker settings save --token hf_xxx --terms-confirmed
python -m video2timeline_worker jobs create --file C:\path\to\clip.mp4
python -m video2timeline_worker jobs create --directory C:\path\to\folder
python -m video2timeline_worker jobs create --source-id primary
python -m video2timeline_worker jobs list
```

The GUI remains the recommended public entry point. The CLI can create and run the same job contract directly from local files, directories, or configured source roots, and is intended for scripting, debugging, and power-user workflows.

## Output Layout

```text
run-YYYYMMDD-HHMMSS-xxxx/
  request.json
  status.json
  result.json
  manifest.json
  RUN_INFO.md
  TRANSCRIPTION_INFO.md
  NOTICE.md
  logs/
    worker.log
  media/
    <media-id>/
      source.json
      audio/
        extracted.mp3
        trimmed.mp3
        cut_map.json
      transcript/
        raw.json
        raw.md
      screen/
        screenshot_01.jpg
        screenshots.jsonl
        screen_diff.jsonl
      timeline/
        timeline.md
  llm/
    timeline_index.jsonl
    batch-001.md
```

## Testing

Current test coverage is intentionally lightweight:

- Python worker unit tests for contracts, screen timestamping, and timeline rendering
- Playwright-based E2E smoke tests for the ASP.NET Core UI
- manual smoke runs with real local jobs

Run worker unit tests:

```powershell
$env:PYTHONPATH=".\worker\src"
python -m unittest discover .\worker\tests
```

Run browser E2E tests:

```powershell
.\scripts\test-e2e.ps1
```

Enable commit-time lint checks:

```powershell
git config core.hooksPath .githooks
```

The current Playwright smoke suite covers:

- root redirect into the gated job flow
- settings page rendering and theme options
- jobs list rendering with completed runs
- completed run details
- ZIP download from a completed run

## License

This repository is licensed under the MIT License. See [LICENSE](LICENSE).

Third-party code and runtime notes:

- [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)
- [MODEL_AND_RUNTIME_NOTES.md](MODEL_AND_RUNTIME_NOTES.md)

## Status

`video2timeline` v1 is stable for local processing. In this development environment, GPU execution was verified on `NVIDIA GeForce RTX 4070`, driver `560.94`, with Docker GPU access available.
