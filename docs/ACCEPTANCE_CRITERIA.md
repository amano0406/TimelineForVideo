# Acceptance Criteria

## Required Behavior

- `POST /settings/init`, `POST /settings/status`, and `POST /settings/save` work.
- `health` works.
- `doctor` checks runtime and configured paths.
- `POST /models/list` reports Audio-compatible model rows, pipeline generation
  signature, Video runtime components, and pyannote/faster-whisper readiness.
- `POST /models/list` with `includeRemote` attaches Hugging Face metadata to
  Hugging Face model rows.
- `POST /files/list` discovers video files from file and directory inputs.
- `POST /items/refresh` extracts bounded frame evidence.
- `POST /items/refresh` writes local frame OCR evidence.
- `POST /items/refresh` writes source-safe audio evidence.
- `POST /items/refresh` with `audioModelMode: "required"` fails structurally when token or
  model prerequisites are missing.
- `POST /items/refresh` runs the full local evidence pipeline for one sample video when `maxItems` is 1.
- `POST /items/list` shows generated items.
- `POST /items/download` creates a ZIP.
- `POST /items/download` with `itemIds` exports selected generated items.
- ZIP exports do not include source videos.
- ZIP exports do not include generated MP3 audio derivatives.
- `POST /items/remove` with `dryRun` reports generated artifacts only.
- `POST /items/remove` removes generated artifacts only.
- `POST /items/remove` with `itemIds` removes selected generated item artifacts only.
- Source videos remain after remove.

## Required Tests

- settings tests
- discovery tests
- sampling tests
- frame OCR tests
- audio analysis tests
- audio model mode tests
- model inventory tests
- ffprobe parsing tests using fixture JSON
- output record shape tests
- ZIP source video exclusion tests
- ZIP MP3 derivative exclusion tests
- selected item download/remove tests
- remove source-safety tests
- generated sample video smoke test

## Required Docs

- `README.md`
- local API documentation
- `docs/OUTPUTS.md`
- `docs/PIPELINE.md`
- `docs/RUNTIME.md`
- `docs/SAFETY.md`
- `docs/THIRD_PARTY_NOTICES.md`
- `docs/TESTING.md`
