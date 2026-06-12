# Outputs

All generated files are written under `outputRoot`. Source videos are read-only
inputs and are never copied into export ZIPs.

The examples below are intentionally compact. Arrays such as `frames`,
`segments`, and `files` can contain many rows in real output.

## Directory Layout

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
        ocr/
          frame-000001-ocr.jpg
        audio/
          source_audio.mp3
  downloads/
    timeline-for-video-items-<timestamp>.zip
  latest/
    items.zip
    download_manifest.json
```

## Field Conventions

- `itemId` / `record_id`: stable video item id derived from source path, file
  size, and modified time.
- `sourceIdentity`: source path, resolved path, input root, extension, size,
  and modified time.
- `sourceFingerprint`: stat-based fingerprint used to identify changed videos.
- `timeSec`, `startSec`, `endSec`, `durationSec`: seconds relative to the
  source video.
- `bbox_norm`: OCR bounding box as `[left, top, right, bottom]`, normalized to
  `0.0` through `1.0`.
- `sourceVideoModified` / `source_video_modified`: always `false` for generated
  output.
- Paths in Docker JSON usually use resolved Linux paths such as `/mnt/c/...`.
  Windows-configured paths are retained where the command reports
  `configuredPath`.

## Main Item Files

### `video_record.json`

Primary item record for consumers that want one document per source video.

```json
{
  "schema_version": "timeline_for_video.video_record.v1",
  "record_id": "video-260b3148c51df872",
  "asset": {
    "source_path": "C:\\apps\\Timeline\\data\\input\\video\\clip.mp4",
    "source_fingerprint": "sha256:...",
    "source_identity": {
      "sourcePath": "C:\\apps\\Timeline\\data\\input\\video\\clip.mp4",
      "resolvedPath": "/mnt/c/apps/Timeline/data/input/video/clip.mp4",
      "inputRoot": "C:\\apps\\Timeline\\data\\input\\video",
      "extension": ".mp4",
      "sizeBytes": 41953444,
      "modifiedTime": "2026-05-13T06:59:16.135547+00:00"
    },
    "source_video_modified": false
  },
  "timeline": {
    "coordinate": "source_video_relative_time",
    "timeline_json": "/mnt/c/apps/Timeline/data/to_text/video/items/video-.../timeline.json"
  },
  "video": {
    "format": {
      "durationSec": 120.4,
      "sizeBytes": 41953444,
      "bitRate": 2789000
    },
    "streams": [
      {
        "index": 0,
        "codecType": "video",
        "codecName": "h264",
        "width": 1920,
        "height": 1080,
        "durationSec": 120.4
      }
    ]
  },
  "audio": {
    "streams": [
      {
        "index": 1,
        "codecType": "audio",
        "codecName": "aac",
        "durationSec": 120.4
      }
    ],
    "analysis": {
      "available": true,
      "audioAnalysisJson": "/mnt/c/.../raw_outputs/audio_analysis.json",
      "speechCandidates": 3,
      "diarizationStatus": "ok",
      "transcriptionStatus": "ok",
      "audioArtifact": {
        "path": "/mnt/c/.../artifacts/audio/source_audio.mp3",
        "includedInDownloadZip": false
      }
    }
  },
  "activity": {
    "available": true,
    "activityMapJson": "/mnt/c/.../raw_outputs/activity_map.json",
    "activeSegments": 2,
    "inactiveSegments": 3,
    "visualSentinels": 5
  },
  "visual": {
    "frame_features": {
      "available": true,
      "framesWithVisualFeatures": 5,
      "warnings": []
    },
    "frame_transition_gate": {
      "available": true,
      "targetModel": "Qwen/Qwen3.5-4B",
      "strategy": "cheap_visual_gate_before_vlm",
      "transitions": 4,
      "wouldSendToVlm": 2,
      "wouldSkip": 2,
      "failedTransitions": 0,
      "byDecision": {
        "skip_same": 2,
        "needs_vlm": 1,
        "uncertain": 1
      }
    },
    "frame_diff_vlm": {
      "available": true,
      "status": "completed",
      "mode": "auto",
      "modelId": "Qwen/Qwen3.5-4B",
      "candidateTransitions": 2,
      "analyzedTransitions": 2,
      "changedTransitions": 1,
      "failedTransitions": 0
    }
  },
  "processing": {
    "stage": "item_refresh",
    "pipeline_version": "timeline_for_video.pipeline.m13",
    "generated_at": "2026-05-13T19:42:06.820807+00:00",
    "source_video_modified": false,
    "raw_outputs": {
      "ffprobe_json": "/mnt/c/.../raw_outputs/ffprobe.json",
      "frame_samples_json": "/mnt/c/.../raw_outputs/frame_samples.json",
      "frame_ocr_json": "/mnt/c/.../raw_outputs/frame_ocr.json",
      "frame_diff_vlm_json": "/mnt/c/.../raw_outputs/frame_diff_vlm.json",
      "audio_analysis_json": "/mnt/c/.../raw_outputs/audio_analysis.json",
      "activity_map_json": "/mnt/c/.../raw_outputs/activity_map.json"
    },
    "artifacts": {
      "contact_sheet": "/mnt/c/.../artifacts/contact_sheet.jpg",
      "frames_dir": "/mnt/c/.../artifacts/frames",
      "audio_artifact": "/mnt/c/.../artifacts/audio/source_audio.mp3"
    },
    "warnings": []
  },
  "segments": [],
  "frames": [
    {
      "frame_id": "frame-000001",
      "time_sec": 0.0,
      "ok": true,
      "artifact_path": "/mnt/c/.../artifacts/frames/frame-000001.jpg",
      "source": "frame_samples",
      "ocr": {
        "has_text": true,
        "block_count": 2,
        "debug_overlay_path": "/mnt/c/.../artifacts/ocr/frame-000001-ocr.jpg"
      },
      "visual": {
        "available": true,
        "quality": {},
        "color_palette": [],
        "grid": []
      }
    }
  ],
  "text": {
    "mode": "frame_ocr_and_audio_reference",
    "ocr": true,
    "transcription": true,
    "full_text": "OCR text...\nTranscript text...",
    "blocks": [
      {
        "block_id": "frame-000001_ocr_0001",
        "text": "visible screen text",
        "frame_id": "frame-000001",
        "time_sec": 0.0,
        "bbox_norm": [0.05, 0.05, 0.95, 0.18],
        "confidence": { "score": 91.2, "level": "high" },
        "evidence": {
          "channel": "frame_ocr",
          "stage": "ocr",
          "frame_path": "/mnt/c/.../artifacts/frames/frame-000001.jpg",
          "debug_overlay_path": "/mnt/c/.../artifacts/ocr/frame-000001-ocr.jpg"
        }
      }
    ],
    "audio": {
      "readableText": "transcribed speech",
      "segments": []
    }
  },
  "review": {
    "contact_sheet": "/mnt/c/.../artifacts/contact_sheet.jpg",
    "contact_sheet_exists": true,
    "frame_count": 5
  }
}
```

### `timeline.json`

Time-lane view for UI rendering, search, and later LLM handoff.

```json
{
  "schemaVersion": "timeline_for_video.timeline.v1",
  "itemId": "video-260b3148c51df872",
  "generatedAt": "2026-05-13T19:42:06.820807+00:00",
  "timelineCoordinate": "source_video_relative_time",
  "sourceFingerprint": "sha256:...",
  "durationSec": 120.4,
  "lanes": {
    "visual": [
      {
        "eventType": "video_observed",
        "timeSec": 0.0,
        "sourcePath": "C:\\apps\\Timeline\\data\\input\\video\\clip.mp4",
        "ffprobeJson": "/mnt/c/.../raw_outputs/ffprobe.json"
      },
      {
        "eventType": "video_interval",
        "startSec": 0.0,
        "endSec": 120.4,
        "durationSec": 120.4
      },
      {
        "eventType": "frame_sample",
        "timeSec": 30.1,
        "frameId": "frame-000002",
        "artifactPath": "/mnt/c/.../artifacts/frames/frame-000002.jpg",
        "ok": true,
        "visual": {}
      },
      {
        "eventType": "frame_transition_gate",
        "startSec": 30.1,
        "endSec": 60.2,
        "fromFrameId": "frame-000002",
        "toFrameId": "frame-000003",
        "ok": true,
        "decision": "needs_vlm",
        "wouldSendToVlm": true,
        "reasons": ["changed_ratio_exceeds_vlm_threshold"],
        "source": "frame_transition_gate",
        "targetModel": "Qwen/Qwen3.5-4B"
      },
      {
        "eventType": "frame_diff_vlm",
        "startSec": 30.1,
        "endSec": 60.2,
        "fromFrameId": "frame-000002",
        "toFrameId": "frame-000003",
        "ok": true,
        "status": "completed",
        "changed": true,
        "changeLevel": "meaningful",
        "summary": "入力欄の文字が追加された。",
        "differences": ["入力欄の文字が増えた"],
        "confidence": 0.9,
        "modelId": "Qwen/Qwen3.5-4B",
        "source": "frame_diff_vlm"
      }
    ],
    "audio": [
      {
        "eventType": "audio_reference",
        "startSec": 0.0,
        "endSec": 120.4,
        "streamCount": 1
      },
      {
        "eventType": "audio_derivative",
        "timeSec": 0.0,
        "artifactPath": "/mnt/c/.../artifacts/audio/source_audio.mp3",
        "ok": true,
        "includedInDownloadZip": false
      },
      {
        "eventType": "audio_speech_candidate",
        "startSec": 12.3,
        "endSec": 18.7,
        "durationSec": 6.4,
        "source": "ffmpeg_silencedetect"
      }
    ],
    "activity": [
      {
        "eventType": "activity_candidate_interval",
        "startSec": 10.0,
        "endSec": 25.0,
        "durationSec": 15.0,
        "source": "activity_map"
      },
      {
        "eventType": "activity_skipped_interval",
        "startSec": 25.0,
        "endSec": 60.0,
        "durationSec": 35.0,
        "reason": "silent_audio_and_static_visual_sentinel",
        "source": "activity_map"
      }
    ],
    "text": [
      {
        "eventType": "frame_ocr_text",
        "timeSec": 30.1,
        "frameId": "frame-000002",
        "text": "visible screen text",
        "bbox_norm": [0.05, 0.05, 0.95, 0.18],
        "confidence": { "score": 91.2, "level": "high" },
        "source": "frame_ocr"
      },
      {
        "eventType": "audio_transcript_segment",
        "startSec": 12.3,
        "endSec": 18.7,
        "text": "spoken words",
        "speaker": "SPEAKER_00",
        "speakerAssignment": {},
        "source": "audio_analysis"
      }
    ]
  }
}
```

### `convert_info.json`

Audit and conversion metadata.

```json
{
  "schemaVersion": "timeline_for_video.convert_info.v1",
  "product": {
    "name": "TimelineForVideo",
    "version": "0.1.0"
  },
  "generatedAt": "2026-05-13T19:42:06.820807+00:00",
  "sourceFingerprint": {},
  "sourceFileIdentity": {},
  "ffprobeVersion": {},
  "ffmpegVersion": {},
  "pipelineVersion": "timeline_for_video.pipeline.m13",
  "generationSignature": "sha256:...",
  "samplingParameters": {
    "strategy": "evenly_spaced_bounded",
    "samplesPerVideo": 5,
    "timesSec": [0.0, 30.1, 60.2, 90.3, 120.4]
  },
  "imageProcessing": {
    "frameOcr": {
      "available": true,
      "frameOcrJson": "/mnt/c/.../raw_outputs/frame_ocr.json",
      "ocrMode": "auto",
      "model": "tesseract:jpn+eng",
      "framesWithText": 4,
      "framesWithVisualFeatures": 5,
      "textBlocks": 12
    },
    "frameVisualFeatures": {
      "available": true,
      "framesWithVisualFeatures": 5,
      "warnings": []
    },
    "frameTransitionGate": {
      "available": true,
      "targetModel": "Qwen/Qwen3.5-4B",
      "transitions": 4,
      "wouldSendToVlm": 2,
      "wouldSkip": 2,
      "failedTransitions": 0
    },
    "frameDiffVlm": {
      "available": true,
      "status": "completed",
      "mode": "auto",
      "modelId": "Qwen/Qwen3.5-4B",
      "candidateTransitions": 2,
      "analyzedTransitions": 2,
      "changedTransitions": 1,
      "failedTransitions": 0
    }
  },
  "audioProcessing": {
    "available": true,
    "speechCandidates": 3,
    "diarizationStatus": "ok",
    "transcriptionStatus": "ok"
  },
  "activityProcessing": {
    "available": true,
    "activeSegments": 2,
    "inactiveSegments": 3,
    "visualSentinels": 5
  },
  "outputFiles": [
    {
      "kind": "video_record",
      "path": "/mnt/c/.../video_record.json",
      "exists": true
    }
  ],
  "counts": {
    "videoStreams": 1,
    "audioStreams": 1,
    "frames": 5,
    "framesWithVisualFeatures": 5,
    "frameTransitions": 4,
    "frameTransitionsForVlm": 2,
    "frameTransitionsSkipped": 2,
    "frameDiffVlmCandidates": 2,
    "frameDiffVlmAnalyzed": 2,
    "frameDiffVlmChanged": 1,
    "ocrTextBlocks": 12,
    "audioSpeechCandidates": 3,
    "activitySegments": 2,
    "inactiveSegments": 3,
    "warnings": 0
  },
  "warnings": [],
  "source_video_modified": false
}
```

## Raw Output Files

### `raw_outputs/ffprobe.json`

Read-only ffprobe result and source identity.

```json
{
  "schemaVersion": "timeline_for_video.probe_record.v1",
  "itemId": "video-260b3148c51df872",
  "recordId": "video-260b3148c51df872",
  "generatedAt": "2026-05-13T19:40:29.000000+00:00",
  "sourceIdentity": {},
  "sourceFingerprint": {},
  "ffprobe": {
    "ok": true,
    "command": ["ffprobe", "-v", "error", "-print_format", "json"],
    "version": {},
    "summary": {
      "format": {},
      "streams": [],
      "counts": {
        "videoStreams": 1,
        "audioStreams": 1
      }
    },
    "raw": {},
    "error": null
  },
  "recordSeed": {},
  "convertInfoSeed": {}
}
```

### `raw_outputs/frame_samples.json`

Bounded frame extraction result.

```json
{
  "schemaVersion": "timeline_for_video.frame_samples.v1",
  "itemId": "video-260b3148c51df872",
  "generatedAt": "2026-05-13T19:40:45.203970+00:00",
  "ok": true,
  "sourceIdentity": {},
  "sourceFingerprint": {},
  "sourceVideoModified": false,
  "samplingParameters": {
    "strategy": "evenly_spaced_bounded",
    "samplesPerVideo": 5,
    "timesSec": [0.0, 30.1, 60.2, 90.3, 120.4]
  },
  "outputs": {
    "itemRoot": "/mnt/c/.../items/video-260b3148c51df872",
    "rawOutputsDir": "/mnt/c/.../raw_outputs",
    "frameSamplesJson": "/mnt/c/.../raw_outputs/frame_samples.json",
    "framesDir": "/mnt/c/.../artifacts/frames",
    "contactSheet": "/mnt/c/.../artifacts/contact_sheet.jpg",
    "outputRootConfiguredPath": "C:\\apps\\Timeline\\data\\to_text\\video"
  },
  "ffprobe": {
    "ok": true,
    "summary": {},
    "error": null
  },
  "ffmpeg": {
    "version": {}
  },
  "frames": [
    {
      "index": 1,
      "frameId": "frame-000001",
      "timeSec": 0.0,
      "ok": true,
      "outputPath": "/mnt/c/.../artifacts/frames/frame-000001.jpg",
      "command": [],
      "error": null
    }
  ],
  "contactSheet": {
    "ok": true,
    "outputPath": "/mnt/c/.../artifacts/contact_sheet.jpg",
    "command": [],
    "error": null
  },
  "visualGate": {
    "schemaVersion": "timeline_for_video.frame_transition_gate.v1",
    "available": true,
    "strategy": "cheap_visual_gate_before_vlm",
    "targetModel": "Qwen/Qwen3.5-4B",
    "counts": {
      "transitions": 4,
      "wouldSendToVlm": 2,
      "wouldSkip": 2,
      "failedTransitions": 0
    },
    "transitions": [
      {
        "fromFrameId": "frame-000001",
        "toFrameId": "frame-000002",
        "fromTimeSec": 0.0,
        "toTimeSec": 30.1,
        "decision": "skip_same",
        "wouldSendToVlm": false,
        "reasons": ["masked_difference_below_safe_same_thresholds"],
        "masked": {
          "meanDiff": 0.00012,
          "changedRatio": 0.0002,
          "largestComponentRatio": 0.0001
        }
      }
    ]
  },
  "counts": {
    "requestedFrames": 5,
    "extractedFrames": 5,
    "failedFrames": 0
  },
  "warnings": []
}
```

### `raw_outputs/frame_diff_vlm.json`

Local VLM comments for adjacent frame transitions selected by `visualGate`.

```json
{
  "schemaVersion": "timeline_for_video.frame_diff_vlm.v1",
  "product": "TimelineForVideo",
  "version": "0.1.0",
  "itemId": "video-260b3148c51df872",
  "generatedAt": "2026-05-13T19:41:02.000000+00:00",
  "ok": true,
  "status": "completed",
  "mode": "auto",
  "model": {
    "modelId": "Qwen/Qwen3.5-4B",
    "maxNewTokens": 512,
    "maxPixels": 230400,
    "modelDtype": "auto"
  },
  "source": {
    "frameSamplesJson": "/mnt/c/.../raw_outputs/frame_samples.json",
    "gateSchemaVersion": "timeline_for_video.frame_transition_gate.v1"
  },
  "outputs": {
    "frameDiffVlmJson": "/mnt/c/.../raw_outputs/frame_diff_vlm.json"
  },
  "counts": {
    "candidateTransitions": 2,
    "analyzedTransitions": 2,
    "skippedTransitions": 0,
    "failedTransitions": 0,
    "changedTransitions": 1,
    "unchangedTransitions": 1
  },
  "transitions": [
    {
      "fromFrameId": "frame-000002",
      "toFrameId": "frame-000003",
      "startSec": 30.1,
      "endSec": 60.2,
      "ok": true,
      "status": "completed",
      "changed": true,
      "changeLevel": "meaningful",
      "summary": "入力欄の文字が追加された。",
      "differences": ["入力欄の文字が増えた"],
      "confidence": 0.9,
      "gate": {
        "decision": "needs_vlm",
        "reasons": ["changed_ratio_exceeds_vlm_threshold"]
      },
      "inputFrames": {
        "leftPath": "/mnt/c/.../artifacts/frames/frame-000002.jpg",
        "rightPath": "/mnt/c/.../artifacts/frames/frame-000003.jpg"
      },
      "rawText": "{\"changed\":true,...}",
      "parsed": {},
      "elapsedSec": 21.4,
      "warnings": []
    }
  ],
  "warnings": []
}
```

If dependencies are not installed and mode is `auto`, `status` becomes
`skipped_dependency_unavailable`, `ok` remains `true`, and transitions are
recorded as skipped. In `required` mode the same condition makes the step fail.

### `raw_outputs/frame_ocr.json`

OCR and visual features over generated frame samples.

```json
{
  "schemaVersion": "timeline_for_video.frame_ocr.v1",
  "product": "TimelineForVideo",
  "version": "0.1.0",
  "generatedAt": "2026-05-13T19:41:27.337166+00:00",
  "itemId": "video-260b3148c51df872",
  "ok": true,
  "ocrMode": "auto",
  "ocrRuntime": {
    "ok": true,
    "mode": "auto",
    "model": "tesseract:jpn+eng"
  },
  "sourceVideoModified": false,
  "inputs": {
    "frameSamplesJson": "/mnt/c/.../raw_outputs/frame_samples.json"
  },
  "outputs": {
    "frameOcrJson": "/mnt/c/.../raw_outputs/frame_ocr.json",
    "ocrArtifactsDir": "/mnt/c/.../artifacts/ocr"
  },
  "frames": [
    {
      "frameId": "frame-000001",
      "timeSec": 0.0,
      "source_frame_path": "/mnt/c/.../artifacts/frames/frame-000001.jpg",
      "debug_overlay_path": "/mnt/c/.../artifacts/ocr/frame-000001-ocr.jpg",
      "ok": true,
      "visual": {
        "available": true,
        "quality": {},
        "color_palette": [],
        "grid": [],
        "warnings": []
      },
      "ocr": {
        "mode": "auto",
        "model": "tesseract:jpn+eng",
        "has_text": true,
        "full_text": "visible screen text",
        "blocks": [
          {
            "block_id": "ocr_0001",
            "text": "visible screen text",
            "bbox_norm": [0.05, 0.05, 0.95, 0.18],
            "confidence": {
              "score": 91.2,
              "level": "high"
            }
          }
        ],
        "warnings": []
      }
    }
  ],
  "counts": {
    "frames": 5,
    "framesWithVisualFeatures": 5,
    "framesWithText": 4,
    "textBlocks": 12,
    "warnings": 0
  },
  "warnings": []
}
```

### `raw_outputs/audio_analysis.json`

Generated audio derivative, temporary model input metadata, speech activity,
diarization, and transcription.

```json
{
  "schemaVersion": "timeline_for_video.audio_analysis.v1",
  "product": "TimelineForVideo",
  "version": "0.1.0",
  "generatedAt": "2026-05-13T19:42:05.328100+00:00",
  "itemId": "video-260b3148c51df872",
  "ok": true,
  "sourceVideoModified": false,
  "sourceIdentity": {},
  "sourceFingerprint": {},
  "outputRoot": {
    "configuredPath": "C:\\apps\\Timeline\\data\\to_text\\video",
    "itemRoot": "/mnt/c/.../items/video-260b3148c51df872"
  },
  "inputs": {
    "ffprobeOk": true,
    "audioStreamCount": 1,
    "durationSec": 120.4
  },
  "audioArtifact": {
    "ok": true,
    "kind": "mp3_audio_derivative",
    "path": "/mnt/c/.../artifacts/audio/source_audio.mp3",
    "sourceVideoModified": false,
    "includedInDownloadZip": false,
    "command": [],
    "error": null
  },
  "audioModelInput": {
    "ok": true,
    "kind": "temporary_normalized_wav",
    "path": "/mnt/c/.../artifacts/audio/.processing/normalized_audio.wav",
    "retained": false,
    "removedAfterProcessing": true,
    "sourceVideoModified": false,
    "includedInDownloadZip": false,
    "command": [],
    "error": null
  },
  "speechActivity": {
    "backend": "ffmpeg_silencedetect",
    "modelId": "ffmpeg.silencedetect",
    "parameters": {
      "noise": "-35dB",
      "durationSec": 0.4
    },
    "ok": true,
    "command": [],
    "silences": [],
    "speechCandidates": [
      {
        "startSec": 12.3,
        "endSec": 18.7,
        "durationSec": 6.4
      }
    ],
    "counts": {
      "silences": 2,
      "speechCandidates": 3
    },
    "error": null
  },
  "diarization": {
    "status": "ok",
    "backend": "pyannote.audio",
    "model_id": "pyannote/speaker-diarization-community-1",
    "turns": [],
    "turn_count": 0,
    "warning_count": 0,
    "warnings": [],
    "error": null
  },
  "transcription": {
    "status": "ok",
    "backend": "faster-whisper",
    "model_id": "Systran/faster-whisper-large-v3",
    "model_alias": "faster_whisper_large_v3",
    "language": {
      "detected": "ja",
      "probability": 0.98
    },
    "segments": [
      {
        "start_sec": 12.3,
        "end_sec": 18.7,
        "text": "spoken words",
        "speaker": "SPEAKER_00",
        "speakerAssignment": {}
      }
    ],
    "segment_count": 1,
    "warning_count": 0,
    "warnings": [],
    "error": null
  },
  "text": {
    "mode": "whisper_transcript",
    "readableText": "spoken words",
    "segments": [],
    "warnings": []
  },
  "audioModels": {
    "schemaVersion": "timeline_for_video.audio_model_result.v1",
    "ok": true,
    "mode": "required",
    "computeMode": "gpu",
    "runtime": {},
    "warnings": []
  },
  "warnings": [],
  "outputs": {
    "audioAnalysisJson": "/mnt/c/.../raw_outputs/audio_analysis.json",
    "audioArtifactsDir": "/mnt/c/.../artifacts/audio"
  }
}
```

The MP3 derivative is a local review artifact. The normalized WAV is temporary
model input and should be removed after processing.

### `raw_outputs/activity_map.json`

Merged activity map used to identify useful intervals and skippable intervals.

```json
{
  "schemaVersion": "timeline_for_video.activity_map.v1",
  "product": "TimelineForVideo",
  "version": "0.1.0",
  "generatedAt": "2026-05-13T19:42:06.323637+00:00",
  "itemId": "video-260b3148c51df872",
  "ok": true,
  "sourceVideoModified": false,
  "sourceIdentity": {},
  "sourceFingerprint": {},
  "inputs": {
    "ffprobeOk": true,
    "durationSec": 120.4,
    "audioAnalysisJson": "/mnt/c/.../raw_outputs/audio_analysis.json"
  },
  "parameters": {
    "audioPaddingSec": 1.0,
    "audioMergeGapSec": 1.5,
    "visualIntervalSec": 300.0,
    "maxVisualSentinels": 20,
    "visualWidth": 64,
    "visualHeight": 36,
    "visualDeltaThreshold": 0.08
  },
  "audio": {
    "available": true,
    "source": "raw_outputs/audio_analysis.json",
    "speechCandidates": 3,
    "rawActiveSec": 21.4,
    "activeSegments": []
  },
  "visual": {
    "available": true,
    "strategy": "five_minute_gray_frame_delta",
    "sentinels": [
      {
        "index": 0,
        "timeSec": 0.0,
        "ok": true,
        "deltaFromPrevious": null,
        "activeTransition": false,
        "command": [],
        "error": null
      }
    ],
    "activeSegments": [],
    "counts": {
      "requestedSentinels": 5,
      "completedSentinels": 5,
      "failedSentinels": 0,
      "activeTransitions": 0
    },
    "warnings": []
  },
  "activity": {
    "strategy": "audio_speech_activity_plus_visual_sentinel",
    "activeSegments": [],
    "inactiveSegments": [],
    "activeSec": 21.4,
    "inactiveSec": 99.0,
    "activeRatio": 0.177741,
    "inactiveRatio": 0.822259,
    "estimatedReductionRatio": 5.626,
    "counts": {
      "activeSegments": 2,
      "inactiveSegments": 3,
      "audioActiveSegments": 2,
      "visualActiveSegments": 0,
      "visualSentinels": 5
    },
    "notes": []
  },
  "outputs": {
    "activityMapJson": "/mnt/c/.../raw_outputs/activity_map.json",
    "outputRootConfiguredPath": "C:\\apps\\Timeline\\data\\to_text\\video"
  },
  "warnings": [],
  "elapsedSec": 0.421
}
```

## Local API JSON Results

The worker-hosted local API returns JSON envelopes for Timeline integration.
These are API results, not necessarily durable item files.

### `POST /items/refresh`

```json
{
  "schemaVersion": "timeline_for_video.run_result.v1",
  "product": "TimelineForVideo",
  "version": "0.1.0",
  "generatedAt": "2026-06-12T00:00:00+00:00",
  "runId": "run-20260612-000000",
  "state": "completed",
  "ok": true,
  "failedSteps": [],
  "outputRoot": {
    "configuredPath": "C:\\apps\\Timeline\\data\\to_text\\video",
    "resolvedPath": "/mnt/c/apps/Timeline/data/to_text/video"
  },
  "counts": {
    "sourceFiles": 1,
    "candidateItems": 1,
    "processedItems": 1,
    "skippedItems": 0,
    "failedItems": 0,
    "completedItems": 1
  },
  "steps": {
    "sample": { "ok": true, "counts": { "items": 1, "frames": 5 } },
    "frameOcr": { "ok": true, "counts": { "items": 1 } },
    "audio": { "ok": true, "counts": { "items": 1 } },
    "activity": { "ok": true, "counts": { "items": 1 } },
    "frameDiffVlm": { "ok": true, "counts": { "items": 1 } },
    "refresh": { "ok": true, "counts": { "items": 1 } }
  },
  "records": [
    {
      "itemId": "video-260b3148c51df872",
      "ok": true,
      "itemRoot": "/mnt/c/.../items/video-260b3148c51df872",
      "videoRecordJson": "/mnt/c/.../video_record.json",
      "timelineJson": "/mnt/c/.../timeline.json",
      "convertInfoJson": "/mnt/c/.../convert_info.json",
      "counts": {
        "frames": 5,
        "visualEvents": 7,
        "audioEvents": 4,
        "textEvents": 12,
        "activityEvents": 5
      },
      "warnings": []
    }
  ]
}
```

### `POST /jobs`

Starts an asynchronous refresh job and returns the same envelope used by
`GET /jobs/{jobId}`.

```json
{
  "schemaVersion": "timeline.product_job.v1",
  "productId": "video",
  "productName": "TimelineForVideo",
  "type": "refresh",
  "jobId": "run-20260612-000000",
  "state": "queued",
  "phase": "queued",
  "stage": "queued",
  "message": "Video refresh job has been queued.",
  "progress": {
    "percent": 0.0,
    "current": 0,
    "total": 0,
    "unit": "files",
    "currentItem": "",
    "estimatedRemainingSeconds": null
  },
  "startedAt": "2026-06-12T00:00:00+00:00",
  "updatedAt": "2026-06-12T00:00:00+00:00",
  "completedAt": "",
  "error": null,
  "warnings": [],
  "result": {
    "schemaVersion": "timeline_for_video.run_result_summary.v1",
    "runId": "run-20260612-000000",
    "state": "queued",
    "ok": false,
    "failedSteps": [],
    "counts": {
      "sourceFiles": 0,
      "candidateItems": 0,
      "processedItems": 0,
      "skippedItems": 0,
      "failedItems": 0,
      "completedItems": 0
    },
    "resultPath": "",
    "resultIncluded": false
  }
}
```

### `GET /jobs`

```json
{
  "schemaVersion": "timeline_for_video.runs_list.v1",
  "product": "TimelineForVideo",
  "version": "0.1.0",
  "ok": true,
  "stateRoot": "/shared/app-data/timeline-for-video-state",
  "counts": { "runs": 1 },
  "runs": [
    {
      "runId": "run-20260612-000000",
      "state": "completed",
      "ok": true,
      "generatedAt": "2026-06-12T00:00:00+00:00",
      "counts": { "processedItems": 1, "failedItems": 0 },
      "resultPath": "/shared/app-data/timeline-for-video-state/runs/run-20260612-000000/result.json",
      "statusPath": "/shared/app-data/timeline-for-video-state/runs/run-20260612-000000/status.json"
    }
  ],
  "activeJobId": ""
}
```

### `POST /items/list`

```json
{
  "schemaVersion": "timeline_for_video.item_list_result.v1",
  "product": "TimelineForVideo",
  "version": "0.1.0",
  "ok": true,
  "outputRoot": {
    "configuredPath": "C:\\apps\\Timeline\\data\\to_text\\video",
    "resolvedPath": "/mnt/c/apps/Timeline/data/to_text/video"
  },
  "counts": {
    "items": 1,
    "returnedItems": 1
  },
  "items": [
    {
      "itemId": "video-260b3148c51df872",
      "ok": true,
      "itemRoot": "/mnt/c/.../items/video-260b3148c51df872",
      "videoRecordJson": "/mnt/c/.../video_record.json",
      "sourcePath": "C:\\apps\\Timeline\\data\\input\\video\\clip.mp4",
      "durationSec": 120.4,
      "frameCount": 5,
      "contactSheet": "/mnt/c/.../artifacts/contact_sheet.jpg",
      "text": {
        "mode": "frame_ocr_and_audio_reference",
        "ocr": true,
        "transcription": true,
        "textBlockCount": 12,
        "fullTextLength": 240
      },
      "audioAnalysis": {
        "available": true,
        "speechCandidates": 3,
        "diarizationStatus": "ok",
        "transcriptionStatus": "ok",
        "audioArtifact": "/mnt/c/.../artifacts/audio/source_audio.mp3",
        "audioArtifactIncludedInDownloadZip": false
      },
      "activity": {
        "available": true,
        "activeSegments": 2,
        "inactiveSegments": 3,
        "visualSentinels": 5
      },
      "warnings": []
    }
  ],
  "pagination": {
    "mode": "page",
    "page": 1,
    "pageSize": 100,
    "total": 1,
    "totalPages": 1,
    "returned": 1,
    "hasPrevious": false,
    "hasNext": false
  }
}
```

### `POST /items/download`

```json
{
  "schemaVersion": "timeline_for_video.item_download_result.v1",
  "product": "TimelineForVideo",
  "version": "0.1.0",
  "generatedAt": "2026-05-13T19:44:00.000000+00:00",
  "ok": true,
  "outputRoot": {},
  "archivePath": "/mnt/c/.../downloads/timeline-for-video-items-20260513T194400Z.zip",
  "latestArchivePath": "/mnt/c/.../latest/items.zip",
  "latestManifestPath": "/mnt/c/.../latest/download_manifest.json",
  "sourceVideosIncluded": false,
  "imageArtifactsIncluded": false,
  "counts": {
    "items": 1,
    "missingItems": 0,
    "files": 8,
    "bytes": 123456
  },
  "requestedItemIds": [],
  "missingItemIds": [],
  "outputFiles": [
    { "kind": "download_zip", "path": "/mnt/c/.../downloads/...", "exists": true },
    { "kind": "latest_zip", "path": "/mnt/c/.../latest/items.zip", "exists": true },
    { "kind": "latest_manifest", "path": "/mnt/c/.../latest/download_manifest.json", "exists": true }
  ],
  "items": [
    {
      "itemId": "video-260b3148c51df872",
      "itemRoot": "/mnt/c/.../items/video-260b3148c51df872",
      "fileCount": 8
    }
  ]
}
```

`latest/download_manifest.json` has the same `schemaVersion` and includes a
`files` array:

```json
{
  "schemaVersion": "timeline_for_video.item_download_result.v1",
  "sourceVideosIncluded": false,
  "imageArtifactsIncluded": false,
  "items": [],
  "files": [
    {
      "path": "/mnt/c/.../video_record.json",
      "archivePath": "items/video-260b3148c51df872/video_record.json",
      "sizeBytes": 1054961
    }
  ]
}
```

### `POST /items/remove`

```json
{
  "schemaVersion": "timeline_for_video.item_remove_result.v1",
  "product": "TimelineForVideo",
  "version": "0.1.0",
  "generatedAt": "2026-05-13T19:46:51.460385+00:00",
  "ok": true,
  "dryRun": false,
  "outputRoot": {},
  "sourceVideosRemoved": false,
  "counts": {
    "targetFiles": 15,
    "targetDirectories": 8,
    "requestedItems": 0,
    "missingItems": 0,
    "deletedFiles": 15,
    "prunedDirectories": 8,
    "skippedFiles": 0,
    "skippedDirectories": 0
  },
  "targets": {
    "files": [],
    "directories": []
  },
  "requestedItemIds": [],
  "missingItemIds": [],
  "deletedFiles": [],
  "prunedDirectories": [],
  "skippedFiles": [],
  "skippedDirectories": []
}
```

`POST /items/remove` removes generated files under `outputRoot`; it does not delete
source videos. It also targets temporary generated `.processing` files under
item artifact directories.

## Worker Run Result

The resident worker pipeline returns a worker run envelope.
Completed runs are also stored in the internal app-data volume, not under
`outputRoot`.

```json
{
  "schemaVersion": "timeline_for_video.run_result.v1",
  "product": "TimelineForVideo",
  "version": "0.1.0",
  "generatedAt": "2026-05-13T19:42:00.000000+00:00",
  "runId": "run-...",
  "state": "completed",
  "ok": true,
  "failedSteps": [],
  "outputRoot": {},
  "counts": {
    "sourceFiles": 1,
    "candidateItems": 1,
    "processedItems": 1,
    "skippedItems": 0,
    "failedItems": 0,
    "completedItems": 1
  },
  "discovery": {},
  "steps": {
    "sample": {},
    "frameOcr": {},
    "audio": {},
    "activity": {},
    "refresh": {}
  },
  "records": []
}
```

## ZIP Exports

ZIP exports include generated item records, raw outputs, frame artifacts, OCR
overlays, and contact sheets. They do not include source videos or generated
MP3 audio derivatives.

The generated MP3 remains under `outputRoot` for local review and removal. The
temporary normalized WAV should not remain after processing and is not exported.
