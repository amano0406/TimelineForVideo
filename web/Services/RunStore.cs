using System.IO.Compression;
using System.Text.Json;
using Video2Timeline.Web.Models;

namespace Video2Timeline.Web.Services;

public sealed class RunStore(AppPaths paths, SettingsStore settingsStore, ScanService scanService)
{
    private readonly JsonSerializerOptions _jsonOptions = new()
    {
        WriteIndented = true,
        PropertyNameCaseInsensitive = true,
    };

    public async Task<IReadOnlyList<UploadedFileReference>> SaveUploadsAsync(
        IEnumerable<IFormFile> files,
        CancellationToken cancellationToken = default)
    {
        var list = files?.Where(static file => file.Length > 0).ToList() ?? [];
        if (list.Count == 0)
        {
            return [];
        }

        var uploadFolder = Path.Combine(
            paths.UploadsRoot,
            $"upload-{DateTimeOffset.Now:yyyyMMdd-HHmmss}-{Guid.NewGuid():N}"[..36]);
        Directory.CreateDirectory(uploadFolder);

        var stored = new List<UploadedFileReference>();
        foreach (var file in list)
        {
            cancellationToken.ThrowIfCancellationRequested();
            var safeName = MakeSafeFileName(file.FileName);
            var storedFileName = $"{stored.Count + 1:D4}-{safeName}";
            var storedPath = Path.Combine(uploadFolder, storedFileName);
            if (File.Exists(storedPath))
            {
                storedFileName = $"{stored.Count + 1:D4}-{Guid.NewGuid():N}".Replace("--", "-");
                storedFileName = $"{storedFileName[..Math.Min(storedFileName.Length, 20)]}-{safeName}";
                storedPath = Path.Combine(uploadFolder, storedFileName);
            }

            await using var stream = File.Create(storedPath);
            await file.CopyToAsync(stream, cancellationToken);
            stored.Add(new UploadedFileReference
            {
                ReferenceId = $"{Path.GetFileName(uploadFolder)}:{storedFileName}",
                StoredPath = storedPath,
                OriginalName = file.FileName,
                SizeBytes = file.Length,
            });
        }

        return stored;
    }

    public async Task<(string JobId, string RunDirectory)> CreateJobAsync(
        CreateJobCommand command,
        CancellationToken cancellationToken = default)
    {
        var settings = await settingsStore.LoadAsync(cancellationToken);
        var outputRoot = settings.OutputRoots
            .FirstOrDefault(root => root.Enabled && string.Equals(root.Id, command.OutputRootId, StringComparison.OrdinalIgnoreCase))
            ?? settings.OutputRoots.FirstOrDefault(static root => root.Enabled);
        if (outputRoot is null)
        {
            throw new InvalidOperationException("No enabled output root is configured.");
        }

        Directory.CreateDirectory(outputRoot.Path);
        var scannedItems = await scanService.ScanAsync(command.SourceIds, cancellationToken);
        var selectedPaths = command.SelectedPaths
            .Where(static path => !string.IsNullOrWhiteSpace(path))
            .ToHashSet(StringComparer.OrdinalIgnoreCase);
        if (selectedPaths.Count > 0)
        {
            scannedItems = scannedItems
                .Where(item => selectedPaths.Contains(item.OriginalPath))
                .ToList();
        }

        var inputItems = scannedItems
            .Select((item, index) => new InputItemDocument
            {
                InputId = $"scan-{index + 1:D4}",
                SourceKind = item.SourceKind,
                SourceId = item.SourceId,
                OriginalPath = item.OriginalPath,
                DisplayName = item.DisplayName,
                SizeBytes = item.SizeBytes,
            })
            .ToList();

        var uploadItems = command.UploadedFiles
            .Select((file, index) => new InputItemDocument
            {
                InputId = $"upload-{index + 1:D4}",
                SourceKind = "upload",
                SourceId = "uploads",
                OriginalPath = file.OriginalName,
                DisplayName = file.OriginalName,
                SizeBytes = file.SizeBytes,
                UploadedPath = file.StoredPath,
            })
            .ToList();

        inputItems.AddRange(uploadItems);
        if (inputItems.Count == 0)
        {
            throw new InvalidOperationException("No input videos were selected.");
        }

        var hasToken = await settingsStore.HasTokenAsync(cancellationToken);
        return await CreateJobFromInputsAsync(
            outputRoot,
            inputItems,
            command.ReprocessDuplicates,
            hasToken,
            settings.ComputeMode,
            settings.ProcessingQuality,
            cancellationToken);
    }

