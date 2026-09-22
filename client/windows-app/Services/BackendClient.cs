using System.Diagnostics;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace NebulaCommanderApp.Services;

/// <summary>
/// HTTP calls to the Nebula Commander backend a device talks to directly -
/// mirrors the endpoints client/ncclient.py's cmd_enroll uses and backend/api/device.py
/// exposes. The service (client/ncclient.py::run_poll_loop) still owns polling
/// for config/certs/DNS - this app only enrolls and checks connectivity.
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

    public sealed class EnrollResponse
    {
        [JsonPropertyName("device_token")]
        public string DeviceToken { get; set; } = "";

        [JsonPropertyName("node_id")]
        public int? NodeId { get; set; }
    }

    public sealed class EnrollException(string message) : Exception(message);

    /// <summary>POST /api/device/enroll {code} -> {device_token, node_id}. Throws
    /// EnrollException with a user-facing message on any failure.</summary>
    public static async Task<EnrollResponse> EnrollAsync(string server, string code, CancellationToken ct = default)
    {
        var baseUrl = NormalizeServerUrl(server);
        var normalizedCode = code.Trim().ToUpperInvariant();
        HttpResponseMessage response;
        try
        {
            response = await Http.PostAsJsonAsync($"{baseUrl}/api/device/enroll", new { code = normalizedCode }, ct);
        }
        catch (Exception e)
        {
            throw new EnrollException($"Could not reach {baseUrl}: {e.Message}");
        }

        using (response)
        {
            if (!response.IsSuccessStatusCode)
            {
                throw new EnrollException(await ExtractErrorDetailAsync(response, ct));
            }

            EnrollResponse? result;
            try
            {
                result = await response.Content.ReadFromJsonAsync<EnrollResponse>(cancellationToken: ct);
            }
            catch (Exception e)
            {
                throw new EnrollException($"Server response was not valid JSON: {e.Message}");
            }

            if (result is null || string.IsNullOrEmpty(result.DeviceToken))
            {
                throw new EnrollException("Enroll succeeded but the response was missing a device token.");
            }
            return result;
        }
    }

    private static async Task<string> ExtractErrorDetailAsync(HttpResponseMessage response, CancellationToken ct)
    {
        var body = await response.Content.ReadAsStringAsync(ct);
        try
        {
            using var doc = JsonDocument.Parse(body);
            if (doc.RootElement.TryGetProperty("detail", out var detail))
            {
                return detail.GetString() ?? body;
            }
        }
        catch (JsonException)
        {
            // Not JSON - fall through to the raw body.
        }
        return string.IsNullOrWhiteSpace(body) ? $"Enroll failed ({(int)response.StatusCode})" : body;
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

    private sealed class AdvertisedRoutesResponse
    {
        [JsonPropertyName("routes")]
        public List<string> Routes { get; set; } = new();
    }

    /// <summary>GET /api/device/advertised-routes (device-token auth): CIDRs *this*
    /// node advertises as a gateway. Empty (never throws) on any failure - this is
    /// a Status page nicety, not something that should block the page on a
    /// transient network error.</summary>
    public static async Task<List<string>> GetAdvertisedRoutesAsync(string server, string token, CancellationToken ct = default)
    {
        try
        {
            var baseUrl = NormalizeServerUrl(server);
            using var request = new HttpRequestMessage(HttpMethod.Get, $"{baseUrl}/api/device/advertised-routes");
            request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", token);
            using var response = await Http.SendAsync(request, ct);
            if (!response.IsSuccessStatusCode)
            {
                return new List<string>();
            }
            var result = await response.Content.ReadFromJsonAsync<AdvertisedRoutesResponse>(cancellationToken: ct);
            return result?.Routes ?? new List<string>();
        }
        catch
        {
            return new List<string>();
        }
    }
}
