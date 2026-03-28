using System.Text.Json.Serialization;

namespace Video2Timeline.Web.Models;

public sealed class RootOption
{
    [JsonPropertyName("id")]
    public string Id { get; set; } = "";

    [JsonPropertyName("displayName")]
    public string DisplayName { get; set; } = "";

    [JsonPropertyName("path")]
    public string Path { get; set; } = "";

    [JsonPropertyName("enabled")]
    public bool Enabled { get; set; } = true;
}

public sealed class AppSettingsDocument
{
    [JsonPropertyName("schemaVersion")]
    public int SchemaVersion { get; set; } = 1;

    [JsonPropertyName("inputRoots")]
    public List<RootOption> InputRoots { get; set; } = [];

    [JsonPropertyName("outputRoots")]
    public List<RootOption> OutputRoots { get; set; } = [];

    [JsonPropertyName("videoExtensions")]
    public List<string> VideoExtensions { get; set; } = [];

    [JsonPropertyName("huggingfaceTermsConfirmed")]
    public bool HuggingfaceTermsConfirmed { get; set; }

    [JsonPropertyName("computeMode")]
    public string ComputeMode { get; set; } = "cpu";

    [JsonPropertyName("processingQuality")]
    public string ProcessingQuality { get; set; } = "standard";

    [JsonPropertyName("uiLanguage")]
    public string UiLanguage { get; set; } = "en";

    [JsonPropertyName("languageSelected")]
    public bool LanguageSelected { get; set; }
}

public sealed class UploadedFileReference
{
    [JsonPropertyName("referenceId")]
    public string ReferenceId { get; set; } = "";

    [JsonPropertyName("storedPath")]
    public string StoredPath { get; set; } = "";

    [JsonPropertyName("originalName")]
    public string OriginalName { get; set; } = "";

    [JsonPropertyName("sizeBytes")]
    public long SizeBytes { get; set; }
}

public sealed class UploadSessionDocument
{
    [JsonPropertyName("sessionId")]
    public string SessionId { get; set; } = "";

    [JsonPropertyName("createdAt")]
    public string CreatedAt { get; set; } = "";

    [JsonPropertyName("chunkSizeBytes")]
    public long ChunkSizeBytes { get; set; }

    [JsonPropertyName("files")]
    public List<UploadSessionFileDocument> Files { get; set; } = [];
}

public sealed class UploadSessionFileDocument
{
    [JsonPropertyName("fileId")]
    public string FileId { get; set; } = "";

    [JsonPropertyName("originalName")]
    public string OriginalName { get; set; } = "";

    [JsonPropertyName("sizeBytes")]
    public long SizeBytes { get; set; }

    [JsonPropertyName("expectedChunks")]
    public int ExpectedChunks { get; set; }

    [JsonPropertyName("uploadedChunks")]
    public int UploadedChunks { get; set; }

    [JsonPropertyName("storedPath")]
    public string StoredPath { get; set; } = "";
}

public sealed class CreateUploadSessionResponse
{
    [JsonPropertyName("sessionId")]
    public string SessionId { get; set; } = "";

    [JsonPropertyName("chunkSizeBytes")]
    public long ChunkSizeBytes { get; set; }
}

public sealed class CreateUploadFileRequest
{
    [JsonPropertyName("originalName")]
    public string OriginalName { get; set; } = "";

    [JsonPropertyName("sizeBytes")]
    public long SizeBytes { get; set; }
}

public sealed class CreateUploadFileResponse
{
    [JsonPropertyName("fileId")]
    public string FileId { get; set; } = "";

    [JsonPropertyName("expectedChunks")]
    public int ExpectedChunks { get; set; }
}

public sealed class ScanRequest
{
    [JsonPropertyName("sourceIds")]
    public List<string> SourceIds { get; set; } = [];
}

public sealed class CreateJobCommand
{
    [JsonPropertyName("sourceIds")]
    public List<string> SourceIds { get; set; } = [];

    [JsonPropertyName("selectedPaths")]
    public List<string> SelectedPaths { get; set; } = [];

    [JsonPropertyName("outputRootId")]
    public string OutputRootId { get; set; } = "runs";

    [JsonPropertyName("reprocessDuplicates")]
    public bool ReprocessDuplicates { get; set; }

    [JsonPropertyName("uploadedFiles")]
    public List<UploadedFileReference> UploadedFiles { get; set; } = [];
}

public sealed class HuggingFaceSaveRequest
{
    [JsonPropertyName("token")]
    public string? Token { get; set; }

    [JsonPropertyName("termsConfirmed")]
    public bool TermsConfirmed { get; set; }
}

public sealed class HuggingFaceAccessSnapshot
{
    [JsonPropertyName("hasToken")]
    public bool HasToken { get; set; }

    [JsonPropertyName("termsConfirmed")]
    public bool TermsConfirmed { get; set; }

    [JsonPropertyName("accessState")]
    public string AccessState { get; set; } = "unknown";

    [JsonPropertyName("accessMessage")]
    public string AccessMessage { get; set; } = "";

    [JsonPropertyName("models")]
    public List<GatedModelStatusItem> Models { get; set; } = [];
}

