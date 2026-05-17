# Design Decisions

## 1. Clean Rebuild

The previous implementation is not the baseline. It was intentionally removed.

## 2. Independent Product

Do not create a shared framework with `TimelineForAudio` or
`TimelineForImage`.

## 3. Product Definition

`TimelineForVideo` v1 is a local Docker worker plus API product that reads video files and writes
structured, timeline-oriented evidence outputs.

## 4. Timeline Coordinate

Use source-video-relative time as the primary coordinate:

- `time_sec`
- `start_sec`
- `end_sec`

Absolute dates may be added only with provenance.

## 5. Source Safety

Source videos are read-only inputs. They must not be modified, copied into item
outputs, or included in exports.

## 6. v1 Analysis Scope

For v1, capture metadata, bounded visual samples, local OCR over generated frame
images, and source-safe audio evidence.

Frame OCR follows the `TimelineForImage` processing contract but is implemented
inside this repository. Video audio follows `TimelineForAudio` behavior,
including pyannote diarization and faster-whisper transcription execution paths, but is
implemented inside this repository. Do not import or share source code between
Timeline products.

Do not implement scene detection, face recognition, person recognition, or
external analysis APIs in v1.
