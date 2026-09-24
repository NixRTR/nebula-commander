using System.IO.Compression;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace NebulaCommanderApp.Services;

/// <summary>
/// Downloads/version-checks the Nebula binary from GitHub releases.
/// </summary>
public static class NebulaDownload
{
    public const string ReleasesUrl = "https://github.com/slackhq/nebula/releases";
    private const string ApiLatestUrl = "https://api.github.com/repos/slackhq/nebula/releases/latest";
    private const string DownloadUrlTemplate = "https://github.com/slackhq/nebula/releases/download/{0}/nebula-windows-amd64.zip";

    private static readonly HttpClient Http = CreateClient();

    private static HttpClient CreateClient()
    {
        var client = new HttpClient { Timeout = TimeSpan.FromSeconds(30) };
        // GitHub's API rejects requests with no User-Agent.
        client.DefaultRequestHeaders.UserAgent.ParseAdd("NebulaCommanderApp");
        return client;
    }

    public static async Task<string?> FetchLatestTagAsync(CancellationToken ct = default)
    {
        try
        {
            using var response = await Http.GetAsync(ApiLatestUrl, ct);
            if (!response.IsSuccessStatusCode)
            {
                return null;
            }
            await using var stream = await response.Content.ReadAsStreamAsync(ct);
            using var doc = await JsonDocument.ParseAsync(stream, cancellationToken: ct);
            return doc.RootElement.TryGetProperty("tag_name", out var tag) ? tag.GetString() : null;
        }
        catch
        {
            return null;
        }
    }

    public static async Task<(bool Ok, string? ExePath, string Error)> DownloadToDirAsync(
        string version, string destDir, CancellationToken ct = default)
    {
        var url = string.Format(DownloadUrlTemplate, version);
        var exePath = Path.Combine(destDir, "nebula.exe");
        Directory.CreateDirectory(destDir);
        var zipPath = Path.Combine(Path.GetTempPath(), "nebula-windows-amd64.zip");
        try
        {
            using (var response = await Http.GetAsync(url, HttpCompletionOption.ResponseHeadersRead, ct))
            {
                if (!response.IsSuccessStatusCode)
                {
                    return (false, null, $"HTTP {(int)response.StatusCode} downloading {url}");
                }
                await using var fs = File.Create(zipPath);
                await response.Content.CopyToAsync(fs, ct);
            }

            using var zip = ZipFile.OpenRead(zipPath);
            var entry = zip.Entries.FirstOrDefault(
                e => e.FullName.EndsWith("nebula.exe", StringComparison.OrdinalIgnoreCase));
            if (entry is null)
            {
                return (false, null, "nebula.exe not found in archive");
            }
            entry.ExtractToFile(exePath, overwrite: true);
            return (true, exePath, "");
        }
        catch (Exception e)
        {
            return (false, null, e.Message);
        }
        finally
        {
            try { File.Delete(zipPath); } catch { /* best effort cleanup */ }
        }
    }

    /// <summary>Runs `nebula -version`/`--version` and parses e.g. "1.10.2", or null.</summary>
    public static string? GetInstalledVersion(string nebulaBin)
    {
        foreach (var flag in new[] { "-version", "--version" })
        {
            try
            {
                var psi = new System.Diagnostics.ProcessStartInfo
                {
                    FileName = nebulaBin,
                    Arguments = flag,
                    RedirectStandardOutput = true,
                    RedirectStandardError = true,
                    UseShellExecute = false,
                    CreateNoWindow = true,
                };
                using var proc = System.Diagnostics.Process.Start(psi);
                if (proc is null)
                {
                    continue;
                }
                var stdout = proc.StandardOutput.ReadToEnd();
                var stderr = proc.StandardError.ReadToEnd();
                proc.WaitForExit(10000);
                var match = Regex.Match(stdout + stderr, @"v?(\d+\.\d+\.\d+)");
                if (match.Success)
                {
                    return match.Groups[1].Value;
                }
            }
            catch
            {
                // Try the next flag, or give up (binary missing/not runnable).
            }
        }
        return null;
    }

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
}
