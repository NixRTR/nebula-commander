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
/// The MSI installer already grants Authenticated Users START/STOP/QUERY_STATUS
/// on this service (`sc sdset`, see installer/windows/Product.wxs -
/// GrantServiceControlAcl), so this works unelevated with no UAC prompt.
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
