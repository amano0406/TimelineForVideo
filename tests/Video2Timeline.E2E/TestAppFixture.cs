using System.Diagnostics;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Text.Json;

namespace Video2Timeline.E2E;

internal sealed class TestAppFixture : IAsyncDisposable
{
    private readonly StringBuilder _logs = new();
    private readonly Process _process;

    private TestAppFixture(string repoRoot, string tempRoot, int port, Process process)
    {
        RepoRoot = repoRoot;
        TempRoot = tempRoot;
        Port = port;
        BaseUrl = $"http://127.0.0.1:{port}";
        _process = process;
        _process.OutputDataReceived += (_, args) =>
        {
            if (args.Data is not null)
            {
                lock (_logs)
                {
                    _logs.AppendLine(args.Data);
                }
            }
        };
        _process.ErrorDataReceived += (_, args) =>
        {
            if (args.Data is not null)
            {
                lock (_logs)
                {
                    _logs.AppendLine(args.Data);
                }
            }
        };
    }

    public string RepoRoot { get; }

    public string TempRoot { get; }

    public int Port { get; }

    public string BaseUrl { get; }

    public string CompletedJobId => "run-e2e-completed";

    public string CompletedMediaId => "sample-media-001";

    public static async Task<TestAppFixture> StartAsync()
    {
        var repoRoot = Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "..", "..", "..", "..", ".."));
        var tempRoot = Path.Combine(Path.GetTempPath(), $"video2timeline-e2e-{Guid.NewGuid():N}");
        Directory.CreateDirectory(tempRoot);

        var port = GetFreePort();
        var fixture = await CreateAndStartAsync(repoRoot, tempRoot, port);
        await fixture.WaitUntilReadyAsync();
        return fixture;
    }

    private static async Task<TestAppFixture> CreateAndStartAsync(string repoRoot, string tempRoot, int port)
    {
        var appDataRoot = Path.Combine(tempRoot, "app-data");
        var uploadsRoot = Path.Combine(tempRoot, "uploads");
        var outputRoot = Path.Combine(tempRoot, "outputs", "runs");
        var runtimeDefaultsPath = Path.Combine(tempRoot, "runtime.defaults.json");
        Directory.CreateDirectory(appDataRoot);
        Directory.CreateDirectory(uploadsRoot);
        Directory.CreateDirectory(outputRoot);

        await File.WriteAllTextAsync(
            runtimeDefaultsPath,
            JsonSerializer.Serialize(CreateRuntimeDefaults(outputRoot), new JsonSerializerOptions { WriteIndented = true }));

        await SeedCompletedRunAsync(outputRoot);

        var appDllPath = Path.Combine(repoRoot, "web", "bin", "Debug", "net10.0", "Video2Timeline.Web.dll");
        var startInfo = new ProcessStartInfo("dotnet", $"\"{appDllPath}\" --urls http://127.0.0.1:{port}")
        {
            WorkingDirectory = repoRoot,
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
        };
        startInfo.Environment["VIDEO2TIMELINE_RUNTIME_DEFAULTS"] = runtimeDefaultsPath;
        startInfo.Environment["VIDEO2TIMELINE_APPDATA_ROOT"] = appDataRoot;
        startInfo.Environment["VIDEO2TIMELINE_UPLOADS_ROOT"] = uploadsRoot;
        startInfo.Environment["ASPNETCORE_ENVIRONMENT"] = "Development";

        var process = new Process { StartInfo = startInfo };
        var fixture = new TestAppFixture(repoRoot, tempRoot, port, process);
        if (!process.Start())
        {
            throw new InvalidOperationException("Failed to start the ASP.NET Core test host.");
        }

        process.BeginOutputReadLine();
        process.BeginErrorReadLine();
        return fixture;
    }

    private async Task WaitUntilReadyAsync()
    {
        using var client = new HttpClient { Timeout = TimeSpan.FromSeconds(2) };
        var deadline = DateTime.UtcNow.AddSeconds(30);

        while (DateTime.UtcNow < deadline)
        {
            if (_process.HasExited)
            {
                throw new InvalidOperationException($"The ASP.NET Core test host exited early.{Environment.NewLine}{GetLogs()}");
            }

            try
            {
                using var response = await client.GetAsync($"{BaseUrl}/");
                if (response.StatusCode == HttpStatusCode.OK)
                {
                    return;
                }
            }
            catch
            {
            }

            await Task.Delay(500);
        }

        throw new TimeoutException($"Timed out waiting for the ASP.NET Core test host.{Environment.NewLine}{GetLogs()}");
    }

    private static object CreateRuntimeDefaults(string outputRoot) => new
    {
        videoExtensions = new[] { ".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm" },
        inputRoots = new object[]
        {
            new { id = "primary", displayName = "Primary Videos", path = "/shared/inputs/primary", enabled = true },
            new { id = "secondary", displayName = "Secondary Videos", path = "/shared/inputs/secondary", enabled = true },
            new { id = "uploads", displayName = "Uploaded Files", path = "/shared/uploads", enabled = true },
        },
        outputRoots = new object[]
        {
            new { id = "runs", displayName = "Runs", path = outputRoot, enabled = true },
        },
    };

    private static async Task SeedCompletedRunAsync(string outputRoot)
    {
        const string jobId = "run-e2e-completed";
        const string mediaId = "sample-media-001";

        var runRoot = Path.Combine(outputRoot, jobId);
        Directory.CreateDirectory(runRoot);
        Directory.CreateDirectory(Path.Combine(runRoot, "llm"));
        Directory.CreateDirectory(Path.Combine(runRoot, "logs"));
        Directory.CreateDirectory(Path.Combine(runRoot, "media", mediaId, "timeline"));

        var request = new
        {
            schema_version = 1,
            job_id = jobId,
            created_at = "2026-03-24T09:00:00+09:00",
            output_root_id = "runs",
            output_root_path = outputRoot.Replace("\\", "/"),
            profile = "quality-first",
            reprocess_duplicates = false,
            token_enabled = false,
            input_items = new object[]
            {
                new
                {
                    input_id = "upload-0001",
                    source_kind = "upload",
                    source_id = "uploads",
                    original_path = "sample-call.mp4",
                    display_name = "sample-call.mp4",
                    size_bytes = 1048576,
                    uploaded_path = (string?)null,
                },
            },
        };

        var status = new
        {
            schema_version = 1,
            job_id = jobId,
            state = "completed",
            current_stage = "completed",
            message = "Job completed.",
            warnings = Array.Empty<string>(),
            videos_total = 1,
            videos_done = 1,
            videos_skipped = 0,
            videos_failed = 0,
            current_media = (string?)null,
            current_media_elapsed_sec = 0.0,
            processed_duration_sec = 70.417,
            total_duration_sec = 70.417,
            estimated_remaining_sec = 0.0,
            started_at = "2026-03-24T09:00:03+09:00",
            updated_at = "2026-03-24T09:02:10+09:00",
            completed_at = "2026-03-24T09:02:10+09:00",
        };

        var result = new
        {
            schema_version = 1,
            job_id = jobId,
            state = "completed",
            run_dir = runRoot.Replace("\\", "/"),
            output_root_id = "runs",
            output_root_path = outputRoot.Replace("\\", "/"),
            processed_count = 1,
            skipped_count = 0,
            error_count = 0,
            batch_count = 1,
            timeline_index_path = Path.Combine(runRoot, "llm", "timeline_index.jsonl").Replace("\\", "/"),
            warnings = Array.Empty<string>(),
        };

        var manifest = new
        {
            schema_version = 1,
            job_id = jobId,
            generated_at = "2026-03-24T09:02:10+09:00",
            items = new object[]
            {
                new
                {
                    input_id = "upload-0001",
                    source_kind = "upload",
                    original_path = "sample-call.mp4",
                    file_name = "sample-call.mp4",
                    size_bytes = 1048576,
                    duration_seconds = 70.417,
                    sha256 = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                    duplicate_status = "new",
                    duplicate_of = (string?)null,
                    media_id = mediaId,
                    status = "completed",
                },
            },
        };

        var jsonOptions = new JsonSerializerOptions { WriteIndented = true };
        await File.WriteAllTextAsync(Path.Combine(runRoot, "request.json"), JsonSerializer.Serialize(request, jsonOptions));
        await File.WriteAllTextAsync(Path.Combine(runRoot, "status.json"), JsonSerializer.Serialize(status, jsonOptions));
        await File.WriteAllTextAsync(Path.Combine(runRoot, "result.json"), JsonSerializer.Serialize(result, jsonOptions));
        await File.WriteAllTextAsync(Path.Combine(runRoot, "manifest.json"), JsonSerializer.Serialize(manifest, jsonOptions));
        await File.WriteAllTextAsync(Path.Combine(runRoot, "RUN_INFO.md"), "# Run Info\n");
        await File.WriteAllTextAsync(Path.Combine(runRoot, "TRANSCRIPTION_INFO.md"), "# Transcription Info\n");
        await File.WriteAllTextAsync(Path.Combine(runRoot, "NOTICE.md"), "# Notice\n");
        await File.WriteAllTextAsync(Path.Combine(runRoot, "logs", "worker.log"), "[info] completed test run\n");
        await File.WriteAllTextAsync(Path.Combine(runRoot, "llm", "timeline_index.jsonl"), "{\"media_id\":\"sample-media-001\"}\n");
        await File.WriteAllTextAsync(
            Path.Combine(runRoot, "llm", "batch-001.md"),
            "# Batch 001\n\nIncluded: sample-media-001\n");
        await File.WriteAllTextAsync(
            Path.Combine(runRoot, "media", mediaId, "timeline", "timeline.md"),
            """
            # Video Timeline

            - Source: `sample-call.mp4`
            - Media ID: `sample-media-001`
            - Duration: `70.417s`

            ## 00:00:11.179 - 00:00:57.194
            Speech:
            SPEAKER_00: Hello, this is a public test sample.

            Screen:
            OCR detected text. Top lines: Example / Sample / Timeline

            Screen change:
            Initial frame.
            """);
    }

    private static int GetFreePort()
    {
        var listener = new TcpListener(IPAddress.Loopback, 0);
        listener.Start();
        var port = ((IPEndPoint)listener.LocalEndpoint).Port;
        listener.Stop();
        return port;
    }

    private string GetLogs()
    {
        lock (_logs)
        {
            return _logs.ToString();
        }
    }

    public async ValueTask DisposeAsync()
    {
        if (!_process.HasExited)
        {
            _process.Kill(entireProcessTree: true);
            await _process.WaitForExitAsync();
        }

        try
        {
            if (Directory.Exists(TempRoot))
            {
                Directory.Delete(TempRoot, recursive: true);
            }
        }
        catch
        {
        }
    }
}
