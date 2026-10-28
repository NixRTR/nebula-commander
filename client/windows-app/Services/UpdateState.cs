namespace NebulaCommanderApp.Services;

/// <summary>Whether a newer Nebula Commander was installed under this running app.
/// The app has no version of its own to compare, so it remembers the service's
/// version from when it started: a different one later means an update was
/// installed (the MSI restarts the service), and this app is the old one.</summary>
public static class UpdateState
{
    private static string? _serviceVersionAtStart;

    /// <summary>Set once known: the service reported another version, or the
    /// app's own exe was replaced (MainWindow.WatchForUpdate).</summary>
    public static bool Installed { get; private set; }

    public static event Action? InstalledChanged;

    /// <summary>Feed every update status the app reads; returns Installed.</summary>
    public static bool Observe(UpdateStatus? status)
    {
        var version = status?.InstalledVersion;
        if (string.IsNullOrEmpty(version) || status!.DevBuild)
        {
            return Installed;
        }
        _serviceVersionAtStart ??= version;
        if (version != _serviceVersionAtStart)
        {
            MarkInstalled();
        }
        return Installed;
    }

    public static void MarkInstalled()
    {
        if (Installed)
        {
            return;
        }
        Installed = true;
        InstalledChanged?.Invoke();
    }
}
