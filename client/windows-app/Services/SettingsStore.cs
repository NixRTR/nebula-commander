using System.Text.Json;
using System.Text.Json.Serialization;

namespace NebulaCommanderApp.Services;

/// <summary>A locally-accepted subnet route: (route, via) - identifies which offered
/// entry in available-routes.json this corresponds to. Matches client/ncclient.py's
/// accepted_subnet_routes shape exactly.</summary>
public sealed class SubnetRouteRef
{
    [JsonPropertyName("route")]
    public string Route { get; set; } = "";

    [JsonPropertyName("via")]
    public string? Via { get; set; }
}

/// <summary>The locally-accepted exit node, identified by its gateway's Nebula IP -
/// at most one at a time. Matches client/ncclient.py's accepted_exit_node shape.</summary>
public sealed class ExitNodeRef
{
    [JsonPropertyName("via")]
    public string? Via { get; set; }
}

/// <summary>settings.json - shared with the service, field names must match
/// client/config.py exactly (server, interval, nebula_path, accept_dns, node_id,
/// accepted_subnet_routes, accepted_exit_node).</summary>
public sealed class NebulaSettings
{
    [JsonPropertyName("server")]
    public string Server { get; set; } = "";

    [JsonPropertyName("interval")]
    public int Interval { get; set; } = 60;

    [JsonPropertyName("nebula_path")]
    public string NebulaPath { get; set; } = "";

    [JsonPropertyName("accept_dns")]
    public bool AcceptDns { get; set; }

    [JsonPropertyName("node_id")]
    public int? NodeId { get; set; }

    /// <summary>Locally accepted subnet routes - the device-consent gate on top of
    /// the server's "Used by" authorization (see docs/unsafe-routes.md). Always
    /// load current settings, adjust just this list, and save back - never
    /// construct a fresh NebulaSettings() and save it, or this (and
    /// AcceptedExitNode) would be silently wiped.</summary>
    [JsonPropertyName("accepted_subnet_routes")]
    public List<SubnetRouteRef> AcceptedSubnetRoutes { get; set; } = new();

    [JsonPropertyName("accepted_exit_node")]
    public ExitNodeRef? AcceptedExitNode { get; set; }
}

public static class SettingsStore
{
    private static readonly JsonSerializerOptions ReadOptions = new()
    {
        PropertyNameCaseInsensitive = true,
    };

    private static readonly JsonSerializerOptions WriteOptions = new()
    {
        WriteIndented = true,
    };

    public static NebulaSettings Load()
    {
        try
        {
            if (!File.Exists(SharedPaths.SettingsPath))
            {
                return new NebulaSettings();
            }
            var json = File.ReadAllText(SharedPaths.SettingsPath);
            return JsonSerializer.Deserialize<NebulaSettings>(json, ReadOptions) ?? new NebulaSettings();
        }
        catch
        {
            return new NebulaSettings();
        }
    }

    public static void Save(NebulaSettings settings)
    {
        Directory.CreateDirectory(SharedPaths.Root);
        var json = JsonSerializer.Serialize(settings, WriteOptions);
        File.WriteAllText(SharedPaths.SettingsPath, json);
    }
}
