# Output Contract

## Output Root

```text
<outputRoot>/
  items/
    <item-id>/
      video_record.json
      timeline.json
      convert_info.json
      raw_outputs/
        ffprobe.json
        frame_samples.json
        frame_ocr.json
        frame_diff_vlm.json
        audio_analysis.json
        activity_map.json
      artifacts/
        contact_sheet.jpg
        frames/
          frame-000001.jpg
          frame-000002.jpg
        ocr/
          frame-000001-ocr.jpg
        audio/
          source_audio.mp3
  downloads/
  latest/
```

## Required Item Files

- `video_record.json`
- `timeline.json`
- `convert_info.json`
- `raw_outputs/ffprobe.json`
- `raw_outputs/frame_samples.json`
- `raw_outputs/frame_ocr.json`
- `raw_outputs/frame_diff_vlm.json`
- `raw_outputs/audio_analysis.json`
- `raw_outputs/activity_map.json`
- `artifacts/contact_sheet.jpg`

## video_record.json

Required top-level keys:

- `schema_version`
- `record_id`
- `asset`
- `timeline`
- `video`
- `audio`
- `activity`
- `visual`
- `processing`
- `segments`
- `frames`
- `text`
- `review`

Schema version:

```text
timeline_for_video.video_record.v1
```

## timeline.json

Required lanes:

- `visual`
- `audio`
- `activity`
- `text`

Initial event types:

- `video_observed`
- `video_interval`
- `frame_sample`
- `frame_transition_gate`
- `frame_diff_vlm`
- `audio_reference`
- `audio_derivative`
- `audio_speech_candidate`
- `activity_candidate_interval`
- `activity_skipped_interval`
- `frame_ocr_text`
- `audio_transcript_segment`

Frame OCR text evidence uses the same OCR subpayload field names as
TimelineForImage: `has_text`, `full_text`, `block_id`, and `bbox_norm`.
Generated frame visual features are attached to frame records and visual lane
events under `visual`, including `quality`, `color_palette`, and a 3x3 color
`grid`.
Adjacent sampled frame transitions are evaluated by a cheap visual gate in
`raw_outputs/frame_samples.json` under `visualGate`; visual lane events expose
the decision and whether the transition should be sent to a heavier VLM.
When enabled and locally available, the frame-difference VLM writes
`raw_outputs/frame_diff_vlm.json` and emits `frame_diff_vlm` visual lane events
for analyzed adjacent-frame transitions. The VLM stage must run locally and must
not call an external analysis API.
Audio transcript evidence uses Whisper `text` segments. pyannote diarization is
used only to attach speaker labels; it must not split, delete, or rewrite
Whisper text. The audio-model input is a temporary normalized WAV. The
generated MP3 audio derivative is only a review artifact and must not be used as
the pyannote/faster-whisper input.

## convert_info.json

Must include:

- product name and version
- generated timestamp
- source fingerprint
- source file identity
- ffmpeg/ffprobe version
- pipeline version
- generation signature
- sampling parameters
- image processing summary including frame OCR and frame visual features
- audio processing summary
- output files
- counts
- warnings
- `source_video_modified: false`

## Export Rule

ZIP exports must not include source videos.

The generated MP3 audio derivative is retained under `outputRoot` for local
review and generated-artifact removal, but is not included in ZIP exports.
Temporary normalized WAV files are processing intermediates and must not remain
in master artifacts or export ZIPs.
