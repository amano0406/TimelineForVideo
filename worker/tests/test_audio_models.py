from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from timeline_for_video_worker.audio_models import (
    diarization_activity_spans,
    MAX_DIARIZATION_ACTIVITY_SPANS,
    run_diarization,
    run_audio_reference_models,
    run_whisper_transcription,
    speaker_assignment_for_interval,
    transcript_segment_from_whisper,
)


class AudioModelTests(unittest.TestCase):
    def test_missing_token_is_structured_and_nonfatal_in_auto_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            audio_path = Path(temp_dir) / "normalized_audio.wav"
            audio_path.write_bytes(b"wav")

            with patch.dict(
                "os.environ",
                {"TIMELINE_FOR_VIDEO_HUGGING_FACE_TOKEN": "", "HUGGING_FACE_HUB_TOKEN": "", "HF_TOKEN": ""},
                clear=False,
            ):
                result = run_audio_reference_models(
                    audio_path=audio_path,
                    speech_candidates=[{"startSec": 0.0, "endSec": 1.0, "durationSec": 1.0}],
                    source_name="clip.mp4",
                    settings={"computeMode": "cpu", "huggingfaceToken": ""},
                    mode="auto",
                )

            self.assertTrue(result["ok"])
            self.assertEqual(result["diarization"]["status"], "not_configured")
            self.assertEqual(result["transcription"]["status"], "not_configured")
            self.assertIn("hugging_face_token_missing", result["warnings"])

    def test_missing_token_is_failure_in_required_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            audio_path = Path(temp_dir) / "normalized_audio.wav"
            audio_path.write_bytes(b"wav")

            with patch.dict(
                "os.environ",
                {"TIMELINE_FOR_VIDEO_HUGGING_FACE_TOKEN": "", "HUGGING_FACE_HUB_TOKEN": "", "HF_TOKEN": ""},
                clear=False,
            ):
                result = run_audio_reference_models(
                    audio_path=audio_path,
                    speech_candidates=[],
                    source_name="clip.mp4",
                    settings={"computeMode": "cpu", "huggingfaceToken": ""},
                )

            self.assertFalse(result["ok"])
            self.assertEqual(result["diarization"]["status"], "not_configured")

    def test_gpu_compute_mode_fails_instead_of_falling_back_to_cpu(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            audio_path = Path(temp_dir) / "normalized_audio.wav"
            audio_path.write_bytes(b"wav")
            runtime = {
                "ready": False,
                "computeMode": "gpu",
                "compute": {
                    "ready": False,
                    "mode": "gpu",
                    "workerFlavor": "cpu",
                    "torchCudaAvailable": False,
                    "ctranslate2CudaDeviceCount": 0,
                    "warnings": [
                        "computeMode gpu requires the GPU worker flavor.",
                        "CUDA is not available to CTranslate2.",
                    ],
                },
                "tokenConfigured": True,
                "modules": {
                    "pyannote.audio": True,
                    "torch": True,
                    "torchaudio": True,
                    "faster_whisper": True,
                    "ctranslate2": True,
                    "huggingface_hub": True,
                },
                "diarization": {"ready": False},
                "transcription": {"ready": False},
            }

            with patch("timeline_for_video_worker.audio_models.audio_model_runtime_status", return_value=runtime):
                with patch("timeline_for_video_worker.audio_models.load_huggingface_token", return_value="token"):
                    result = run_audio_reference_models(
                        audio_path=audio_path,
                        speech_candidates=[],
                        source_name="clip.mp4",
                        settings={"computeMode": "gpu", "huggingfaceToken": "token"},
                    )

            self.assertFalse(result["ok"])
            self.assertEqual(result["diarization"]["status"], "compute_runtime_unavailable")
            self.assertEqual(result["transcription"]["status"], "compute_runtime_unavailable")
            self.assertTrue(any("GPU worker flavor" in warning for warning in result["warnings"]))

    def test_speaker_assignment_prefers_overlap_without_modifying_text(self) -> None:
        assignment = speaker_assignment_for_interval(
            1.0,
            3.0,
            [
                {"startSec": 0.0, "endSec": 1.2, "speaker": "SPEAKER_00"},
                {"startSec": 1.5, "endSec": 4.0, "speaker": "SPEAKER_01"},
            ],
        )

        self.assertEqual(assignment["speaker"], "SPEAKER_01")
        self.assertEqual(assignment["method"], "max_overlap")

    def test_diarization_activity_spans_pad_and_merge_candidates(self) -> None:
        spans = diarization_activity_spans(
            [
                {"startSec": 10.0, "endSec": 12.0},
                {"startSec": 13.0, "endSec": 14.0},
                {"startSec": 30.0, "endSec": 31.0},
            ]
        )

        self.assertEqual(spans, [(9.0, 15.0), (29.0, 32.0)])

    def test_required_mode_accepts_transcript_without_fallback_speaker(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            audio_path = Path(temp_dir) / "normalized_audio.wav"
            audio_path.write_bytes(b"wav")
            runtime = {
                "ready": True,
                "computeMode": "cpu",
                "compute": {
                    "ready": True,
                    "mode": "cpu",
                    "workerFlavor": "cpu",
                    "torchCudaAvailable": None,
                    "ctranslate2CudaDeviceCount": None,
                    "warnings": [],
                },
                "tokenConfigured": True,
                "modules": {
                    "pyannote.audio": True,
                    "torch": True,
                    "torchaudio": True,
                    "faster_whisper": True,
                    "ctranslate2": True,
                    "huggingface_hub": True,
                },
                "diarization": {"ready": True},
                "transcription": {"ready": True},
            }

            with patch("timeline_for_video_worker.audio_models.audio_model_runtime_status", return_value=runtime):
                with patch("timeline_for_video_worker.audio_models.load_huggingface_token", return_value="token"):
                    with patch(
                        "timeline_for_video_worker.audio_models.run_diarization",
                        return_value={
                            "status": "no_speaker_turns",
                            "backend": "pyannote.audio",
                            "model_id": "pyannote/speaker-diarization-community-1",
                            "turns": [],
                            "turn_count": 0,
                            "warning_count": 1,
                            "warnings": ["Speaker diarization completed, but no speaker turns were found."],
                            "error": None,
                        },
                    ):
                        with patch(
                            "timeline_for_video_worker.audio_models.run_whisper_transcription",
                            return_value={
                                "status": "ok",
                                "backend": "faster-whisper",
                                "model_id": "Systran/faster-whisper-large-v3",
                                "model_alias": "faster_whisper_large_v3",
                                "segments": [
                                    {
                                        "start_sec": 1.0,
                                        "end_sec": 2.0,
                                        "speaker": None,
                                        "speakerAssignment": {"method": "none", "speaker": None, "overlapSec": 0.0},
                                        "text": "Whisper text must remain intact.",
                                        "confidence": None,
                                        "index": 1,
                                    }
                                ],
                                "segment_count": 1,
                                "warning_count": 0,
                                "warnings": [],
                                "error": None,
                            },
                        ):
                            result = run_audio_reference_models(
                                audio_path=audio_path,
                                speech_candidates=[],
                                source_name="silent.mp4",
                                settings={"computeMode": "cpu", "huggingfaceToken": "token"},
                            )

            self.assertTrue(result["ok"])
            self.assertEqual(result["diarization"]["turns"], [])
            self.assertEqual(result["transcription"]["segments"][0]["speaker"], None)
            self.assertEqual(result["text"]["readableText"], "Whisper text must remain intact.")

    def test_transcript_segment_preserves_whisper_text_when_assigning_speaker(self) -> None:
        class FakeWhisperSegment:
            start = 10.0
            end = 20.0
            text = "今日はこの動画を確認します。"
            avg_logprob = -0.1

        segment = transcript_segment_from_whisper(
            1,
            FakeWhisperSegment(),
            [
                {"startSec": 9.0, "endSec": 15.0, "speaker": "SPEAKER_00"},
                {"startSec": 15.0, "endSec": 22.0, "speaker": "SPEAKER_01"},
            ],
        )

        self.assertEqual(segment["text"], "今日はこの動画を確認します。")
        self.assertEqual(segment["speaker"], "SPEAKER_00")
        self.assertEqual(segment["speakerAssignment"]["method"], "max_overlap")

    def test_run_whisper_transcription_adds_speaker_labels(self) -> None:
        class FakeWhisperSegment:
            start = 1.0
            end = 3.0
            text = " hello world "
            avg_logprob = -0.2

        class FakeInfo:
            language = "en"
            language_probability = 0.75

        class FakeModel:
            def transcribe(self, *args, **kwargs):
                return iter([FakeWhisperSegment()]), FakeInfo()

        with patch("timeline_for_video_worker.audio_models.load_whisper_model", return_value=FakeModel()):
            result = run_whisper_transcription(
                Path("normalized_audio.wav"),
                compute_mode="cpu",
                speaker_turns=[{"startSec": 0.0, "endSec": 5.0, "speaker": "SPEAKER_00"}],
                speech_candidates=[{"startSec": 0.0, "endSec": 5.0}],
            )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["language"]["detected"], "en")
        self.assertEqual(result["segments"][0]["text"], "hello world")
        self.assertEqual(result["segments"][0]["speaker"], "SPEAKER_00")
        self.assertEqual(result["raw_segment_count"], 1)
        self.assertEqual(result["rejected_segment_count"], 0)

    def test_run_whisper_transcription_rejects_silence_hallucination(self) -> None:
        class FakeWhisperSegment:
            text = " ご視聴ありがとうございました "
            avg_logprob = -0.4
            no_speech_prob = 0.1

            def __init__(self, start: float) -> None:
                self.start = start
                self.end = start + 2.0

        class FakeInfo:
            language = "ja"
            language_probability = 0.98

        class FakeModel:
            def transcribe(self, *args, **kwargs):
                return iter([
                    FakeWhisperSegment(176.44),
                    FakeWhisperSegment(206.44),
                    FakeWhisperSegment(236.44),
                ]), FakeInfo()

        with patch("timeline_for_video_worker.audio_models.load_whisper_model", return_value=FakeModel()):
            result = run_whisper_transcription(
                Path("normalized_audio.wav"),
                compute_mode="cpu",
                speaker_turns=[],
                speech_candidates=[{"startSec": 0.0, "endSec": 160.0}],
            )

        self.assertEqual(result["status"], "no_segments")
        self.assertEqual(result["raw_segment_count"], 3)
        self.assertEqual(result["segment_count"], 0)
        self.assertEqual(result["rejected_segment_count"], 3)
        self.assertIn("no_speech_candidate_overlap", result["rejectedSegments"][0]["rejectionReasons"])
        self.assertIn("known_silence_hallucination_phrase", result["rejectedSegments"][0]["rejectionReasons"])

    def test_run_diarization_uses_preloaded_audio_input(self) -> None:
        class FakeSegment:
            start = 1.0
            end = 2.5

        class FakeAnnotation:
            def itertracks(self, yield_label: bool = False):
                yield FakeSegment(), None, "SPEAKER_00"

        class FakePipeline:
            def __init__(self) -> None:
                self.received = None

            def __call__(self, payload):
                self.received = payload
                return FakeAnnotation()

        pipeline = FakePipeline()
        audio_input = {"waveform": object(), "sample_rate": 16000}

        with patch("timeline_for_video_worker.audio_models.load_diarization_pipeline", return_value=pipeline):
            with patch("timeline_for_video_worker.audio_models.load_diarization_audio_input", return_value=audio_input):
                result = run_diarization(
                    Path("normalized_audio.wav"),
                    token="token",
                    compute_mode="cpu",
                    source_name="clip.mp4",
                )

        self.assertIs(pipeline.received, audio_input)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["turn_count"], 1)
        self.assertEqual(result["turns"][0]["speaker"], "SPEAKER_00")

    def test_run_diarization_offsets_speech_candidate_spans(self) -> None:
        class FakeSegment:
            start = 1.0
            end = 2.5

        class FakeAnnotation:
            def itertracks(self, yield_label: bool = False):
                yield FakeSegment(), None, "SPEAKER_00"

        class FakePipeline:
            def __init__(self) -> None:
                self.received = []

            def __call__(self, payload):
                self.received.append(payload)
                return FakeAnnotation()

        pipeline = FakePipeline()
        audio_input = {"waveform": object(), "sample_rate": 16000}

        with patch("timeline_for_video_worker.audio_models.load_diarization_pipeline", return_value=pipeline):
            with patch("timeline_for_video_worker.audio_models.load_diarization_audio_input", return_value=audio_input):
                result = run_diarization(
                    Path("normalized_audio.wav"),
                    token="token",
                    compute_mode="cpu",
                    source_name="clip.mp4",
                    speech_candidates=[{"startSec": 10.0, "endSec": 12.0}],
                )

        self.assertEqual(len(pipeline.received), 1)
        self.assertEqual(result["scope"]["mode"], "speech_candidates")
        self.assertEqual(result["scope"]["activeSec"], 4.0)
        self.assertEqual(result["turns"][0]["start"], 10.0)
        self.assertEqual(result["turns"][0]["end"], 11.5)

    def test_run_diarization_uses_full_audio_when_candidate_spans_are_many(self) -> None:
        class FakeSegment:
            start = 1.0
            end = 2.5

        class FakeAnnotation:
            def itertracks(self, yield_label: bool = False):
                yield FakeSegment(), None, "SPEAKER_00"

        class FakePipeline:
            def __init__(self) -> None:
                self.received = []

            def __call__(self, payload):
                self.received.append(payload)
                return FakeAnnotation()

        pipeline = FakePipeline()
        audio_input = {"waveform": object(), "sample_rate": 16000}
        speech_candidates = [
            {"startSec": float(index * 10), "endSec": float(index * 10) + 1.0}
            for index in range(MAX_DIARIZATION_ACTIVITY_SPANS + 1)
        ]

        with patch("timeline_for_video_worker.audio_models.load_diarization_pipeline", return_value=pipeline):
            with patch("timeline_for_video_worker.audio_models.load_diarization_audio_input", return_value=audio_input) as load_audio:
                result = run_diarization(
                    Path("normalized_audio.wav"),
                    token="token",
                    compute_mode="cpu",
                    source_name="clip.mp4",
                    speech_candidates=speech_candidates,
                )

        self.assertEqual(len(pipeline.received), 1)
        load_audio.assert_called_once_with(Path("normalized_audio.wav"))
        self.assertEqual(result["scope"]["mode"], "full_audio_many_speech_candidates")
        self.assertEqual(result["scope"]["spans"], MAX_DIARIZATION_ACTIVITY_SPANS + 1)
        self.assertEqual(result["turns"][0]["start"], 1.0)


if __name__ == "__main__":
    unittest.main()
