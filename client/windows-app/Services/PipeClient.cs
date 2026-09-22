using System.IO.Pipes;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace NebulaCommanderApp.Services;

/// <summary>
/// Named-pipe control channel to the service - see client/windows/pipe_protocol.py.
/// Single-shot request/response: connect, write one JSON message, read one JSON
/// response, close. Never throws - failures (service not installed/running,
/// pipe busy) come back as a non-ok result, matching pipe_protocol.send_command's
/// contract, since a failed "act now" nudge is non-fatal: the service picks the
/// change up on its own next poll cycle regardless.
/// </summary>
public static class PipeClient
{
    public const string PipeName = "NebulaCommanderControl";

    /// <summary>Re-poll config/certs right now instead of waiting for the next interval tick.</summary>
    public const string CmdPollNow = "poll_now";

    /// <summary>Stop the current poll loop and start a fresh one, re-reading settings.json.</summary>
    public const string CmdReloadSettings = "reload_settings";

    public sealed class PipeResult
    {
        [JsonPropertyName("ok")]
        public bool Ok { get; init; }

        [JsonPropertyName("error")]
        public string? Error { get; init; }
    }

    public static async Task<PipeResult> SendCommandAsync(string cmd, int timeoutMs = 3000)
    {
        try
        {
            using var pipe = new NamedPipeClientStream(".", PipeName, PipeDirection.InOut, PipeOptions.None);
            using var cts = new CancellationTokenSource(timeoutMs);
            await pipe.ConnectAsync(timeoutMs, cts.Token);
            pipe.ReadMode = PipeTransmissionMode.Message;

            var payload = JsonSerializer.SerializeToUtf8Bytes(new { cmd });
            await pipe.WriteAsync(payload, cts.Token);

            var buffer = new byte[4096];
            var read = await pipe.ReadAsync(buffer, cts.Token);
            if (read == 0)
            {
                return new PipeResult { Ok = false, Error = "empty response from service" };
            }
            return JsonSerializer.Deserialize<PipeResult>(buffer.AsSpan(0, read))
                ?? new PipeResult { Ok = false, Error = "unparseable response from service" };
        }
        catch (Exception e)
        {
            return new PipeResult { Ok = false, Error = $"service not reachable: {e.Message}" };
        }
    }
}
