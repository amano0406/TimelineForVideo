using System.Diagnostics;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

var productPaths = ProductPaths.Resolve(args);
var settingsForBind = ProductSettings.Load(productPaths);
var bindPortArg = ProductPaths.ArgValue(args, "--port");
var bindPort = string.IsNullOrWhiteSpace(bindPortArg)
    ? settingsForBind.Runtime.ApiPort
    : ProductSettings.ParsePort(bindPortArg);

var builder = WebApplication.CreateBuilder(args);
builder.Services.AddSingleton(productPaths);
builder.Services.AddSingleton<ProductOperationRunner>();
if (string.IsNullOrWhiteSpace(Environment.GetEnvironmentVariable("ASPNETCORE_URLS")))
{
    builder.WebHost.UseUrls($"http://127.0.0.1:{bindPort}");
}

var app = builder.Build();

app.MapGet("/health", () =>
{
    try
    {
        _ = ProductSettings.Load(productPaths);
        return Results.Text(File.Exists(productPaths.DockerComposePath) ? "true" : "false", "text/plain");
    }
    catch
    {
        return Results.Text("false", "text/plain");
    }
});

var settings = app.MapGroup("/settings");

settings.MapPost("/init", async (
    HttpContext context,
    ProductOperationRunner runner,
    CancellationToken cancellationToken) =>
{
    return await ExecuteJsonEndpointAsync(async () =>
    {
        var request = await ReadJsonObjectAsync(context, cancellationToken);
        return await runner.RunJsonAsync(
            BuildSettingsInitArguments(request),
            TimeSpan.FromSeconds(60),
            cancellationToken);
    });
});

settings.MapPost("/status", async (
    HttpContext context,
    ProductOperationRunner runner,
    CancellationToken cancellationToken) =>
{
    return await ExecuteJsonEndpointAsync(async () =>
    {
        _ = await ReadJsonObjectAsync(context, cancellationToken);
        return await runner.RunJsonAsync(
            ["settings", "status", "--json"],
            TimeSpan.FromSeconds(60),
            cancellationToken);
    });
});

settings.MapPost("/save", async (
    HttpContext context,
    ProductOperationRunner runner,
    CancellationToken cancellationToken) =>
{
    return await ExecuteJsonEndpointAsync(async () =>
    {
        var request = await ReadJsonObjectAsync(context, cancellationToken);
        return await runner.RunJsonAsync(
            BuildSettingsSaveArguments(request),
            TimeSpan.FromSeconds(60),
            cancellationToken);
    });
});

var files = app.MapGroup("/files");

files.MapPost("/list", async (
    HttpContext context,
    ProductOperationRunner runner,
    CancellationToken cancellationToken) =>
{
    return await ExecuteJsonEndpointAsync(async () =>
    {
        var request = await ReadJsonObjectAsync(context, cancellationToken);
        return await runner.RunJsonAsync(
            BuildPagedArguments(request, "files", "list"),
            TimeSpan.FromSeconds(120),
            cancellationToken);
    });
});

var items = app.MapGroup("/items");

items.MapPost("/list", async (
    HttpContext context,
    ProductOperationRunner runner,
    CancellationToken cancellationToken) =>
{
    return await ExecuteJsonEndpointAsync(async () =>
    {
        var request = await ReadJsonObjectAsync(context, cancellationToken);
        return await runner.RunJsonAsync(
            BuildPagedArguments(request, "items", "list"),
            TimeSpan.FromSeconds(120),
            cancellationToken);
    });
});

items.MapPost("/refresh", async (
    HttpContext context,
    ProductOperationRunner runner,
    CancellationToken cancellationToken) =>
{
    return await ExecuteJsonEndpointAsync(async () =>
    {
        var request = await ReadJsonObjectAsync(context, cancellationToken);
        return await runner.RunJsonAsync(
            BuildItemsRefreshArguments(request),
            TimeSpan.FromSeconds(900),
            cancellationToken);
    });
});

items.MapPost("/download", async (
    HttpContext context,
    ProductOperationRunner runner,
    CancellationToken cancellationToken) =>
{
    return await ExecuteJsonEndpointAsync(async () =>
    {
        var request = await ReadJsonObjectAsync(context, cancellationToken);
        return await runner.RunJsonAsync(
            BuildItemsDownloadArguments(request),
            TimeSpan.FromSeconds(900),
            cancellationToken);
    });
});

