using System.Text.Json;
using System.Text.Json.Serialization;

namespace NebulaCommanderApp.Services;

/// <summary>status.json - written by the service on every state change (see
/// client/windows/shared_paths.py::save_status), read-only from this app.</summary>
public sealed class NebulaStatus
{
    [JsonPropertyName("state")]
    public string State { get; set; } = "unknown";

    [JsonPropertyName("message")]
    public string Message { get; set; } = "Service not reachable";

    [JsonPropertyName("updated_at")]
    public string? UpdatedAt { get; set; }
}

public static class StatusStore
{
    private static readonly JsonSerializerOptions ReadOptions = new()
    {
        PropertyNameCaseInsensitive = true,
    };

    public static NebulaStatus Load()
    {
        try
        {
            if (!File.Exists(SharedPaths.StatusPath))
            {
                return new NebulaStatus();
            }
            var json = File.ReadAllText(SharedPaths.StatusPath);
            return JsonSerializer.Deserialize<NebulaStatus>(json, ReadOptions) ?? new NebulaStatus();
        }
        catch
        {
            return new NebulaStatus();
        }
    }
}
