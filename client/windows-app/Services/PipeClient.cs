using System.IO.Pipes;
using System.Runtime.InteropServices;
using System.Security.Principal;
using System.Text.Json;
using System.Text.Json.Serialization;
using Microsoft.Win32.SafeHandles;

namespace NebulaCommanderApp.Services;

/// <summary>
/// Named-pipe API to the service - see client/windows/pipe_protocol.py and
/// pipe_server.py. This is the app's only way to read or change service state:
/// %ProgramData%\nebula-commander\ is SYSTEM/Administrators-only.
///
/// Single-shot request/response: connect, write one JSON message, read one JSON
/// response, close. Never throws - failures come back as a non-ok response
/// (<see cref="PipeResponse.Unreachable"/> when the service can't be reached).
///
/// Two security details:
/// - Connects with TokenImpersonationLevel.Identification so the service can
///   check whether this process is an elevated administrator (MANAGE commands).
///   .NET's default (None = anonymous) would make every MANAGE call fail.
/// - Before sending anything, verifies the pipe's server process IS the
///   NebulaCommanderService process. Any local user can create a pipe with this
///   name while the service isn't running; without this check the app could be
///   talking to (and sending an enrollment code to) an impostor.
/// </summary>
public static class PipeClient
{
    public const string PipeName = "NebulaCommanderControl";

    public const string ErrAdminRequired = "administrator_required";
    public const string ErrUnreachable = "unreachable";

    public sealed class PipeResponse
    {
        [JsonPropertyName("ok")]
        public bool Ok { get; init; }

        [JsonPropertyName("result")]
        public JsonElement Result { get; init; }

        [JsonPropertyName("error")]
        public string? Error { get; init; }

        [JsonPropertyName("code")]
        public string? Code { get; init; }

        public bool AdministratorRequired => Code == ErrAdminRequired;
        public bool Unreachable => Code == ErrUnreachable;

        public static PipeResponse Fail(string code, string error) => new() { Ok = false, Code = code, Error = error };
    }

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetNamedPipeServerProcessId(SafePipeHandle pipe, out uint serverProcessId);

    public static async Task<PipeResponse> SendAsync(string cmd, object? args = null, int timeoutMs = 5000)
    {
        try
        {
            using var cts = new CancellationTokenSource(timeoutMs);
            using var pipe = new NamedPipeClientStream(
                ".", PipeName, PipeDirection.InOut, PipeOptions.Asynchronous, TokenImpersonationLevel.Identification);
            await pipe.ConnectAsync(cts.Token);
            pipe.ReadMode = PipeTransmissionMode.Message;

            var servicePid = ServiceControl.GetProcessId();
            if (servicePid is null
                || !GetNamedPipeServerProcessId(pipe.SafePipeHandle, out var serverPid)
                || serverPid != servicePid.Value)
            {
                return PipeResponse.Fail(
                    ErrUnreachable,
                    "The control pipe is not owned by the Nebula Commander service - refusing to use it.");
            }

            var payload = JsonSerializer.SerializeToUtf8Bytes(
                args is null ? new Dictionary<string, object?> { ["cmd"] = cmd }
                             : new Dictionary<string, object?> { ["cmd"] = cmd, ["args"] = args });
            await pipe.WriteAsync(payload, cts.Token);
            await pipe.FlushAsync(cts.Token);

            using var response = new MemoryStream();
            var buffer = new byte[64 * 1024];
            do
            {
                var read = await pipe.ReadAsync(buffer, cts.Token);
                if (read == 0)
                {
                    break;
                }
                response.Write(buffer, 0, read);
            }
            while (!pipe.IsMessageComplete);

            if (response.Length == 0)
            {
                return PipeResponse.Fail(ErrUnreachable, "empty response from service");
            }
            return JsonSerializer.Deserialize<PipeResponse>(response.ToArray())
                ?? PipeResponse.Fail(ErrUnreachable, "unparseable response from service");
        }
        catch (Exception e)
        {
            return PipeResponse.Fail(ErrUnreachable, $"service not reachable: {e.Message}");
        }
    }
}