items.MapPost("/remove", async (
    HttpContext context,
    ProductOperationRunner runner,
    CancellationToken cancellationToken) =>
{
    return await ExecuteJsonEndpointAsync(async () =>
    {
        var request = await ReadJsonObjectAsync(context, cancellationToken);
        return await runner.RunJsonAsync(
            BuildItemsRemoveArguments(request),
            TimeSpan.FromSeconds(900),
            cancellationToken);
    });
});

var models = app.MapGroup("/models");

models.MapPost("/list", async (
    HttpContext context,
    ProductOperationRunner runner,
    CancellationToken cancellationToken) =>
{
    return await ExecuteJsonEndpointAsync(async () =>
    {
        var request = await ReadJsonObjectAsync(context, cancellationToken);
        return await runner.RunJsonAsync(
            BuildModelsListArguments(request),
            TimeSpan.FromSeconds(GetBoolAny(request, ["includeRemote", "include_remote", "remote"], false) ? 300 : 120),
            cancellationToken);
    });
});

app.Run();

static async Task<IResult> ExecuteJsonEndpointAsync(Func<Task<JsonNode?>> operation)
{
    try
    {
        return Results.Json(await operation());
    }
    catch (ProductCommandException ex)
    {
        return Results.Json(
            ex.Payload ?? ErrorPayload(ex.Message),
            statusCode: StatusCodes.Status500InternalServerError);
    }
    catch (Exception ex) when (ex is not OperationCanceledException)
    {
        return Results.Json(
            ErrorPayload(ex.Message),
            statusCode: StatusCodes.Status500InternalServerError);
    }
}

static async Task<JsonObject?> ReadJsonObjectAsync(HttpContext context, CancellationToken cancellationToken)
{
    if (context.Request.ContentLength == 0)
    {
        return null;
    }

    try
    {
        return await context.Request.ReadFromJsonAsync<JsonObject>(cancellationToken: cancellationToken);
    }
    catch (JsonException ex)
    {
        throw new InvalidOperationException($"Invalid JSON request body: {ex.Message}", ex);
    }
}

static IReadOnlyList<string> BuildSettingsInitArguments(JsonObject? request)
{
    var arguments = new List<string>
    {
        "settings",
        "init",
        "--json",
    };
    if (GetBoolAny(request, ["force"], false))
    {
        arguments.Add("--force");
    }
    return arguments;
}

static IReadOnlyList<string> BuildSettingsSaveArguments(JsonObject? request)
{
    var arguments = new List<string>
    {
        "settings",
        "save",
        "--json",
    };
    foreach (var inputRoot in GetStringArrayAny(request, ["inputRoots", "input_roots", "inputRoot", "input_root"]))
    {
        arguments.Add("--input-root");
        arguments.Add(inputRoot);
    }
    AddOptionalValue(arguments, "--output-root", GetStringAny(request, ["outputRoot", "output_root"]));
    AddOptionalValue(arguments, "--token", GetStringAny(request, ["token", "huggingFaceToken", "huggingfaceToken"]));
    AddOptionalValue(arguments, "--compute-mode", GetStringAny(request, ["computeMode", "compute_mode"]));
    if (GetBoolAny(request, ["clearToken", "clear_token"], false))
    {
        arguments.Add("--clear-token");
    }
    return arguments;
}

static IReadOnlyList<string> BuildPagedArguments(JsonObject? request, string command, string subcommand)
{
    var arguments = new List<string>
    {
        command,
        subcommand,
        "--json",
    };
    AddOptionalInt(arguments, "--page", GetIntAny(request, ["page"]));
    AddOptionalInt(arguments, "--page-size", GetIntAny(request, ["pageSize", "page_size"]));
    return arguments;
}

static IReadOnlyList<string> BuildItemsRefreshArguments(JsonObject? request)
{
    var arguments = new List<string>
    {
        "items",
        "refresh",
        "--json",
    };
    AddOptionalInt(arguments, "--max-items", GetIntAny(request, ["maxItems", "max_items", "limit"]));
    AddOptionalInt(arguments, "--samples-per-video", GetIntAny(request, ["samplesPerVideo", "samples_per_video"]));
    AddOptionalValue(arguments, "--ocr-mode", GetStringAny(request, ["ocrMode", "ocr_mode"]));
    AddOptionalValue(arguments, "--audio-model-mode", GetStringAny(request, ["audioModelMode", "audio_model_mode"]));
    if (GetBoolAny(request, ["reprocessDuplicates", "reprocess_duplicates"], false))
    {
        arguments.Add("--reprocess-duplicates");
    }
    return arguments;
}

