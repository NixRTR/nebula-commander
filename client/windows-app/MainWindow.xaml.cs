using System.Linq;
using Microsoft.UI.Windowing;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using NebulaCommanderApp.Pages;
using NebulaCommanderApp.Services;
using NebulaCommanderApp.Tray;

// To learn more about WinUI, the WinUI project structure,
// and more about our project templates, see: http://aka.ms/winui-project-info.

namespace NebulaCommanderApp;

public sealed partial class MainWindow : Window
{
    private readonly TrayIcon _trayIcon;

    // Set only by ExitFromTray(); AppWindow_Closing checks it to tell "user
    // clicked X" (hide to tray) apart from "user picked Exit in the tray menu"
    // (let the close actually happen) - both raise the same Closing event.
    private bool _isExiting;

    public MainWindow()
    {
        InitializeComponent();

        ExtendsContentIntoTitleBar = true;
        SetTitleBar(AppTitleBar);
        AppWindow.TitleBar.PreferredHeightOption = TitleBarHeightOption.Tall;
        AppWindow.SetIcon("Assets/AppIcon.ico");

        AppWindow.Closing += AppWindow_Closing;
        _trayIcon = new TrayIcon(onOpen: ShowAndActivate, onExit: ExitFromTray);
        AdminBar.IsOpen = !Elevation.IsElevated;

        // Let an automatic update's installer close and reopen the app (SessionEnd.cs).
        SessionEnd.Hook(WinRT.Interop.WindowNative.GetWindowHandle(this), ExitFromTray);
        SessionEnd.RegisterRestart(inTray: false);
        WatchForUpdate();
    }

    // An automatic update installs while the app may be running. Windows Installer
    // moves the running exe aside and installs the new one, but the installer
    // (started by the service) can't always close an app in the user's session -
    // seen on Win11 25H2 - so the old version would keep running until someone
    // restarts it. Notice the new file and offer to restart.
    private void WatchForUpdate()
    {
        var exe = Environment.ProcessPath;
        if (string.IsNullOrEmpty(exe))
        {
            return;
        }
        // Creation time too: Windows Installer keeps the packaged file's write time,
        // so an identical rebuild would look unchanged by write time alone, but the
        // replacement file is always newly created.
        (DateTime, DateTime, long)? Stamp()
        {
            var info = new FileInfo(exe);
            return info.Exists ? (info.CreationTimeUtc, info.LastWriteTimeUtc, info.Length) : null;
        }
        var startedWith = Stamp();
        var timer = DispatcherQueue.CreateTimer();
        timer.Interval = TimeSpan.FromSeconds(30);
        timer.Tick += (_, _) =>
        {
            var now = Stamp();
            if (now is not null && now != startedWith)
            {
                UpdatedBar.IsOpen = true;
                timer.Stop();
            }
        };
        timer.Start();
    }

    private void RestartUpdated_Click(object sender, RoutedEventArgs e)
    {
        var exe = Environment.ProcessPath;
        if (string.IsNullOrEmpty(exe))
        {
            return;
        }
        System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo(exe) { UseShellExecute = true });
        ExitFromTray();
    }

    /// <summary>Called by pages when the service answered administrator_required
    /// (or a service start/stop was denied): re-show the bar, highlighted.</summary>
    public void ShowAdminRequired()
    {
        AdminBar.Severity = InfoBarSeverity.Warning;
        AdminBar.Title = "Administrator required";
        AdminBar.IsOpen = true;
    }

    private void RelaunchElevated_Click(object sender, RoutedEventArgs e)
    {
        if (Elevation.TryRelaunchElevated())
        {
            ExitFromTray();
        }
    }

    private void AppWindow_Closing(AppWindow sender, AppWindowClosingEventArgs args)
    {
        if (_isExiting)
        {
            return;
        }
        // Closing the window (X button, Alt+F4) minimizes to tray instead of
        // exiting - the service keeps running regardless either way, but the UI
        // should stay reachable from the tray rather than requiring a relaunch.
        args.Cancel = true;
        HideToTray();
    }

    public void HideToTray()
    {
        AppWindow.Hide();
        SessionEnd.RegisterRestart(inTray: true);
    }

    public void ShowAndActivate()
    {
        AppWindow.Show();
        Activate();
        SessionEnd.RegisterRestart(inTray: false);
    }

    private void ExitFromTray()
    {
        _isExiting = true;
        _trayIcon.Dispose();
        Application.Current.Exit();
    }

    /// <summary>Selects the given MenuItem tag ("status"/"enrollment"), which
    /// fires NavView_SelectionChanged and navigates the frame to match.</summary>
    public void NavigateToTag(string tag)
    {
        var item = NavView.MenuItems
            .OfType<NavigationViewItem>()
            .FirstOrDefault(i => (string?)i.Tag == tag);
        if (item is not null)
        {
            NavView.SelectedItem = item;
        }
    }

    /// <summary>Enrolled -> Status, not enrolled -> Enrollment. Called once at
    /// launch (see App.xaml.cs::OnLaunched). Asks the service (is_enrolled) -
    /// the token itself is never readable by this app. Service unreachable ->
    /// Status, which explains that.</summary>
    public async void NavigateInitial()
    {
        var enrollment = await ServiceApi.GetEnrollmentAsync();
        NavigateToTag(enrollment is { Enrolled: false } ? "enrollment" : "status");
    }

    private void TitleBar_PaneToggleRequested(TitleBar sender, object args)
    {
        NavView.IsPaneOpen = !NavView.IsPaneOpen;
    }

    private void TitleBar_BackRequested(TitleBar sender, object args)
    {
        NavFrame.GoBack();
    }

    private void NavView_SelectionChanged(NavigationView sender, NavigationViewSelectionChangedEventArgs args)
    {
        if (args.IsSettingsSelected)
        {
            NavFrame.Navigate(typeof(SettingsPage));
        }
        else if (args.SelectedItem is NavigationViewItem item)
        {
            switch (item.Tag)
            {
                case "status":
                    NavFrame.Navigate(typeof(StatusPage));
                    break;
                case "enrollment":
                    NavFrame.Navigate(typeof(EnrollmentPage));
                    break;
                default:
                    throw new InvalidOperationException($"Unknown navigation item tag: {item.Tag}");
            }
        }
    }
}