    public async Task<RunSummary?> GetActiveRunAsync(CancellationToken cancellationToken = default)
    {
        var summaries = await ListRunsAsync(cancellationToken);
        return summaries.FirstOrDefault(static run =>
            string.Equals(run.State, "pending", StringComparison.OrdinalIgnoreCase) ||
            string.Equals(run.State, "running", StringComparison.OrdinalIgnoreCase));
    }

    public async Task<(string JobId, string RunDirectory)> CreateJobFromExistingAsync(
        string jobId,
        CancellationToken cancellationToken = default)
    {
        var settings = await settingsStore.LoadAsync(cancellationToken);
        var existingRunDirectory = await FindRunDirectoryAsync(jobId, cancellationToken);
        if (existingRunDirectory is null)
        {
            throw new InvalidOperationException("The selected run could not be found.");
        }

        var existingRequest = await ReadJsonAsync<JobRequestDocument>(
            Path.Combine(existingRunDirectory, "request.json"),
            cancellationToken);
        if (existingRequest is null || existingRequest.InputItems.Count == 0)
        {
            throw new InvalidOperationException("The selected run does not have a reusable request.");
        }

        var outputRoot = settings.OutputRoots
            .FirstOrDefault(root => root.Enabled && string.Equals(root.Id, existingRequest.OutputRootId, StringComparison.OrdinalIgnoreCase))
            ?? settings.OutputRoots.FirstOrDefault(static root => root.Enabled);
        if (outputRoot is null)
        {
            throw new InvalidOperationException("No enabled output root is configured.");
        }

        var hasToken = await settingsStore.HasTokenAsync(cancellationToken);
        return await CreateJobFromInputsAsync(
            outputRoot,
            existingRequest.InputItems.Select(CloneInputItem).ToList(),
            existingRequest.ReprocessDuplicates,
            hasToken,
            existingRequest.ComputeMode,
            existingRequest.ProcessingQuality,
            cancellationToken);
    }

    public async Task<JobRequestDocument?> GetJobRequestAsync(string jobId, CancellationToken cancellationToken = default)
    {
        var runDirectory = await FindRunDirectoryAsync(jobId, cancellationToken);
        if (runDirectory is null)
        {
            return null;
        }

        return await ReadJsonAsync<JobRequestDocument>(Path.Combine(runDirectory, "request.json"), cancellationToken);
    }

    public async Task DeleteRunAsync(string jobId, CancellationToken cancellationToken = default)
    {
        var runDirectory = await FindRunDirectoryAsync(jobId, cancellationToken);
        if (runDirectory is null)
        {
            throw new InvalidOperationException("The selected run could not be found.");
        }

        var status = await ReadJsonAsync<JobStatusDocument>(Path.Combine(runDirectory, "status.json"), cancellationToken);
        if (status is not null &&
            (string.Equals(status.State, "pending", StringComparison.OrdinalIgnoreCase) ||
             string.Equals(status.State, "running", StringComparison.OrdinalIgnoreCase)))
        {
            throw new InvalidOperationException("Active runs cannot be deleted.");
        }

        var request = await ReadJsonAsync<JobRequestDocument>(Path.Combine(runDirectory, "request.json"), cancellationToken);
        DeleteUploadDirectories(request);
        Directory.Delete(runDirectory, recursive: true);
    }

