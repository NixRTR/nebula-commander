using System.Security.Cryptography;
using System.Text;

namespace NebulaCommanderApp.Services;

/// <summary>
/// Device token, DPAPI-encrypted at machine scope (token.bin), shared with the
/// Windows service and the Python tray - see client/token_store.py's
/// _dpapi_get_token/_dpapi_set_token. .NET's ProtectedData with
/// DataProtectionScope.LocalMachine and no extra entropy is the byte-compatible
/// equivalent of win32crypt.CryptProtectData(..., None, ..., CRYPTPROTECT_LOCAL_MACHINE
/// | CRYPTPROTECT_UI_FORBIDDEN) - the "nebula-commander-token" description string
/// Python passes is DPAPI metadata only, not entropy, so it doesn't need to match
/// here for CryptUnprotectData/ProtectedData.Unprotect to succeed either way.
/// </summary>
public static class TokenStore
{
    public static string? GetToken()
    {
        try
        {
            if (!File.Exists(SharedPaths.TokenPath))
            {
                return null;
            }
            var blob = File.ReadAllBytes(SharedPaths.TokenPath);
            if (blob.Length == 0)
            {
                return null;
            }
            var data = ProtectedData.Unprotect(blob, null, DataProtectionScope.LocalMachine);
            return Encoding.UTF8.GetString(data);
        }
        catch
        {
            return null;
        }
    }

    public static void SetToken(string token)
    {
        Directory.CreateDirectory(SharedPaths.Root);
        var data = Encoding.UTF8.GetBytes(token);
        var blob = ProtectedData.Protect(data, null, DataProtectionScope.LocalMachine);
        var tmp = SharedPaths.TokenPath + ".tmp";
        File.WriteAllBytes(tmp, blob);
        File.Move(tmp, SharedPaths.TokenPath, overwrite: true);
    }
}
