# Implementation Milestones

## Milestone 0: Read-Only Plan

- inspect the empty repo state
- read the handoff docs
- inspect reference products only as needed
- propose implementation plan
- do not modify code

## Milestone 1: Scaffold

- Python package
- Dockerfile
- docker-compose
- Windows launcher
- settings file
- `health`
- `POST /settings/init`, `POST /settings/status`, `POST /settings/save`

## Milestone 2: Discovery And Doctor

- input file and directory support
- recursive discovery
- supported video extensions
- `POST /files/list`
- `doctor`

## Milestone 3: ffprobe And Source Identity

- ffprobe execution
- `raw_outputs/ffprobe.json`
- metadata parsing
- source fingerprint
- item id

## Milestone 4: Visual Sampling

- bounded sampling
- frame extraction
- `raw_outputs/frame_samples.json`
- frame artifacts
- contact sheet

## Milestone 5: Records And Items

- `video_record.json`
- `timeline.json`
- `convert_info.json`
- `POST /items/refresh`
- `POST /items/list`

## Milestone 6: Export And Remove

- `POST /items/download`
- `latest/`
- `POST /items/remove` with `dryRun`
- `POST /items/remove`
- source-safety tests

## Milestone 7: Docs And Validation

- unit tests
- smoke test
- README
- docs
- final validation report

## Milestone 8: Audio/Image Processing Parity

- frame OCR over generated frame artifacts, following TimelineForImage behavior
  without source sharing
- audio derivative, speech candidate evidence, pyannote diarization, and
  faster-whisper transcription execution paths, following TimelineForAudio behavior without
  source sharing
- OCR stage
- audio analysis stage
- full processing pipeline
- record, timeline, export, and remove integration

## Milestone 9: Resident Worker Parity Correction

- keep the changed-video worker loop behind explicit API requests
- make `POST /items/refresh` the normal full processing entrypoint
- add internal catalog, lock, run status, and skip-no-changes behavior
- expose run inspection through API/debug output
- document the remaining parity gaps in `docs/VIDEO_REBUILD_TODO.md`
