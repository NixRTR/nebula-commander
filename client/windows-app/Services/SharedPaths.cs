namespace NebulaCommanderApp.Services;

/// <summary>
/// %ProgramData%\nebula-commander\ - the service's state folder (see
/// client/windows/shared_paths.py). SYSTEM/Administrators-only: this app never
/// reads or writes it directly (everything goes through <see cref="ServiceApi"/>);
/// the path is only used for the "Open folder" convenience button, which works
/// for an elevated administrator.
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
}