public sealed class GatedModelStatusItem
{
    [JsonPropertyName("modelId")]
    public string ModelId { get; set; } = "";

    [JsonPropertyName("displayName")]
    public string DisplayName { get; set; } = "";

    [JsonPropertyName("purpose")]
    public string Purpose { get; set; } = "";

    [JsonPropertyName("approvalUrl")]
    public string ApprovalUrl { get; set; } = "";

    [JsonPropertyName("requiresApproval")]
    public bool RequiresApproval { get; set; }

    [JsonPropertyName("tokenConfigured")]
    public bool TokenConfigured { get; set; }

    [JsonPropertyName("termsConfirmed")]
    public bool TermsConfirmed { get; set; }

    [JsonPropertyName("accessState")]
    public string AccessState { get; set; } = "unknown";
}

public sealed class WorkerCapabilitySnapshot
{
    [JsonPropertyName("generatedAt")]
    public string? GeneratedAt { get; set; }

    [JsonPropertyName("torchInstalled")]
    public bool TorchInstalled { get; set; }

    [JsonPropertyName("torchCudaBuilt")]
    public bool TorchCudaBuilt { get; set; }

    [JsonPropertyName("gpuAvailable")]
    public bool GpuAvailable { get; set; }

    [JsonPropertyName("deviceCount")]
    public int DeviceCount { get; set; }

    [JsonPropertyName("deviceNames")]
    public List<string> DeviceNames { get; set; } = [];

    [JsonPropertyName("deviceMemoryGiB")]
    public List<double> DeviceMemoryGiB { get; set; } = [];

    [JsonPropertyName("maxGpuMemoryGiB")]
    public double MaxGpuMemoryGiB { get; set; }

    [JsonPropertyName("message")]
    public string Message { get; set; } = "";
}

public sealed class ModelCacheSnapshot
{
    [JsonPropertyName("hasCache")]
    public bool HasCache { get; set; }

    [JsonPropertyName("totalBytes")]
    public long TotalBytes { get; set; }

    [JsonPropertyName("directoryCount")]
    public int DirectoryCount { get; set; }
}

public sealed class SetupState
{
    public bool HasToken { get; set; }

    public bool TermsConfirmed { get; set; }

    public bool HasSelectedLanguage { get; set; }

    public bool IsReady => HasToken && TermsConfirmed;
}

public sealed class ScannedVideoItem
{
    public string SourceId { get; set; } = "";
    public string SourceKind { get; set; } = "mounted_root";
    public string OriginalPath { get; set; } = "";
    public string DisplayName { get; set; } = "";
    public long SizeBytes { get; set; }
}

public sealed class InputItemDocument
{
    [JsonPropertyName("input_id")]
    public string InputId { get; set; } = "";

    [JsonPropertyName("source_kind")]
    public string SourceKind { get; set; } = "";

    [JsonPropertyName("source_id")]
    public string SourceId { get; set; } = "";

    [JsonPropertyName("original_path")]
    public string OriginalPath { get; set; } = "";

    [JsonPropertyName("display_name")]
    public string DisplayName { get; set; } = "";

    [JsonPropertyName("size_bytes")]
    public long SizeBytes { get; set; }

    [JsonPropertyName("uploaded_path")]
    public string? UploadedPath { get; set; }
}

public sealed class JobRequestDocument
{
    [JsonPropertyName("schema_version")]
    public int SchemaVersion { get; set; } = 1;

    [JsonPropertyName("job_id")]
    public string JobId { get; set; } = "";

    [JsonPropertyName("created_at")]
    public string CreatedAt { get; set; } = "";

    [JsonPropertyName("output_root_id")]
    public string OutputRootId { get; set; } = "";

    [JsonPropertyName("output_root_path")]
    public string OutputRootPath { get; set; } = "";

    [JsonPropertyName("profile")]
    public string Profile { get; set; } = "quality-first";

    [JsonPropertyName("compute_mode")]
    public string ComputeMode { get; set; } = "cpu";

    [JsonPropertyName("processing_quality")]
    public string ProcessingQuality { get; set; } = "standard";

    [JsonPropertyName("reprocess_duplicates")]
    public bool ReprocessDuplicates { get; set; }

    [JsonPropertyName("token_enabled")]
    public bool TokenEnabled { get; set; }

    [JsonPropertyName("input_items")]
    public List<InputItemDocument> InputItems { get; set; } = [];
}

public sealed class JobStatusDocument
{
    [JsonPropertyName("schema_version")]
    public int SchemaVersion { get; set; } = 1;

    [JsonPropertyName("job_id")]
    public string JobId { get; set; } = "";

    [JsonPropertyName("state")]
    public string State { get; set; } = "pending";

    [JsonPropertyName("current_stage")]
    public string CurrentStage { get; set; } = "queued";

    [JsonPropertyName("message")]
    public string Message { get; set; } = "";

    [JsonPropertyName("warnings")]
    public List<string> Warnings { get; set; } = [];

    [JsonPropertyName("videos_total")]
    public int VideosTotal { get; set; }

