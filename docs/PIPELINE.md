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

## 6. Frame OCR

The OCR stage runs local Tesseract OCR over generated frame sample artifacts. This
follows the TimelineForImage OCR contract, but the implementation is local to
TimelineForVideo.

The same pass records bounded visual features for each generated frame:
brightness, contrast, dominant colors, and a 3x3 average-color grid.

## 7. Audio Analysis

The audio analysis stage extracts a generated MP3 derivative under `outputRoot` for
review, creates a temporary normalized WAV for model processing, runs ffmpeg
speech candidate detection on that WAV, and runs pyannote diarization plus
faster-whisper transcription over the same WAV. Whisper decides what was said;
pyannote is used only to attach speaker labels by time overlap, without
splitting, deleting, or rewriting Whisper text. The temporary WAV is removed
after processing. The source video is not modified or copied.

## 8. Refresh Items

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
5. item record assembly

It writes:

- `video_record.json`
- `timeline.json`
- `convert_info.json`
- `raw_outputs/ffprobe.json`
- `raw_outputs/activity_map.json`

The internal catalog, lock, worker status, and run status are stored under the
Docker app-data volume. They are not source inputs and are not exported.

## 9. Full Processing

The full processing pipeline forces the same stages over the selected batch. It is primarily
for manual validation and reprocessing.

## 10. Export Or Remove

`POST /items/download` creates a generated-artifact ZIP and updates `latest`.
`POST /items/remove` deletes only known generated artifacts.
