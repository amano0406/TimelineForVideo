# TimelineForVideo Rebuild TODO

## Active Scope

Target video input roots:

- `C:\Users\amano\Videos\`
- `F:\Video\`

## Checklist

- [x] Confirm current repo and Docker state.
- [x] Update local `settings.json` to target the two video input roots.
- [x] Change `serve` from idle loop to resident refresh worker.
- [x] Make `items refresh` the normal full processing entrypoint.
- [x] Add minimal internal lock, catalog, run status, and skip-no-changes behavior.
- [x] Add `serve --once` for deterministic worker testing.
- [x] Add `runs list` and `runs show` for worker run inspection.
- [x] Expand Image parity beyond OCR into frame-level visual features.
- [x] Add GPU worker flavor for Video audio models, matching Audio's CPU/GPU split.
- [x] Add item-selected download/remove options.
- [x] Add `--page` / `--page-size` to list-style worker commands for Timeline UI integration.
- [x] Run Docker build and resident-worker smoke check after this change set.
- [x] Do final source-safety and ZIP exclusion validation.

## Current Correction

`items refresh` now runs the local Video evidence pipeline for changed source
videos:

1. discover configured source videos
2. select changed or incomplete items using source fingerprint + catalog state
3. extract bounded frame samples and contact sheet
4. run frame OCR over generated frame artifacts
5. extract frame visual features from generated frame artifacts
6. extract generated audio evidence and TimelineForAudio-compatible audio models
7. write `video_record.json`, `timeline.json`, `convert_info.json`, and raw outputs
8. record run state under the internal app-data area

`serve` runs the same refresh loop continuously. It no longer exists only to
keep the container alive.