    [JsonPropertyName("videos_done")]
    public int VideosDone { get; set; }

    [JsonPropertyName("videos_skipped")]
    public int VideosSkipped { get; set; }

    [JsonPropertyName("videos_failed")]
    public int VideosFailed { get; set; }

    [JsonPropertyName("current_media")]
    public string? CurrentMedia { get; set; }

    [JsonPropertyName("current_media_elapsed_sec")]
    public double CurrentMediaElapsedSec { get; set; }

    [JsonPropertyName("processed_duration_sec")]
    public double ProcessedDurationSec { get; set; }

    [JsonPropertyName("total_duration_sec")]
    public double TotalDurationSec { get; set; }

    [JsonPropertyName("estimated_remaining_sec")]
    public double? EstimatedRemainingSec { get; set; }

    [JsonPropertyName("progress_percent")]
    public double ProgressPercent { get; set; }

    [JsonPropertyName("started_at")]
    public string? StartedAt { get; set; }

    [JsonPropertyName("updated_at")]
    public string? UpdatedAt { get; set; }

    [JsonPropertyName("completed_at")]
    public string? CompletedAt { get; set; }
}

public sealed class JobResultDocument
{
    [JsonPropertyName("schema_version")]
    public int SchemaVersion { get; set; } = 1;

    [JsonPropertyName("job_id")]
    public string JobId { get; set; } = "";

    [JsonPropertyName("state")]
    public string State { get; set; } = "pending";

    [JsonPropertyName("run_dir")]
    public string RunDir { get; set; } = "";

    [JsonPropertyName("output_root_id")]
    public string OutputRootId { get; set; } = "";

    [JsonPropertyName("output_root_path")]
    public string OutputRootPath { get; set; } = "";

    [JsonPropertyName("processed_count")]
    public int ProcessedCount { get; set; }

    [JsonPropertyName("skipped_count")]
    public int SkippedCount { get; set; }

    [JsonPropertyName("error_count")]
    public int ErrorCount { get; set; }

    [JsonPropertyName("batch_count")]
    public int BatchCount { get; set; }

    [JsonPropertyName("timeline_index_path")]
    public string? TimelineIndexPath { get; set; }

    [JsonPropertyName("warnings")]
    public List<string> Warnings { get; set; } = [];
}

public sealed class ManifestItemDocument
{
    [JsonPropertyName("input_id")]
    public string InputId { get; set; } = "";

    [JsonPropertyName("source_kind")]
    public string SourceKind { get; set; } = "";

    [JsonPropertyName("original_path")]
    public string OriginalPath { get; set; } = "";

    [JsonPropertyName("file_name")]
    public string FileName { get; set; } = "";

    [JsonPropertyName("size_bytes")]
    public long SizeBytes { get; set; }

    [JsonPropertyName("duration_seconds")]
    public double DurationSeconds { get; set; }

    [JsonPropertyName("sha256")]
    public string Sha256 { get; set; } = "";

    [JsonPropertyName("duplicate_status")]
    public string DuplicateStatus { get; set; } = "";

    [JsonPropertyName("duplicate_of")]
    public string? DuplicateOf { get; set; }

    [JsonPropertyName("media_id")]
    public string? MediaId { get; set; }

    [JsonPropertyName("status")]
    public string Status { get; set; } = "pending";
}

public sealed class ManifestDocument
{
    [JsonPropertyName("schema_version")]
    public int SchemaVersion { get; set; } = 1;

    [JsonPropertyName("job_id")]
    public string JobId { get; set; } = "";

    [JsonPropertyName("generated_at")]
    public string GeneratedAt { get; set; } = "";

    [JsonPropertyName("items")]
    public List<ManifestItemDocument> Items { get; set; } = [];
}

public sealed class RunSummary
{
    public string JobId { get; set; } = "";
    public string RunDirectory { get; set; } = "";
    public string OutputRootId { get; set; } = "";
    public string State { get; set; } = "pending";
    public string CurrentStage { get; set; } = "queued";
    public int VideosTotal { get; set; }
    public int VideosDone { get; set; }
    public int VideosSkipped { get; set; }
    public int VideosFailed { get; set; }
    public long TotalSizeBytes { get; set; }
    public double TotalDurationSec { get; set; }
    public double? EstimatedRemainingSec { get; set; }
    public double ProgressPercent { get; set; }
    public bool HasDownloadableArchive { get; set; }
    public string? UpdatedAt { get; set; }
    public string? CreatedAt { get; set; }
}

public sealed class TimelineMediaItem
{
    public string MediaId { get; set; } = "";
    public string SourcePath { get; set; } = "";
    public string TimelinePath { get; set; } = "";
    public string Status { get; set; } = "pending";
}

public sealed class RunDetails
{
    public string JobId { get; set; } = "";
    public string RunDirectory { get; set; } = "";
    public JobStatusDocument? Status { get; set; }
    public JobResultDocument? Result { get; set; }
    public ManifestDocument? Manifest { get; set; }
    public IReadOnlyList<TimelineMediaItem> TimelineItems { get; set; } = [];
    public string LogTail { get; set; } = "";
}