    public async Task<int> DeleteCompletedRunsAsync(CancellationToken cancellationToken = default)
    {
        var deleted = 0;
        var settings = await settingsStore.LoadAsync(cancellationToken);
        foreach (var root in settings.OutputRoots.Where(static root => root.Enabled))
        {
            if (!Directory.Exists(root.Path))
            {
                continue;
            }

            foreach (var runDirectory in Directory.EnumerateDirectories(root.Path, "run-*", SearchOption.TopDirectoryOnly))
            {
                cancellationToken.ThrowIfCancellationRequested();
                var status = await ReadJsonAsync<JobStatusDocument>(Path.Combine(runDirectory, "status.json"), cancellationToken);
                if (status is null ||
                    string.Equals(status.State, "pending", StringComparison.OrdinalIgnoreCase) ||
                    string.Equals(status.State, "running", StringComparison.OrdinalIgnoreCase))
                {
                    continue;
                }

                var request = await ReadJsonAsync<JobRequestDocument>(Path.Combine(runDirectory, "request.json"), cancellationToken);
                DeleteUploadDirectories(request);
                Directory.Delete(runDirectory, recursive: true);
                deleted++;
            }
        }

        if (Directory.Exists(paths.DownloadsRoot))
        {
            foreach (var archive in Directory.EnumerateFiles(paths.DownloadsRoot, "*.zip", SearchOption.TopDirectoryOnly))
            {
                cancellationToken.ThrowIfCancellationRequested();
                File.Delete(archive);
            }
        }

        return deleted;
    }

    public async Task<int> CleanupExpiredUploadsAsync(TimeSpan retention, CancellationToken cancellationToken = default)
    {
        var deletedCount = 0;
        var now = DateTimeOffset.Now;
        var settings = await settingsStore.LoadAsync(cancellationToken);
        foreach (var root in settings.OutputRoots.Where(static root => root.Enabled))
        {
            if (!Directory.Exists(root.Path))
            {
                continue;
            }

            foreach (var runDirectory in Directory.EnumerateDirectories(root.Path, "run-*", SearchOption.TopDirectoryOnly))
            {
                cancellationToken.ThrowIfCancellationRequested();
                var status = await ReadJsonAsync<JobStatusDocument>(Path.Combine(runDirectory, "status.json"), cancellationToken);
                if (status is null)
                {
                    continue;
                }

                if (!string.Equals(status.State, "completed", StringComparison.OrdinalIgnoreCase) &&
                    !string.Equals(status.State, "failed", StringComparison.OrdinalIgnoreCase) &&
                    !string.Equals(status.State, "canceled", StringComparison.OrdinalIgnoreCase))
                {
                    continue;
                }

                var completedAt = ParseTimestamp(status.CompletedAt) ?? ParseTimestamp(status.UpdatedAt);
                if (completedAt is null || now - completedAt.Value < retention)
                {
                    continue;
                }

                var request = await ReadJsonAsync<JobRequestDocument>(Path.Combine(runDirectory, "request.json"), cancellationToken);
                deletedCount += DeleteUploadDirectories(request);
            }
        }

        return deletedCount;
    }

    public async Task<int> CleanupOrphanedUploadSessionsAsync(TimeSpan retention, CancellationToken cancellationToken = default)
    {
        if (!Directory.Exists(paths.UploadsRoot))
        {
            return 0;
        }

        var referencedDirectories = await GetReferencedUploadDirectoriesAsync(cancellationToken);
        var deletedCount = 0;
        var now = DateTimeOffset.Now;

        foreach (var sessionDirectory in Directory.EnumerateDirectories(paths.UploadsRoot, "session-*", SearchOption.TopDirectoryOnly))
        {
            cancellationToken.ThrowIfCancellationRequested();

            var fullDirectory = Path.GetFullPath(sessionDirectory);
            if (!IsSubdirectoryOf(fullDirectory, Path.GetFullPath(paths.UploadsRoot)))
            {
                continue;
            }

            if (referencedDirectories.Contains(fullDirectory))
            {
                continue;
            }

            var sessionCreatedAt = await ReadUploadSessionCreatedAtAsync(sessionDirectory, cancellationToken)
                ?? new DateTimeOffset(Directory.GetCreationTimeUtc(sessionDirectory));

            if (retention > TimeSpan.Zero && now - sessionCreatedAt < retention)
            {
                continue;
            }

            Directory.Delete(fullDirectory, recursive: true);
            deletedCount += 1;
        }

        return deletedCount;
    }

