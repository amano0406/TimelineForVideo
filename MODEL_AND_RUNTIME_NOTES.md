# Model and Runtime Notes

This document explains what `video2timeline` downloads or expects at runtime and what users should know before running the app locally.

## CPU-First Public Release

The current public release is CPU-first.

- CPU processing is the supported path today.
- GPU acceleration is planned, but it is not part of the current public release.
- The UI may mention GPU support as coming soon, but current documentation and validation target CPU execution.

## Models Used by the Worker

`video2timeline` uses a local-first pipeline and downloads model/data assets only when they are actually needed.

Current main components:

- `whisperx`
  - transcription
  - timestamp alignment
  - optional diarization integration
- `EasyOCR`
  - OCR for screenshots when a frame is important enough to inspect
- `pytesseract` / Tesseract
  - supplemental OCR backend
- `florence-community/Florence-2-base`
  - screenshot captioning / image description when screen changes are important
- `pyannote/speaker-diarization-community-1`
  - optional speaker diarization

## First-Run Downloads

On first use, the worker may download:

- Python package dependencies
- Hugging Face model weights
- OCR-related model/data files

These downloads are cached for reuse. The exact cache location depends on the runtime environment. In the Docker setup, cache volumes are mounted so the app does not need to download the same assets on every restart.

## Hugging Face Token and Gated Approval

Speaker diarization is optional, but if you want it, two things are required:

1. a Hugging Face access token
2. approval for the gated `pyannote/speaker-diarization-community-1` model page

Without those two conditions, the app does not fail the whole job. It continues with transcription and timeline generation, but without speaker diarization.

## OCR and Image Notes

The app does not run OCR or captioning on every frame.

Current behavior:

- frames are sampled from the video
- lightweight screen-diff logic classifies each frame change
- OCR and image-caption steps run only on the initial frame or on major screen changes
- minor cursor movement or trivial UI movement is intentionally suppressed

This keeps exported timelines smaller and more useful for LLM workflows.

## Silence Trimming

Silence trimming is used internally as a processing optimization.

- It can reduce unnecessary transcription work.
- It does not redefine the authoritative timeline.
- Final exported timeline entries are aligned back to original media time.
- `cut_map.json` is written so the mapping remains inspectable.

## Intended Workflow

The generated run output is designed to be reviewed locally, then compressed and uploaded to ChatGPT or another LLM for follow-up analysis.

Typical follow-up use cases:

- meeting review
- topic extraction
- communication analysis
- personal conversation review over time
- turning many local recordings into a structured corpus for downstream prompts

## Public Samples

The sample timelines in this repository are based on real generated output, but names and sensitive details are redacted.

- English sample: [docs/examples/sample-timeline.en.md](docs/examples/sample-timeline.en.md)
- Japanese sample: [docs/examples/sample-timeline.ja.md](docs/examples/sample-timeline.ja.md)