static IReadOnlyList<string> BuildItemsDownloadArguments(JsonObject? request)
{
    var arguments = new List<string>
    {
        "items",
        "download",
        "--json",
    };
    foreach (var itemId in GetItemIds(request))
    {
        arguments.Add("--item-id");
        arguments.Add(itemId);
    }
    return arguments;
}

static IReadOnlyList<string> BuildItemsRemoveArguments(JsonObject? request)
{
    var arguments = new List<string>
    {
        "items",
        "remove",
        "--json",
    };
    foreach (var itemId in GetItemIds(request))
    {
        arguments.Add("--item-id");
        arguments.Add(itemId);
    }
    if (GetBoolAny(request, ["dryRun", "dry_run"], false))
    {
        arguments.Add("--dry-run");
    }
    return arguments;
}

static IReadOnlyList<string> BuildModelsListArguments(JsonObject? request)
{
    var arguments = new List<string>
    {
        "models",
        "list",
        "--json",
    };
    if (GetBoolAny(request, ["includeRemote", "include_remote", "remote"], false))
    {
        arguments.Add("--include-remote");
    }
    AddOptionalValue(arguments, "--output", GetStringAny(request, ["outputPath", "output"]));
    return arguments;
}

static JsonObject ErrorPayload(string message)
{
    return new JsonObject
    {
        ["ok"] = false,
        ["error"] = new JsonObject
        {
            ["message"] = message,
        },
    };
}

static void AddOptionalValue(List<string> arguments, string name, string value)
{
    if (string.IsNullOrWhiteSpace(value))
    {
        return;
    }

    arguments.Add(name);
    arguments.Add(value.Trim());
}

static void AddOptionalInt(List<string> arguments, string name, int? value)
{
    if (value is not > 0)
    {
        return;
    }

    arguments.Add(name);
    arguments.Add(value.Value.ToString());
}

static List<string> GetItemIds(JsonObject? request)
{
    return GetStringArrayAny(request, ["itemIds", "item_ids", "itemId", "item_id"])
        .Where(value => !string.IsNullOrWhiteSpace(value))
        .Distinct(StringComparer.Ordinal)
        .ToList();
}

static List<string> GetStringArrayAny(JsonObject? source, string[] names)
{
    foreach (var name in names)
    {
        var values = GetStringArray(source, name);
        if (values.Count > 0)
        {
            return values;
        }
    }

    return [];
}

static List<string> GetStringArray(JsonObject? source, string name)
{
    var node = GetNode(source, name);
    if (node is null)
    {
        return [];
    }
    if (node is JsonArray array)
    {
        return array
            .Select(item => ConvertJsonText(item))
            .Where(value => !string.IsNullOrWhiteSpace(value))
            .ToList();
    }

    var text = ConvertJsonText(node);
    if (string.IsNullOrWhiteSpace(text))
    {
        return [];
    }

    return text
        .Replace("\r", ",", StringComparison.Ordinal)
        .Replace("\n", ",", StringComparison.Ordinal)
        .Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)
        .Where(value => !string.IsNullOrWhiteSpace(value))
        .ToList();
}

static string GetStringAny(JsonObject? source, string[] names)
{
    foreach (var name in names)
    {
        var node = GetNode(source, name);
        if (node is not null)
        {
            return ConvertJsonText(node);
        }
    }

    return string.Empty;
}

static int? GetIntAny(JsonObject? source, string[] names)
{
    foreach (var name in names)
    {
        var node = GetNode(source, name);
        if (node is null)
        {
            continue;
        }

        if (node is JsonValue value)
        {
            if (value.TryGetValue<int>(out var intValue))
            {
                return intValue;
            }
            if (value.TryGetValue<string>(out var textValue)
                && int.TryParse(textValue, out var parsed))
            {
                return parsed;
            }
        }
    }

    return null;
}

