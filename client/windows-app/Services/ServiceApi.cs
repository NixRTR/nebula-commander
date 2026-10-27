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

    /// <summary>Per-network commands take the network's id (from
    /// <see cref="ListNetworksAsync"/>); null means the service-wide/first network.</summary>
    private static Dictionary<string, object?>? Net(string? network, Dictionary<string, object?>? args = null)
    {
        if (network is null)
        {
            return args;
        }
        args ??= new Dictionary<string, object?>();
        args["network"] = network;
        return args;
    }

    // --- reads (any user) ---

    /// <summary>Every enrolled network (one service, several networks); empty when not
    /// enrolled, null when the service isn't reachable.</summary>
    public static async Task<List<NetworkInfo>?> ListNetworksAsync() =>
        As<List<NetworkInfo>>(await PipeClient.SendAsync("list_networks"));

    /// <summary>A network's status, or the whole service's when network is null.</summary>
    public static async Task<NebulaStatus> GetStatusAsync(string? network = null) =>
        As<NebulaStatus>(await PipeClient.SendAsync("get_status", Net(network))) ?? new NebulaStatus();

    /// <summary>null when the service isn't reachable.</summary>
    public static async Task<NebulaSettings?> GetSettingsAsync(string? network = null) =>
        As<NebulaSettings>(await PipeClient.SendAsync("get_settings", Net(network)));

    /// <summary>null when the service isn't reachable.</summary>
    public static async Task<EnrollmentState?> GetEnrollmentAsync() =>
        As<EnrollmentState>(await PipeClient.SendAsync("is_enrolled"));

    public static async Task<List<AvailableRoute>> GetAvailableRoutesAsync(string? network = null) =>
        As<List<AvailableRoute>>(await PipeClient.SendAsync("get_available_routes", Net(network))) ?? new();

    public static async Task<List<string>> GetAdvertisedRoutesAsync(string? network = null) =>
        As<List<string>>(await PipeClient.SendAsync("get_advertised_routes", Net(network), timeoutMs: 15000)) ?? new();

    /// <summary>config.yaml with the private key redacted by the service.</summary>
    public static Task<PipeClient.PipeResponse> GetConfigYamlAsync(string? network = null) =>
        PipeClient.SendAsync("get_config_yaml", Net(network));

    /// <summary>Live interface/lighthouse check (pings, so seconds - not for timers);
    /// null when the service isn't reachable.</summary>
    public static async Task<ConnectivityInfo?> GetConnectivityAsync(string? network = null) =>
        As<ConnectivityInfo>(await PipeClient.SendAsync("get_connectivity", Net(network), timeoutMs: 20000));

    public static async Task<bool> GetDnsConfiguredAsync(string? network = null) =>
        As<bool>(await PipeClient.SendAsync("get_dns_configured", Net(network)));

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

    /// <summary>Settings for every network (each keeps the server it enrolled with).</summary>
    public static Task<PipeClient.PipeResponse> SetSettingsAsync(int interval, bool acceptDns) =>
        PipeClient.SendAsync("set_settings", new Dictionary<string, object?>
        {
            ["interval"] = interval,
            ["accept_dns"] = acceptDns,
        }, timeoutMs: 30000);

    /// <summary>Enroll in a network (another one, if already enrolled). The result has
    /// "network" (its id) and "name".</summary>
    public static Task<PipeClient.PipeResponse> EnrollAsync(string server, string code) =>
        PipeClient.SendAsync("enroll", new Dictionary<string, object?> { ["server"] = server, ["code"] = code },
            timeoutMs: 60000);

    /// <summary>Leave a network: its Nebula stops and the device forgets its token.</summary>
    public static Task<PipeClient.PipeResponse> RemoveNetworkAsync(string network) =>
        PipeClient.SendAsync("remove_network", new Dictionary<string, object?> { ["network"] = network },
            timeoutMs: 60000);

    public static Task<PipeClient.PipeResponse> AcceptRouteAsync(string cidr, string? via, string? network = null) =>
        PipeClient.SendAsync("accept_route", Net(network, new Dictionary<string, object?> { ["cidr"] = cidr, ["via"] = via }),
            timeoutMs: 30000);

    public static Task<PipeClient.PipeResponse> RejectRouteAsync(string cidr, string? network = null) =>
        PipeClient.SendAsync("reject_route", Net(network, new Dictionary<string, object?> { ["cidr"] = cidr }), timeoutMs: 30000);

    /// <summary>A device has one exit node: one in use in another network is replaced.</summary>
    public static Task<PipeClient.PipeResponse> AcceptExitNodeAsync(string via, string? network = null) =>
        PipeClient.SendAsync("accept_exit_node", Net(network, new Dictionary<string, object?> { ["via"] = via }), timeoutMs: 30000);

    public static Task<PipeClient.PipeResponse> RejectExitNodeAsync(string? network = null) =>
        PipeClient.SendAsync("reject_exit_node", Net(network), timeoutMs: 30000);

    public static Task<PipeClient.PipeResponse> SetExitAllowLanAsync(bool allowLan) =>
        PipeClient.SendAsync("set_settings", new Dictionary<string, object?> { ["exit_allow_lan"] = allowLan },
            timeoutMs: 30000);

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
