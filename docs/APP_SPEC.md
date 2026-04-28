# App Spec

## Goal

`TimelineForVideo` converts local video files into timeline-oriented text that can be handed to ChatGPT or another LLM.

The system prioritizes:

- simple input selection for the user
- readable run output for LLM workflows
- local processing over cloud dependencies

## App Model

- `worker`: Python
- interface: CLI commands
- storage: fixed local folders mounted into Docker

## User Flow

1. put one or more videos under `data/input`
2. run `jobs create`
3. inspect the generated job under `data/output`
4. run `jobs archive` when a ZIP handoff package is needed

## Input Model

v1 supports:

- fixed Docker input root: `/data/input`
- direct CLI file paths inside the runtime

The CLI expands selected files or directories into concrete input items before writing `request.json`.

## Current Docker Storage Contract

The current Docker contract uses repo-local fixed folders mounted into the worker container:

- input root: `data/input` on the host, mounted as `/data/input`
- run output root: `data/output` on the host, mounted as `/data/output`
- app state and secrets root: `data/app-data` on the host, mounted as `/data/app-data`
- model caches: `data/cache/huggingface` and `data/cache/torch`

Previous named Docker volumes are no longer the active runtime contract.

## Output Model

Every run writes:

- `request.json`
- `status.json`
- `result.json`
- `manifest.json`
- `RUN_INFO.md`
- `TRANSCRIPTION_INFO.md`
- `NOTICE.md`

Each processed media item writes:

- `source.json`
- `audio/trimmed.mp3`
- `audio/cut_map.json`
- `transcript/raw.json`
- `transcript/raw.md`
- `screen/screenshots.jsonl`
- `screen/screen_diff.jsonl`
- `timeline/timeline.md`

LLM export writes:

- `llm/timeline_index.jsonl`
- `llm/batch-*.md`

## Progress Model

`status.json` records:

- `videos_done / videos_total`
- `videos_skipped`
- `videos_failed`
- `current_stage`
- `current_media`
- `processed_duration_sec / total_duration_sec`
- `estimated_remaining_sec`

ETA is derived from processed media duration versus elapsed wall time.

## Settings

Stored in `data/app-data/settings.json`:

- input roots
- output roots
- video extensions
- Hugging Face terms confirmation

Stored separately in `data/app-data/secrets/huggingface.token`:

- Hugging Face token

## Profile

v1 uses a single fixed profile:

- `quality-first`

There is no user-facing model picker in v1.

## CPU / GPU

- CPU path is implemented
- GPU is optional and best-effort on supported NVIDIA + Docker GPU setups

## Duplicate Handling

- duplicate key: file SHA-256
- default policy: skip
- optional override: reprocess all duplicates

## Diarization

- use `pyannote` only if token and terms confirmation are present
- otherwise continue without diarization
- do not use GPL-dependent `simple-diarizer`
