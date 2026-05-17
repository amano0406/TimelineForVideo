# Acceptance Criteria

## Required Behavior

- `settings init/status/save` work.
- `health` works.
- `doctor` checks runtime and configured paths.
- `models list` reports Audio-compatible model rows, pipeline generation
  signature, Video runtime components, and pyannote/faster-whisper readiness.
- `models list --include-remote --json` attaches Hugging Face metadata to
  Hugging Face model rows.
- `files list` discovers video files from file and directory inputs.
- `sample frames --max-items 1` extracts bounded frame evidence.
- `ocr frames --max-items 1` writes local frame OCR evidence.
- `audio analyze --max-items 1` writes source-safe audio evidence.
- `audio analyze --audio-model-mode required` fails structurally when token or
  model prerequisites are missing.
- `process all --max-items 1` runs the full local evidence pipeline.
- `items refresh --max-items 1` processes one sample video.
- `serve --once --max-items 1` runs one resident-worker refresh cycle.
- `runs list` and `runs show` expose worker run state.
- `items list` shows generated items.
- `items download` creates a ZIP.
- `items download --item-id <id>` exports selected generated items.
- ZIP exports do not include source videos.
- ZIP exports do not include generated MP3 audio derivatives.
- `items remove --dry-run` reports generated artifacts only.
- `items remove` removes generated artifacts only.
- `items remove --item-id <id>` removes selected generated item artifacts only.
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