static bool GetBoolAny(JsonObject? source, string[] names, bool fallback)
{
    foreach (var name in names)
    {
        var node = GetNode(source, name);
        if (node is null)
        {
            continue;
        }
        if (node is JsonValue value)
        {
            if (value.TryGetValue<bool>(out var boolValue))
            {
                return boolValue;
            }
            if (value.TryGetValue<string>(out var textValue))
            {
                var text = textValue.Trim().ToLowerInvariant();
                if (text is "1" or "true" or "yes" or "on")
                {
                    return true;
                }
                if (text is "0" or "false" or "no" or "off")
                {
                    return false;
                }
            }
        }
    }

    return fallback;
}

static JsonNode? GetNode(JsonObject? source, string name)
{
    if (source is null)
    {
        return null;
    }
    if (source.TryGetPropertyValue(name, out var node))
    {
        return node;
    }

    foreach (var property in source)
    {
        if (property.Key.Equals(name, StringComparison.OrdinalIgnoreCase))
        {
            return property.Value;
        }
    }

    return null;
}

static string ConvertJsonText(JsonNode? node)
{
    if (node is null || node.GetValueKind() == JsonValueKind.Null)
    {
        return string.Empty;
    }

    if (node is JsonValue value)
    {
        if (value.TryGetValue<string>(out var text))
        {
            return text.Trim();
        }
        if (value.TryGetValue<int>(out var intValue))
        {
            return intValue.ToString();
        }
        if (value.TryGetValue<bool>(out var boolValue))
        {
            return boolValue ? "true" : "false";
        }
    }

    return node.ToJsonString().Trim();
}

internal sealed class ProductPaths
{
    public ProductPaths(string productRoot, string? settingsPath = null)
    {
        ProductRoot = Path.GetFullPath(productRoot);
        SettingsPath = Path.GetFullPath(
            string.IsNullOrWhiteSpace(settingsPath)
                ? Path.Combine(ProductRoot, "settings.json")
                : settingsPath);
        SettingsExamplePath = Path.Combine(ProductRoot, "settings.example.json");
        DockerComposePath = Path.Combine(ProductRoot, "docker-compose.yml");
        DockerComposeGpuPath = Path.Combine(ProductRoot, "docker-compose.gpu.yml");
    }

    public string ProductRoot { get; }

    public string SettingsPath { get; }

    public string SettingsExamplePath { get; }

    public string DockerComposePath { get; }

    public string DockerComposeGpuPath { get; }

    public static ProductPaths Resolve(string[] args)
    {
        var explicitRoot = ArgValue(args, "--product-root")
            ?? Environment.GetEnvironmentVariable("TIMELINE_FOR_VIDEO_ROOT");
        var explicitSettings = ArgValue(args, "--settings-path")
            ?? Environment.GetEnvironmentVariable("TIMELINE_FOR_VIDEO_SETTINGS_PATH");
        if (!string.IsNullOrWhiteSpace(explicitRoot))
        {
            return new ProductPaths(explicitRoot, explicitSettings);
        }

        var current = AppContext.BaseDirectory;
        for (var directory = new DirectoryInfo(current); directory is not null; directory = directory.Parent)
        {
            if (File.Exists(Path.Combine(directory.FullName, "docker-compose.yml"))
                && Directory.Exists(Path.Combine(directory.FullName, "worker")))
            {
                return new ProductPaths(directory.FullName, explicitSettings);
            }
        }

        return new ProductPaths(Directory.GetCurrentDirectory(), explicitSettings);
    }

    public static string? ArgValue(string[] args, string name)
    {
        for (var index = 0; index < args.Length; index++)
        {
            if (string.Equals(args[index], name, StringComparison.OrdinalIgnoreCase) && index + 1 < args.Length)
            {
                return args[index + 1];
            }

            var prefix = name + "=";
            if (args[index].StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
            {
                return args[index][prefix.Length..];
            }
        }

        return null;
    }
}

internal sealed record RuntimeSettings(int ApiPort);

internal sealed record ProductSettings(RuntimeSettings Runtime)
{
    public static ProductSettings Load(ProductPaths paths)
    {
        var defaults = Default();
        if (!File.Exists(paths.SettingsPath))
        {
            return defaults;
        }

        try
        {
            using var document = JsonDocument.Parse(File.ReadAllText(paths.SettingsPath));
            var root = document.RootElement;
            if (!root.TryGetProperty("runtime", out var runtime))
            {
                return defaults;
            }

            return new ProductSettings(new RuntimeSettings(
                ReadPort(runtime, "apiPort") ?? defaults.Runtime.ApiPort));
        }
        catch (Exception ex) when (ex is IOException or JsonException or UnauthorizedAccessException)
        {
            return defaults;
        }
    }

