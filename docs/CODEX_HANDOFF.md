# TimelineForVideo Clean Rebuild Handoff

## Current State

This repository was deliberately emptied on commit `81276ac`:

```text
Empty TimelineForVideo repository for rebuild
```

Do not restore the previous codebase. Start from a clean product design.

## Product Goal

`TimelineForVideo` v1 should process local video files or video directories and
write timeline-oriented evidence packages.

The first useful version is not a full video-understanding system. It is a
safe, local, structured evidence generator.

The old TimelineForVideo implementation remains out of scope and must not be
restored. `TimelineForAudio` and `TimelineForImage` are reference products for
processing contracts and behavior, but their source code is not imported, shared,
or copied as a common implementation.

## v1 Scope

Build:

- Windows-friendly local API
- Docker-first runtime
- settings for input roots and output root
- video file discovery from files and directories
- ffprobe metadata capture
- bounded frame sampling
- extracted review frames
- cheap adjacent-frame visual transition gate
- optional local frame-difference VLM analysis over generated adjacent frames
- local OCR over generated frame images, following the TimelineForImage
  processing contract inside this repo
- source-safe audio derivative analysis plus pyannote/faster-whisper audio-model execution
  paths, following TimelineForAudio behavior inside this repo
- contact sheet
- per-item structured outputs
- ZIP export excluding source videos
- generated-artifact remove command
- tests and smoke test with a generated sample video

Do not build in v1:

- hosted service
- web UI
- old TimelineForVideo compatibility layer
- scene detection
- face/person recognition
- external API analysis or hosted VLM calls
- source video conversion

## Reference Sources

Read only as needed:

- `C:\apps\TimelineForAudio`
- `C:\apps\TimelineForImage`

The ChatGPT design discussion was captured through DockForChatGPT:

```text
C:\Codex\workspaces\dockforchatgpt\chat_conversations\snapshots\20260506-114835-69f96218-7de4-83a9-b46b-d660584e0639-a7f37b4b-62b8-443c-905d-c71a0e9c6d78.json
```

Use references for concepts and contracts. Do not import reference packages or
create a shared framework. Video-specific implementations live in this repo.

## Implementation Stance

Keep the first product small and rebuildable:

- one repo
- one worker package
- one worker API action surface
- clear JSON outputs
- generated artifacts separated from source videos
- direct smoke test path

Avoid a shared framework with other Timeline products.
