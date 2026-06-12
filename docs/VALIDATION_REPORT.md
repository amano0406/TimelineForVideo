# Validation Report

Generated after current resident-worker, audio/image parity, frame-difference
VLM, export, and source safety validation.

## Status

Passed.

## Checks

```bash
python -m pytest worker/tests
python -m compileall -q worker/src worker/tests scripts
git diff --check
docker compose config
docker compose -f docker-compose.yml -f docker-compose.gpu.yml config
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build --no-deps worker
curl.exe http://127.0.0.1:19500/health
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:19500/models/list -Body "{}"
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:19500/settings/status -Body "{}"
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:19500/items/refresh -Body "{""maxItems"":1,""samplesPerVideo"":3}"
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:<temporary-port>/items/refresh -Body "{""maxItems"":1,""samplesPerVideo"":3,""ocrMode"":""off"",""audioModelMode"":""off"",""frameDiffVlmMode"":""required"",""reprocessDuplicates"":true}"
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "<parse start.ps1/stop.ps1>"
```

## Results

- Python unit tests: 82 passed.
- Compile check: passed.
- Whitespace check: passed.
- Docker compose config: passed for CPU and GPU compose layers.
- Docker image build: passed.
- Docker health: passed.
- Docker `POST /settings/status`: passed with configured roots `C:\Users\amano\Videos\`
  and `F:\Video\`.
- Model inventory unit tests: passed, including required component counts,
  compute mode, and source-safety flags.
- Token redaction tests: passed for environment-token precedence and redacted
  JSON status.
- Docker model inventory: passed, including local components, pyannote/faster-whisper
  dependencies, and redacted token status.
- Temporary GPU image validation: passed for `frame_diff_vlm` dependencies
  (`transformers`, `torchvision`, `qwen-vl-utils`, `torch`, and Pillow).
- Live Qwen3.5 frame-difference smoke test: passed in a temporary container on
  a separate port, with 2 candidate transitions, 2 analyzed transitions, 2
  changed transitions, and 0 failed transitions.
- Docker doctor: passed, including ffmpeg/ffprobe, Tesseract `jpn+eng`, and
  audio-model dependency/token status.
- Third-party notices: added for direct worker dependencies and model
  prerequisites.
- PowerShell launcher parse check: passed.
- Generated-video resident-worker smoke test: passed through the local API.
- Selected item ZIP export and selected item remove smoke tests: passed.

## Smoke Coverage

The final smoke test generated a short local sample video with audio under
`C:\Codex\tmp`, then verified:

- `POST /health` and settings/model readiness checks
- `POST /models/list`
- `POST /items/refresh` with `maxItems: 1` and `samplesPerVideo: 3`
- `POST /items/refresh` with `audioModelMode: "required"`
- `POST /items/list`
- `POST /items/download`
- `POST /items/remove` with `dryRun`
- `POST /items/remove`

The smoke test confirmed:

- `raw_outputs/frame_ocr.json` was written.
- `raw_outputs/frame_diff_vlm.json` was written in live Qwen validation.
- `timeline.json` included `frame_diff_vlm` visual events in live Qwen validation.
- frame OCR subpayloads used Image-compatible snake_case fields such as
  `has_text`, `full_text`, `block_id`, and `bbox_norm`.
- `raw_outputs/audio_analysis.json` was written.
- `artifacts/audio/source_audio.mp3` was written under `outputRoot`.
- `convert_info.json` included both `ffprobeVersion` and `ffmpegVersion`.
- `POST /items/list` reported OCR and audio-evidence counts.
- Diagnostic `audioModelMode: "auto"` recorded `not_configured` without
  inventing speaker turns or transcript text when no Hugging Face token was
  configured.
- Default required audio-model execution returned a structured failure when no
  Hugging Face token was configured.
- Required audio-model execution also fails structurally when the video has no
  audio stream.
- the ZIP contained generated item files and did not contain `.mp4` source video
  files or `.mp3` audio derivatives.
- after `POST /items/remove`, the source video still existed and its size/mtime were
  unchanged.

Temporary smoke-test files were removed after validation.
Temporary Docker containers, test image tags, and test app-data volumes created
for Qwen validation were removed after validation. The running production
TimelineForVideo container and its production app/cache volumes were not
stopped or removed.