    public async Task<string?> BuildRunArchiveAsync(string jobId, CancellationToken cancellationToken = default)
    {
        var runDirectory = await FindRunDirectoryAsync(jobId, cancellationToken);
        if (runDirectory is null)
        {
            return null;
        }

        var status = await ReadJsonAsync<JobStatusDocument>(Path.Combine(runDirectory, "status.json"), cancellationToken);
        if (status is null || !string.Equals(status.State, "completed", StringComparison.OrdinalIgnoreCase))
        {
            throw new InvalidOperationException("The run is not completed yet.");
        }

        Directory.CreateDirectory(paths.DownloadsRoot);
        var destination = Path.Combine(paths.DownloadsRoot, $"{jobId}.zip");
        if (File.Exists(destination))
        {
            File.Delete(destination);
        }

        var stagingRoot = Path.Combine(paths.DownloadsRoot, $"{jobId}-export-{Guid.NewGuid():N}");
        Directory.CreateDirectory(stagingRoot);

        try
        {
            await Task.Run(() => BuildExportPackage(runDirectory, jobId, stagingRoot), cancellationToken);
            await Task.Run(
                () => ZipFile.CreateFromDirectory(stagingRoot, destination, CompressionLevel.Fastest, includeBaseDirectory: false),
                cancellationToken);
        }
        finally
        {
            if (Directory.Exists(stagingRoot))
            {
                Directory.Delete(stagingRoot, recursive: true);
            }
        }

        return destination;
    }

    public async Task<JobStatusDocument?> GetJobStatusAsync(string jobId, CancellationToken cancellationToken = default)
    {
        var runDirectory = await FindRunDirectoryAsync(jobId, cancellationToken);
        if (runDirectory is null)
        {
            return null;
        }

        var path = Path.Combine(runDirectory, "status.json");
        return await ReadJsonAsync<JobStatusDocument>(path, cancellationToken);
    }

    public async Task<RunDetails?> GetRunDetailsAsync(string jobId, CancellationToken cancellationToken = default)
    {
        var runDirectory = await FindRunDirectoryAsync(jobId, cancellationToken);
        if (runDirectory is null)
        {
            return null;
        }

        var details = new RunDetails
        {
            JobId = jobId,
            RunDirectory = runDirectory,
            Status = await ReadJsonAsync<JobStatusDocument>(Path.Combine(runDirectory, "status.json"), cancellationToken),
            Result = await ReadJsonAsync<JobResultDocument>(Path.Combine(runDirectory, "result.json"), cancellationToken),
            Manifest = await ReadJsonAsync<ManifestDocument>(Path.Combine(runDirectory, "manifest.json"), cancellationToken),
            LogTail = await ReadLogTailAsync(Path.Combine(runDirectory, "logs", "worker.log"), cancellationToken),
        };

        details.TimelineItems = details.Manifest?.Items
            .Where(static item => !string.IsNullOrWhiteSpace(item.MediaId))
            .Select(item => new TimelineMediaItem
            {
                MediaId = item.MediaId!,
                SourcePath = item.OriginalPath,
                TimelinePath = Path.Combine(runDirectory, "media", item.MediaId!, "timeline", "timeline.md"),
                Status = item.Status,
            })
            .Where(static item => File.Exists(item.TimelinePath))
            .ToList() ?? [];

        return details;
    }

    public async Task<string?> ReadTimelineAsync(string jobId, string mediaId, CancellationToken cancellationToken = default)
    {
        var runDirectory = await FindRunDirectoryAsync(jobId, cancellationToken);
        if (runDirectory is null)
        {
            return null;
        }

        var timelinePath = Path.Combine(runDirectory, "media", mediaId, "timeline", "timeline.md");
        if (!File.Exists(timelinePath))
        {
            return null;
        }

        return await File.ReadAllTextAsync(timelinePath, cancellationToken);
    }

