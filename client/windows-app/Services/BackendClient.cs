using System.Diagnostics;

namespace NebulaCommanderApp.Services;

/// <summary>
/// Unauthenticated HTTP calls this app makes to the Nebula Commander backend
/// itself (connectivity check only). Anything needing the device token -
/// enrollment, advertised routes - happens inside the service (see ServiceApi),
/// so the token never leaves the SYSTEM-only state folder.
/// </summary>
public static class BackendClient
{
    private static readonly HttpClient Http = new() { Timeout = TimeSpan.FromSeconds(30) };

    /// <summary>"example.com" -> "https://example.com"; strips a trailing slash either way.</summary>
    public static string NormalizeServerUrl(string server)
    {
        var trimmed = server.Trim().TrimEnd('/');
        if (!trimmed.StartsWith("http", StringComparison.OrdinalIgnoreCase))
        {
            trimmed = "https://" + trimmed;
        }
        return trimmed;
    }

    /// <summary>GET /api/health (unauthenticated). Used by Status page's Test Connection.</summary>
    public static async Task<(bool Ok, string Message)> TestConnectionAsync(string server, CancellationToken ct = default)
    {
        try
        {
            var baseUrl = NormalizeServerUrl(server);
            var sw = Stopwatch.StartNew();
            using var response = await Http.GetAsync($"{baseUrl}/api/health", ct);
            sw.Stop();
            return response.IsSuccessStatusCode
                ? (true, $"OK ({(int)response.StatusCode}, {sw.ElapsedMilliseconds} ms)")
                : (false, $"HTTP {(int)response.StatusCode}");
        }
        catch (Exception e)
        {
            return (false, e.Message);
        }
    }
}
