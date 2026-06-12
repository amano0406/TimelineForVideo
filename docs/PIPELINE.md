# Pipeline

## 1. Configure

`POST /settings/save` defines input video roots and `outputRoot`.

## 2. Discover

`POST /files/list` scans configured input roots for supported video extensions.

Supported extensions:

```text
.avi .m4v .mkv .mov .mp4 .webm .wmv
```

## 3. Probe

`probe list` runs ffprobe read-only and derives source identity, source
fingerprint, and item id from path/stat metadata.

## 4. Inspect Components

`POST /models/list` reports an Audio-compatible `models` array and
`pipeline.generation_signature` for model license/access review, plus a Video
`components` array for runtime readiness.
`POST /models/list` with `includeRemote` fetches Hugging Face metadata. It does
not process source videos.

## 5. Sample

The frame sampling stage extracts a bounded set of review frames and a contact sheet.
It does not extract all frames.

The same stage also computes a cheap adjacent-frame visual gate under
`raw_outputs/frame_samples.json` as `visualGate`. This gate is not a VLM result.
It classifies sampled frame transitions as `skip_same`, `skip_volatile_only`,
`uncertain`, or `needs_vlm` so a heavier model such as `Qwen/Qwen3.5-4B` can be
run only for meaningful or uncertain transitions.

## 6. Frame Diff VLM

`frame_diff_vlm` reads `visualGate` candidates from
`raw_outputs/frame_samples.json` and writes `raw_outputs/frame_diff_vlm.json`.
It sends only `needs_vlm` and `uncertain` adjacent-frame transitions to the local
Qwen3.5-class VLM. High-confidence `skip_same` and `skip_volatile_only`
transitions are not sent to the heavy model.

Execution modes are controlled on the existing refresh request:

- `frameDiffVlmMode: "auto"`: run when local dependencies are installed, otherwise write a structured skip.
- `frameDiffVlmMode: "required"`: fail the step if dependencies, model loading, or JSON parsing fail.
- `frameDiffVlmMode: "off"`: write a disabled result without running the model.

The stage is local-only. It does not call an external analysis API and it does
not perform face or person recognition.

## 7. Frame OCR

The OCR stage runs local Tesseract OCR over generated frame sample artifacts. This
follows the TimelineForImage OCR contract, but the implementation is local to
TimelineForVideo.

The same pass records bounded visual features for each generated frame:
brightness, contrast, dominant colors, and a 3x3 average-color grid.

## 8. Audio Analysis

The audio analysis stage extracts a generated MP3 derivative under `outputRoot` for
review, creates a temporary normalized WAV for model processing, runs ffmpeg
speech candidate detection on that WAV, and runs pyannote diarization plus
faster-whisper transcription over the same WAV. Whisper decides what was said;
pyannote is used only to attach speaker labels by time overlap, without
splitting, deleting, or rewriting Whisper text. The temporary WAV is removed
after processing. The source video is not modified or copied.

## 9. Refresh Items

`activity map` combines the audio speech candidates with five-minute visual
sentinel deltas. It writes `raw_outputs/activity_map.json` with active
candidate intervals and inactive intervals that can be skipped because the
audio is silent and the visual signal is static.

`POST /items/refresh` is the normal product processing entrypoint. It discovers
configured source videos, checks the internal catalog, and processes changed or
incomplete items only.

For selected candidates it runs:

1. bounded frame sampling
2. frame OCR over generated frame artifacts
3. generated audio evidence and TimelineForAudio-compatible audio models
4. activity mapping
5. optional frame-difference VLM comments for gated adjacent frames
6. item record assembly

It writes:

- `video_record.json`
- `timeline.json`
- `convert_info.json`
- `raw_outputs/ffprobe.json`
- `raw_outputs/activity_map.json`
- `raw_outputs/frame_diff_vlm.json`

The internal catalog, lock, worker status, and run status are stored under the
Docker app-data volume. They are not source inputs and are not exported.

## 10. Full Processing

The full processing pipeline forces the same stages over the selected batch. It is primarily
for manual validation and reprocessing.

## 11. Export Or Remove

`POST /items/download` creates a generated-artifact ZIP and updates `latest`.
`POST /items/remove` deletes only known generated artifacts.