    public static int ParsePort(string value)
    {
        if (!int.TryParse(value, out var port))
        {
            throw new InvalidOperationException("TimelineForVideo API port must be an integer.");
        }

        if (port is < 1 or > 65535)
        {
            throw new InvalidOperationException("TimelineForVideo API port must be between 1 and 65535.");
        }

        return port;
    }

    private static ProductSettings Default() => new(new RuntimeSettings(19500));

    private static int? ReadPort(JsonElement source, string name)
    {
        if (!source.TryGetProperty(name, out var value))
        {
            return null;
        }
        if (value.ValueKind == JsonValueKind.Number && value.TryGetInt32(out var number))
        {
            return number is >= 1 and <= 65535 ? number : null;
        }
        if (value.ValueKind == JsonValueKind.String && int.TryParse(value.GetString(), out var parsed))
        {
            return parsed is >= 1 and <= 65535 ? parsed : null;
        }
        return null;
    }
}

internal sealed class ProductCommandException : Exception
{
    public ProductCommandException(
        string message,
        int exitCode,
        JsonNode? payload,
        string stdout,
        string stderr)
        : base(message)
    {
        ExitCode = exitCode;
        Payload = payload;
        Stdout = stdout;
        Stderr = stderr;
    }

    public int ExitCode { get; }

    public JsonNode? Payload { get; }

    public string Stdout { get; }

    public string Stderr { get; }
}

internal sealed class ProductOperationRunner
{
    private readonly ProductPaths _paths;

    public ProductOperationRunner(ProductPaths paths)
    {
        _paths = paths;
    }

    public async Task<JsonNode?> RunJsonAsync(
        IReadOnlyList<string> arguments,
        TimeSpan timeout,
        CancellationToken cancellationToken)
    {
        var runtime = VideoRuntime.Ensure(_paths);
        var dockerPath = ResolveDockerCommand();
        var composeArguments = BuildComposeArguments(runtime);

        var workerState = await GetWorkerStateAsync(dockerPath, composeArguments, runtime, timeout, cancellationToken);
        if (!workerState.IsRunning)
        {
            throw new InvalidOperationException(workerState.Message);
        }

        var dockerArguments = new List<string>
        {
            "compose",
        };
        dockerArguments.AddRange(composeArguments);
        dockerArguments.AddRange([
            "exec",
            "-T",
            "worker",
            "python",
            "-m",
            "timeline_for_video_worker",
        ]);
        dockerArguments.AddRange(arguments);

        var result = await RunProcessAsync(
            dockerPath,
            dockerArguments,
            _paths.ProductRoot,
            runtime,
            timeout,
            cancellationToken);

        var stdout = result.Stdout;
        var stderr = result.Stderr;
        var payload = TryParseJson(stdout) ?? TryParseJson(stderr);
        if (result.ExitCode != 0)
        {
            var message = GetErrorMessage(payload);
            if (string.IsNullOrEmpty(message))
            {
                message = !string.IsNullOrWhiteSpace(stderr)
                    ? stderr.Trim()
                    : !string.IsNullOrWhiteSpace(stdout)
                        ? stdout.Trim()
                        : $"exit code {result.ExitCode}";
            }

            throw new ProductCommandException(message, result.ExitCode, payload, stdout, stderr);
        }

        if (payload is null)
        {
            throw new InvalidOperationException("TimelineForVideo operation did not return JSON.");
        }

        return payload;
    }

    private async Task<WorkerState> GetWorkerStateAsync(
        string dockerPath,
        IReadOnlyList<string> composeArguments,
        VideoRuntime runtime,
        TimeSpan timeout,
        CancellationToken cancellationToken)
    {
        var arguments = new List<string>
        {
            "compose",
        };
        arguments.AddRange(composeArguments);
        arguments.AddRange(["ps", "--status", "running", "--services"]);

        var result = await RunProcessAsync(
            dockerPath,
            arguments,
            _paths.ProductRoot,
            runtime,
            timeout,
            cancellationToken);
        if (result.ExitCode != 0)
        {
            var message = !string.IsNullOrWhiteSpace(result.Stderr)
                ? result.Stderr.Trim()
                : !string.IsNullOrWhiteSpace(result.Stdout)
                    ? result.Stdout.Trim()
                    : "TimelineForVideo worker status could not be checked.";
            return new WorkerState(false, message);
        }

        var isRunning = result.Stdout
            .Split(['\r', '\n'], StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)
            .Any(service => string.Equals(service, "worker", StringComparison.Ordinal));
        return isRunning
            ? new WorkerState(true, string.Empty)
            : new WorkerState(false, "TimelineForVideo worker is not running.");
    }

