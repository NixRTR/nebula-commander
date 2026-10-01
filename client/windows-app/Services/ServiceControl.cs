using System.Runtime.InteropServices;
using System.ServiceProcess;

namespace NebulaCommanderApp.Services;

public enum NebulaServiceState
{
    Running,
    Stopped,
    Transitioning,
    NotInstalled,
}

/// <summary>
/// Wraps System.ServiceProcess.ServiceController for the NebulaCommanderService.
/// The MSI's service ACL (`sc sdset`, see installer/windows/Product.wxs -
/// GrantServiceControlAcl) lets Authenticated Users only QUERY the service;
/// Start/Stop/Restart need an elevated administrator (see Elevation.cs) and
/// throw InvalidOperationException (access denied) otherwise.
/// </summary>
public static class ServiceControl
{
    public const string ServiceName = "NebulaCommanderService";

    public static NebulaServiceState GetState()
    {
        try
        {
            using var sc = new ServiceController(ServiceName);
            return sc.Status switch
            {
                ServiceControllerStatus.Running => NebulaServiceState.Running,
                ServiceControllerStatus.Stopped => NebulaServiceState.Stopped,
                _ => NebulaServiceState.Transitioning,
            };
        }
        catch (InvalidOperationException)
        {
            // Thrown when the service isn't installed.
            return NebulaServiceState.NotInstalled;
        }
    }

    // --- QueryServiceStatusEx: the service's process ID, used by PipeClient to
    // verify the control pipe is really served by this service. ---

    private const uint ScManagerConnect = 0x0001;
    private const uint ServiceQueryStatus = 0x0004;
    private const int ScStatusProcessInfo = 0;

    [StructLayout(LayoutKind.Sequential)]
    private struct ServiceStatusProcess
    {
        public uint ServiceType;
        public uint CurrentState;
        public uint ControlsAccepted;
        public uint Win32ExitCode;
        public uint ServiceSpecificExitCode;
        public uint CheckPoint;
        public uint WaitHint;
        public uint ProcessId;
        public uint ServiceFlags;
    }

    [DllImport("advapi32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    private static extern IntPtr OpenSCManagerW(string? machineName, string? databaseName, uint desiredAccess);

    [DllImport("advapi32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    private static extern IntPtr OpenServiceW(IntPtr scManager, string serviceName, uint desiredAccess);

    [DllImport("advapi32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool QueryServiceStatusEx(
        IntPtr service, int infoLevel, out ServiceStatusProcess buffer, int bufSize, out int bytesNeeded);

    [DllImport("advapi32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CloseServiceHandle(IntPtr handle);

    /// <summary>PID of the running service process, or null if it isn't installed/running.</summary>
    public static uint? GetProcessId()
    {
        var scm = OpenSCManagerW(null, null, ScManagerConnect);
        if (scm == IntPtr.Zero)
        {
            return null;
        }
        try
        {
            var svc = OpenServiceW(scm, ServiceName, ServiceQueryStatus);
            if (svc == IntPtr.Zero)
            {
                return null;
            }
            try
            {
                if (!QueryServiceStatusEx(svc, ScStatusProcessInfo, out var status,
                        Marshal.SizeOf<ServiceStatusProcess>(), out _))
                {
                    return null;
                }
                return status.ProcessId != 0 ? status.ProcessId : null;
            }
            finally
            {
                CloseServiceHandle(svc);
            }
        }
        finally
        {
            CloseServiceHandle(scm);
        }
    }

    public static void Start(TimeSpan? timeout = null)
    {
        using var sc = new ServiceController(ServiceName);
        sc.Refresh();
        if (sc.Status == ServiceControllerStatus.Running)
        {
            return;
        }
        sc.Start();
        sc.WaitForStatus(ServiceControllerStatus.Running, timeout ?? TimeSpan.FromSeconds(15));
    }

    public static void Stop(TimeSpan? timeout = null)
    {
        using var sc = new ServiceController(ServiceName);
        sc.Refresh();
        if (sc.Status == ServiceControllerStatus.Stopped)
        {
            return;
        }
        sc.Stop();
        sc.WaitForStatus(ServiceControllerStatus.Stopped, timeout ?? TimeSpan.FromSeconds(15));
    }

    public static void Restart(TimeSpan? timeout = null)
    {
        Stop(timeout);
        Start(timeout);
    }
}
