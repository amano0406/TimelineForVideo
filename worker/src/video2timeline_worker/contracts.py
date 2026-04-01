from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class InputItem:
    input_id: str
    source_kind: str
    source_id: str
    original_path: str
    display_name: str
    size_bytes: int = 0
    uploaded_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class JobRequest:
    schema_version: int
    job_id: str
    created_at: str
    output_root_id: str
    output_root_path: str
    profile: str
    compute_mode: str
    processing_quality: str
    reprocess_duplicates: bool
    token_enabled: bool
    input_items: list[InputItem]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "job_id": self.job_id,
            "created_at": self.created_at,
            "output_root_id": self.output_root_id,
            "output_root_path": self.output_root_path,
            "profile": self.profile,
            "compute_mode": self.compute_mode,
            "processing_quality": self.processing_quality,
            "reprocess_duplicates": self.reprocess_duplicates,
            "token_enabled": self.token_enabled,
            "input_items": [item.to_dict() for item in self.input_items],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "JobRequest":
        return cls(
            schema_version=int(payload["schema_version"]),
            job_id=str(payload["job_id"]),
            created_at=str(payload["created_at"]),
            output_root_id=str(payload["output_root_id"]),
            output_root_path=str(payload["output_root_path"]),
            profile=str(payload["profile"]),
            compute_mode=str(payload.get("compute_mode") or "cpu"),
            processing_quality=str(payload.get("processing_quality") or "standard"),
            reprocess_duplicates=bool(payload["reprocess_duplicates"]),
            token_enabled=bool(payload.get("token_enabled", False)),
            input_items=[InputItem(**item) for item in payload.get("input_items", [])],
        )


@dataclass
class JobStatus:
    schema_version: int = 1
    job_id: str = ""
    state: str = "pending"
    current_stage: str = "queued"
    message: str = ""
    warnings: list[str] = field(default_factory=list)
    videos_total: int = 0
    videos_done: int = 0
    videos_skipped: int = 0
    videos_failed: int = 0
    current_media: str | None = None
    current_media_elapsed_sec: float = 0.0
    current_stage_elapsed_sec: float = 0.0
    processed_duration_sec: float = 0.0
    total_duration_sec: float = 0.0
    estimated_remaining_sec: float | None = None
    progress_percent: float = 0.0
    started_at: str | None = None
    updated_at: str | None = None
    completed_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class JobResult:
    schema_version: int = 1
    job_id: str = ""
    state: str = "pending"
    run_dir: str = ""
    output_root_id: str = ""
    output_root_path: str = ""
    processed_count: int = 0
    skipped_count: int = 0
    error_count: int = 0
    batch_count: int = 0
    timeline_index_path: str | None = None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ManifestItem:
    input_id: str
    source_kind: str
    original_path: str
    file_name: str
    size_bytes: int
    duration_seconds: float
    sha256: str
    duplicate_status: str
    duplicate_of: str | None = None
    media_id: str | None = None
    status: str = "pending"
    container_name: str | None = None
    video_codec: str | None = None
    audio_codec: str | None = None
    width: int | None = None
    height: int | None = None
    frame_rate: float | None = None
    audio_channels: int | None = None
    audio_sample_rate: int | None = None
    has_video: bool | None = None
    has_audio: bool | None = None
    captured_at: str | None = None
    processing_wall_seconds: float | None = None
    stage_elapsed_seconds: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