    public async Task<IReadOnlyList<RunSummary>> ListRunsAsync(CancellationToken cancellationToken = default)
    {
        var settings = await settingsStore.LoadAsync(cancellationToken);
        var summaries = new List<RunSummary>();
        foreach (var root in settings.OutputRoots.Where(static root => root.Enabled))
        {
            if (!Directory.Exists(root.Path))
            {
                continue;
            }

            foreach (var runDirectory in Directory.EnumerateDirectories(root.Path, "run-*", SearchOption.TopDirectoryOnly))
            {
                cancellationToken.ThrowIfCancellationRequested();
                var request = await ReadJsonAsync<JobRequestDocument>(Path.Combine(runDirectory, "request.json"), cancellationToken);
                var status = await ReadJsonAsync<JobStatusDocument>(Path.Combine(runDirectory, "status.json"), cancellationToken);
                if (request is null || status is null)
                {
                    continue;
                }

                var manifest = await ReadJsonAsync<ManifestDocument>(Path.Combine(runDirectory, "manifest.json"), cancellationToken);
                var totalSizeBytes = manifest?.Items.Sum(static item => item.SizeBytes) ?? 0L;
                var totalDurationSec = manifest?.Items.Sum(static item => item.DurationSeconds) ?? 0.0;

                summaries.Add(new RunSummary
                {
                    JobId = request.JobId,
                    RunDirectory = runDirectory,
                    OutputRootId = request.OutputRootId,
                    State = status.State,
                    CurrentStage = status.CurrentStage,
                    VideosTotal = status.VideosTotal,
                    VideosDone = status.VideosDone,
                    VideosSkipped = status.VideosSkipped,
                    VideosFailed = status.VideosFailed,
                    TotalSizeBytes = totalSizeBytes,
                    TotalDurationSec = totalDurationSec,
                    ProgressPercent = status.ProgressPercent > 0
                        ? status.ProgressPercent
                        : status.VideosTotal > 0
                            ? Math.Round(status.VideosDone * 100.0 / status.VideosTotal, 1)
                            : 0,
                    UpdatedAt = status.UpdatedAt,
                    CreatedAt = request.CreatedAt,
                });
            }
        }

        return summaries
            .OrderByDescending(static row => row.CreatedAt)
            .ToList();
    }

    private async Task<(string JobId, string RunDirectory)> CreateJobFromInputsAsync(
        RootOption outputRoot,
        IReadOnlyList<InputItemDocument> inputItems,
        bool reprocessDuplicates,
        bool hasToken,
        string computeMode,
        string processingQuality,
        CancellationToken cancellationToken)
    {
        var jobId = $"run-{DateTimeOffset.Now:yyyyMMdd-HHmmss}-{Guid.NewGuid():N}"[..28];
        var runDirectory = Path.Combine(outputRoot.Path, jobId);
        Directory.CreateDirectory(runDirectory);
        Directory.CreateDirectory(Path.Combine(runDirectory, "media"));
        Directory.CreateDirectory(Path.Combine(runDirectory, "llm"));
        Directory.CreateDirectory(Path.Combine(runDirectory, "logs"));

        var request = new JobRequestDocument
        {
            SchemaVersion = 1,
            JobId = jobId,
            CreatedAt = DateTimeOffset.Now.ToString("O"),
            OutputRootId = outputRoot.Id,
            OutputRootPath = outputRoot.Path,
            Profile = "quality-first",
            ComputeMode = string.Equals(computeMode, "gpu", StringComparison.OrdinalIgnoreCase) ? "gpu" : "cpu",
            ProcessingQuality = string.Equals(processingQuality, "high", StringComparison.OrdinalIgnoreCase) ? "high" : "standard",
            ReprocessDuplicates = reprocessDuplicates,
            TokenEnabled = hasToken,
            InputItems = inputItems.Select(CloneInputItem).ToList(),
        };

        var status = new JobStatusDocument
        {
            JobId = jobId,
            State = "pending",
            CurrentStage = "queued",
            Message = "Queued for worker pickup.",
            VideosTotal = inputItems.Count,
            UpdatedAt = DateTimeOffset.Now.ToString("O"),
        };

        var result = new JobResultDocument
        {
            JobId = jobId,
            State = "pending",
            RunDir = runDirectory,
            OutputRootId = outputRoot.Id,
            OutputRootPath = outputRoot.Path,
        };

        var manifest = new ManifestDocument
        {
            JobId = jobId,
            GeneratedAt = DateTimeOffset.Now.ToString("O"),
            Items = [],
        };

        await WriteJsonAsync(Path.Combine(runDirectory, "request.json"), request, cancellationToken);
        await WriteJsonAsync(Path.Combine(runDirectory, "status.json"), status, cancellationToken);
        await WriteJsonAsync(Path.Combine(runDirectory, "result.json"), result, cancellationToken);
        await WriteJsonAsync(Path.Combine(runDirectory, "manifest.json"), manifest, cancellationToken);
        await File.WriteAllTextAsync(Path.Combine(runDirectory, "RUN_INFO.md"), "# Run Info\n\nPending worker pickup.\n", cancellationToken);
        await File.WriteAllTextAsync(Path.Combine(runDirectory, "TRANSCRIPTION_INFO.md"), "# Transcription Info\n\nPending worker pickup.\n", cancellationToken);
        await File.WriteAllTextAsync(Path.Combine(runDirectory, "NOTICE.md"), "# Notice\n\nPending worker pickup.\n", cancellationToken);

        return (jobId, runDirectory);
    }

