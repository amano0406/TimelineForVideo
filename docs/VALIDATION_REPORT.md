# Validation Report

Generated after current resident-worker, audio/image parity, export, and source
safety validation.

## Status

Passed.

## Checks

```bash
PYTHONPATH=worker/src python3 -m unittest discover -s worker/tests -v
python3 -m compileall -q worker/src worker/tests
git diff --check
docker compose config
docker compose -f docker-compose.yml -f docker-compose.gpu.yml config
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build --no-deps worker
curl.exe http://127.0.0.1:19500/health
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:19500/models/list -Body "{}"
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:19500/settings/status -Body "{}"
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:19500/items/refresh -Body "{""maxItems"":1,""samplesPerVideo"":3}"
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "<parse start.ps1/stop.ps1>"
```

## Results

- Python unit tests: 55 passed.
- Compile check: passed.
- Whitespace check: passed.
- Docker compose config: passed for CPU and GPU compose layers.
- Docker image build: passed.
- Docker health: passed.
- Docker settings status: passed with configured roots `C:\Users\amano\Videos\`
  and `F:\Video\`.
- Model inventory unit tests: passed, including required component counts,
  compute mode, and source-safety flags.
- Token redaction tests: passed for environment-token precedence and redacted
  JSON status.
- Docker model inventory: passed, including local components, pyannote/faster-whisper
  dependencies, and redacted token status.
- Docker doctor: passed, including ffmpeg/ffprobe, Tesseract `jpn+eng`, and
  audio-model dependency/token status.
- Third-party notices: added for direct worker dependencies and model
  prerequisites.
- PowerShell launcher parse check: passed.
- Generated-video resident-worker smoke test: passed with `serve --once`.
- Selected item ZIP export and selected item remove smoke tests: passed.

## Smoke Coverage

The final smoke test generated a short local sample video with audio under
`C:\Codex\tmp`, then verified:

- `doctor`
- `models list`
- `serve --once --max-items 1 --samples-per-video 3`
- `audio analyze --audio-model-mode required`
- `items list`
- `items download`
- `items remove --dry-run`
- `items remove`

The smoke test confirmed:

- `raw_outputs/frame_ocr.json` was written.
- frame OCR subpayloads used Image-compatible snake_case fields such as
  `has_text`, `full_text`, `block_id`, and `bbox_norm`.
- `raw_outputs/audio_analysis.json` was written.
- `artifacts/audio/source_audio.mp3` was written under `outputRoot`.
- `convert_info.json` included both `ffprobeVersion` and `ffmpegVersion`.
- `items list` reported OCR and audio-evidence counts.
- Diagnostic `--audio-model-mode auto` recorded `not_configured` without
  inventing speaker turns or transcript text when no Hugging Face token was
  configured.
- Default required audio-model execution returned a structured failure when no
  Hugging Face token was configured.
- Required audio-model execution also fails structurally when the video has no
  audio stream.
- the ZIP contained generated item files and did not contain `.mp4` source video
  files or `.mp3` audio derivatives.
- after `items remove`, the source video still existed and its size/mtime were
  unchanged.

Temporary smoke-test files were removed after validation.
