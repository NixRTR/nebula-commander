using System.Text.Json;
using System.Text.Json.Serialization;

namespace NebulaCommanderApp.Services;

/// <summary>settings.json - shared with the service/tray, field names must match
/// client/config.py exactly (server, interval, nebula_path, accept_dns, node_id).</summary>
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