    private async Task<string?> FindRunDirectoryAsync(string jobId, CancellationToken cancellationToken)
    {
        var settings = await settingsStore.LoadAsync(cancellationToken);
        foreach (var root in settings.OutputRoots.Where(static root => root.Enabled))
        {
            var candidate = Path.Combine(root.Path, jobId);
            if (Directory.Exists(candidate))
            {
                return candidate;
            }
        }

        return null;
    }

    private async Task<T?> ReadJsonAsync<T>(string path, CancellationToken cancellationToken)
    {
        if (!File.Exists(path))
        {
            return default;
        }

        await using var stream = File.OpenRead(path);
        return await JsonSerializer.DeserializeAsync<T>(stream, _jsonOptions, cancellationToken);
    }

    private async Task WriteJsonAsync<T>(string path, T value, CancellationToken cancellationToken)
    {
        var directory = Path.GetDirectoryName(path);
        if (!string.IsNullOrWhiteSpace(directory))
        {
            Directory.CreateDirectory(directory);
        }

        await File.WriteAllTextAsync(path, JsonSerializer.Serialize(value, _jsonOptions), cancellationToken);
    }

    private static async Task<string> ReadLogTailAsync(string path, CancellationToken cancellationToken)
    {
        if (!File.Exists(path))
        {
            return "";
        }

        var text = await File.ReadAllTextAsync(path, cancellationToken);
        var lines = text.Split('\n', StringSplitOptions.None);
        return string.Join(Environment.NewLine, lines.TakeLast(80));
    }

    private static string MakeSafeFileName(string value)
    {
        var invalid = Path.GetInvalidFileNameChars();
        var sanitized = new string(value.Select(ch => invalid.Contains(ch) ? '_' : ch).ToArray());
        return string.IsNullOrWhiteSpace(sanitized) ? $"upload-{Guid.NewGuid():N}.bin" : sanitized;
    }

    private int DeleteUploadDirectories(JobRequestDocument? request)
    {
        if (request is null)
        {
            return 0;
        }

        var uploadsRoot = Path.GetFullPath(paths.UploadsRoot);
        var deletedCount = 0;
        var directories = request.InputItems
            .Where(static item => string.Equals(item.SourceKind, "upload", StringComparison.OrdinalIgnoreCase))
            .Select(static item => item.UploadedPath)
            .Where(static path => !string.IsNullOrWhiteSpace(path))
            .Select(static path => Path.GetDirectoryName(path!))
            .Where(static path => !string.IsNullOrWhiteSpace(path))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToList();

        foreach (var directory in directories)
        {
            if (directory is null || !Directory.Exists(directory))
            {
                continue;
            }

            var fullDirectory = Path.GetFullPath(directory);
            if (!IsSubdirectoryOf(fullDirectory, uploadsRoot))
            {
                continue;
            }

            Directory.Delete(directory, recursive: true);
            deletedCount += 1;
        }

        return deletedCount;
    }

