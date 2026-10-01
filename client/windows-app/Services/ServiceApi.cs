using System.Text.Json;
using System.Text.RegularExpressions;

namespace NebulaCommanderApp.Services;

/// <summary>
/// Typed wrappers over <see cref="PipeClient"/> - one per command in
/// client/windows/pipe_protocol.py. Read calls return a fallback value when the
/// service can't be reached; change calls return the raw
/// <see cref="PipeClient.PipeResponse"/> so callers can show its error (and
/// handle <see cref="PipeClient.PipeResponse.AdministratorRequired"/>).
/// </summary>
public static class ServiceApi
{
    private static readonly JsonSerializerOptions ReadOptions = new() { PropertyNameCaseInsensitive = true };

    private static T? As<T>(PipeClient.PipeResponse r)
    {
        if (!r.Ok || r.Result.ValueKind is JsonValueKind.Undefined or JsonValueKind.Null)
        {
            return default;
        }
        try
        {
            return r.Result.Deserialize<T>(ReadOptions);
        }
        catch (JsonException)
        {
            return default;
        }
    }

    // --- reads (any user) ---

    public static async Task<NebulaStatus> GetStatusAsync() =>
        As<NebulaStatus>(await PipeClient.SendAsync("get_status")) ?? new NebulaStatus();

    /// <summary>null when the service isn't reachable.</summary>
    public static async Task<NebulaSettings?> GetSettingsAsync() =>
        As<NebulaSettings>(await PipeClient.SendAsync("get_settings"));

    /// <summary>null when the service isn't reachable.</summary>
    public static async Task<EnrollmentState?> GetEnrollmentAsync() =>
        As<EnrollmentState>(await PipeClient.SendAsync("is_enrolled"));

    public static async Task<List<AvailableRoute>> GetAvailableRoutesAsync() =>
        As<List<AvailableRoute>>(await PipeClient.SendAsync("get_available_routes")) ?? new();

    public static async Task<List<string>> GetAdvertisedRoutesAsync() =>
        As<List<string>>(await PipeClient.SendAsync("get_advertised_routes", timeoutMs: 15000)) ?? new();

    /// <summary>config.yaml with the private key redacted by the service.</summary>
    public static Task<PipeClient.PipeResponse> GetConfigYamlAsync() => PipeClient.SendAsync("get_config_yaml");

    public static async Task<bool> GetDnsConfiguredAsync() =>
        As<bool>(await PipeClient.SendAsync("get_dns_configured"));

    public static async Task<string?> GetNebulaVersionAsync() =>
        As<string>(await PipeClient.SendAsync("get_nebula_version", timeoutMs: 15000));

    public static Task<PipeClient.PipeResponse> GetLatestNebulaTagAsync() =>
        PipeClient.SendAsync("get_latest_nebula_tag", timeoutMs: 70000);

    /// <summary>null when the service isn't reachable (or predates automatic updates).</summary>
    public static async Task<UpdateStatus?> GetUpdateStatusAsync() =>
        As<UpdateStatus>(await PipeClient.SendAsync("get_update_status"));

    // --- changes (elevated administrator) ---

    public static Task<PipeClient.PipeResponse> SetAutoUpdateAsync(bool enabled, string windowStart, string windowEnd) =>
        PipeClient.SendAsync("set_auto_update", new Dictionary<string, object?>
        {
            ["enabled"] = enabled,
            ["window_start"] = windowStart,
            ["window_end"] = windowEnd,
        }, timeoutMs: 30000);

    /// <summary>Starts a check on the service's updater thread (and an install, if
    /// automatic updates are on); poll <see cref="GetUpdateStatusAsync"/> for the outcome.</summary>
    public static Task<PipeClient.PipeResponse> UpdateCheckNowAsync() =>
        PipeClient.SendAsync("update_check_now", timeoutMs: 30000);

    public static Task<PipeClient.PipeResponse> SetSettingsAsync(string server, int interval, bool acceptDns) =>
        PipeClient.SendAsync("set_settings", new Dictionary<string, object?>
        {
            ["server"] = server,
            ["interval"] = interval,
            ["accept_dns"] = acceptDns,
        }, timeoutMs: 30000);

    public static Task<PipeClient.PipeResponse> EnrollAsync(string server, string code) =>
        PipeClient.SendAsync("enroll", new Dictionary<string, object?> { ["server"] = server, ["code"] = code },
            timeoutMs: 60000);

    public static Task<PipeClient.PipeResponse> AcceptRouteAsync(string cidr, string? via) =>
        PipeClient.SendAsync("accept_route", new Dictionary<string, object?> { ["cidr"] = cidr, ["via"] = via },
            timeoutMs: 30000);

    public static Task<PipeClient.PipeResponse> RejectRouteAsync(string cidr) =>
        PipeClient.SendAsync("reject_route", new Dictionary<string, object?> { ["cidr"] = cidr }, timeoutMs: 30000);

    public static Task<PipeClient.PipeResponse> AcceptExitNodeAsync(string via) =>
        PipeClient.SendAsync("accept_exit_node", new Dictionary<string, object?> { ["via"] = via }, timeoutMs: 30000);

    public static Task<PipeClient.PipeResponse> RejectExitNodeAsync() =>
        PipeClient.SendAsync("reject_exit_node", timeoutMs: 30000);

    /// <summary>Service downloads, SHA256-verifies and installs the whole release
    /// (nebula.exe, nebula-cert.exe, dist\) itself - can take a while.</summary>
    public static Task<PipeClient.PipeResponse> UpdateNebulaAsync(string? tag) =>
        PipeClient.SendAsync("update_nebula", tag is null ? null : new Dictionary<string, object?> { ["tag"] = tag },
            timeoutMs: 300000);

    // --- helpers ---

    public static (int Major, int Minor, int Patch) ParseVersionTuple(string? versionStr)
    {
        if (string.IsNullOrWhiteSpace(versionStr))
        {
            return (0, 0, 0);
        }
        var match = Regex.Match(versionStr.Trim(), @"v?(\d+)\.?(\d*)\.?(\d*)");
        if (!match.Success)
        {
            return (0, 0, 0);
        }
        int Part(int group) => match.Groups[group].Value.Length > 0 ? int.Parse(match.Groups[group].Value) : 0;
        return (Part(1), Part(2), Part(3));
    }

    public static bool IsNewerVersion(string? localVersion, string? latestTag) =>
        ParseVersionTuple(latestTag).CompareTo(ParseVersionTuple(localVersion)) > 0;

    public static string Describe(PipeClient.PipeResponse r) => r.Error ?? (r.Ok ? "OK" : "Unknown error");
}
