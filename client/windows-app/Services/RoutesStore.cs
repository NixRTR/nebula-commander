using System.Text.Json;
using System.Text.Json.Serialization;

namespace NebulaCommanderApp.Services;

/// <summary>One entry from available-routes.json - everything this node is
/// currently authorized to consume (server-side "Used by" list), independent
/// of what's been locally accepted. Written by client/ncclient.py's
/// extract_available_routes/_write_available_routes.</summary>
public sealed class AvailableRoute
{
    [JsonPropertyName("route")]
    public string Route { get; set; } = "";

    [JsonPropertyName("via")]
    public string? Via { get; set; }

    /// <summary>"subnet" or "exit" - 0.0.0.0/0 and ::/0 are always "exit".</summary>
    [JsonPropertyName("kind")]
    public string Kind { get; set; } = "subnet";

    public bool IsExit => Kind == "exit";
}

/// <summary>Reads available-routes.json - same pattern as StatusStore reads
/// status.json. Written by the service each time it polls a config with a
/// changed tun.unsafe_routes; may not exist yet before the first poll after
/// enrollment.</summary>
public static class RoutesStore
{
    private static readonly JsonSerializerOptions ReadOptions = new()
    {
        PropertyNameCaseInsensitive = true,
    };

    public static List<AvailableRoute> Load()
    {
        try
        {
            if (!File.Exists(SharedPaths.AvailableRoutesPath))
            {
                return new List<AvailableRoute>();
            }
            var json = File.ReadAllText(SharedPaths.AvailableRoutesPath);
            return JsonSerializer.Deserialize<List<AvailableRoute>>(json, ReadOptions) ?? new List<AvailableRoute>();
        }
        catch
        {
            return new List<AvailableRoute>();
        }
    }
}