    private async Task<HashSet<string>> GetReferencedUploadDirectoriesAsync(CancellationToken cancellationToken)
    {
        var referenced = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var settings = await settingsStore.LoadAsync(cancellationToken);

        foreach (var root in settings.OutputRoots.Where(static root => root.Enabled))
        {
            if (!Directory.Exists(root.Path))
            {
                continue;
            }

            foreach (var runDirectory in Directory.EnumerateDirectories(root.Path, "run-*", SearchOption.TopDirectoryOnly))
            {
                cancellationToken.ThrowIfCancellationRequested();
                var request = await ReadJsonAsync<JobRequestDocument>(Path.Combine(runDirectory, "request.json"), cancellationToken);
                if (request is null)
                {
                    continue;
                }

                foreach (var directory in request.InputItems
                    .Where(static item => string.Equals(item.SourceKind, "upload", StringComparison.OrdinalIgnoreCase))
                    .Select(static item => item.UploadedPath)
                    .Where(static path => !string.IsNullOrWhiteSpace(path))
                    .Select(static path => Path.GetDirectoryName(path!))
                    .Where(static path => !string.IsNullOrWhiteSpace(path)))
                {
                    referenced.Add(Path.GetFullPath(directory!));
                }
            }
        }

        return referenced;
    }

    private async Task<DateTimeOffset?> ReadUploadSessionCreatedAtAsync(string sessionDirectory, CancellationToken cancellationToken)
    {
        var path = Path.Combine(sessionDirectory, "session.json");
        var session = await ReadJsonAsync<UploadSessionDocument>(path, cancellationToken);
        return ParseTimestamp(session?.CreatedAt);
    }

    private static DateTimeOffset? ParseTimestamp(string? value)
    {
        if (string.IsNullOrWhiteSpace(value))
        {
            return null;
        }

        return DateTimeOffset.TryParse(value, out var parsed) ? parsed : null;
    }

    private static InputItemDocument CloneInputItem(InputItemDocument source) =>
        new()
        {
            InputId = source.InputId,
            SourceKind = source.SourceKind,
            SourceId = source.SourceId,
            OriginalPath = source.OriginalPath,
            DisplayName = source.DisplayName,
            SizeBytes = source.SizeBytes,
            UploadedPath = source.UploadedPath,
        };

