namespace NebulaCommanderApp.Services;

/// <summary>
/// Paths under %ProgramData%\nebula-commander\ shared with the Windows service
/// (see client/windows/shared_paths.py on the Python side). This app never
/// changes that layout - it's a second reader/writer of it.
/// </summary>
public static class SharedPaths
{
    public static string Root { get; } = ResolveRoot();

    private static string ResolveRoot()
    {
        var programData = Environment.GetEnvironmentVariable("ProgramData")
            ?? Environment.GetEnvironmentVariable("ALLUSERSPROFILE")
            ?? @"C:\ProgramData";
        return Path.Combine(programData, "nebula-commander");
    }

    public static string SettingsPath => Path.Combine(Root, "settings.json");
    public static string StatusPath => Path.Combine(Root, "status.json");
    public static string TokenPath => Path.Combine(Root, "token.bin");
    public static string ConfigPath => Path.Combine(Root, "config.yaml");
    public static string DnsClientConfigPath => Path.Combine(Root, "dns-client.json");
    public static string AvailableRoutesPath => Path.Combine(Root, "available-routes.json");
    public static string NebulaLogPath => Path.Combine(Root, "nebula.log");
    public static string NebulaDir => Path.Combine(Root, "nebula");
    public static string NebulaExePath => Path.Combine(NebulaDir, "nebula.exe");
}