    private List<string> BuildComposeArguments(VideoRuntime runtime)
    {
        var arguments = new List<string>
        {
            "--project-directory",
            _paths.ProductRoot,
            "-p",
            runtime.ComposeProject,
            "-f",
            _paths.DockerComposePath,
        };

        if (runtime.ComputeMode == "gpu" && File.Exists(_paths.DockerComposeGpuPath))
        {
            arguments.Add("-f");
            arguments.Add(_paths.DockerComposeGpuPath);
        }

        return arguments;
    }

    private static async Task<OperationResult> RunProcessAsync(
        string fileName,
        IReadOnlyList<string> arguments,
        string workingDirectory,
        VideoRuntime runtime,
        TimeSpan timeout,
        CancellationToken cancellationToken)
    {
        var processStart = new ProcessStartInfo
        {
            FileName = fileName,
            WorkingDirectory = workingDirectory,
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            CreateNoWindow = true,
            StandardOutputEncoding = Encoding.UTF8,
            StandardErrorEncoding = Encoding.UTF8,
        };
        processStart.Environment["COMPOSE_PROJECT_NAME"] = runtime.ComposeProject;
        processStart.Environment["TIMELINE_FOR_VIDEO_INSTANCE_NAME"] = runtime.InstanceName;
        processStart.Environment["TIMELINE_FOR_VIDEO_COMPOSE_PROJECT"] = runtime.ComposeProject;
        processStart.Environment["TIMELINE_FOR_VIDEO_IMAGE_TAG"] = runtime.ImageTag;
        processStart.Environment["TIMELINE_FOR_VIDEO_API_PORT"] = runtime.ApiPort.ToString();
        processStart.Environment["TIMELINE_FOR_VIDEO_SETTINGS_PATH"] = runtime.ContainerSettingsPath;
        processStart.Environment["TIMELINE_FOR_VIDEO_C_DRIVE_MOUNT"] = Environment.GetEnvironmentVariable("TIMELINE_FOR_VIDEO_C_DRIVE_MOUNT") ?? @"C:\";
        processStart.Environment["TIMELINE_FOR_VIDEO_F_DRIVE_MOUNT"] = Environment.GetEnvironmentVariable("TIMELINE_FOR_VIDEO_F_DRIVE_MOUNT") ?? @"F:\";
        foreach (var argument in arguments)
        {
            processStart.ArgumentList.Add(argument);
        }

        using var process = Process.Start(processStart)
            ?? throw new InvalidOperationException("TimelineForVideo command process could not be started.");
        var stdoutTask = process.StandardOutput.ReadToEndAsync();
        var stderrTask = process.StandardError.ReadToEndAsync();

        using var timeoutSource = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        timeoutSource.CancelAfter(timeout);
        try
        {
            await process.WaitForExitAsync(timeoutSource.Token);
        }
        catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested)
        {
            KillProcessTree(process);
            throw new TimeoutException($"TimelineForVideo command timed out after {(int)timeout.TotalSeconds} seconds.");
        }
        catch
        {
            KillProcessTree(process);
            throw;
        }

        var stdout = await stdoutTask;
        var stderr = await stderrTask;
        return new OperationResult(process.ExitCode, stdout, stderr);
    }

    private static void KillProcessTree(Process process)
    {
        try
        {
            if (!process.HasExited)
            {
                process.Kill(entireProcessTree: true);
            }
        }
        catch
        {
        }
    }

    private static JsonNode? TryParseJson(string text)
    {
        var trimmed = text.Trim();
        if (string.IsNullOrEmpty(trimmed))
        {
            return null;
        }

        try
        {
            return JsonNode.Parse(trimmed);
        }
        catch (JsonException)
        {
        }

        var objectStart = trimmed.IndexOf('{');
        var objectEnd = trimmed.LastIndexOf('}');
        if (objectStart >= 0 && objectEnd > objectStart)
        {
            try
            {
                return JsonNode.Parse(trimmed[objectStart..(objectEnd + 1)]);
            }
            catch (JsonException)
            {
            }
        }

        var arrayStart = trimmed.IndexOf('[');
        var arrayEnd = trimmed.LastIndexOf(']');
        if (arrayStart >= 0 && arrayEnd > arrayStart)
        {
            try
            {
                return JsonNode.Parse(trimmed[arrayStart..(arrayEnd + 1)]);
            }
            catch (JsonException)
            {
            }
        }

        return null;
    }