    private static bool IsSubdirectoryOf(string candidate, string root)
    {
        if (string.Equals(candidate, root, StringComparison.OrdinalIgnoreCase))
        {
            return false;
        }

        var normalizedRoot = root.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar)
            + Path.DirectorySeparatorChar;
        return candidate.StartsWith(normalizedRoot, StringComparison.OrdinalIgnoreCase);
    }

    private static void BuildExportPackage(string runDirectory, string jobId, string exportRoot)
    {
        Directory.CreateDirectory(exportRoot);
        var timelinesRoot = Path.Combine(exportRoot, "timelines");
        Directory.CreateDirectory(timelinesRoot);
        var timelineRows = new List<(string MediaId, string Label, string TimelinePath, string SourcePath)>();
        var mediaRoot = Path.Combine(runDirectory, "media");

        if (Directory.Exists(mediaRoot))
        {
            foreach (var mediaDirectory in Directory.EnumerateDirectories(mediaRoot).OrderBy(static value => value, StringComparer.OrdinalIgnoreCase))
            {
                var mediaId = Path.GetFileName(mediaDirectory);
                var timelinePath = Path.Combine(mediaDirectory, "timeline", "timeline.md");
                if (!File.Exists(timelinePath))
                {
                    continue;
                }

                SourceInfoExportDocument? sourceInfo = null;
                var sourcePath = Path.Combine(mediaDirectory, "source.json");
                if (File.Exists(sourcePath))
                {
                    try
                    {
                        sourceInfo = JsonSerializer.Deserialize<SourceInfoExportDocument>(File.ReadAllText(sourcePath));
                    }
                    catch
                    {
                        sourceInfo = null;
                    }
                }

                timelineRows.Add((
                    mediaId,
                    BestExportLabel(mediaId, sourceInfo),
                    timelinePath,
                    sourceInfo?.OriginalPath ?? string.Empty));
            }
        }

        timelineRows = timelineRows
            .OrderBy(static row => row.Label, StringComparer.OrdinalIgnoreCase)
            .ThenBy(static row => row.MediaId, StringComparer.OrdinalIgnoreCase)
            .ToList();

        var transcriptionInfoPath = Path.Combine(runDirectory, "TRANSCRIPTION_INFO.md");
        if (File.Exists(transcriptionInfoPath))
        {
            File.Copy(transcriptionInfoPath, Path.Combine(exportRoot, "TRANSCRIPTION_INFO.md"), overwrite: true);
        }

        var packageInfo = string.Join(
            Environment.NewLine,
            [
                "# README",
                "",
                "This ZIP contains timeline markdown files that are ready to review or upload to an LLM such as ChatGPT.",
                "",
                $"- Job ID: `{jobId}`",
                "- Main folder: `timelines/`",
                "- Each markdown file is one video timeline.",
                "- `TRANSCRIPTION_INFO.md` explains which processing and models were used.",
                "",
            ]);
        File.WriteAllText(Path.Combine(exportRoot, "README.md"), packageInfo);

        var usedNames = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var row in timelineRows)
        {
            var fileName = EnsureUniqueExportFileName($"{row.Label}.md", usedNames);
            File.Copy(row.TimelinePath, Path.Combine(timelinesRoot, fileName), overwrite: true);
        }
    }

    private static string BestExportLabel(string mediaId, SourceInfoExportDocument? sourceInfo)
    {
        var candidates = new[]
        {
            sourceInfo?.CapturedAt,
            sourceInfo?.DisplayName,
            sourceInfo?.OriginalPath,
            mediaId,
        };

        foreach (var candidate in candidates)
        {
            if (string.IsNullOrWhiteSpace(candidate))
            {
                continue;
            }

            if (TryParseBestEffortDateTime(candidate, out var parsed))
            {
                return parsed.ToString("yyyy-MM-dd HH-mm-ss", System.Globalization.CultureInfo.InvariantCulture);
            }
        }

        if (!string.IsNullOrWhiteSpace(sourceInfo?.ResolvedPath) && File.Exists(sourceInfo.ResolvedPath))
        {
            return File.GetLastWriteTime(sourceInfo.ResolvedPath).ToString("yyyy-MM-dd HH-mm-ss", System.Globalization.CultureInfo.InvariantCulture);
        }

        return MakeSafeFileName(mediaId);
    }

    private static string EnsureUniqueExportFileName(string fileName, HashSet<string> usedNames)
    {
        var baseName = Path.GetFileNameWithoutExtension(fileName);
        var extension = Path.GetExtension(fileName);
        var candidate = fileName;
        var suffix = 2;

        while (!usedNames.Add(candidate))
        {
            candidate = $"{baseName}-{suffix}{extension}";
            suffix++;
        }

        return candidate;
    }

    private static bool TryParseBestEffortDateTime(string value, out DateTime parsed)
    {
        if (DateTime.TryParse(value, out parsed))
        {
            return true;
        }

        foreach (var pattern in new[]
                 {
                     "yyyy-MM-dd HH-mm-ss",
                     "yyyy-MM-dd HH:mm:ss",
                     "yyyyMMdd-HHmmss",
                     "yyyyMMddHHmmss",
                     "yyyy-MM-ddTHH:mm:ss",
                     "yyyy-MM-ddTHH:mm:ssK",
                 })
        {
            if (DateTime.TryParseExact(
                value,
                pattern,
                System.Globalization.CultureInfo.InvariantCulture,
                System.Globalization.DateTimeStyles.AllowWhiteSpaces | System.Globalization.DateTimeStyles.AssumeLocal,
                out parsed))
            {
                return true;
            }
        }

        parsed = default;
        return false;
    }

    private sealed class SourceInfoExportDocument
    {
        public string? OriginalPath { get; set; }

        public string? ResolvedPath { get; set; }

        public string? DisplayName { get; set; }

        public string? CapturedAt { get; set; }
    }
}
