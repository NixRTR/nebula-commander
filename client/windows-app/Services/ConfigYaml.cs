using YamlDotNet.Serialization;

namespace NebulaCommanderApp.Services;

public sealed record UnsafeRoute(string Route, string Via);

public sealed class TunConfig
{
    public string? Dev { get; init; }
    public IReadOnlyList<UnsafeRoute> UnsafeRoutes { get; init; } = Array.Empty<UnsafeRoute>();
}

/// <summary>
/// Minimal read of config.yaml's tun.dev/tun.unsafe_routes - just enough for the
/// Status page to show what this node consumes as a subnet-router/exit-node
/// client. A node's *own* advertised routes never appear here (Nebula's `via`
/// points at other nodes reaching it, not at itself) - see
/// BackendClient.GetAdvertisedRoutesAsync for that half of the picture.
/// </summary>
public static class ConfigYaml
{
    public static TunConfig? ReadTunConfig(string path)
    {
        if (!File.Exists(path))
        {
            return null;
        }
        try
        {
            var deserializer = new DeserializerBuilder().Build();
            using var reader = new StreamReader(path);
            var root = deserializer.Deserialize<Dictionary<object, object>>(reader);
            if (root is null || !TryGet(root, "tun", out var tunObj) || tunObj is not Dictionary<object, object> tun)
            {
                return null;
            }

            TryGet(tun, "dev", out var devObj);
            var routes = new List<UnsafeRoute>();
            if (TryGet(tun, "unsafe_routes", out var routesObj) && routesObj is List<object> routesList)
            {
                foreach (var entry in routesList)
                {
                    if (entry is not Dictionary<object, object> map)
                    {
                        continue;
                    }
                    TryGet(map, "route", out var routeObj);
                    TryGet(map, "via", out var viaObj);
                    var route = routeObj?.ToString();
                    if (!string.IsNullOrWhiteSpace(route))
                    {
                        routes.Add(new UnsafeRoute(route, viaObj?.ToString() ?? ""));
                    }
                }
            }

            return new TunConfig { Dev = devObj?.ToString(), UnsafeRoutes = routes };
        }
        catch
        {
            return null;
        }
    }

    private static bool TryGet(Dictionary<object, object> map, string key, out object? value)
    {
        foreach (var kv in map)
        {
            if (string.Equals(kv.Key?.ToString(), key, StringComparison.Ordinal))
            {
                value = kv.Value;
                return true;
            }
        }
        value = null;
        return false;
    }
}
