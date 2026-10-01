using System.Diagnostics;
using System.Security.Principal;

namespace NebulaCommanderApp.Services;

/// <summary>
/// Changing anything (settings, enrollment, routes, Nebula updates, service
/// start/stop) requires an elevated administrator - the service enforces it on
/// every pipe call and the service's ACL enforces it for start/stop. The app
/// itself stays asInvoker (so login autostart keeps working) and offers to
/// relaunch elevated when a change is attempted.
/// </summary>
public static class Elevation
{
    public static bool IsElevated { get; } = ComputeIsElevated();

    private static bool ComputeIsElevated()
    {
        try
        {
            using var identity = WindowsIdentity.GetCurrent();
            return new WindowsPrincipal(identity).IsInRole(WindowsBuiltInRole.Administrator);
        }
        catch
        {
            return false;
        }
    }

    /// <summary>Starts an elevated copy of this app (UAC prompt). Returns false if
    /// the user declined or it couldn't start; the caller exits on true.</summary>
    public static bool TryRelaunchElevated()
    {
        var exe = Environment.ProcessPath;
        if (string.IsNullOrEmpty(exe))
        {
            return false;
        }
        try
        {
            Process.Start(new ProcessStartInfo
            {
                FileName = exe,
                UseShellExecute = true,
                Verb = "runas",
            });
            return true;
        }
        catch (System.ComponentModel.Win32Exception)
        {
            // ERROR_CANCELLED - user said no at the UAC prompt.
            return false;
        }
    }
}