    private static string GetErrorMessage(JsonNode? payload)
    {
        if (payload is not JsonObject obj)
        {
            return string.Empty;
        }

        if (obj["error"] is JsonObject error &&
            error["message"] is JsonValue errorMessage &&
            errorMessage.TryGetValue<string>(out var message) &&
            !string.IsNullOrWhiteSpace(message))
        {
            return message.Trim();
        }

        if (obj["message"] is JsonValue messageValue &&
            messageValue.TryGetValue<string>(out var rootMessage) &&
            !string.IsNullOrWhiteSpace(rootMessage))
        {
            return rootMessage.Trim();
        }

        return string.Empty;
    }

    private static string ResolveDockerCommand()
    {
        var programFiles = Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles);
        if (!string.IsNullOrWhiteSpace(programFiles))
        {
            var dockerExe = Path.Combine(programFiles, "Docker", "Docker", "resources", "bin", "docker.exe");
            if (File.Exists(dockerExe))
            {
                return dockerExe;
            }
        }

        return "docker";
    }
}

internal sealed record OperationResult(int ExitCode, string Stdout, string Stderr);

internal sealed record WorkerState(bool IsRunning, string Message);

internal sealed record VideoRuntime(
    string InstanceName,
    int ApiPort,
    string ComposeProject,
    string ImageTag,
    string ComputeMode,
    string ContainerSettingsPath)
{
    public static VideoRuntime Ensure(ProductPaths paths)
    {
        var sourcePath = File.Exists(paths.SettingsPath)
            ? paths.SettingsPath
            : File.Exists(paths.SettingsExamplePath)
                ? paths.SettingsExamplePath
                : string.Empty;
        var root = !string.IsNullOrWhiteSpace(sourcePath)
            ? JsonNode.Parse(File.ReadAllText(sourcePath, Encoding.UTF8)) as JsonObject ?? new JsonObject()
            : DefaultSettings();

        var runtime = root["runtime"] as JsonObject ?? new JsonObject();
        root["runtime"] = runtime;

        var envInstance = NormalizeInstanceName(Environment.GetEnvironmentVariable("TIMELINE_FOR_VIDEO_INSTANCE_NAME") ?? string.Empty);
        var instanceName = !string.IsNullOrWhiteSpace(envInstance)
            ? envInstance
            : NormalizeInstanceName(GetString(runtime, "instanceName"));
        if (string.IsNullOrWhiteSpace(instanceName))
        {
            instanceName = Guid.NewGuid().ToString("N")[..10];
        }

        var envPort = Environment.GetEnvironmentVariable("TIMELINE_FOR_VIDEO_API_PORT");
        var apiPort = TryParsePort(envPort) ?? GetInt(runtime, "apiPort") ?? 19500;
        if (apiPort is < 1 or > 65535)
        {
            apiPort = 19500;
        }

        var inputRoots = GetStringArray(root, "inputRoots");
        var outputRoot = GetString(root, "outputRoot");
        if (string.IsNullOrWhiteSpace(outputRoot))
        {
            outputRoot = @"C:\TimelineData\video";
        }

        var token = GetString(root, "huggingFaceToken");
        var computeMode = GetString(root, "computeMode").Trim().ToLowerInvariant();
        if (computeMode is not ("cpu" or "gpu"))
        {
            computeMode = "gpu";
        }

        var inputRootArray = new JsonArray();
        foreach (var inputRoot in inputRoots)
        {
            inputRootArray.Add(inputRoot);
        }

        var normalized = new JsonObject
        {
            ["schemaVersion"] = GetInt(root, "schemaVersion") ?? 1,
            ["runtime"] = new JsonObject
            {
                ["instanceName"] = instanceName,
                ["apiPort"] = apiPort,
            },
            ["inputRoots"] = inputRootArray,
            ["outputRoot"] = outputRoot,
            ["huggingFaceToken"] = token,
            ["computeMode"] = computeMode,
        };

        Directory.CreateDirectory(Path.GetDirectoryName(paths.SettingsPath) ?? paths.ProductRoot);
        File.WriteAllText(
            paths.SettingsPath,
            normalized.ToJsonString(new JsonSerializerOptions { WriteIndented = true }) + Environment.NewLine,
            new UTF8Encoding(encoderShouldEmitUTF8Identifier: false));

        var composeProject = NormalizeSlug(Environment.GetEnvironmentVariable("TIMELINE_FOR_VIDEO_COMPOSE_PROJECT") ?? string.Empty);
        if (string.IsNullOrWhiteSpace(composeProject))
        {
            composeProject = NormalizeSlug(Environment.GetEnvironmentVariable("COMPOSE_PROJECT_NAME") ?? string.Empty);
        }
        if (string.IsNullOrWhiteSpace(composeProject))
        {
            composeProject = $"timeline-for-video-{instanceName}";
        }

        var imageTag = NormalizeSlug(Environment.GetEnvironmentVariable("TIMELINE_FOR_VIDEO_IMAGE_TAG") ?? string.Empty);
        if (string.IsNullOrWhiteSpace(imageTag))
        {
            imageTag = composeProject;
        }

        var containerSettingsPath = PathsEqual(paths.SettingsPath, Path.Combine(paths.ProductRoot, "settings.json"))
            ? "/workspace/settings.json"
            : paths.SettingsPath;

        return new VideoRuntime(
            instanceName,
            apiPort,
            composeProject,
            imageTag,
            computeMode,
            containerSettingsPath);
    }

    private static JsonObject DefaultSettings() => new()
    {
        ["schemaVersion"] = 1,
        ["runtime"] = new JsonObject
        {
            ["instanceName"] = string.Empty,
            ["apiPort"] = 19500,
        },
        ["inputRoots"] = new JsonArray(@"C:\TimelineData\input-video\"),
        ["outputRoot"] = @"C:\TimelineData\video",
        ["huggingFaceToken"] = string.Empty,
        ["computeMode"] = "gpu",
    };

    private static string NormalizeInstanceName(string value)
    {
        var text = NormalizeSlug(value);
        if (text.StartsWith("local-", StringComparison.Ordinal))
        {
            text = text["local-".Length..];
        }
        return text;
    }

    private static string NormalizeSlug(string value)
    {
        var builder = new StringBuilder();
        var lastWasDash = false;
        foreach (var ch in value.Trim().ToLowerInvariant())
        {
            var isValid = ch is >= 'a' and <= 'z' || ch is >= '0' and <= '9';
            if (isValid)
            {
                builder.Append(ch);
                lastWasDash = false;
            }
            else if (!lastWasDash)
            {
                builder.Append('-');
                lastWasDash = true;
            }
        }
        return builder.ToString().Trim('-');
    }

    private static string GetString(JsonObject source, string name)
    {
        if (source[name] is JsonValue value)
        {
            if (value.TryGetValue<string>(out var text))
            {
                return text.Trim();
            }
            if (value.TryGetValue<int>(out var intValue))
            {
                return intValue.ToString();
            }
        }
        return string.Empty;
    }

    private static int? GetInt(JsonObject source, string name)
    {
        if (source[name] is not JsonValue value)
        {
            return null;
        }
        if (value.TryGetValue<int>(out var intValue))
        {
            return intValue;
        }
        if (value.TryGetValue<string>(out var textValue) && int.TryParse(textValue, out var parsed))
        {
            return parsed;
        }
        return null;
    }

    private static int? TryParsePort(string? value)
    {
        if (string.IsNullOrWhiteSpace(value) || !int.TryParse(value, out var port))
        {
            return null;
        }
        return port is >= 1 and <= 65535 ? port : null;
    }

    private static IReadOnlyList<string> GetStringArray(JsonObject source, string name)
    {
        if (source[name] is not JsonArray array)
        {
            return [@"C:\TimelineData\input-video\"];
        }

        var rows = array
            .OfType<JsonValue>()
            .Select(value => value.TryGetValue<string>(out var text) ? text.Trim() : string.Empty)
            .Where(value => !string.IsNullOrWhiteSpace(value))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToArray();
        return rows.Length > 0 ? rows : [@"C:\TimelineData\input-video\"];
    }

    private static bool PathsEqual(string left, string right)
        => string.Equals(Path.GetFullPath(left), Path.GetFullPath(right), StringComparison.OrdinalIgnoreCase);
}
