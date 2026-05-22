from __future__ import annotations

import json
from pathlib import Path
import stat
import sys
import tempfile
import unittest

from timeline_for_video_worker.discovery import video_file_from_path
from timeline_for_video_worker.probe import (
    build_probe_record,
    ffprobe_summary,
    ffprobe_version,
    item_id_from_fingerprint,
    probe_video_files,
    run_ffprobe,
    source_fingerprint,
    source_identity,
)


FFPROBE_FIXTURE = {
    "streams": [
        {
            "index": 0,
            "codec_type": "video",
            "codec_name": "h264",
            "width": 1920,
            "height": 1080,
            "duration": "12.500000",
        },
        {
            "index": 1,
            "codec_type": "audio",
            "codec_name": "aac",
            "sample_rate": "48000",
            "channels": 2,
            "duration": "12.480000",
        },
    ],
    "format": {
        "format_name": "mov,mp4,m4a,3gp,3g2,mj2",
        "format_long_name": "QuickTime / MOV",
        "duration": "12.500000",
        "size": "12345",
        "bit_rate": "7900",
    },
}

FFPROBE_WITHOUT_DURATION = {
    "streams": [
        {
            "index": 0,
            "codec_type": "video",
            "codec_name": "h264",
            "width": 1920,
            "height": 1080,
        },
        {
            "index": 1,
            "codec_type": "audio",
            "codec_name": "aac",
            "sample_rate": "48000",
            "channels": 2,
        },
    ],
    "format": {
        "format_name": "matroska,webm",
        "format_long_name": "Matroska / WebM",
        "size": "12345",
    },
}


def write_fake_ffprobe(directory: Path) -> str:
    script = directory / "fake_ffprobe.py"
    script.write_text(
        "\n".join(
            [
                "import json",
                "import sys",
                "if '-version' in sys.argv:",
                "    print('ffprobe fake 1.0')",
                "else:",
                f"    print(json.dumps({FFPROBE_FIXTURE!r}))",
            ]
        ),
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return f"{sys.executable} {script}"


def write_duration_recovery_ffprobe(directory: Path) -> str:
    script = directory / "fake_ffprobe_recovery.py"
    script.write_text(
        "\n".join(
            [
                "import json",
                "import sys",
                "if '-version' in sys.argv:",
                "    print('ffprobe fake 1.0')",
                "elif sys.argv[-1].endswith('source.remux.mkv'):",
                f"    print(json.dumps({FFPROBE_FIXTURE!r}))",
                "else:",
                f"    print(json.dumps({FFPROBE_WITHOUT_DURATION!r}))",
            ]
        ),
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return f"{sys.executable} {script}"


def write_fake_ffmpeg_remux(directory: Path) -> str:
    script = directory / "fake_ffmpeg_remux.py"
    script.write_text(
        "\n".join(
            [
                "from pathlib import Path",
                "import sys",
                "Path(sys.argv[-1]).parent.mkdir(parents=True, exist_ok=True)",
                "Path(sys.argv[-1]).write_bytes(b'remuxed')",
            ]
        ),
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return f"{sys.executable} {script}"


class ProbeTests(unittest.TestCase):
    def test_ffprobe_summary_parses_fixture_json(self) -> None:
        summary = ffprobe_summary(FFPROBE_FIXTURE)

        self.assertEqual(summary["format"]["durationSec"], 12.5)
        self.assertEqual(summary["format"]["sizeBytes"], 12345)
        self.assertEqual(summary["counts"]["videoStreams"], 1)
        self.assertEqual(summary["counts"]["audioStreams"], 1)
        self.assertEqual(summary["streams"][0]["width"], 1920)

    def test_source_fingerprint_is_stat_based_without_content_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "clip.mp4"
            source.write_bytes(b"small fixture")
            video_file = video_file_from_path(source, str(source.parent))

            identity = source_identity(video_file)
            fingerprint = source_fingerprint(identity)
            item_id = item_id_from_fingerprint(fingerprint)

            self.assertEqual(fingerprint["algorithm"], "source-stat-v1")
            self.assertFalse(fingerprint["contentHash"]["computed"])
            self.assertTrue(fingerprint["value"].startswith("sha256:"))
            self.assertTrue(item_id.startswith("video-"))
            self.assertEqual(source.read_bytes(), b"small fixture")

    def test_run_ffprobe_uses_metadata_json_without_modifying_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "clip.mp4"
            source.write_bytes(b"video")
            source_before = source.read_bytes()
            fake_ffprobe = write_fake_ffprobe(root)

            result = run_ffprobe(str(source), fake_ffprobe)

            self.assertTrue(result.ok)
            self.assertEqual(result.raw, FFPROBE_FIXTURE)
            self.assertEqual(source.read_bytes(), source_before)

    def test_build_probe_record_contains_record_and_convert_info_seeds(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "clip.mp4"
            source.write_bytes(b"video")
            fake_ffprobe = write_fake_ffprobe(root)
            video_file = video_file_from_path(source, str(root))
            version = ffprobe_version(fake_ffprobe)
            ffprobe_run = run_ffprobe(str(source), fake_ffprobe)

            record = build_probe_record(video_file, ffprobe_run, version, "2026-05-06T00:00:00+00:00")

            self.assertEqual(record["schemaVersion"], "timeline_for_video.probe_record.v1")
            self.assertEqual(record["recordSeed"]["schema_version"], "timeline_for_video.video_record.v1")
            self.assertIs(record["convertInfoSeed"]["source_video_modified"], False)
            self.assertEqual(record["ffprobe"]["summary"]["counts"]["streams"], 2)

    def test_probe_video_files_reports_counts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "clip.mp4"
            source.write_bytes(b"video")
            fake_ffprobe = write_fake_ffprobe(root)
            video_file = video_file_from_path(source, str(root))

            result = probe_video_files([video_file], fake_ffprobe)

            self.assertEqual(result["counts"]["discoveredFiles"], 1)
            self.assertEqual(result["counts"]["probedFiles"], 1)
            self.assertEqual(result["counts"]["failedProbes"], 0)
            self.assertEqual(len(result["records"]), 1)

    def test_probe_video_files_remuxes_when_duration_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output_root = root / "output"
            source = root / "clip.mkv"
            source.write_bytes(b"video")
            source_before = source.read_bytes()
            fake_ffprobe = write_duration_recovery_ffprobe(root)
            fake_ffmpeg = write_fake_ffmpeg_remux(root)
            video_file = video_file_from_path(source, str(root))

            result = probe_video_files(
                [video_file],
                ffprobe_bin=fake_ffprobe,
                ffmpeg_bin=fake_ffmpeg,
                output_root_text=str(output_root),
            )

            record = result["records"][0]
            self.assertEqual(record["ffprobe"]["summary"]["format"]["durationSec"], 12.5)
            self.assertEqual(record["sourceIdentity"]["resolvedPath"], str(source))
            self.assertEqual(record["analysisInput"]["kind"], "normalized_media")
            self.assertTrue(record["mediaNormalization"]["attempted"])
            self.assertTrue(record["mediaNormalization"]["ok"])
            self.assertIn("-c", record["mediaNormalization"]["command"])
            self.assertTrue(Path(record["analysisInput"]["resolvedPath"]).exists())
            self.assertEqual(source.read_bytes(), source_before)
            self.assertIn(
                "duration_missing_resolved_by_media_normalization",
                record["recordSeed"]["processing"]["warnings"],
            )


if __name__ == "__main__":
    unittest.main()
