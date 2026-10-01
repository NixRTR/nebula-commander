using System.Runtime.InteropServices;

namespace NebulaCommanderApp.Services;

/// <summary>
/// Lets Windows Installer replace this app while it runs - an automatic update
/// (client/windows/updater.py) installs the MSI quietly while the app may be open or
/// sitting in the tray. The installer's Restart Manager asks running apps to close
/// with WM_QUERYENDSESSION / WM_ENDSESSION (ENDSESSION_CLOSEAPP), then restarts the
/// ones registered with RegisterApplicationRestart. Closing the window normally only
/// hides it to the tray, so without this the app would hold its files and the
/// upgrade would wait for a reboot. The same messages arrive at logoff/shutdown,
/// where exiting is right too.
/// </summary>
public static class SessionEnd
{
    /// <summary>Command-line flag the restarted app gets when it was in the tray.</summary>
    public const string BackgroundArg = "--background";

    private const uint WM_QUERYENDSESSION = 0x0011;
    private const uint WM_ENDSESSION = 0x0016;
    private const int RESTART_NO_CRASH = 1, RESTART_NO_HANG = 2, RESTART_NO_REBOOT = 8;

    private delegate IntPtr SubclassProc(IntPtr hWnd, uint msg, IntPtr wParam, IntPtr lParam, UIntPtr id, UIntPtr refData);

    [DllImport("comctl32.dll")]
    private static extern bool SetWindowSubclass(IntPtr hWnd, SubclassProc proc, UIntPtr id, UIntPtr refData);

    [DllImport("comctl32.dll")]
    private static extern IntPtr DefSubclassProc(IntPtr hWnd, uint msg, IntPtr wParam, IntPtr lParam);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode)]
    private static extern int RegisterApplicationRestart(string? commandLine, int flags);

    // Kept referenced for the window's lifetime - the native side only holds a pointer.
    private static SubclassProc? _proc;

    /// <summary>Call once with the main window's HWND; onEnd runs (on the UI thread)
    /// when the session or the installer tells the app to close.</summary>
    public static void Hook(IntPtr hwnd, Action onEnd)
    {
        _proc = (h, msg, wParam, lParam, id, refData) =>
        {
            if (msg == WM_QUERYENDSESSION)
            {
                return 1; // fine to close
            }
            if (msg == WM_ENDSESSION && wParam != IntPtr.Zero)
            {
                onEnd();
                return IntPtr.Zero;
            }
            return DefSubclassProc(h, msg, wParam, lParam);
        };
        SetWindowSubclass(hwnd, _proc, UIntPtr.Zero, UIntPtr.Zero);
    }

    /// <summary>Have Restart Manager reopen the app after an update, in the same
    /// state: visible, or just in the tray.</summary>
    public static void RegisterRestart(bool inTray) =>
        RegisterApplicationRestart(inTray ? BackgroundArg : "", RESTART_NO_CRASH | RESTART_NO_HANG | RESTART_NO_REBOOT);
}
